#!/usr/bin/env python3
import numpy as np, pandas as pd
REQUIRED_COLS = ["open", "high", "low", "close", "volume"]
def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    if len(df) < 20:
        return df
    df = df.copy()
    for col in REQUIRED_COLS:
        if col not in df.columns:
            raise ValueError(f"Missing {col}")
    c = df["close"]
    if c.isna().all():
        return df
    for n in (1, 2, 3, 5, 10, 21):
        try:
            df[f"ret_{n}"] = c.pct_change(n)
        except:
            df[f"ret_{n}"] = np.nan
    try:
        vol = df["volume"].replace(0, np.nan)
        df["vol_ratio"] = vol / vol.rolling(20).mean().shift(1)
    except:
        df["vol_ratio"] = np.nan
    try:
        rng = df["high"] - df["low"]
        df["close_pos"] = (c - df["low"]) / rng.replace(0, np.nan)
        df["upper_shadow"] = (df["high"] - df[["open", "close"]].max(axis=1)) / rng.replace(0, np.nan)
        df["lower_shadow"] = (df[["open", "close"]].min(axis=1) - df["low"]) / rng.replace(0, np.nan)
        body = (df["close"] - df["open"]).abs()
        df["body_pct"] = body / df["open"].replace(0, np.nan)
    except:
        df["close_pos"] = 0.5; df["upper_shadow"] = 0; df["lower_shadow"] = 0; df["body_pct"] = 0
    try:
        df["gap"] = df["open"].pct_change()
    except:
        df["gap"] = 0
    try:
        delta = c.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        df["rsi14"] = 100 - 100 / (1 + rs)
    except:
        df["rsi14"] = 50
    try:
        for n in (20, 50):
            df[f"sma{n}"] = c.rolling(n).mean()
        df["sma200"] = c.rolling(200, min_periods=120).mean()
        df["ema20"] = c.ewm(span=20, adjust=False).mean()
        df["ema50"] = c.ewm(span=50, adjust=False).mean()
        df["px_sma50"] = (c - df["sma50"]) / df["sma50"]
        df["px_sma200"] = (c - df["sma200"]) / df["sma200"]
        df["trend_sma20_50"] = (df["sma20"] - df["sma50"]) / df["sma50"]
        df["trend_ema20_50"] = (df["ema20"] - df["ema50"]) / df["ema50"]
    except:
        for col in ["sma20","sma50","sma200","ema20","ema50","px_sma50","px_sma200","trend_sma20_50","trend_ema20_50"]:
            if col not in df.columns:
                df[col] = np.nan
    try:
        tr = pd.concat([df["high"] - df["low"], (df["high"] - c.shift(1)).abs(), (df["low"] - c.shift(1)).abs()], axis=1).max(axis=1)
        df["atr14"] = tr.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
        df["atr14_pct"] = df["atr14"] / c
        df["adr10"] = (df["high"] - df["low"]).rolling(10).mean() / c
        df["range_ratio"] = (df["high"] - df["low"]) / (df["high"] - df["low"]).rolling(10).mean().shift(1)
    except:
        df["atr14"] = np.nan; df["atr14_pct"] = 0.05; df["adr10"] = 0.05; df["range_ratio"] = 1.0
    try:
        hh52 = df["high"].rolling(252, min_periods=120).max()
        ll52 = df["low"].rolling(252, min_periods=120).min()
        df["dist_52w_high"] = (c - hh52) / hh52
        df["dist_52w_low"] = (c - ll52) / ll52
    except:
        df["dist_52w_high"] = 0; df["dist_52w_low"] = 0
    try:
        up = (c.diff() > 0).astype(int)
        streak = []; cur = 0; prev_dir = 0
        for u in up:
            if u == 1:
                cur = cur + 1 if prev_dir == 1 else 1; prev_dir = 1
            else:
                cur = cur - 1 if prev_dir == -1 else -1; prev_dir = -1
            streak.append(cur)
        df["streak"] = streak
    except:
        df["streak"] = 0
    try:
        df["dollar_vol21"] = (df["close"] * df["volume"]).rolling(21).mean()
    except:
        df["dollar_vol21"] = 1e6
    # ---- pre-move / coil features: is the stock COILING before a move? ----
    try:
        sma20c = c.rolling(20).mean()
        sd20 = c.rolling(20).std()
        df["bbw"] = (4 * sd20) / sma20c                       # Bollinger width (20,2)
        df["bbw_pct120"] = df["bbw"].rolling(120, min_periods=60).rank(pct=True)  # low = squeeze
        rngc = (df["high"] - df["low"]) / c
        df["adr_ratio_5_21"] = rngc.rolling(5).mean() / rngc.rolling(21).mean()   # <1 = range contracting
        v2 = df["volume"].replace(0, np.nan)
        vr2 = v2 / v2.rolling(20).mean().shift(1)
        df["vol_dry5"] = vr2.rolling(5).mean()                # <1 = volume drying up
        r1c = c.pct_change()
        df["ret5_std"] = r1c.rolling(5).std()                 # tightness of the coil
        df["ret5_std_atr"] = df["ret5_std"] / df["atr14_pct"].replace(0, np.nan)
        df["quiet10"] = (r1c.abs() < 0.015).rolling(10).sum() # quiet days in last 10
        df["close_to_10d_high"] = c / c.rolling(10).max() - 1 # coiling near top of base
        df["range10_pct"] = (df["high"].rolling(10).max() - df["low"].rolling(10).min()) / c
        df["range10_pct120"] = df["range10_pct"].rolling(120, min_periods=60).rank(pct=True)
        df["sma20_slope5"] = sma20c / sma20c.shift(5) - 1     # gentle upward base slope
        df["max_abs_ret10"] = r1c.abs().rolling(10).max()     # <4% = no spike in the coil
    except:
        for col in ["bbw","bbw_pct120","adr_ratio_5_21","vol_dry5","ret5_std","ret5_std_atr",
                    "quiet10","close_to_10d_high","range10_pct","range10_pct120",
                    "sma20_slope5","max_abs_ret10"]:
            if col not in df.columns:
                df[col] = np.nan
    try:
        df["touch_high_5d"] = (c.rolling(5).max() - df["sma20"]) / df["sma20"]
    except:
        df["touch_high_5d"] = 0
    try:
        f1 = c.shift(-1) / c - 1
        f2 = c.shift(-2) / c - 1
        df["fwd1"] = f1; df["fwd2"] = f2
        df["best_fwd"] = pd.concat([f1, f2], axis=1).max(axis=1)
        df["worst_fwd"] = pd.concat([f1, f2], axis=1).min(axis=1)
        df["target_2pct"] = (df["best_fwd"] >= 0.02).astype(float)
    except:
        df["fwd1"] = 0; df["fwd2"] = 0; df["best_fwd"] = 0; df["worst_fwd"] = 0; df["target_2pct"] = 0
    return df
FEATURES = ["ret_1", "ret_2", "ret_3", "ret_5", "ret_10", "ret_21", "vol_ratio", "close_pos", "upper_shadow", "lower_shadow", "body_pct", "gap", "rsi14", "px_sma50", "px_sma200", "trend_sma20_50", "trend_ema20_50", "atr14_pct", "adr10", "range_ratio", "dist_52w_high", "dist_52w_low", "streak", "touch_high_5d"]

# Pre-move / coil features: volatility contraction + base structure (stocks "before the move")
COIL_FEATURES = ["bbw", "bbw_pct120", "adr_ratio_5_21", "vol_dry5", "ret5_std", "ret5_std_atr",
                 "quiet10", "close_to_10d_high", "range10_pct", "range10_pct120",
                 "sma20_slope5", "max_abs_ret10"]

# Full feature set used by the model (base momentum + coil)
ALL_FEATURES = FEATURES + COIL_FEATURES
