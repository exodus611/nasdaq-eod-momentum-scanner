#!/usr/bin/env python3
"""Walk-forward backtest - ROBUST v3 FIXED."""
import os, sys, json, warnings, numpy as np, pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from features import FEATURES, COIL_FEATURES, ALL_FEATURES
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)
def load_panel(min_files=10):
    import glob
    pattern = os.path.join(ROOT, "data", "hist_*.csv")
    files = glob.glob(pattern)
    print(f"[load_panel] Found {len(files)} hist files")
    if len(files) < min_files:
        raise FileNotFoundError(f"No hist files")
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
        except:
            failed += 1
            continue
    if not frames:
        raise ValueError(f"All files failed")
    panel = pd.concat(frames, ignore_index=True)
    panel = panel.sort_values(["ticker", "date"]).reset_index(drop=True)
    print(f"panel rows: {len(panel):,} tickers: {panel['ticker'].nunique()} (failed: {failed})")
    return panel
def _apply_features(group):
    from features import add_indicators
    try:
        result = add_indicators(group)
        if "ticker" not in result.columns and "ticker" in group.columns:
            result["ticker"] = group["ticker"].iloc[0]
        return result
    except Exception as e:
        print(f"[add_indicators] Failed: {e}")
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
    print(f"[build_featured] Keeping {len(tickers_ok)}/{len(keep)} tickers")
    if len(tickers_ok) == 0:
        tickers_ok = keep[keep >= 120].index
        print(f"[build_featured] Fallback {len(tickers_ok)}")
        if len(tickers_ok) == 0:
            raise ValueError("No tickers")
    panel = panel[panel["ticker"].isin(tickers_ok)].copy()
    print(f"[build_featured] Applying indicators to {panel['ticker'].nunique()} tickers...")
    feats = panel.groupby("ticker", sort=False, group_keys=False).apply(_apply_features)
    if "ticker" not in feats.columns:
        print(f"[build_featured] WARNING: ticker missing, restoring...")
        if len(feats) == len(panel):
            feats["ticker"] = panel["ticker"].values
        else:
            raise ValueError(f"ticker missing, cols: {feats.columns.tolist()}")
    before = len(feats)
    feats = feats.dropna(subset=FEATURES + ["fwd1", "fwd2"])
    print(f"[build_featured] After dropna: {len(feats):,}/{before:,}")
    if len(feats) == 0:
        raise ValueError("All dropped")
    before_liq = len(feats)
    feats = feats[feats["dollar_vol21"] >= min_dollar_vol]
    print(f"[build_featured] After liquidity ${min_dollar_vol}: {len(feats):,}/{before_liq:,}")
    if len(feats) == 0:
        feats = panel.groupby("ticker", sort=False, group_keys=False).apply(_apply_features)
        if "ticker" not in feats.columns:
            feats["ticker"] = panel["ticker"].values if len(feats) == len(panel) else "UNKNOWN"
        feats = feats.dropna(subset=FEATURES + ["fwd1", "fwd2"])
        feats = feats[feats["dollar_vol21"] >= 5e5]
        print(f"[build_featured] Fallback $500k: {len(feats):,}")
    hit_rate = feats["target_2pct"].mean() if "target_2pct" in feats.columns else 0
    ticker_count = feats["ticker"].nunique() if "ticker" in feats.columns else 0
    print(f"featured panel: {len(feats):,} rows, {ticker_count} tickers, base hit-rate = {hit_rate:.3f} ({time.time()-t0:.0f}s)")
    return feats
def pre_move_mask(feats):
    """Structural 'before the move' conditions (validated OOS, top-2/day 37.8% vs base 30.9%):
    uptrend above SMA50 AND SMA200, within 15% of 52w high, quiet today, no spike this week."""
    m = (feats["px_sma50"] > 0)
    m &= (feats["px_sma200"] > 0)
    m &= (feats["dist_52w_high"] > -0.15)
    m &= (feats["ret_1"].abs() < 0.03)
    m &= (feats["max_abs_ret10"] < 0.04)
    return m.fillna(False)

def walk_forward(feats, warmup_months=8):
    feats = feats.copy()
    feats["ym"] = feats["date"].dt.to_period("M")
    months = sorted(feats["ym"].unique())
    print(f"[walk_forward] Months: {len(months)} from {months[0]} to {months[-1]}")
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
            Xtr = train[ALL_FEATURES].values
            ytr = train["target_2pct"].values
            Xte = test[ALL_FEATURES].values
            model = HistGradientBoostingClassifier(max_iter=250, learning_rate=0.05, max_depth=5, min_samples_leaf=200, l2_regularization=1.0, random_state=42)
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
        raise ValueError("No OOS")
    oos = pd.concat(results, ignore_index=True)
    print(f"[walk_forward] OOS total: {len(oos):,}")
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
        return {"label": label, "n": n, "hit_rate_2pct": float(d["target_2pct"].mean()) if n else 0, "avg_best_move": float(d["best_fwd"].mean()) if n else 0, "avg_fwd2": float(d["fwd2"].mean()) if n else 0, "avg_worst": float(d["worst_fwd"].mean()) if n else 0, "p95_best": float(d["best_fwd"].quantile(0.95)) if n else 0}
    return stats(sel, "STRATEGY"), stats(base, "BASE_ALL")
def monthly_hits(oos, top_frac=0.10):
    ev = oos.copy()
    ev["selected"] = ev.groupby("model_idx")["prob"].rank(pct=True) >= (1 - top_frac)
    sel = ev[ev["selected"]]
    m = sel.groupby(sel["date"].dt.to_period("M")).agg(n=("ticker", "count"), hit=("target_2pct", "mean"), avg_best=("best_fwd", "mean"))
    b = ev.groupby(ev["date"].dt.to_period("M"))["target_2pct"].mean().rename("base_hit")
    return m.join(b)
def tier_report(oos):
    """Pre-move tier (strict structural mask) vs momentum tier, both ranked by OOS prob."""
    o = oos.copy()
    o["s"] = o.groupby("model_idx")["prob"].rank(pct=True) >= 0.90
    mom = o[o["s"]]
    sub = o[pre_move_mask(o)].copy()
    sub["sel"] = sub.groupby("model_idx")["prob"].rank(pct=True) >= 0.90
    top = sub[sub["sel"]]
    per_day = top.groupby("date").size().mean()
    months = top["date"].dt.to_period("M")
    base_m = oos.groupby(oos["date"].dt.to_period("M"))["target_2pct"].mean()
    top_m = top.groupby(months)["target_2pct"].mean()
    beat = int((top_m.reindex(base_m.index).fillna(0) >= base_m).sum())
    return {
        "oos_period": [str(oos["date"].min().date()), str(oos["date"].max().date())],
        "base_hit": round(float(oos["target_2pct"].mean()), 4),
        "pre_move": {
            "hit": round(float(top["target_2pct"].mean()), 4),
            "avg_best": round(float(top["best_fwd"].mean()), 4),
            "avg_fwd2": round(float(top["fwd2"].mean()), 4),
            "avg_worst": round(float(top["worst_fwd"].mean()), 4),
            "per_day": round(float(per_day), 1),
            "months_beat_base": f"{beat}/{len(base_m)}",
        },
        "momentum": {
            "hit": round(float(mom["target_2pct"].mean()), 4),
            "avg_best": round(float(mom["best_fwd"].mean()), 4),
            "avg_worst": round(float(mom["worst_fwd"].mean()), 4),
        },
    }

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
        json.dump({"n_features": len(ALL_FEATURES),
                   "features_version": "pre-move-v1",
                   "built_utc": pd.Timestamp.utcnow().isoformat()},
                  open(os.path.join(ROOT, "data", "oos_model_version.json"), "w"), indent=1)
        print(f"Saved {oos_path}: {len(oos):,}")
        strat, base = eval_strategy(oos, top_frac=0.10)
        print("\n", pd.DataFrame([strat, base]).T)
        mh = monthly_hits(oos, top_frac=0.10)
        print("\nmonthly:", mh.round(3).to_string())
        tr = tier_report(oos)
        json.dump(tr, open(os.path.join(ROOT, "data", "tier_summary.json"), "w"), indent=1)
        print("\n=== TIER REPORT (pre-move vs momentum) ===")
        print(json.dumps(tr, indent=1))
        print("\n=== BACKTEST DONE ===")
    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback; traceback.print_exc(); sys.exit(1)
