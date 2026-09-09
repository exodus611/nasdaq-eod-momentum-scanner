"""IN-SAMPLE (2010-2019) survey of candidate families. Realistic execution: next open entry, close T+2 exit, costs."""
import numpy as np, pandas as pd
from harness import load, trade_ret, portfolio, show
H = load("2010-01-01", "2019-12-31")
print("IS panel", H.shape, H.ticker.nunique(), H.date.min().date(), H.date.max().date(), flush=True)
rows = []
def run(label, m, hold=2, entry="open", cap=None, rank_col=None, asc=True, stop=None):
    d = H[m].dropna(subset=["o1", "c2"])
    if len(d) < 200:
        print(f"{label}: n={len(d)} too few"); return
    r = trade_ret(d, entry=entry, hold=hold, stop=stop)
    s, _, _ = portfolio(d, r, hold=hold, cap=cap, rank_col=rank_col, ascending=asc, label=label)
    rows.append(s)

up = H.close > H.sma200
print("\n--- baseline ---")
run("universe, buy open hold 2d", H.dv21 > 0)
run("universe, above SMA200", up)

print("\n--- A. short-term reversal family ---")
run("A1 drop<=-4% intraday(gap>-2%), >SMA200, cp<0.5", (H.ret_1 <= -0.04) & (H.gap > -0.02) & up & (H.close_pos < 0.5))
run("A1 cap10 worst first", (H.ret_1 <= -0.04) & (H.gap > -0.02) & up & (H.close_pos < 0.5), cap=10, rank_col="ret_1")
run("A2 drop<=-5% any, >SMA200", (H.ret_1 <= -0.05) & up)
run("A3 drop<=-4%, >SMA200, vratio<1.5 (no news)", (H.ret_1 <= -0.04) & up & (H.vratio < 1.5))
run("A4 drop<=-4%, >SMA200, vratio>=2 (news)", (H.ret_1 <= -0.04) & up & (H.vratio >= 2))
run("A5 RSI2<5, >SMA200", (H.rsi2 < 5) & up)
run("A6 RSI2<10, >SMA200, close<sma10", (H.rsi2 < 10) & up & (H.close < H.sma10))
run("A7 3+ down days, >SMA200", (H.down_streak >= 3) & up)
run("A8 5d ret<=-8%, >SMA200", (H.ret_5 <= -0.08) & up)
run("A9 close < 20d low (ll20), >SMA200", (H.close < H.ll20) & up)
run("A10 drop<=-4% intraday in liquid top-300", (H.ret_1 <= -0.04) & (H.gap > -0.02) & up & (H.liq_rank <= 300))
run("A11 drop<=-4% in mega top-100", (H.ret_1 <= -0.04) & up & (H.liq_rank <= 100))
run("A1 but hold 1d", (H.ret_1 <= -0.04) & (H.gap > -0.02) & up & (H.close_pos < 0.5), hold=1)
run("A1 but hold 3d", (H.ret_1 <= -0.04) & (H.gap > -0.02) & up & (H.close_pos < 0.5), hold=3)
run("A1 entry at close T (15:55)", (H.ret_1 <= -0.04) & (H.gap > -0.02) & up & (H.close_pos < 0.5), entry="close")
run("A1 below SMA200 (downtrend) for contrast", (H.ret_1 <= -0.04) & (H.gap > -0.02) & ~up & (H.close_pos < 0.5))

print("\n--- B. overnight / gap family ---")
run("B1 buy close, sell next open: universe", H.dv21 > 0, entry="close", hold=1)  # NOTE hold=1 here means close->close; overnight separately below
run("B2 gap-up>3% on vratio>2, close_pos>0.7 (PEAD proxy)", (H.gap > 0.03) & (H.vratio > 2) & (H.close_pos > 0.7))
run("B3 gap-up>5% vratio>3 cp>0.8, >SMA200", (H.gap > 0.05) & (H.vratio > 3) & (H.close_pos > 0.8) & up)
run("B4 gap-down<-5% vratio>2, close_pos>0.6 (reversal after news)", (H.gap < -0.05) & (H.vratio > 2) & (H.close_pos > 0.6))
run("B5 gap-down<-5% vratio>2, close_pos<0.3 (drift down?)", (H.gap < -0.05) & (H.vratio > 2) & (H.close_pos < 0.3))

print("\n--- C. breakout / momentum family ---")
run("C1 close>52w high, vratio>1.5", (H.close > H.hh252) & (H.vratio > 1.5))
run("C2 close>52w high, vratio>1.5, ret_1<3% (quiet breakout)", (H.close > H.hh252) & (H.vratio > 1.5) & (H.ret_1 < 0.03))
run("C3 ret_1>5% vratio>3 cp>0.8 >SMA200 (momentum burst)", (H.ret_1 > 0.05) & (H.vratio > 3) & (H.close_pos > 0.8) & up)
run("C4 top decile ret_126, quiet day", (H.groupby('date')['ret_126'].rank(pct=True) > 0.9) & (H.ret_1.abs() < 0.02))

print("\n--- E. market-panic family ---")
run("E1 breadth: >=25% of universe down>4% today -> buy all >SMA200", (H.pct_down4 >= 0.25) & up)
run("E2 breadth >=15%, buy names down>4%", (H.pct_down4 >= 0.15) & (H.ret_1 <= -0.04))
run("E3 QQQ RSI2<10 -> buy names down>3% & >SMA200", (H.q_rsi2 < 10) & (H.ret_1 <= -0.03) & up)
run("E4 QQQ day <-2% -> buy names down>4% intraday, >SMA200", (H.q_ret1 <= -0.02) & (H.ret_1 <= -0.04) & (H.gap > -0.02) & up)
run("E5 A1 on non-panic days only (QQQ>-1%)", (H.ret_1 <= -0.04) & (H.gap > -0.02) & up & (H.close_pos < 0.5) & (H.q_ret1 > -0.01))

show(rows)
pd.DataFrame(rows).to_csv("research/data/is_results.csv", index=False)
