import glob, numpy as np, pandas as pd
from harness import COLS, cost_of
pd.set_option("display.width", 220)
mk = pd.read_parquet("research/data/long/market.parquet").reset_index()
days20 = set(mk.loc[mk.q_rsi2 < 25, "date"])
ALL = pd.Series(mk.date[mk.date >= "2010-01-01"].values)
parts = []
for p in sorted(glob.glob("research/data/long/feat/f_*.parquet")):
    f = pd.read_parquet(p, columns=COLS)
    f = f[(f.date >= "2010-01-01") & (f.dv21 >= 2e7) & (f.close >= 5) & f.date.isin(days20) & (f.ret_1 <= -0.02) & (f.close > f.sma200)]
    parts.append(f)
D = pd.concat(parts, ignore_index=True).merge(mk, on="date", how="left").dropna(subset=["o1", "c2"])
D["r_close"] = D.c2 - cost_of(D.dv21.values)
D["r_open"] = (1 + D.c2) / (1 + D.o1) - 1 - cost_of(D.dv21.values)

def port(d, col="r_close"):
    coh = d.groupby("date")[col].mean() / 2
    daily = coh.reindex(ALL).fillna(0.0)
    eq = (1 + daily).cumprod(); yrs = (ALL.iloc[-1] - ALL.iloc[0]).days / 365.25
    py = d.groupby(d.date.dt.year)[col].mean()
    return dict(trades=len(d), days=d.date.nunique(), net_bp=round(d[col].mean() * 1e4, 1), hit=round((d[col] > 0).mean(), 3),
                t_daily=round(daily.mean() / (daily.std() / np.sqrt(len(daily))), 2), sharpe=round(daily.mean() / daily.std() * np.sqrt(252), 2),
                cagr=round((eq.iloc[-1] ** (1 / yrs) - 1) * 100, 1), maxdd=round((eq / eq.cummax() - 1).min() * 100, 1), years_pos=f"{int((py > 0).sum())}/{len(py)}")

print("=== corrected RSI-threshold sweep (dip<=-3%, >SMA200, 10 most liquid, entry close, FULL 2010-2026) ===")
rows = []
for thr in (5, 8, 10, 12, 15, 20, 25):
    d = D[(D.q_rsi2 < thr) & (D.ret_1 <= -0.03)].copy()
    d["rk"] = d.groupby("date")["dv21"].rank(ascending=False, method="first"); d = d[d.rk <= 10]
    s = port(d); s["rsi_thr"] = thr; rows.append(s)
print(pd.DataFrame(rows).set_index("rsi_thr").to_string())
print("\n=== and the band 10<=RSI2<20 alone (what you get on 'near-miss' days) ===")
d = D[(D.q_rsi2 >= 10) & (D.q_rsi2 < 20) & (D.ret_1 <= -0.03)].copy()
d["rk"] = d.groupby("date")["dv21"].rank(ascending=False, method="first"); print(port(d[d.rk <= 10]))

print("\n=== survivorship check: restrict to top-100 by $volume that day (mega caps, ~never delisted) ===")
F = D[(D.q_rsi2 < 10) & (D.ret_1 <= -0.03)].copy()
F["rk"] = F.groupby("date")["dv21"].rank(ascending=False, method="first")
print("10 most liquid (F):", port(F[F.rk <= 10]))
print("names ranked 11-30 by liquidity:", port(F[(F.rk > 10) & (F.rk <= 30)]))
big = F[F.dv21 >= 2e8].copy(); big["rk"] = big.groupby("date")["dv21"].rank(ascending=False, method="first")
print("only $vol>=200M, up to 10:", port(big[big.rk <= 10]))

print("\n=== open-entry variant (after-close scan, MOO next day) for the same F, by period ===")
F10 = F[F.rk <= 10]
for lab, m in (("IS", F10.date < "2020"), ("OOS", F10.date >= "2020"), ("FULL", F10.date > "2000")):
    print(lab, "open:", port(F10[m], "r_open"), "\n    close:", port(F10[m], "r_close"))

print("\n=== time in market ===")
coh = F10.groupby("date").size()
print(f"signal days {len(coh)} of {len(ALL)} = {len(coh)/len(ALL):.1%}; avg names/day {coh.mean():.1f}; days with <10 names: {(coh < 10).mean():.0%}")
print("names per signal day distribution:", coh.describe()[["min", "25%", "50%", "75%", "max"]].to_dict())
print("\nmost frequent tickers in F:", F10.ticker.value_counts().head(12).to_dict())
