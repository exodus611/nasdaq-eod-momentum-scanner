"""
v2 research: same tier-A signal as v1 (QQQ RSI2<10, stock >SMA200, day <= -3%, liquid), different EXIT.
Portfolio simulation 2010-06..2026-09 on a 2009-2026 daily panel (NASDAQ universe of data/universe_nasdaq.csv, yfinance, adjusted).
Protocol: the SMA10 exit was selected on 2016-2026; 2010-2016 was run ONCE afterwards as the out-of-sample check.
Outputs results/v2_variants_2010_2026.csv, results/v2_trades_2010_2026.csv, results/v2_by_year_2010_2026.csv.

  python research/build_long.py      # (or any script producing long_O/C/V.parquet + long_etf.pkl: Open/Close/Volume, float32)
  python research/v2_exit_test.py
"""
import io, contextlib, sys, os, numpy as np, pandas as pd, warnings; warnings.filterwarnings("ignore")
W = os.environ.get("PANEL_DIR", "/home/user/work")
O = pd.read_parquet(f"{W}/long_O.parquet"); C = pd.read_parquet(f"{W}/long_C.parquet"); V = pd.read_parquet(f"{W}/long_V.parquet")
etf = pd.read_pickle(f"{W}/long_etf.pkl"); qc = etf["QQQ"]["Close"].reindex(C.index).ffill()
idx = C.index; N = len(idx); cols = list(C.columns); Ov, Cv = O.values, C.values

def rsi2(x):
    d = x.diff(); up = d.clip(lower=0).ewm(alpha=0.5, adjust=False).mean(); dn = (-d).clip(lower=0).ewm(alpha=0.5, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))
ret1 = C / C.shift(1) - 1; sma200 = C.rolling(200).mean(); sma5 = C.rolling(5).mean(); sma10 = C.rolling(10).mean()
dv21 = (C * V).shift(1).rolling(21).mean(); srsi = C.apply(rsi2); q = rsi2(qc).values[:, None]
liq = (dv21 >= 2e7) & (C >= 5); up = C > sma200
A = (ret1 <= -0.03) & up & liq & (q < 10)                 # tier A signal (as in v1)
E = (ret1 <= -0.03) & up & liq                            # same stock filter, every day (control)
F = pd.DataFrame(False, index=idx, columns=cols)
i_oos_end = idx.get_loc(idx[idx <= "2016-09-09"][-1])

def sim(entry, exit_cond, rank, K, maxhold=20, cost=0.0010, start=252, end=None, max_new=2, w=None):
    """signal at close t -> buy next open (K slots, w of equity each, <= max_new per day, most liquid first);
    sell next open after exit_cond at a close, or after maxhold sessions. cost = round trip."""
    Ev = entry.values; X = exit_cond.values; R = rank.values; w = w or 1 / K
    cash = 1.0; pos = {}; eqs = np.ones(N); trades = []; last = (N - 1) if end is None else end
    for t in range(start, last):
        o = Ov[t + 1]
        for j in list(pos):
            p = pos[j]; held = t + 1 - p["entry_i"]
            if X[t, j] or held >= maxhold:
                px = o[j] if np.isfinite(o[j]) else Cv[t, j]
                cash += p["shares"] * px * (1 - cost / 2); trades.append((idx[p["entry_i"]], cols[j], idx[t + 1], held, px / p["entry_px"] - 1 - cost)); del pos[j]
        free = min(K - len(pos), max_new)
        if free > 0:
            cand = [j for j in np.where(Ev[t] & np.isfinite(o) & np.isfinite(R[t]))[0] if j not in pos]
            cand = sorted(cand, key=lambda j: -R[t, j])[:free]
            if cand:
                eq_now = cash + sum(p["shares"] * Cv[t, j2] for j2, p in pos.items())
                for j in cand:
                    amt = min(eq_now * w, cash)
                    if amt <= 0: break
                    cash -= amt; pos[j] = dict(shares=amt / (o[j] * (1 + cost / 2)), entry_i=t + 1, entry_px=o[j])
        eqs[t + 1] = cash + sum(p["shares"] * (Cv[t + 1, j] if np.isfinite(Cv[t + 1, j]) else Cv[t, j]) for j, p in pos.items())
    eqs[:start + 1] = 1.0
    if end is not None: eqs[end + 1:] = eqs[end]
    return pd.Series(eqs, index=idx), pd.DataFrame(trades, columns=["entry", "ticker", "exit", "hold", "r"])

rows = []
def run(name, entry, exitc, K=4, mn=2, w=None, cost=0.001, maxhold=20, start=252, end=None):
    e, tr = sim(entry, exitc, dv21, K, maxhold=maxhold, cost=cost, max_new=mn, w=w, start=start, end=end)
    ee = e.iloc[start:(end + 1 if end else None)]; r = ee.pct_change().fillna(0); yrs = (ee.index[-1] - ee.index[0]).days / 365.25
    cagr = (ee.iloc[-1] / ee.iloc[0]) ** (1 / yrs) - 1; dd = (ee / ee.cummax() - 1).min(); sh = r.mean() / r.std() * np.sqrt(252)
    g = ee.groupby(ee.index.year); by = g.last() / g.first() - 1
    rows.append(dict(variant=name, cagr_pct=round(cagr * 100, 1), maxdd_pct=round(dd * 100, 1), sharpe=round(sh, 2), years_pos=f"{(by > 0).sum()}/{by.size}",
                     worst_year_pct=round(by.min() * 100), trades_per_yr=round(len(tr) / yrs), hit_pct=round((tr.r > 0).mean() * 100),
                     mean_bp=round(tr.r.mean() * 1e4), median_bp=round(tr.r.median() * 1e4), avg_hold=round(tr.hold.mean(), 1)))
    print(rows[-1], flush=True); return e, tr

e, tr = run("v2 (A: QQQ RSI2<10, K=4, 25%/name, max 2 new/day, exit close>SMA10 max 20) FULL 2010-26", A, C > sma10)
run("v2 OOS 2010-06..2016-09 (rule chosen on 2016-26)", A, C > sma10, end=i_oos_end)
run("v2 IS 2016-09..2026-09", A, C > sma10, start=i_oos_end)
run("v1 exit: same signal, sell open T+2 (fixed 48h)", A, F, maxhold=2)
run("exit close>SMA5 max 20", A, C > sma5)
run("exit RSI2>60 max 10", A, srsi > 60, maxhold=10)
run("v2 with 30 bp costs", A, C > sma10, cost=0.003)
run("v2 sizing 10%/name", A, C > sma10, w=0.10)
run("v2 sizing 15%/name", A, C > sma10, w=0.15)
run("v2 K=6 (16.7%/name)", A, C > sma10, K=6)
run("v2 without the 2-new-per-day cap", A, C > sma10, mn=99)
run("CONTROL every day, no market filter (same entry/exit)", E, C > sma10)
run("CONTROL tier B only (QQQ RSI2 10-30)", (ret1 <= -0.03) & up & liq & (q >= 10) & (q < 30), C > sma10)
run("CONTROL tier C only (QQQ RSI2 >= 30)", (ret1 <= -0.03) & up & liq & (q >= 30), C > sma10)
run("CONTROL A+B (QQQ RSI2<30) exit SMA5 — the overfit candidate", (ret1 <= -0.03) & up & liq & (q < 30), C > sma5)
run("CONTROL A+B (QQQ RSI2<30) exit SMA5 OOS 2010-16", (ret1 <= -0.03) & up & liq & (q < 30), C > sma5, end=i_oos_end)

R = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "results")
pd.DataFrame(rows).to_csv(f"{R}/v2_variants_2010_2026.csv", index=False)
tr.to_csv(f"{R}/v2_trades_2010_2026.csv", index=False)
ee = e.iloc[252:]; g = ee.groupby(ee.index.year); by = g.last() / g.first() - 1; ddy = (ee / ee.cummax() - 1).groupby(ee.index.year).min()
yr = pd.DataFrame({"return_pct": (by * 100).round(1), "trades": tr.groupby(tr.entry.dt.year).size(), "hit_pct": (tr.groupby(tr.entry.dt.year).r.apply(lambda x: (x > 0).mean()) * 100).round(0),
                   "mean_bp": (tr.groupby(tr.entry.dt.year).r.mean() * 1e4).round(0), "maxdd_pct": (ddy * 100).round(1)}).fillna(0)
yr.index.name = "year"; yr.to_csv(f"{R}/v2_by_year_2010_2026.csv"); print(yr.to_string())
