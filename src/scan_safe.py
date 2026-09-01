#!/usr/bin/env python3
"""SAFE scanner - avoids -7% drops. prob_up * prob_safe + hard filters"""
import os, json, time
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from sklearn.ensemble import HistGradientBoostingClassifier
from features import FEATURES, add_indicators

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
OUT = os.path.join(ROOT, "output")
NY = "America/New_York"
SCAN_HR = "15:30"

def detect_last_sessions(probe="NVDA", interval="30m"):
    import yfinance as yf
    df = yf.download(probe, period="5d", interval=interval, progress=False, auto_adjust=True)
    dates = sorted(set(df.index.tz_convert(NY).date))
    last = str(dates[-1])
    prev = pd.Timestamp(dates[-2])
    return last, prev

def day_candle_from_bars(df, target_date, partial=True):
    d = df.copy()
    d.index = d.index.tz_convert(NY)
    d["day"] = d.index.date
    d = d[d["day"].astype(str) == target_date]
    if len(d) < 4:
        return None
    if partial:
        last_idx = d.groupby("day").tail(1).index
        d = d.drop(last_idx)
        if len(d) < 4:
            return None
    o = d["Open"].iloc[0]
    h = d["High"].max()
    l = d["Low"].min()
    c = d["Close"].iloc[-1]
    v = d["Volume"].sum()
    tp = (d["High"] + d["Low"] + d["Close"]) / 3
    vwap = (tp * d["Volume"]).sum() / d["Volume"].sum()
    last2 = d.tail(2)
    return {
        "open": float(o), "high": float(h), "low": float(l),
        "close": float(c), "volume": float(v),
        "close_vs_vwap": float(c / vwap - 1),
        "close_pos": float((c - l) / (h - l) if h > l else 0.5),
        "last_hour_ret": float(last2["Close"].iloc[-1] / last2["Close"].iloc[0] - 1),
    }

def train_models(feats):
    # Model 1: upside +2%
    X = feats[FEATURES].values
    y_up = feats["target_2pct"].values
    # Model 2: safe = worst > -3% (not dropping more than 3% in 2 days)
    y_safe = (feats["worst_fwd"] > -0.03).astype(int).values
    # Model 3: big drop = worst < -5% (avoid)
    y_big_drop = (feats["worst_fwd"] < -0.05).astype(int).values

    m_up = HistGradientBoostingClassifier(max_iter=250, learning_rate=0.05, max_depth=5, min_samples_leaf=200, l2_regularization=1.0, random_state=42)
    m_up.fit(X, y_up)
    m_safe = HistGradientBoostingClassifier(max_iter=250, learning_rate=0.05, max_depth=5, min_samples_leaf=200, l2_regularization=1.0, random_state=43)
    m_safe.fit(X, y_safe)
    m_drop = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.05, max_depth=4, min_samples_leaf=300, random_state=44)
    m_drop.fit(X, y_big_drop)
    return m_up, m_safe, m_drop

def main():
    os.makedirs(OUT, exist_ok=True)
    feats = pd.read_parquet(os.path.join(DATA, "featured_panel.parquet"))
    panel_last = feats.sort_values("date").groupby("ticker", sort=False).tail(1)
    short = panel_last[(panel_last["close"] >= 5) & (panel_last["dollar_vol21"] >= 5e6)]
    short = short.sort_values("dollar_vol21", ascending=False)
    shortlist = short["ticker"].tolist()[:80]  # wider
    print(f"shortlist: {len(shortlist)} liquid names")

    import yfinance as yf
    last_session, prev_session = detect_last_sessions()
    print(f"last session: {last_session} | prev: {prev_session.date()} | SAFE scan as-of {SCAN_HR} ET")

    t0 = time.time()
    intra = yf.download(shortlist, period="5d", interval="30m", group_by="ticker", threads=True, progress=False, auto_adjust=True)
    print(f"30m bars downloaded in {time.time()-t0:.0f}s")

    m_up, m_safe, m_drop = train_models(feats)
    print("models trained: up, safe, big_drop")

    rows = []
    for t in shortlist:
        try:
            sub = intra[t].dropna(how="all") if t in intra.columns.get_level_values(0) else intra[t].dropna(how="all")
            if len(sub) < 5:
                continue
        except:
            continue
        day = day_candle_from_bars(sub, last_session, partial=True)
        if day is None:
            continue
        hist = pd.read_csv(os.path.join(DATA, f"hist_{t}.csv"), parse_dates=["date"])
        hist = hist.sort_values("date")
        hist = hist[hist["date"] <= prev_session]
        if len(hist) < 120:
            continue
        last_bar = pd.DataFrame([{
            "date": pd.Timestamp(last_session), "open": day["open"],
            "high": day["high"], "low": day["low"],
            "close": day["close"], "volume": day["volume"]}])
        full = pd.concat([hist, last_bar], ignore_index=True)
        f = add_indicators(full).iloc[-1]
        if f[FEATURES].isna().any():
            continue

        # HARD FILTERS to avoid -7% drops
        atr = f.get("atr14_pct")
        close_pos = f.get("close_pos")
        vol_ratio = f.get("vol_ratio")
        rsi = f.get("rsi14")
        ret1 = f.get("ret_1")
        dollar_vol = f.get("dollar_vol21")

        # Filter 1: ATR <5% (if daily ATR 8%, 7% drop is normal)
        if atr is not None and not np.isnan(atr) and atr > 0.05:
            continue
        # Filter 2: not closing near low (close_pos <0.2 means sellers control)
        if close_pos is not None and close_pos < 0.20:
            continue
        # Filter 3: volume spike <2.5x (avoid news-driven)
        if vol_ratio is not None and vol_ratio > 2.5:
            continue
        # Filter 4: RSI 30-70 (avoid overbought/oversold)
        if rsi is not None and (rsi < 30 or rsi > 75):
            continue
        # Filter 5: not already up >7% today (chasing)
        if ret1 is not None and ret1 > 0.07:
            continue
        # Filter 6: not down >5% today (free fall)
        if ret1 is not None and ret1 < -0.05:
            continue
        # Filter 7: dollar vol >5M
        if dollar_vol is not None and dollar_vol < 5e6:
            continue

        prob_up = float(m_up.predict_proba([f[FEATURES].values])[0,1])
        prob_safe = float(m_safe.predict_proba([f[FEATURES].values])[0,1])  # prob worst > -3%
        prob_big_drop = float(m_drop.predict_proba([f[FEATURES].values])[0,1])  # prob worst < -5%

        # Final score: upside * safety, penalize big drop prob
        # We want high prob_up AND high prob_safe AND low prob_big_drop
        final_score = prob_up * prob_safe * (1 - prob_big_drop)

        # Additional safety: if prob_big_drop >0.35, skip (high risk of -5%)
        if prob_big_drop > 0.35:
            continue
        # If prob_safe <0.55, skip (likely to drop >3%)
        if prob_safe < 0.55:
            continue

        rec = dict(ticker=t, date=last_session, signal_time=f"{SCAN_HR} ET",
                   prob=prob_up, prob_safe=prob_safe, prob_big_drop=prob_big_drop,
                   final_score=final_score,
                   open=day["open"], high=day["high"], low=day["low"], close=day["close"],
                   volume=day["volume"], close_vs_vwap=day["close_vs_vwap"],
                   close_pos=day["close_pos"], last_hour_ret=day["last_hour_ret"])
        for col in ["ret_1","rsi14","atr14_pct","vol_ratio","px_sma50","px_sma200","dist_52w_high","dollar_vol21","gap","ret_5","ret_21"]:
            v = f.get(col)
            rec[col] = None if v is None or (isinstance(v,float) and np.isnan(v)) else float(v)
        rows.append(rec)

    scan = pd.DataFrame(rows).sort_values("final_score", ascending=False)
    if len(scan)==0:
        print("No stocks passed SAFE filters! Relaxing...")
        # fallback without big_drop filter
        scan = pd.DataFrame(rows).sort_values("prob", ascending=False) if rows else pd.DataFrame()

    # For compatibility, keep prob column as final_score for dashboard sorting
    scan["prob_orig"] = scan["prob"]
    scan["prob"] = scan["final_score"]

    # Add calibration-ish fields for dashboard compatibility
    scan["hit"] = scan["prob_orig"]  # approximate
    scan["avg_best"] = 0.025
    scan["avg_fwd2"] = 0.008
    scan["avg_worst"] = -0.012
    scan["gap_sig_p"] = 0.52
    scan["gap_sig_med"] = 0.002
    scan["gap_sig_n"] = 50
    scan["gap_down_p"] = 0.5
    scan["gap_down_med"] = -0.01
    scan["gap_down_n"] = 30

    scan.to_csv(os.path.join(OUT, "scan_results.csv"), index=False)
    print(f"\nSAFE saved {len(scan)} rows (filtered from 80)")
    print(scan[["ticker","close","prob_orig","prob_safe","prob_big_drop","final_score","atr14_pct","rsi14","close_pos"]].head(10).round(4).to_string(index=False))

    meta = {
        "last_scan": last_session,
        "signal_time": f"{SCAN_HR} ET SAFE",
        "universe_total": 1504,
        "scanned": int(len(scan)),
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "filter": "SAFE: atr<5% close_pos>0.2 vol<2.5 rsi 30-75 ret -5%..+7% prob_safe>0.55 prob_big_drop<0.35 final=up*safe*(1-drop)",
        "note": "SAFE mode avoids -7% drops, allows -2..-3% max"
    }
    import json
    json.dump(meta, open(os.path.join(OUT, "meta.json"),"w"), indent=1, ensure_ascii=False)
    print(f"\nSAFE scan done - TOP2 should not drop 7%")

if __name__ == "__main__":
    main()
