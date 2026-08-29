#!/usr/bin/env python3
"""Walk-forward backtest of the EOD scanner strategy - ROBUST v3 FIXED."""
import os
import sys
import warnings
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier

from features import FEATURES

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Suppress FutureWarning about groupby
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)

def load_panel(min_files=10):
    """Load all per-ticker CSVs into one long panel."""
    import glob
    pattern = os.path.join(ROOT, "data", "hist_*.csv")
    files = glob.glob(pattern)
    print(f"[load_panel] Found {len(files)} hist files")
    
    if len(files) < min_files:
        print(f"[load_panel] ERROR: Only {len(files)} files found, need at least {min_files}")
        if len(files) == 0:
            raise FileNotFoundError(f"No hist files found in data/. Run download_history.py first.")
    
    frames = []
    failed = 0
    for f in files:
        try:
            t = os.path.basename(f).split("hist_")[1].replace(".csv", "")
            df = pd.read_csv(f, parse_dates=["date"])
            if len(df) < 50:
                failed += 1
                continue
            df["ticker"] = t
            frames.append(df)
        except Exception as e:
            failed += 1
            continue
    
    if not frames:
        raise ValueError(f"All {len(files)} files failed to load")
    
    panel = pd.concat(frames, ignore_index=True)
    panel = panel.sort_values(["ticker", "date"]).reset_index(drop=True)
    print(f"panel rows: {len(panel):,} tickers: {panel['ticker'].nunique()} (failed: {failed})")
    return panel


def _apply_features(group):
    from features import add_indicators
    try:
        result = add_indicators(group)
        # Ensure ticker column preserved
        if "ticker" not in result.columns and "ticker" in group.columns:
            result["ticker"] = group["ticker"].iloc[0]
        return result
    except Exception as e:
        print(f"[add_indicators] Failed for {group['ticker'].iloc[0] if 'ticker' in group.columns else 'unknown'}: {e}")
        return group


def build_featured_panel(panel, min_rows=250, min_dollar_vol=2e6):
    import time
    t0 = time.time()
    
    if len(panel) == 0:
        raise ValueError("Empty panel")
    
    g = panel.groupby("ticker", sort=False)
    keep = g.size()
    print(f"[build_featured] Ticker counts: min={keep.min()}, max={keep.max()}, mean={keep.mean():.0f}")
    tickers_ok = keep[keep >= min_rows].index
    print(f"[build_featured] Keeping {len(tickers_ok)}/{len(keep)} tickers with >= {min_rows} rows")
    
    if len(tickers_ok) == 0:
        print(f"[build_featured] No tickers with {min_rows} rows, trying 120")
        tickers_ok = keep[keep >= 120].index
        print(f"[build_featured] Fallback keeping {len(tickers_ok)} tickers")
        if len(tickers_ok) == 0:
            raise ValueError(f"No tickers with enough rows. Max: {keep.max()}")
    
    panel = panel[panel["ticker"].isin(tickers_ok)].copy()
    
    # FIXED: Don't use include_groups=False - it removes ticker column in new pandas
    # Use group_keys=False and handle FutureWarning via warnings filter
    print(f"[build_featured] Applying indicators to {panel['ticker'].nunique()} tickers...")
    feats = panel.groupby("ticker", sort=False, group_keys=False).apply(_apply_features)
    
    # Ensure ticker column exists after groupby apply
    if "ticker" not in feats.columns:
        print(f"[build_featured] WARNING: ticker column missing after groupby, restoring...")
        # Try to restore from index or original
        # In some pandas versions, ticker becomes index level
        if feats.index.nlevels > 1 or "ticker" in str(feats.index.names):
            try:
                feats = feats.reset_index()
            except:
                pass
        # If still missing, merge back
        if "ticker" not in feats.columns:
            # Reconstruct: panel has ticker, feats should have same length as panel after filtering?
            # For safety, we add ticker from panel's last known mapping
            # This is fallback - better to re-apply without groupby
            print(f"[build_featured] CRITICAL: ticker still missing, columns: {feats.columns.tolist()[:10]}")
            # As last resort, use panel's ticker where possible
            # feats should have same order as panel after groupby apply
            if len(feats) == len(panel):
                feats["ticker"] = panel["ticker"].values
            else:
                # Try to get ticker from original group
                raise ValueError(f"ticker column missing after groupby apply, columns: {feats.columns.tolist()}")
    
    before = len(feats)
    feats = feats.dropna(subset=FEATURES + ["fwd1", "fwd2"])
    print(f"[build_featured] After dropna: {len(feats):,}/{before:,} rows ({len(feats)/before:.1%})")
    
    if len(feats) == 0:
        raise ValueError("All rows dropped after feature NA check")
    
    before_liq = len(feats)
    feats = feats[feats["dollar_vol21"] >= min_dollar_vol]
    print(f"[build_featured] After liquidity ${min_dollar_vol:,.0f}: {len(feats):,}/{before_liq:,}")
    
    if len(feats) == 0:
        print(f"[build_featured] No rows after liquidity, trying $500k")
        # Re-apply with lower threshold
        feats = panel.groupby("ticker", sort=False, group_keys=False).apply(_apply_features)
        if "ticker" not in feats.columns:
            feats["ticker"] = panel["ticker"].values if len(feats) == len(panel) else "UNKNOWN"
        feats = feats.dropna(subset=FEATURES + ["fwd1", "fwd2"])
        feats = feats[feats["dollar_vol21"] >= 5e5]
        print(f"[build_featured] Fallback $500k: {len(feats):,}")
        if len(feats) == 0:
            raise ValueError(f"No rows after liquidity filter")
    
    hit_rate = feats["target_2pct"].mean() if "target_2pct" in feats.columns else 0
    ticker_count = feats["ticker"].nunique() if "ticker" in feats.columns else 0
    print(f"featured panel: {len(feats):,} rows, {ticker_count} tickers, "
          f"base hit-rate = {hit_rate:.3f} ({time.time()-t0:.0f}s)")
    return feats


def walk_forward(feats, warmup_months=8):
    feats = feats.copy()
    if len(feats) < 1000:
        print(f"[walk_forward] WARNING: Only {len(feats)} rows")
    
    feats["ym"] = feats["date"].dt.to_period("M")
    months = sorted(feats["ym"].unique())
    print(f"[walk_forward] Months: {len(months)} from {months[0]} to {months[-1]}, warmup {warmup_months}")
    
    results = []
    for i in range(warmup_months, len(months)):
        test_m = months[i]
        test = feats[feats["ym"] == test_m]
        if len(test) < 200:
            continue
        train = feats[feats["ym"] < test_m]
        if len(train) < 5000:
            continue
        try:
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
            top_hit = test.nlargest(int(len(test)*0.10),'prob')['target_2pct'].mean() if len(test) >= 10 else 0
            print(f"  OOS {test_m}: rows={len(test)}, base={test['target_2pct'].mean():.3f}, top10%={top_hit:.3f}")
        except Exception as e:
            print(f"  Failed {test_m}: {e}")
            continue
    
    if not results:
        raise ValueError("No OOS results")
    
    oos = pd.concat(results, ignore_index=True)
    print(f"[walk_forward] OOS total: {len(oos):,} rows, {oos['model_idx'].nunique()} months")
    return oos, []


def eval_strategy(oos, top_frac=0.10, min_prob=None):
    ev = oos.copy()
    if min_prob is None:
        ev["selected"] = ev.groupby("model_idx")["prob"].rank(pct=True) >= (1 - top_frac)
    else:
        ev["selected"] = ev["prob"] >= min_prob
    sel = ev[ev["selected"]]
    base = ev
    def stats(d, label):
        n = len(d)
        return {
            "label": label, "n": n, "hit_rate_2pct": float(d["target_2pct"].mean()) if n else 0,
            "avg_best_move": float(d["best_fwd"].mean()) if n else 0,
            "avg_fwd2": float(d["fwd2"].mean()) if n else 0,
            "avg_worst": float(d["worst_fwd"].mean()) if n else 0,
            "p95_best": float(d["best_fwd"].quantile(0.95)) if n else 0,
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
    print("=== BACKTEST START ===")
    try:
        panel = load_panel()
        feats = build_featured_panel(panel)
        out_path = os.path.join(ROOT, "data", "featured_panel.parquet")
        feats.to_parquet(out_path)
        print(f"Saved {out_path}: {len(feats):,}")
        
        print("\n=== WALK-FORWARD BACKTEST ===")
        oos, models = walk_forward(feats)
        oos_path = os.path.join(ROOT, "data", "oos_predictions.parquet")
        oos.to_parquet(oos_path)
        print(f"Saved {oos_path}: {len(oos):,}")
        
        strat, base = eval_strategy(oos, top_frac=0.10)
        print("\n", pd.DataFrame([strat, base]).T)
        mh = monthly_hits(oos, top_frac=0.10)
        print("\nmonthly:", mh.round(3).to_string())
        print("\n=== BACKTEST DONE ===")
    except Exception as e:
        print(f"\n[ERROR] Backtest failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
