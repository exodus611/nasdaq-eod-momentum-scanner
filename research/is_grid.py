"""IS grid on the 'market oversold + stock oversold' family. Small grid, look for a stable plateau, not a peak."""
import numpy as np, pandas as pd, itertools
from harness import load, trade_ret, portfolio, show
H = load("2010-01-01", "2019-12-31").dropna(subset=["o1", "c2", "c3", "c1"])
up = H.close > H.sma200
H["q_dd10"] = np.nan  # placeholder
mk = pd.read_parquet("research/data/long/market.parquet")
b = pd.read_pickle("research/data/long/bench.pkl"); q = b["QQQ"]["Close"]; q.index = pd.to_datetime(q.index).tz_localize(None)
extra = pd.DataFrame({"q_dd10": q / q.rolling(10).max() - 1, "q_ret2": q.pct_change(2), "q_ret3": q.pct_change(3),
                      "q_below5lo": q < q.rolling(5).min().shift(1)})
H = H.drop(columns=["q_dd10"]).merge(extra, left_on="date", right_index=True, how="left")

rows = []
def run(label, m, hold=2, entry="open", cap=None, rank_col="ret_1", asc=True):
    d = H[m]
    if len(d) < 300: return
    r = trade_ret(d, entry=entry, hold=hold)
    s, daily, py = portfolio(d, r, hold=hold, cap=cap, rank_col=rank_col, ascending=asc, label=label)
    s["days"] = d.date.nunique()
    rows.append(s)

print("=== market trigger sweep (stock: ret_1<=-3%, >SMA200; hold 2; next open; no cap) ===")
for thr in (3, 5, 8, 10, 15, 20):
    run(f"QQQ RSI2<{thr}", (H.q_rsi2 < thr) & (H.ret_1 <= -0.03) & up)
for thr in (-0.015, -0.02, -0.03, -0.04):
    run(f"QQQ 2d ret<{thr}", (H.q_ret2 < thr) & (H.ret_1 <= -0.03) & up)
for thr in (-0.02, -0.03, -0.05):
    run(f"QQQ dd from 10d high<{thr}", (H.q_dd10 < thr) & (H.ret_1 <= -0.03) & up)
for thr in (0.10, 0.15, 0.20, 0.30):
    run(f"breadth down4>={thr}", (H.pct_down4 >= thr) & (H.ret_1 <= -0.03) & up)
run("QQQ close < prior 5d low", H.q_below5lo & (H.ret_1 <= -0.03) & up)
run("QQQ RSI2<10 AND QQQ>SMA200", (H.q_rsi2 < 10) & H.q_above200 & (H.ret_1 <= -0.03) & up)
run("QQQ RSI2<10 AND QQQ<SMA200", (H.q_rsi2 < 10) & ~H.q_above200 & (H.ret_1 <= -0.03) & up)
show(rows); rows.clear()

print("\n=== stock filter sweep (market: QQQ RSI2<10) ===")
M = H.q_rsi2 < 10
run("all stocks", M)
run("all stocks >SMA200", M & up)
run("ret_1<=-2% >SMA200", M & (H.ret_1 <= -0.02) & up)
run("ret_1<=-3% >SMA200", M & (H.ret_1 <= -0.03) & up)
run("ret_1<=-4% >SMA200", M & (H.ret_1 <= -0.04) & up)
run("ret_1<=-3% <SMA200", M & (H.ret_1 <= -0.03) & ~up)
run("ret_1<=-3% >SMA200 & gap>-2% (intraday)", M & (H.ret_1 <= -0.03) & up & (H.gap > -0.02))
run("ret_1<=-3% >SMA200 & vratio<2", M & (H.ret_1 <= -0.03) & up & (H.vratio < 2))
run("ret_1<=-3% >SMA200 & cp<0.5", M & (H.ret_1 <= -0.03) & up & (H.close_pos < 0.5))
run("RSI2<10 stock, >SMA200", M & (H.rsi2 < 10) & up)
run("ret_5<=-5% >SMA200", M & (H.ret_5 <= -0.05) & up)
run("ret_1<=-3% >SMA200 liq top-300", M & (H.ret_1 <= -0.03) & up & (H.liq_rank <= 300))
run("ret_1<=-3% >SMA200 liq top-100", M & (H.ret_1 <= -0.03) & up & (H.liq_rank <= 100))
run("ret_1<=-3% >SMA200 cap5 worst", M & (H.ret_1 <= -0.03) & up, cap=5)
run("ret_1<=-3% >SMA200 cap10 worst", M & (H.ret_1 <= -0.03) & up, cap=10)
run("ret_1<=-3% >SMA200 cap20 worst", M & (H.ret_1 <= -0.03) & up, cap=20)
run("ret_1<=-3% >SMA200 cap10 most liquid", M & (H.ret_1 <= -0.03) & up, cap=10, rank_col="dv21", asc=False)
run("ret_1<=-3% >SMA200 cap10 lowest ATR", M & (H.ret_1 <= -0.03) & up, cap=10, rank_col="atr14", asc=True)
run("ret_1<=-3% >SMA200 cap10 highest ATR", M & (H.ret_1 <= -0.03) & up, cap=10, rank_col="atr14", asc=False)
show(rows); rows.clear()

print("\n=== hold / entry sweep (QQQ RSI2<10, ret_1<=-3%, >SMA200) ===")
S = M & (H.ret_1 <= -0.03) & up
for hold in (1, 2, 3):
    for entry in ("open", "close"):
        run(f"hold {hold} entry {entry}", S, hold=hold, entry=entry)
show(rows); rows.clear()

print("\n=== turn-of-month check (buy open of last trading day of month... proxy: last 1 day / first 2 days) ===")
dd = pd.Series(sorted(H.date.unique()))
mon = dd.dt.to_period("M")
last_day = dd[mon != mon.shift(-1)]
first_day = dd[mon != mon.shift(1)]
run("TOM: signal on day before last trading day, hold 2 (liquid top-300)", H.date.isin(set(dd.shift(1)[dd.isin(last_day)].dropna())) & (H.liq_rank <= 300))
run("TOM: signal on last trading day, hold 2", H.date.isin(set(last_day)) & (H.liq_rank <= 300))
run("TOM: signal on first trading day, hold 2", H.date.isin(set(first_day)) & (H.liq_rank <= 300))
show(rows)
