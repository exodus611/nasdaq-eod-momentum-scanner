#!/usr/bin/env python3
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
print("=== PREP_PANEL START ===")
try:
    from backtest import load_panel, build_featured_panel
    import glob
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    hist_files = glob.glob(os.path.join(ROOT, "data", "hist_*.csv"))
    print(f"Found {len(hist_files)} hist files")
    if len(hist_files) < 5:
        print(f"ERROR: Only {len(hist_files)} hist files!"); sys.exit(1)
    panel = load_panel(min_files=5)
    print(f"Panel loaded: {len(panel):,} rows")
    feats = build_featured_panel(panel)
    print(f"Featured panel: {len(feats):,} rows, {feats['ticker'].nunique()} tickers")
    out = os.path.join(ROOT, "data", "featured_panel.parquet")
    feats.to_parquet(out)
    print(f"Saved {out}: {len(feats):,}")
    print("=== PREP_PANEL DONE ===")
except Exception as e:
    print(f"\n[ERROR] {e}")
    import traceback; traceback.print_exc(); sys.exit(1)
