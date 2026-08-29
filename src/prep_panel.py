#!/usr/bin/env python3
"""Rebuild the featured panel (features + labels) from stored history CSVs."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
from backtest import load_panel, build_featured_panel

if __name__ == "__main__":
    panel = load_panel()
    feats = build_featured_panel(panel)
    feats.to_parquet("data/featured_panel.parquet")
    print("featured_panel.parquet rebuilt:", len(feats), "rows")
