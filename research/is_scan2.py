"""IS deep-dive: gross vs net, regime dependence (VIX / QQQ RSI2 / breadth), by year."""
import numpy as np, pandas as pd
from harness import load, trade_ret, portfolio, show, cost_of
H = load("2010-01-01", "2019-12-31")
H = H.dropna(subset=["o1", "c2"])
up = H.close > H.sma200
H["gross2"] = (1 + H.c2) / (1 + H.o1) - 1
H["gross1"] = (1 + H.c1) / (1 + H.o1) - 1
H["on"] = H.o1  # overnight close->open
H["year"] = H.date.dt.year

def by(label, m, col="gross2"):
    d = H[m]
    yr = d.groupby("year")[col].mean() * 1e4
    print(f"{label:52s} n={len(d):7d} gross {d[col].mean()*1e4:+6.1f}bp | " + " ".join(f"{y}:{v:+4.0f}" for y, v in yr.items()))

print("=== GROSS 2-day return (open T+1 -> close T+2) by year, bp ===")
by("universe", H.dv21 > 0)
by("A1 reversal (-4% intraday, >SMA200, cp<.5)", (H.ret_1 <= -0.04) & (H.gap > -0.02) & up & (H.close_pos < 0.5))
by("A8 5d<=-8% >SMA200", (H.ret_5 <= -0.08) & up)
by("A5 RSI2<5 >SMA200", (H.rsi2 < 5) & up)
by("E3 QQQ RSI2<10 & stock -3% & >SMA200", (H.q_rsi2 < 10) & (H.ret_1 <= -0.03) & up)
by("C1 52w-high breakout vol>1.5", (H.close > H.hh252) & (H.vratio > 1.5))
print("\n=== overnight (close T -> open T+1) gross by year ===")
by("universe overnight", H.dv21 > 0, "on")
by("top-100 liquid overnight", H.liq_rank <= 100, "on")
by("A1 overnight", (H.ret_1 <= -0.04) & (H.gap > -0.02) & up & (H.close_pos < 0.5), "on")

print("\n=== REGIME: A1-like reversal (-4% intraday, >SMA200) gross 2d by VIX bucket ===")
m = (H.ret_1 <= -0.04) & (H.gap > -0.02) & up
d = H[m].copy(); d["vixb"] = pd.cut(d.vix, [0, 13, 16, 20, 25, 35, 100])
print(d.groupby("vixb", observed=True).agg(n=("gross2", "size"), gross_bp=("gross2", lambda s: s.mean()*1e4), hit=("gross2", lambda s: (s > 0).mean()), days=("date", "nunique")).round(1).to_string())
print("\n... by QQQ RSI2 bucket")
d["qb"] = pd.cut(d.q_rsi2, [0, 5, 10, 20, 40, 60, 80, 100])
print(d.groupby("qb", observed=True).agg(n=("gross2", "size"), gross_bp=("gross2", lambda s: s.mean()*1e4), hit=("gross2", lambda s: (s > 0).mean()), days=("date", "nunique")).round(1).to_string())
print("\n... by breadth (share of universe down >4%)")
d["bb"] = pd.cut(d.pct_down4, [-1, 0.02, 0.05, 0.10, 0.20, 1])
print(d.groupby("bb", observed=True).agg(n=("gross2", "size"), gross_bp=("gross2", lambda s: s.mean()*1e4), hit=("gross2", lambda s: (s > 0).mean()), days=("date", "nunique")).round(1).to_string())
print("\n... by QQQ same-day return")
d["qr"] = pd.cut(d.q_ret1, [-1, -0.02, -0.01, -0.005, 0, 0.005, 1])
print(d.groupby("qr", observed=True).agg(n=("gross2", "size"), gross_bp=("gross2", lambda s: s.mean()*1e4), hit=("gross2", lambda s: (s > 0).mean()), days=("date", "nunique")).round(1).to_string())

print("\n=== ALL stocks (no stock-level filter): gross 2d by QQQ RSI2 bucket (is it just market timing?) ===")
H["qb"] = pd.cut(H.q_rsi2, [0, 5, 10, 20, 40, 60, 80, 100])
print(H.groupby("qb", observed=True).agg(n=("gross2", "size"), gross_bp=("gross2", lambda s: s.mean()*1e4), qqq_bp=("q_c2o1", lambda s: s.mean()*1e4), days=("date", "nunique")).round(1).to_string())
print("\n=== within QQQ RSI2<10 days: stock-level sort by ret_1 quintile (does picking losers add over the market bounce?) ===")
L = H[H.q_rsi2 < 10].copy()
L["r1q"] = L.groupby("date")["ret_1"].transform(lambda s: pd.qcut(s.rank(method="first"), 5, labels=False))
print(L.groupby("r1q").agg(n=("gross2", "size"), gross_bp=("gross2", lambda s: s.mean()*1e4), excess_vs_qqq=("gross2", lambda s: 0)).drop(columns="excess_vs_qqq").round(1).to_string())
print("QQQ itself on those days (open T+1->close T+2):", round(L.groupby("date")["q_c2o1"].first().mean()*1e4, 1), "bp")
