#!/usr/bin/env python3
"""Feature engineering for the EOD momentum strategy."""
import numpy as np
import pandas as pd

REQUIRED_COLS = ["open", "high", "low", "close", "volume"]


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add technical indicators (no forward-looking leakage)."""
    df = df.copy()
    c = df["close"]

    # --- returns ---
    for n in (1, 2, 3, 5, 10, 21):
        df[f"ret_{n}"] = c.pct_change(n)

    # --- volume ---
    vol = df["volume"].replace(0, np.nan)
    df["vol_ratio"] = vol / vol.rolling(20).mean().shift(1)

    # --- candle geometry ---
    rng = df["high"] - df["low"]
    df["close_pos"] = (c - df["low"]) / rng.replace(0, np.nan)
    df["upper_shadow"] = (df["high"] - df[["open", "close"]].max(axis=1)) / rng.replace(0, np.nan)
    df["lower_shadow"] = (df[["open", "close"]].min(axis=1) - df["low"]) / rng.replace(0, np.nan)
    body = (df["close"] - df["open"]).abs()
    df["body_pct"] = body / df["open"]

    # --- gaps ---
    df["gap"] = df["open"].pct_change()

    # --- RSI(14) Wilder ---
    delta = c.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df["rsi14"] = 100 - 100 / (1 + rs)

    # --- moving averages & trend ---
    for n in (20, 50):
        df[f"sma{n}"] = c.rolling(n).mean()
    df["sma200"] = c.rolling(200, min_periods=120).mean()
    df["ema20"] = c.ewm(span=20, adjust=False).mean()
    df["ema50"] = c.ewm(span=50, adjust=False).mean()
    df["px_sma50"] = (c - df["sma50"]) / df["sma50"]
    df["px_sma200"] = (c - df["sma200"]) / df["sma200"]
    df["trend_sma20_50"] = (df["sma20"] - df["sma50"]) / df["sma50"]
    df["trend_ema20_50"] = (df["ema20"] - df["ema50"]) / df["ema50"]

    # --- volatility ---
    tr = pd.concat([df["high"] - df["low"],
                    (df["high"] - c.shift(1)).abs(),
                    (df["low"] - c.shift(1)).abs()], axis=1).max(axis=1)
    df["atr14"] = tr.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
    df["atr14_pct"] = df["atr14"] / c
    df["adr10"] = (df["high"] - df["low"]).rolling(10).mean() / c
    df["range_ratio"] = rng / (df["high"] - df["low"]).rolling(10).mean().shift(1)

    # --- distance from 52-week extremes ---
    hh52 = df["high"].rolling(252, min_periods=120).max()
    ll52 = df["low"].rolling(252, min_periods=120).min()
    df["dist_52w_high"] = (c - hh52) / hh52
    df["dist_52w_low"] = (c - ll52) / ll52

    # --- streak ---
    up = (c.diff() > 0).astype(int)
    streak = []
    cur = 0
    prev_dir = 0
    for u in up:
        if u == 1:
            cur = cur + 1 if prev_dir == 1 else 1
            prev_dir = 1
        else:
            cur = cur - 1 if prev_dir == -1 else -1
            prev_dir = -1
        streak.append(cur)
    df["streak"] = streak

    # --- dollar volume (liquidity) ---
    df["dollar_vol21"] = (df["close"] * df["volume"]).rolling(21).mean()

    # --- recent high-touch ---
    df["touch_high_5d"] = (c.rolling(5).max() - df["sma20"]) / df["sma20"]

    # --- forward labels (for training) ---
    f1 = c.shift(-1) / c - 1
    f2 = c.shift(-2) / c - 1
    df["fwd1"] = f1
    df["fwd2"] = f2
    df["best_fwd"] = pd.concat([f1, f2], axis=1).max(axis=1)  # best move within 2 sessions
    df["worst_fwd"] = pd.concat([f1, f2], axis=1).min(axis=1)
    df["target_2pct"] = (df["best_fwd"] >= 0.02).astype(float)  # >= +2% within 2 sessions

    return df


FEATURES = [
    "ret_1", "ret_2", "ret_3", "ret_5", "ret_10", "ret_21",
    "vol_ratio", "close_pos", "upper_shadow", "lower_shadow", "body_pct", "gap",
    "rsi14", "px_sma50", "px_sma200", "trend_sma20_50", "trend_ema20_50",
    "atr14_pct", "adr10", "range_ratio", "dist_52w_high", "dist_52w_low",
    "streak", "touch_high_5d",
]
