#!/usr/bin/env python3
"""Live EOD scanner — signal 30 min before close (15:30 ET).

Builds the CURRENT day candle from intraday bars up to 15:30 ET (incomplete candle),
scores the universe, and reports the expected next-day gap. Entry happens at the
market close; the profit target is a positive next-day gap / +2..5% move in 24-48h.
"""
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
SCAN_HR = "15:30"  # ET — за 30 минут до закрытия


def detect_last_sessions(probe="NVDA", interval="30m"):
    """Return (last_session_str, prev_session_ts) from intraday bars of a liquid ticker."""
    d = pd.read_csv if False else None
    import yfinance as yf
    df = yf.download(probe, period="5d", interval=interval, progress=False, auto_adjust=True)
    if len(df) == 0:
        raise RuntimeError("no intraday data")
    dates = sorted(set(df.index.tz_convert(NY).date))
    if len(dates) < 2:
        raise RuntimeError("not enough sessions")
    last = str(dates[-1])
    prev = pd.Timestamp(dates[-2])
    return last, prev


def day_candle_from_bars(df, target_date, partial=True, interval="30m"):
    """Build a daily candle for target_date from intraday bars.
    partial=True -> as-of 15:30 ET: the final 15:30-16:00 bar is EXCLUDED
    (it is still in progress at scan time)."""
    d = df.copy()
    d.index = d.index.tz_convert(NY)
    d["day"] = d.index.date
    d = d[d["day"].astype(str) == target_date]
    if len(d) < 4:
        return None
    if partial:
        last_idx = d.groupby("day").tail(1).index
        d = d.drop(last_idx)  # убираем незавершённый бар 15:30-16:00
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


def gap_stats(ticker, min_n=30):
    """Next-day open-gap distribution after similar 'big down day on volume' setups."""
    try:
        df = pd.read_csv(os.path.join(DATA, f"hist_{ticker}.csv"), parse_dates=["date"])
        df = df.sort_values("date")
        df["gap"] = df["open"] / df["close"].shift(1) - 1
        df["ret1"] = df["close"].pct_change()
        df["volr"] = df["volume"] / df["volume"].rolling(20).mean().shift(1)
        cond = (df["ret1"] <= -0.03) & (df["volr"] >= 1.2)
        if int(cond.sum()) < min_n:
            cond = (df["ret1"] <= -0.02) & (df["volr"] >= 1.0)
        g = df.loc[cond, "gap"].dropna()
        if len(g) == 0:
            return None
        return dict(gap_down_p=float((g > 0).mean()), gap_down_med=float(g.median()),
                    gap_down_n=int(len(g)))
    except Exception:
        return None


def model_gap_stats(ticker, oos, threshold=0.45, min_n=12):
    """Next-day open-gap after historical OUT-OF-SAMPLE model signals (prob>=threshold)."""
    try:
        df = pd.read_csv(os.path.join(DATA, f"hist_{ticker}.csv"), parse_dates=["date"])
        df = df.sort_values("date")
        df["gap"] = df["open"] / df["close"].shift(1) - 1
        df["gap_next"] = df["gap"].shift(-1)
        gmap = dict(zip(df["date"], df["gap_next"]))
        o = oos[oos["ticker"] == ticker]
        s = o[o["prob"] >= threshold]
        g = pd.Series([gmap.get(d) for d in s["date"]]).dropna()
        if len(g) < min_n:
            return None
        return dict(gap_sig_p=float((g > 0).mean()), gap_sig_med=float(g.median()),
                    gap_sig_n=int(len(g)))
    except Exception:
        return None


def train_final_model(feats):
    X = feats[FEATURES].values
    y = feats["target_2pct"].values
    m = HistGradientBoostingClassifier(
        max_iter=250, learning_rate=0.05, max_depth=5,
        min_samples_leaf=200, l2_regularization=1.0, random_state=42)
    m.fit(X, y)
    return m


def calibrate(feats, model, bins=10):
    feats = feats.copy()
    feats["prob"] = model.predict_proba(feats[FEATURES].values)[:, 1]
    feats["pbin"] = pd.qcut(feats["prob"], bins, duplicates="drop")
    cal = feats.groupby("pbin", observed=True).agg(
        prob=("prob", "mean"), hit=("target_2pct", "mean"),
        avg_best=("best_fwd", "mean"), avg_fwd2=("fwd2", "mean"),
        avg_worst=("worst_fwd", "mean"), n=("prob", "size")).reset_index()
    cal["pbin"] = cal["prob"].map(lambda p: f"{p:.2f}")
    return cal


def expected_move(prob, cal):
    idx = (cal["prob"] - prob).abs().idxmin()
    row = cal.loc[idx]
    return dict(hit=float(row["hit"]), avg_best=float(row["avg_best"]),
                avg_fwd2=float(row["avg_fwd2"]), avg_worst=float(row["avg_worst"]))


def main():
    os.makedirs(OUT, exist_ok=True)

    # ---- shortlist из панели ----
    feats = pd.read_parquet(os.path.join(DATA, "featured_panel.parquet"))
    panel_last = feats.sort_values("date").groupby("ticker", sort=False).tail(1)
    short = panel_last[(panel_last["close"] >= 5) & (panel_last["dollar_vol21"] >= 5e6)]
    short = short.sort_values("dollar_vol21", ascending=False)
    shortlist = short["ticker"].tolist()[:60]
    print(f"shortlist: {len(shortlist)} liquid names")

    # ---- последняя сессия + 30-мин бары одним запросом ----
    import yfinance as yf
    last_session, prev_session = detect_last_sessions()
    print(f"last session: {last_session} | prev: {prev_session.date()} | scan as-of {SCAN_HR} ET (неполная свеча)")

    t0 = time.time()
    intra = yf.download(shortlist, period="5d", interval="30m", group_by="ticker",
                        threads=True, progress=False, auto_adjust=True)
    print(f"30m bars downloaded in {time.time()-t0:.0f}s")

    model = train_final_model(feats)
    cal = calibrate(feats, model)
    print("calibration bins:", len(cal))

    # OOS-предсказания для честной статистики гэпов после сигнала
    oos_path = os.path.join(DATA, "oos_predictions.parquet")
    oos = pd.read_parquet(oos_path) if os.path.exists(oos_path) else pd.DataFrame()

    rows = []
    for t in shortlist:
        try:
            sub = intra[t].dropna(how="all") if t in intra.columns.get_level_values(0) else intra[t].dropna(how="all")
            if len(sub) < 5:
                continue
        except Exception:
            continue
        day = day_candle_from_bars(sub, last_session, partial=True)
        if day is None:
            continue
        # дневная история для признаков (прогрев) + неполная свеча дня
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
        prob = float(model.predict_proba([f[FEATURES].values])[0, 1])
        em = expected_move(prob, cal)
        gs = gap_stats(t) or {}
        mg = (model_gap_stats(t, oos) or {}) if len(oos) else {}
        rec = dict(ticker=t, date=last_session, signal_time=f"{SCAN_HR} ET", **mg,
                   prob=prob, **em, **gs, **day)
        for col in ["ret_1", "rsi14", "atr14_pct", "close_pos", "vol_ratio",
                    "px_sma50", "px_sma200", "dist_52w_high", "dollar_vol21",
                    "gap", "ret_5", "ret_21", "adr10", "streak", "body_pct",
                    "range_ratio", "trend_sma20_50", "touch_high_5d"]:
            v = f.get(col)
            rec[col] = None if v is None or (isinstance(v, float) and np.isnan(v)) else float(v)
        rows.append(rec)
        time.sleep(0.05)

    scan = pd.DataFrame(rows).sort_values("prob", ascending=False)
    scan.to_csv(os.path.join(OUT, "scan_results.csv"), index=False)
    scan.to_parquet(os.path.join(DATA, "live_scan.parquet"))
    print(f"\nsaved output/scan_results.csv ({len(scan)} rows)")

    cols = ["ticker", "close", "prob", "hit", "avg_best", "avg_fwd2",
            "gap_sig_p", "gap_sig_med", "gap_down_p", "gap_down_med", "vol_ratio", "rsi14"]
    pd.set_option("display.width", 220)
    print("\n=== SCAN (top 12, сигнал 15:30 ET) ===")
    print(scan[cols].head(12).round(4).to_string(index=False))
    print("\n'close' = цена на 15:30 ET (вход по закрытию ≈ этой цене)")


if __name__ == "__main__":
    main()
