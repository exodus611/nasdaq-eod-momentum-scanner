#!/usr/bin/env python3
"""Live EOD scanner: rank NASDAQ universe as of Friday close, produce top picks."""
import os, json, time
import numpy as np
import pandas as pd
import urllib.request
from datetime import datetime, timezone
from sklearn.ensemble import HistGradientBoostingClassifier

from features import FEATURES, add_indicators

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
OUT = os.path.join(ROOT, "output")

FRIDAY = "2026-08-28"
THURSDAY = pd.Timestamp("2026-08-27")


# ---------------- Friday bar reconstruction from intraday ----------------
def yf_chart(ticker, rng="5d", interval="60m"):
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
           f"?range={rng}&interval={interval}")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode())


def reconstruct_friday(ticker, target_date=FRIDAY):
    """Rebuild the Friday daily candle + intraday features from 60m bars."""
    try:
        d = yf_chart(ticker)
        res = d["chart"]["result"][0]
        if res is None or "timestamp" not in res:
            return None
        ts = res["timestamp"]
        q = res["indicators"]["quote"][0]
        rows = []
        for i, t in enumerate(ts):
            o, h, l, c, v = q["open"][i], q["high"][i], q["low"][i], q["close"][i], q["volume"][i]
            if None in (o, h, l, c, v):
                continue
            rows.append((t, o, h, l, c, v))
        if not rows:
            return None
        df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
        df["dt_utc"] = pd.to_datetime(df["ts"], unit="s", utc=True)
        df["date_ny"] = df["dt_utc"].dt.tz_convert("America/New_York").dt.date
        fri = df[df["date_ny"].astype(str) == target_date]
        if len(fri) < 4:
            return None
        o = fri["open"].iloc[0]
        h = fri["high"].max()
        l = fri["low"].min()
        c = fri["close"].iloc[-1]
        v = fri["volume"].sum()
        tp = (fri["high"] + fri["low"] + fri["close"]) / 3
        vwap = (tp * fri["volume"]).sum() / fri["volume"].sum()
        last2 = fri.tail(2)
        return {
            "friday_open": float(o), "friday_high": float(h), "friday_low": float(l),
            "friday_close": float(c), "friday_volume": float(v),
            "close_vs_vwap": float(c / vwap - 1),
            "friday_close_pos": float((c - l) / (h - l) if h > l else 0.5),
            "last_hour_ret": float(last2["close"].iloc[-1] / last2["close"].iloc[0] - 1),
        }
    except Exception as e:
        return None


# ---------------- model ----------------
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


def ticker_features_asof(ticker, asof):
    """Compute feature row as of `asof` date from stored daily CSV."""
    hist = pd.read_csv(os.path.join(DATA, f"hist_{ticker}.csv"), parse_dates=["date"])
    hist = hist.sort_values("date")
    hist = hist[hist["date"] <= asof]
    if len(hist) < 60:
        return None
    f = add_indicators(hist)
    row = f.iloc[-1]
    return row


# ---------------- main scan ----------------
def main():
    os.makedirs(OUT, exist_ok=True)
    feats = pd.read_parquet(os.path.join(DATA, "featured_panel.parquet"))

    model = train_final_model(feats)
    cal = calibrate(feats, model)
    print("calibration bins:", len(cal))

    # ---- liquidity shortlist from stored panel (last available row per ticker) ----
    panel_last = feats.sort_values("date").groupby("ticker", sort=False).tail(1)
    short = panel_last[(panel_last["close"] >= 5) & (panel_last["dollar_vol21"] >= 5e6)]
    short = short.sort_values("dollar_vol21", ascending=False)
    shortlist = short["ticker"].tolist()[:60]
    print(f"shortlist: {len(shortlist)} liquid names (dv21>=$5M, px>=$5)")

    # ---- reconstruct Friday bars + score ----
    rows = []
    for t in shortlist:
        fr = reconstruct_friday(t)
        if fr is None:
            continue
        # features as of Thursday
        r = ticker_features_asof(t, THURSDAY)
        if r is None:
            continue
        # rebuild Thursday feature vector + append Friday bar
        hist = pd.read_csv(os.path.join(DATA, f"hist_{t}.csv"), parse_dates=["date"])
        hist = hist.sort_values("date")
        hist = hist[hist["date"] <= THURSDAY]
        fri_bar = pd.DataFrame([{
            "date": pd.Timestamp(FRIDAY), "open": fr["friday_open"],
            "high": fr["friday_high"], "low": fr["friday_low"],
            "close": fr["friday_close"], "volume": fr["friday_volume"],
        }])
        full = pd.concat([hist, fri_bar], ignore_index=True)
        f = add_indicators(full).iloc[-1]
        if f[FEATURES].isna().any():
            continue
        prob = float(model.predict_proba([f[FEATURES].values])[0, 1])
        em = expected_move(prob, cal)
        rec = dict(ticker=t, date=FRIDAY, close=fr["friday_close"], prob=prob, **em, **fr)
        for col in ["ret_1", "rsi14", "atr14_pct", "close_pos", "vol_ratio",
                    "px_sma50", "px_sma200", "dist_52w_high", "dollar_vol21",
                    "gap", "ret_5", "ret_21", "adr10", "streak", "body_pct",
                    "range_ratio", "trend_sma20_50", "touch_high_5d"]:
            v = f.get(col)
            rec[col] = None if v is None or (isinstance(v, float) and np.isnan(v)) else float(v)
        rows.append(rec)
        time.sleep(0.12)

    scan = pd.DataFrame(rows).sort_values("prob", ascending=False)
    scan.to_csv(os.path.join(OUT, "scan_results.csv"), index=False)
    print("\n=== SCAN RESULT (all, top 20) ===")
    cols = ["ticker", "close", "prob", "hit", "avg_best", "avg_fwd2", "avg_worst",
            "close_vs_vwap", "friday_close_pos", "last_hour_ret", "vol_ratio",
            "rsi14", "px_sma50", "dist_52w_high"]
    print(scan[cols].head(20).round(4).to_string(index=False))

    scan.to_parquet(os.path.join(DATA, "live_scan.parquet"))
    print("\nsaved scan -> output/scan_results.csv")


if __name__ == "__main__":
    main()
