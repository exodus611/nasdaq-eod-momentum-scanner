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
def build_featured_panel(panel, min_rows=250, min_dollar_vol=2e6, chunk=250):
    """Chunked build (250 tickers at a time) — memory-safe on 2-8GB runners.
    Features are per-ticker, so chunking does not change results."""
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
    sub = panel[panel["ticker"].isin(tickers_ok)]
    tmp = os.path.join(ROOT, "data", "_feat_tmp.parquet")
    tmp_parts = []
    tot = 0
    tickers_all = sorted(sub["ticker"].unique())
    for i in range(0, len(tickers_all), chunk):
        ct = tickers_all[i:i + chunk]
        cs = sub[sub["ticker"].isin(ct)]
        cf = cs.groupby("ticker", sort=False, group_keys=False).apply(_apply_features)
        if "ticker" not in cf.columns:
            cf["ticker"] = cs["ticker"].values if len(cf) == len(cs) else "UNKNOWN"
        cf = cf.dropna(subset=FEATURES + ["fwd1", "fwd2", "fwd2o", "path_win"])
        cf = cf[cf["dollar_vol21"] >= min_dollar_vol] if "dollar_vol21" in cf.columns else cf

        cf.to_parquet(tmp.replace(".parquet", f".{i}.parquet"))
        tmp_parts.append(tmp.replace(".parquet", f".{i}.parquet"))
        tot += len(cf)
        print(f"[build_featured] chunk {i // chunk + 1}/{(len(tickers_all) - 1) // chunk + 1}: +{len(cf):,} (total {tot:,})")
        del cf, cs
    feats = pd.concat([pd.read_parquet(p) for p in tmp_parts], ignore_index=True)
    for p in tmp_parts:
        os.remove(p)
    feats = feats.sort_values(["ticker", "date"]).reset_index(drop=True)
    before_liq = len(feats)
    print(f"[build_featured] After dropna+liquidity ${min_dollar_vol}: {len(feats):,}/{before_liq:,}")
    if len(feats) == 0:
        # liquidity fallback: rebuild once with $500k
        for i in range(0, len(tickers_all), chunk):
            ct = tickers_all[i:i + chunk]
            cs = sub[sub["ticker"].isin(ct)]
            cf = cs.groupby("ticker", sort=False, group_keys=False).apply(_apply_features)
            if "ticker" not in cf.columns:
                cf["ticker"] = cs["ticker"].values if len(cf) == len(cs) else "UNKNOWN"
            cf = cf.dropna(subset=FEATURES + ["fwd1", "fwd2", "fwd2o", "path_win"])
            cf = cf[cf["dollar_vol21"] >= 5e5] if "dollar_vol21" in cf.columns else cf
    
            feats = pd.concat([feats, cf], ignore_index=True)
        print(f"[build_featured] Fallback $500k: {len(feats):,}")
    hit_rate = feats["path_win"].mean() if "path_win" in feats.columns else 0
    ticker_count = feats["ticker"].nunique() if "ticker" in feats.columns else 0
    print(f"featured panel: {len(feats):,} rows, {ticker_count} tickers, base win rate = {hit_rate:.3f} ({time.time()-t0:.0f}s)")
    return feats
def pre_move_mask(feats):
    """Structural 'before the move' conditions, strict level (production).
    Validated OOS full NASDAQ (13m, ~1500 tickers, strict top-2/day, path labels:
    entry at next open, +2% target vs -3% stop, 48h): win=57.5%, loss=33.5%,
    EV=+0.15%/trade vs 54.4%/-0.09% without the mask.
    Conditions: uptrend above SMA50 & SMA200, within 15% of 52w high, quiet today
    (<3%), no spike this week (<4%), gently rising SMA20 slope, low 5d volume."""
    m = (feats["px_sma50"] > 0)
    m &= (feats["px_sma200"] > 0)
    m &= (feats["dist_52w_high"] > -0.15)
    m &= (feats["ret_1"].abs() < 0.03)
    m &= (feats["max_abs_ret10"] < 0.04)
    m &= (feats["trend_sma20_50"] > 0)
    m &= (feats["vol_dry5"] < 1.0)
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
            ytr = train["path_win"].values
            Xte = test[ALL_FEATURES].values
            model = HistGradientBoostingClassifier(max_iter=250, learning_rate=0.05, max_depth=5, min_samples_leaf=200, l2_regularization=1.0, random_state=42)
            model.fit(Xtr, ytr)
            test = test.copy()
            test["prob"] = model.predict_proba(Xte)[:, 1]
            test["model_idx"] = i
            results.append(test)
            top_hit = test.nlargest(int(len(test)*0.10),'prob')['path_win'].mean() if len(test) >= 10 else 0
            print(f"  OOS {test_m}: rows={len(test)}, base_win={test['path_win'].mean():.3f}, top10%={top_hit:.3f}")
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
        return {"label": label, "n": n, "win_rate": float(d["path_win"].mean()) if n else 0, "avg_best_move": float(d["best_fwdo"].mean()) if n else 0, "avg_fwd2": float(d["fwd2o"].mean()) if n else 0, "avg_worst": float(d["worst_fwdo"].mean()) if n else 0, "p95_best": float(d["best_fwdo"].quantile(0.95)) if n else 0}
    return stats(sel, "STRATEGY"), stats(base, "BASE_ALL")
def monthly_hits(oos, top_frac=0.10):
    ev = oos.copy()
    ev["selected"] = ev.groupby("model_idx")["prob"].rank(pct=True) >= (1 - top_frac)
    sel = ev[ev["selected"]]
    m = sel.groupby(sel["date"].dt.to_period("M")).agg(n=("ticker", "count"), hit=("path_win", "mean"), avg_best=("best_fwdo", "mean"))
    b = ev.groupby(ev["date"].dt.to_period("M"))["path_win"].mean().rename("base_win")
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
    base_m = oos.groupby(oos["date"].dt.to_period("M"))["path_win"].mean()
    top_m = top.groupby(months)["path_win"].mean()
    beat = int((top_m.reindex(base_m.index).fillna(0) >= base_m).sum())
    return {
        "oos_period": [str(oos["date"].min().date()), str(oos["date"].max().date())],
        "base_win": round(float(oos["path_win"].mean()), 4),
        "pre_move": {
            "win": round(float(top["path_win"].mean()), 4),
            "loss": round(float(top["path_loss"].mean()), 4),
            "neutral": round(float(top["path_neutral"].mean()), 4),
            "avg_best": round(float(top["best_fwdo"].mean()), 4),
            "avg_worst": round(float(top["worst_fwdo"].mean()), 4),
            "ev_per_trade": round(float((top["path_win"] * 0.02 - top["path_loss"] * 0.03).mean()), 4),
            "per_day": round(float(per_day), 1),
            "months_beat_base": f"{beat}/{len(base_m)}",
        },
        "momentum": {
            "win": round(float(mom["path_win"].mean()), 4),
            "loss": round(float(mom["path_loss"].mean()), 4),
            "avg_best": round(float(mom["best_fwdo"].mean()), 4),
            "avg_worst": round(float(mom["worst_fwdo"].mean()), 4),
        },
    }

if __name__ == "__main__":
    print("=== BACKTEST START ===")
    try:
        import time as _t
        out_path = os.path.join(ROOT, "data", "featured_panel.parquet")
        fresh = os.path.exists(out_path) and _t.time() - os.path.getmtime(out_path) < 3 * 3600
        if fresh:
            feats = pd.read_parquet(out_path)
            if "path_win" not in feats.columns:
                fresh = False
                print("featured panel lacks path_win -> rebuild")
        if fresh:
            print(f"Reusing fresh {out_path}: {len(feats):,} rows")
        else:
            panel = load_panel()
            feats = build_featured_panel(panel)
            feats.to_parquet(out_path)
            print(f"Saved {out_path}: {len(feats):,}")
        print("\n=== WALK-FORWARD BACKTEST ===")
        oos, models = walk_forward(feats)
        oos_path = os.path.join(ROOT, "data", "oos_predictions.parquet")
        oos.to_parquet(oos_path)
        json.dump({"n_features": len(ALL_FEATURES),
                   "features_version": "pre-move-v1",
                   "label_version": "path_win_v1",
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
