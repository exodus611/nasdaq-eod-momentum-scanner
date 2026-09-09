"""OUT-OF-SAMPLE 2020-01 .. 2026-09. Pre-registered rules from PLAN.md. Run once."""
import numpy as np, pandas as pd
from harness import load, trade_ret, portfolio, show
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt

def variants(H, label_prefix=""):
    H = H.dropna(subset=["o1", "c2"])
    up = H.close > H.sma200
    base = (H.q_rsi2 < 10) & up & (H.ret_1 <= -0.03) & (H.dv21 >= 2e7) & (H.close >= 5)
    rows, curves = [], {}
    def run(label, m, hold=2, entry="open", cap=None, rank_col="ret_1", asc=True):
        d = H[m]
        r = trade_ret(d, entry=entry, hold=hold)
        s, daily, py = portfolio(d, r, hold=hold, cap=cap, rank_col=rank_col, ascending=asc, label=label_prefix + label)
        s["days"] = d.date.nunique()
        rows.append(s); curves[label] = (daily, py, d.assign(r=r))
    run("P1 cap10 worst-first, hold2, open", base, cap=10)
    run("P2 cap10 most-liquid", base, cap=10, rank_col="dv21", asc=False)
    run("P3 no cap", base)
    run("P4 P1 + QQQ>SMA200", base & H.q_above200, cap=10)
    run("S1 P1 entry at close T", base, cap=10, entry="close")
    run("S2 P1 hold 3", base, cap=10, hold=3)
    run("S3 P1 hold 1", base, cap=10, hold=1)
    return rows, curves

# --- market-only benchmark M1 from QQQ directly
b = pd.read_pickle("research/data/long/bench.pkl"); q = b["QQQ"].copy(); q.index = pd.to_datetime(q.index).tz_localize(None)
mk = pd.read_parquet("research/data/long/market.parquet")
def m1(start, end):
    m = mk[(mk.index >= start) & (mk.index <= end)]
    sig = m[m.q_rsi2 < 10]
    r = sig.q_c2o1 - 0.0004  # QQQ ~2bp spread + commission
    daily = (r / 2).reindex(m.index).fillna(0)
    eq = (1 + daily).cumprod(); yrs = (m.index[-1] - m.index[0]).days / 365.25
    py = r.groupby(sig.index.year).mean() * 1e4
    return dict(label="M1 QQQ-only RSI2<10, open T+1 -> close T+2", trades=len(sig), per_day=1, active_days=round(len(sig)/len(m), 2), net_bp=round(r.mean()*1e4, 1), med_bp=round(r.median()*1e4, 1), hit=round((r > 0).mean(), 3),
                t_daily=round(daily.mean()/(daily.std()/np.sqrt(len(daily))), 2), sharpe=round(daily.mean()/daily.std()*np.sqrt(252), 2), cagr=round((eq.iloc[-1]**(1/yrs)-1)*100, 1),
                maxdd=round((eq/eq.cummax()-1).min()*100, 1), years_pos=f"{int((py>0).sum())}/{len(py)}", med_dv=None, days=len(sig)), daily

print("=== IN-SAMPLE 2010-2019 (for reference, same code path) ===")
HIS = load("2010-01-01", "2019-12-31")
rows_is, _ = variants(HIS)
m1s, _ = m1("2010-01-01", "2019-12-31"); rows_is.append(m1s)
show(rows_is)
del HIS

print("\n=== OUT-OF-SAMPLE 2020-01 .. 2026-09 (first and only run) ===")
H = load("2020-01-01", "2026-12-31")
rows, curves = variants(H)
m1o, m1d = m1("2020-01-01", "2026-12-31"); rows.append(m1o)
show(rows)

print("\n=== P1 by year (net bp/trade, trades) ===")
d = curves["P1 cap10 worst-first, hold2, open"][2]
d["rk"] = d.groupby("date")["ret_1"].rank(method="first"); d = d[d.rk <= 10]
print(d.groupby(d.date.dt.year).agg(trades=("r", "size"), days=("date", "nunique"), net_bp=("r", lambda s: s.mean()*1e4), hit=("r", lambda s: (s > 0).mean()), worst=("r", "min"), best=("r", "max")).round(3).to_string())
print("\n=== P3 by year ===")
d3 = curves["P3 no cap"][2]
print(d3.groupby(d3.date.dt.year).agg(trades=("r", "size"), days=("date", "nunique"), net_bp=("r", lambda s: s.mean()*1e4), hit=("r", lambda s: (s > 0).mean())).round(3).to_string())
print("\n=== P1: worst 10 days (cohort return) ===")
dayr = d.groupby("date")["r"].mean().sort_values()
print((dayr.head(10) * 100).round(2).to_string())
print("\n=== P1: distribution of trade returns ===")
print((d.r.describe(percentiles=[.01, .05, .25, .5, .75, .95, .99]) * 100).round(2).to_string())

# equity plot
fig, ax = plt.subplots(figsize=(11, 5.5), dpi=130)
for k, col in [("P1 cap10 worst-first, hold2, open", "#1e8449"), ("P3 no cap", "#27ae60"), ("P4 P1 + QQQ>SMA200", "#2980b9"), ("S1 P1 entry at close T", "#8e44ad")]:
    daily = curves[k][0]; ax.plot((1 + daily).cumprod(), label=k, color=col, lw=1.8 if k.startswith("P1") else 1.2)
ax.plot((1 + m1d).cumprod(), label="M1 QQQ-only RSI2<10", color="#e67e22", lw=1.2, ls="--")
qd = q["Close"].pct_change(); qd = qd[(qd.index >= "2020-01-01")]
ax.plot((1 + qd).cumprod(), label="QQQ buy&hold", color="#2c3e50", lw=1.2, alpha=.7)
ax.set_yscale("log"); ax.grid(alpha=.3); ax.legend(fontsize=8.5)
ax.set_title("OUT-OF-SAMPLE 2020-2026: rules fixed on 2010-2019. Net of 15-30bp/trade. Cash when no signal.", fontsize=10.5)
plt.tight_layout(); plt.savefig("research/data/oos_equity.png")
pd.DataFrame(rows).to_csv("research/data/oos_results.csv", index=False)
curves["P1 cap10 worst-first, hold2, open"][0].to_csv("research/data/p1_daily.csv")
d.to_parquet("research/data/p1_trades_oos.parquet")
