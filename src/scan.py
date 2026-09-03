#!/usr/bin/env python3
"""Live EOD scanner — signal AFTER market close (~16:15 ET), entry NEXT session open.

The market is closed at scan time: the CURRENT day candle is COMPLETE (all intraday
bars, no volume scaling). Scores the universe with the base+coil model (trained on
open-entry targets: fwd returns measured from the NEXT session's open) and outputs
TWO tiers:

  * pre_move  — structural "before the move" mask (uptrend, near 52w high, quiet today,
                no spike this week) ranked by model prob. This is the MAIN list.
  * momentum  — all liquid names ranked by model prob (already-moving names; for reference).

Entry at the next trading day's open (09:30 ET); target +2..+5% in 24-48h from entry;
stop -3%. Calibration and gap stats come from the OUT-OF-SAMPLE walk-forward
predictions (data/oos_predictions.parquet) when available.
"""
import os, json, time
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from sklearn.ensemble import HistGradientBoostingClassifier

from features import FEATURES, COIL_FEATURES, ALL_FEATURES, add_indicators

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
OUT = os.path.join(ROOT, "output")
NY = "America/New_York"
SCAN_HR = "after close"  # ET — после закрытия рынка (~16:15 ET)
MINUTES_OPEN = 390  # 09:30-16:00

PROBES = ["NVDA", "AAPL", "MSFT", "AMZN", "GOOGL"]  # fallback chain for session detection


# ---------------------------------------------------------------- session detection
def detect_last_sessions(probes=PROBES, interval="30m"):
    """Return (last_session_str, prev_session_ts) from intraday bars of a liquid ticker."""
    import yfinance as yf
    last_err = None
    for probe in probes:
        try:
            df = yf.download(probe, period="5d", interval=interval, progress=False, auto_adjust=True)
            if df is None or len(df) == 0:
                continue
            dates = sorted(set(df.index.tz_convert(NY).date))
            if len(dates) < 2:
                continue
            return str(dates[-1]), pd.Timestamp(dates[-2])
        except Exception as e:
            last_err = e
    raise RuntimeError(f"no intraday data from any probe: {last_err}")


# ---------------------------------------------------------------- partial candle
def day_candle_from_bars(df, target_date, partial=True, asof="15:30"):
    """Build a daily candle for target_date from intraday bars.

    partial=True -> as-of `asof` (default 15:30 ET): bars that have NOT ended by `asof`
    are excluded (they are still in progress at scan time). Volume is scaled to the
    full trading day (390 min) so vol_ratio is comparable to training candles.
    """
    d = df.copy()
    d.index = d.index.tz_convert(NY)
    d["day"] = d.index.date
    d = d[d["day"].astype(str) == target_date]
    if len(d) < 4:
        return None
    if partial:
        # keep only bars that ended at or before `asof`
        hh, mm = map(int, asof.split(":"))
        cutoff = d.index.normalize() + pd.Timedelta(hours=hh, minutes=mm)
        d["bar_end"] = d.index + pd.Timedelta(minutes=30)
        d = d[d["bar_end"] <= cutoff]
        if len(d) < 4:
            return None
    o = d["Open"].iloc[0]
    h = d["High"].max()
    l = d["Low"].min()
    c = d["Close"].iloc[-1]
    v = float(d["Volume"].sum())
    # scale partial volume to full day
    elapsed_min = (d.index[-1] - d.index[0]).total_seconds() / 60.0 + 30
    elapsed_min = min(max(elapsed_min, 1), MINUTES_OPEN)
    v_scaled = v * (MINUTES_OPEN / elapsed_min)
    tp = (d["High"] + d["Low"] + d["Close"]) / 3
    vwap = (tp * d["Volume"]).sum() / d["Volume"].sum()
    last2 = d.tail(2)
    return {
        "open": float(o), "high": float(h), "low": float(l),
        "close": float(c), "volume": v_scaled, "volume_raw": v,
        "close_vs_vwap": float(c / vwap - 1),
        "close_pos": float((c - l) / (h - l) if h > l else 0.5),
        "last_hour_ret": float(last2["Close"].iloc[-1] / last2["Close"].iloc[0] - 1),
    }


# ---------------------------------------------------------------- gap statistics
def gap_stats(ticker, min_n=30):
    """Next-day open-gap distribution after 'big down day on volume' setups (history)."""
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


# ---------------------------------------------------------------- model + calibration
def train_final_model(feats):
    X = feats[ALL_FEATURES].values
    y = feats["path_win"].values
    m = HistGradientBoostingClassifier(
        max_iter=250, learning_rate=0.05, max_depth=5,
        min_samples_leaf=200, l2_regularization=1.0, random_state=42)
    m.fit(X, y)
    return m


def calibrate(feats, model, oos, bins=10):
    """Calibration bins from OOS predictions when available (honest stats), else full panel."""
    if oos is not None and len(oos):
        d = oos.copy()
        d["prob"] = d["prob"].values  # already OOS prob
    else:
        d = feats.copy()
        d["prob"] = model.predict_proba(feats[ALL_FEATURES].values)[:, 1]
    d["pbin"] = pd.qcut(d["prob"], bins, duplicates="drop")
    cal = d.groupby("pbin", observed=True).agg(
        prob=("prob", "mean"), win=("path_win", "mean"),
        loss=("path_loss", "mean"),
        avg_best=("best_fwdo", "mean"), avg_worst=("worst_fwdo", "mean"),
        n=("prob", "size")).reset_index()
    cal["pbin"] = cal["prob"].map(lambda p: f"{p:.2f}")
    return cal, ("OOS" if (oos is not None and len(oos)) else "INSAMPLE")


def expected_move(prob, cal):
    idx = (cal["prob"] - prob).abs().idxmin()
    row = cal.loc[idx]
    return dict(win=float(row["win"]), loss=float(row["loss"]),
                avg_best=float(row["avg_best"]), avg_worst=float(row["avg_worst"]))


# ---------------------------------------------------------------- pre-move mask
def pre_move_tier(scored):
    """Apply the validated 'before the move' structural mask with a relaxation ladder.
    Returns (tiered_df, level_used). Level 1 = strict; relax one condition at a time."""
    # Relaxation ladder: level 1 = strict production mask (validated OOS: win 57.5%,
    # loss 33.5%, EV +0.15%/trade); relax trend/vol-coil first, then quiet/spike.
    up = (scored["px_sma50"] > 0) & (scored["px_sma200"] > 0) & (scored["dist_52w_high"] > -0.15)
    quiet = (scored["ret_1"].abs() < 0.03) & (scored["max_abs_ret10"] < 0.04)
    coil = (scored["trend_sma20_50"] > 0) & (scored["vol_dry5"] < 1.0)
    levels = [
        (1, up & quiet & coil),
        (2, up & quiet),
        (3, up & (scored["ret_1"].abs() < 0.03)),
        (4, up),
    ]
    for level, mask in levels:
        sub = scored[mask.fillna(False)].copy()
        if len(sub) >= 3:
            return sub, level
    # last resort: the loosest mask, even if small (never return empty if anything passed)
    sub = scored[levels[-1][1].fillna(False)].copy()
    return sub, 3


def main():
    os.makedirs(OUT, exist_ok=True)

    # ---- shortlist из панели ----
    feats = pd.read_parquet(os.path.join(DATA, "featured_panel.parquet"))
    panel_last = feats.sort_values("date").groupby("ticker", sort=False).tail(1)
    short = panel_last[(panel_last["close"] >= 5) & (panel_last["dollar_vol21"] >= 5e6)]
    short = short.sort_values("dollar_vol21", ascending=False)
    shortlist = short["ticker"].tolist()[:200]
    print(f"shortlist: {len(shortlist)} liquid names")

    # ---- последняя сессия + 30-мин бары ----
    import yfinance as yf
    last_session, prev_session = detect_last_sessions()
    print(f"last session: {last_session} | prev: {prev_session.date()} | scan {SCAN_HR} (полная свеча, вход по открытию след. сессии)")

    t0 = time.time()
    intra = yf.download(shortlist, period="5d", interval="30m", group_by="ticker",
                        threads=True, progress=False, auto_adjust=True)
    print(f"30m bars downloaded in {time.time()-t0:.0f}s")

    model = train_final_model(feats)
    oos_path = os.path.join(DATA, "oos_predictions.parquet")
    oos = pd.read_parquet(oos_path) if os.path.exists(oos_path) else pd.DataFrame()
    cal, cal_src = calibrate(feats, model, oos)
    print(f"calibration: {len(cal)} bins (source: {cal_src})")

    rows = []
    for t in shortlist:
        try:
            sub = intra[t].dropna(how="all") if t in intra.columns.get_level_values(0) else None
            if sub is None or len(sub) < 5:
                continue
        except Exception:
            continue
        day = day_candle_from_bars(sub, last_session, partial=False)
        if day is None:
            continue
        hist = pd.read_csv(os.path.join(DATA, f"hist_{t}.csv"), parse_dates=["date"])
        hist = hist.sort_values("date")
        hist = hist[hist["date"] <= prev_session]
        if len(hist) < 120:
            continue
        if hist["date"].iloc[-1] != prev_session:
            print(f"  {t}: WARNING hist last date {hist['date'].iloc[-1].date()} != prev session")
        last_bar = pd.DataFrame([{
            "date": pd.Timestamp(last_session), "open": day["open"],
            "high": day["high"], "low": day["low"],
            "close": day["close"], "volume": day["volume"]}])
        full = pd.concat([hist, last_bar], ignore_index=True)
        f = add_indicators(full).iloc[-1]
        if f[ALL_FEATURES].isna().any():
            continue
        prob = float(model.predict_proba([f[ALL_FEATURES].values])[0, 1])
        em = expected_move(prob, cal)
        gs = gap_stats(t) or {}
        mg = (model_gap_stats(t, oos) or {}) if len(oos) else {}
        rec = dict(ticker=t, date=last_session, signal_time=f"{SCAN_HR} ET", entry="next_session_open",
                   prob=prob, **em, **mg, **gs,
                   open=day["open"], high=day["high"], low=day["low"],
                   close=day["close"], volume=day["volume"],
                   close_vs_vwap=day["close_vs_vwap"], close_pos=day["close_pos"],
                   last_hour_ret=day["last_hour_ret"])
        for col in ["ret_1", "ret_5", "ret_21", "rsi14", "atr14_pct", "vol_ratio",
                    "px_sma50", "px_sma200", "dist_52w_high", "dollar_vol21", "gap",
                    "streak", "body_pct", "range_ratio", "trend_sma20_50", "touch_high_5d",
                    "bbw_pct120", "adr_ratio_5_21", "vol_dry5", "quiet10",
                    "close_to_10d_high", "max_abs_ret10", "sma20_slope5"]:
            v = f.get(col)
            rec[col] = None if v is None or (isinstance(v, float) and np.isnan(v)) else float(v)
        rows.append(rec)
        time.sleep(0.02)

    if not rows:
        print("ERROR: no tickers scored — check data/intraday")
        raise SystemExit(1)

    scored = pd.DataFrame(rows)
    scored = scored.sort_values("prob", ascending=False).reset_index(drop=True)

    # ---- tiers ----
    pm, level = pre_move_tier(scored)
    scored["tier"] = "momentum"
    scored.loc[pm.index, "tier"] = "pre_move"
    pm_count = int((scored["tier"] == "pre_move").sum())
    print(f"tiers: pre_move={pm_count} (mask level {level}), momentum={len(scored) - pm_count}")

    scan = scored.sort_values(["tier", "prob"], ascending=[True, False]).reset_index(drop=True)
    scan.to_csv(os.path.join(OUT, "scan_results.csv"), index=False)
    scan.to_parquet(os.path.join(DATA, "live_scan.parquet"))

    # ---- tier summary (OOS backtest numbers for the dashboard footer) ----
    tier_summary = {}
    ts_path = os.path.join(DATA, "tier_summary.json")
    if os.path.exists(ts_path):
        try:
            tier_summary = json.load(open(ts_path))
        except Exception:
            tier_summary = {}

    # ---- метаданные для дашборда ----
    uni = pd.read_csv(os.path.join(DATA, "nasdaq_universe.csv"))
    meta = {
        "last_scan": last_session,
        "signal_time": f"{SCAN_HR} ET",
        "universe_total": int(len(uni)),
        "scanned": int(len(scan)),
        "pre_move_n": pm_count,
        "pre_move_mask_level": level,
        "calibration_source": cal_src,
        "tier_summary": tier_summary,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "universe_note": "Состав вселенной обновляется автоматически при каждом прогоне (Nasdaq.com screener): "
                         "новые IPO добавляются, делистинги/банкротства удаляются, "
                         "акции переходят границы по цене ≥$3 и капитализации ≥$500 млн.",
        "pre_move_note": "pre_move = аптренд (выше SMA50 и SMA200) + в пределах 15% от 52-нед максимума + "
                         "тихий день (<3%) + нет всплеска за неделю (<4%). Сигнал после закрытия, "
                         "вход по открытию следующей сессии 09:30 ET.",
    }
    json.dump(meta, open(os.path.join(OUT, "meta.json"), "w"), indent=1, ensure_ascii=False)
    print(f"\nsaved output/scan_results.csv ({len(scan)} rows) + meta.json")

    pm_show = scan[scan["tier"] == "pre_move"].head(12)
    cols = ["ticker", "close", "prob", "win", "loss", "avg_best", "avg_worst",
            "gap_sig_p", "ret_1", "ret_5", "dist_52w_high", "bbw_pct120", "vol_dry5"]
    pd.set_option("display.width", 220)
    print("\n=== PRE-MOVE TIER (top 12, сигнал после закрытия, вход по открытию завтра) ===")
    print(pm_show[cols].round(4).to_string(index=False))
    mom = scan[scan["tier"] == "momentum"].head(5)
    print("\n=== MOMENTUM TIER (top 5, для справки) ===")
    print(mom[["ticker", "close", "prob", "win"]].round(4).to_string(index=False))
    print("\n'close' = закрытие последней сессии (ОРИЕНТИР); фактический вход — по открытию следующего дня")


if __name__ == "__main__":
    main()
