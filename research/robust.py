"""Robustness of final candidate F (entry close T, exit close T+2, 10 most liquid dip names on QQQ-oversold days)."""
import glob, numpy as np, pandas as pd
from harness import COLS, cost_of
pd.set_option("display.width", 220)
mk = pd.read_parquet("research/data/long/market.parquet").reset_index()
sig_days = set(mk.loc[mk.q_rsi2 < 10, "date"])
ALL = pd.Series(mk.date[mk.date >= "2010-01-01"].values)

# stream: keep every row on signal days with dv21>=20M (for baselines) -- small enough
parts = []
for p in sorted(glob.glob("research/data/long/feat/f_*.parquet")):
    f = pd.read_parquet(p, columns=COLS)
    f = f[(f.date >= "2010-01-01") & (f.dv21 >= 2e7) & (f.close >= 5) & f.date.isin(sig_days)]
    parts.append(f)
D = pd.concat(parts, ignore_index=True).merge(mk, on="date", how="left").dropna(subset=["o1", "c2"])
D["r_close"] = D.c2 - cost_of(D.dv21.values)                       # entry close T, exit close T+2
D["r_open"] = (1 + D.c2) / (1 + D.o1) - 1 - cost_of(D.dv21.values)
D["up"] = D.close > D.sma200
D["liq_rk_all"] = D.groupby("date")["dv21"].rank(ascending=False, method="first")
print(f"signal days: {D.date.nunique()}  rows on signal days (liquid): {len(D):,}")

def port(d, col="r_close", w=None):
    coh = d.groupby("date")[col].mean() / 2 if w is None else (d[col] * w).groupby(d.date).sum() / 2
    daily = coh.reindex(ALL).fillna(0.0)
    eq = (1 + daily).cumprod(); yrs = (ALL.iloc[-1] - ALL.iloc[0]).days / 365.25
    py = d.groupby(d.date.dt.year)[col].mean()
    return dict(trades=len(d), net_bp=round(d[col].mean() * 1e4, 1), hit=round((d[col] > 0).mean(), 3),
                t_daily=round(daily.mean() / (daily.std() / np.sqrt(len(daily))), 2), sharpe=round(daily.mean() / daily.std() * np.sqrt(252), 2),
                cagr=round((eq.iloc[-1] ** (1 / yrs) - 1) * 100, 1), maxdd=round((eq / eq.cummax() - 1).min() * 100, 1), years_pos=f"{int((py > 0).sum())}/{len(py)}")

F = D[D.up & (D.ret_1 <= -0.03)].copy()
F["rk"] = F.groupby("date")["dv21"].rank(ascending=False, method="first")
F10 = F[F.rk <= 10]

print("\n=== 1. Does the STOCK filter add anything beyond market timing? (same days, same period, entry close) ===")
rows = {}
rows["F: dip>=3% & >SMA200, 10 most liquid"] = port(F10)
rows["baseline: 10 most liquid of ALL names (no stock filter)"] = port(D[D.liq_rk_all <= 10])
rng = np.random.default_rng(0)
sims = []
for _ in range(200):
    pick = D.groupby("date", group_keys=False).apply(lambda g: g.sample(n=min(10, len(g)), random_state=int(rng.integers(1e9))))
    sims.append(pick.r_close.mean() * 1e4)
rows["baseline: random 10 liquid names, mean of 200 draws"] = {"net_bp": round(float(np.mean(sims)), 1), "p95_bp": round(float(np.percentile(sims, 95)), 1)}
U = D[D.up].copy(); U["rk"] = U.groupby("date")["dv21"].rank(ascending=False, method="first")
rows["only >SMA200 (no dip), 10 most liquid"] = port(U[U.rk <= 10])
Dn = D[D.ret_1 <= -0.03].copy(); Dn["rk"] = Dn.groupby("date")["dv21"].rank(ascending=False, method="first")
rows["only dip>=3% (no trend), 10 most liquid"] = port(Dn[Dn.rk <= 10])
q = mk.set_index("date").loc[sorted(sig_days)]
q = q[q.index >= "2010-01-01"]
rows["QQQ itself, buy close T sell close T+2"] = {"net_bp": round(float((q.q_o1 + (1 + q.q_o1) * q.q_c2o1 - 0.0004).mean() * 1e4), 1)}
print(pd.DataFrame(rows).T.to_string())

print("\n=== 2. Neighbourhood of the chosen parameters (FULL period, entry close). Looking for a plateau, not a peak ===")
rows = []
for rsi_thr in (8, 10, 12, 15):
    for dip in (-0.02, -0.03, -0.04):
        for cap in (5, 10, 20):
            d = D[(D.q_rsi2 < rsi_thr) & D.up & (D.ret_1 <= dip)].copy()
            d["rk"] = d.groupby("date")["dv21"].rank(ascending=False, method="first")
            d = d[d.rk <= cap]
            s = port(d); s.update(rsi=rsi_thr, dip=dip, cap=cap); rows.append(s)
R = pd.DataFrame(rows)[["rsi", "dip", "cap", "trades", "net_bp", "hit", "t_daily", "sharpe", "cagr", "maxdd", "years_pos"]]
print(R.to_string(index=False))
print(f"\nshare of grid points with t_daily>2: {(R.t_daily > 2).mean():.0%};  all positive: {(R.net_bp > 0).mean():.0%}")

print("\n=== 3. Outlier dependence (F, entry close) ===")
r = F10.r_close.sort_values(ascending=False)
print(f"mean {r.mean()*1e4:.0f}bp | drop top-1% trades -> {r.iloc[int(len(r)*0.01):].mean()*1e4:.0f}bp | drop top-5% -> {r.iloc[int(len(r)*0.05):].mean()*1e4:.0f}bp | winsor 1/99 -> {r.clip(r.quantile(.01), r.quantile(.99)).mean()*1e4:.0f}bp")
coh = F10.groupby("date")["r_close"].mean()
print(f"cohort days: {len(coh)}, positive {(coh > 0).mean():.2f}; drop best 5 days: total goes from {(coh/2).sum()*100:.1f}% to {(coh.sort_values().iloc[:-5]/2).sum()*100:.1f}% (sum of cohort returns)")
y26 = F10[F10.date.dt.year == 2026]
print(f"2026: {len(y26)} trades, {y26.r_close.mean()*1e4:.0f}bp; without top-3 trades: {y26.r_close.sort_values().iloc[:-3].mean()*1e4:.0f}bp; top-3: {y26.nlargest(3,'r_close')[['ticker','date','r_close']].values.tolist()}")

print("\n=== 4. Disaster stop on top (daily lows, -30bp slippage), entry close ===")
for s in (-0.05, -0.08, -0.12, None):
    if s is None:
        print(f"no stop: {F10.r_close.mean()*1e4:.0f}bp"); continue
    low = np.minimum(F10.l1.values, F10.l2.values)
    rr = np.where(low <= s, s - 0.003 - cost_of(F10.dv21.values), F10.r_close.values)
    print(f"stop {s*100:.0f}%: {rr.mean()*1e4:.0f}bp, stop-rate {(low <= s).mean():.2f}")

print("\n=== 5. Block bootstrap (monthly blocks) of daily P&L: CI for Sharpe and annual return, FULL period ===")
daily = (F10.groupby("date")["r_close"].mean() / 2).reindex(ALL).fillna(0.0)
months = daily.groupby(daily.index.to_period("M"))
blocks = [g.values for _, g in months]
rng = np.random.default_rng(1)
sh, ann, neg_year = [], [], []
for _ in range(2000):
    idx = rng.integers(0, len(blocks), len(blocks))
    s = np.concatenate([blocks[i] for i in idx])
    sh.append(s.mean() / s.std() * np.sqrt(252)); ann.append(s.mean() * 252)
    # random 12-month windows negative?
    yrs = [np.concatenate([blocks[j] for j in idx[k:k+12]]).sum() for k in range(0, len(idx) - 12, 12)]
    neg_year.append(np.mean(np.array(yrs) < 0))
print(f"Sharpe 5-50-95%: {np.percentile(sh, 5):.2f} / {np.percentile(sh, 50):.2f} / {np.percentile(sh, 95):.2f}")
print(f"annual return 5-50-95%: {np.percentile(ann, 5)*100:.1f}% / {np.percentile(ann, 50)*100:.1f}% / {np.percentile(ann, 95)*100:.1f}%")
print(f"P(random 12-month window negative) ~ {np.mean(neg_year):.2f}")
print(f"P(Sharpe<0) = {(np.array(sh) < 0).mean():.3f}")

print("\n=== 6. Same-day-of-signal risk: what if the 15:50 estimate is wrong and QQQ RSI2 ends up 10-15? (trades taken on 'near-miss' days) ===")
nm = D[(D.q_rsi2 >= 10) & (D.q_rsi2 < 15)] if False else None
mk2 = pd.read_parquet("research/data/long/market.parquet")
print("days with RSI2 in [10,15):", int(((mk2.q_rsi2 >= 10) & (mk2.q_rsi2 < 15) & (mk2.index >= '2010')).sum()), " (IS test showed these still ~+26bp gross with stock filter, i.e. a near-miss is not a disaster)")

F10.to_parquet("research/data/F10_trades.parquet")
