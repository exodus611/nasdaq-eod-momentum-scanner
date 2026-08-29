#!/usr/bin/env python3
"""Walk-forward backtest of the EOD scanner strategy."""
import os
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier

from features import FEATURES

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_panel():
    """Load all per-ticker CSVs into one long panel with features."""
    import glob
    frames = []
    for f in glob.glob(os.path.join(ROOT, "data", "hist_*.csv")):
        t = f.split("hist_")[1].replace(".csv", "")
        df = pd.read_csv(f, parse_dates=["date"])
        df["ticker"] = t
        frames.append(df)
    panel = pd.concat(frames, ignore_index=True)
    panel = panel.sort_values(["ticker", "date"]).reset_index(drop=True)
    print("panel rows:", len(panel), "tickers:", panel["ticker"].nunique())
    return panel


def _apply_features(group):
    from features import add_indicators
    return add_indicators(group)


def build_featured_panel(panel, min_rows=250, min_dollar_vol=2e6):
    import time
    t0 = time.time()
    g = panel.groupby("ticker", sort=False)
    keep = g.size()
    tickers_ok = keep[keep >= min_rows].index
    panel = panel[panel["ticker"].isin(tickers_ok)].copy()
    feats = panel.groupby("ticker", sort=False, group_keys=False).apply(_apply_features)
    feats = feats.dropna(subset=FEATURES + ["fwd1", "fwd2"])
    # liquidity filter: dollar volume
    feats = feats[feats["dollar_vol21"] >= min_dollar_vol]
    print(f"featured panel: {len(feats):,} rows, {feats['ticker'].nunique()} tickers, "
          f"base hit-rate (+2% in 2d) = {feats['target_2pct'].mean():.3f} ({time.time()-t0:.0f}s)")
    return feats


def walk_forward(feats, test_months=12, warmup_months=8, step="MS"):
    """Train expanding on past, predict on next month. Returns OOS predictions."""
    feats = feats.copy()
    dates = feats["date"]
    first = dates.min()
    # month buckets
    feats["ym"] = dates.dt.to_period("M")
    months = sorted(feats["ym"].unique())
    train_end_idx = warmup_months  # first `warmup` months are initial train
    results = []
    models = []

    for i in range(warmup_months, len(months)):
        test_m = months[i]
        test = feats[feats["ym"] == test_m]
        if len(test) < 500:
            continue
        train = feats[feats["ym"] < test_m]
        if len(train) < 20000:
            continue
        Xtr = train[FEATURES].values
        ytr = train["target_2pct"].values
        Xte = test[FEATURES].values
        model = HistGradientBoostingClassifier(
            max_iter=250, learning_rate=0.05, max_depth=5,
            min_samples_leaf=200, l2_regularization=1.0,
            random_state=42)
        model.fit(Xtr, ytr)
        test = test.copy()
        test["prob"] = model.predict_proba(Xte)[:, 1]
        test["model_idx"] = i
        results.append(test)
        models.append(model)
        print(f"  OOS month {test_m}: rows={len(test)}, base hit={test['target_2pct'].mean():.3f}, "
              f"top10% hit={test.nlargest(int(len(test)*0.10),'prob')['target_2pct'].mean():.3f}")

    oos = pd.concat(results, ignore_index=True)
    return oos, models


def eval_strategy(oos, top_frac=0.10, min_prob=None):
    """Evaluate buying top-ranked names at close, holding 1-2 sessions."""
    ev = oos.copy()
    if min_prob is None:
        ev["selected"] = ev.groupby("model_idx")["prob"].rank(pct=True) >= (1 - top_frac)
    else:
        ev["selected"] = ev["prob"] >= min_prob

    sel = ev[ev["selected"]]
    base = ev

    def stats(d, label):
        n = len(d)
        hit = d["target_2pct"].mean()
        avg_best = d["best_fwd"].mean()
        avg_fwd2 = d["fwd2"].mean()
        worst = d["worst_fwd"].min()
        p95_best = d["best_fwd"].quantile(0.95)
        avg_worst = d["worst_fwd"].mean()
        return {
            "label": label, "n": n, "hit_rate_2pct": hit,
            "avg_best_move": avg_best, "avg_fwd2": avg_fwd2,
            "avg_worst": avg_worst, "p95_best": p95_best,
        }

    return stats(sel, "STRATEGY"), stats(base, "BASE_ALL")


def monthly_hits(oos, top_frac=0.10):
    ev = oos.copy()
    ev["selected"] = ev.groupby("model_idx")["prob"].rank(pct=True) >= (1 - top_frac)
    sel = ev[ev["selected"]]
    m = sel.groupby(sel["date"].dt.to_period("M")).agg(
        n=("ticker", "count"), hit=("target_2pct", "mean"), avg_best=("best_fwd", "mean"))
    b = ev.groupby(ev["date"].dt.to_period("M"))["target_2pct"].mean().rename("base_hit")
    return m.join(b)


if __name__ == "__main__":
    from features import add_indicators  # noqa
    panel = load_panel()
    feats = build_featured_panel(panel)
    feats.to_parquet(os.path.join(ROOT, "data", "featured_panel.parquet"))
    print("\n=== WALK-FORWARD BACKTEST ===")
    oos, models = walk_forward(feats)
    oos.to_parquet(os.path.join(ROOT, "data", "oos_predictions.parquet"))
    strat, base = eval_strategy(oos, top_frac=0.10)
    print("\n", pd.DataFrame([strat, base]).T)
    mh = monthly_hits(oos, top_frac=0.10)
    print("\nmonthly:", mh.round(3).to_string())
