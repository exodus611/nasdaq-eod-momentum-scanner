"""Final numbers for the deliverable: two sizing schemes, two entry modes, IS/OOS/FULL, by-year, equity chart."""
import numpy as np, pandas as pd, os
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
pd.set_option("display.width", 220)
F = pd.read_parquet("research/data/F10_trades.parquet")   # QQQ RSI2<10, dip<=-3%, >SMA200, $vol>=20M, 10 most liquid
mk = pd.read_parquet("research/data/long/market.parquet")
ALL = pd.DatetimeIndex(mk.index[mk.index >= "2010-01-01"])
os.makedirs("results", exist_ok=True)

def daily_pnl(d, col, sizing):
    if sizing == "cohort50":      # day's cohort always = 50% of capital, equal split
        coh = d.groupby("date")[col].mean() / 2
    else:                          # 5% of capital per name (max 10 names = 50%)
        coh = d.groupby("date")[col].sum() * 0.05
    return coh.reindex(ALL).fillna(0.0)

def stats(daily, label):
    eq = (1 + daily).cumprod(); yrs = (daily.index[-1] - daily.index[0]).days / 365.25
    dd = (eq / eq.cummax() - 1)
    yr = eq.resample("YE").last().pct_change(); yr.iloc[0] = eq.resample("YE").last().iloc[0] - 1
    return dict(variant=label, cagr_pct=round((eq.iloc[-1] ** (1 / yrs) - 1) * 100, 1), total_pct=round((eq.iloc[-1] - 1) * 100, 0),
                sharpe=round(daily.mean() / daily.std() * np.sqrt(252), 2), t_stat=round(daily.mean() / (daily.std() / np.sqrt(len(daily))), 2),
                maxdd_pct=round(dd.min() * 100, 1), worst_day_pct=round(daily.min() * 100, 2), years_pos=f"{int((yr > 0).sum())}/{len(yr)}",
                time_in_mkt_pct=round((daily != 0).mean() * 100, 0))

rows = []
for entry, col in (("close T (MOC)", "r_close"), ("open T+1 (MOO)", "r_open")):
    for sizing in ("5% per name", "cohort50"):
        for per, m in (("IS 2010-19", F.date < "2020"), ("OOS 2020-26", F.date >= "2020"), ("FULL 2010-26", F.date > "2000")):
            dly = daily_pnl(F[m], col, "cohort50" if sizing == "cohort50" else "pername")
            dly = dly[(dly.index >= F[m].date.min()) & (dly.index <= F[m].date.max() + pd.Timedelta(days=3))]
            s = stats(dly, f"{entry} | {sizing} | {per}"); s["trades"] = int(m.sum()); s["net_bp_per_trade"] = round(F.loc[m, col].mean() * 1e4, 0); s["hit"] = round((F.loc[m, col] > 0).mean(), 3)
            rows.append(s)
R = pd.DataFrame(rows)
print(R.to_string(index=False))
R.to_csv("results/summary.csv", index=False)

# by-year table for primary (close entry, 5%/name)
dly = daily_pnl(F, "r_close", "pername")
eq = (1 + dly).cumprod()
yr = pd.DataFrame({"year_return_pct": (eq.resample("YE").last().pct_change() * 100)})
yr.iloc[0, 0] = (eq.resample("YE").last().iloc[0] - 1) * 100
yr.index = yr.index.year
by = F.groupby(F.date.dt.year).agg(signal_days=("date", "nunique"), trades=("r_close", "size"), net_bp_per_trade=("r_close", lambda s: s.mean() * 1e4), hit=("r_close", lambda s: (s > 0).mean()), worst_trade_pct=("r_close", lambda s: s.min() * 100), best_trade_pct=("r_close", lambda s: s.max() * 100))
by = by.join(yr)
by["maxdd_in_year_pct"] = [((1 + dly[dly.index.year == y]).cumprod() / (1 + dly[dly.index.year == y]).cumprod().cummax() - 1).min() * 100 for y in by.index]
q = pd.read_pickle("research/data/long/bench.pkl")["QQQ"]["Close"]; q.index = pd.to_datetime(q.index).tz_localize(None)
qy = q.resample("YE").last().pct_change() * 100; qy.index = qy.index.year
by["QQQ_year_pct"] = qy.reindex(by.index)
by = by.round(1)
print("\n", by.to_string())
by.to_csv("results/by_year.csv")

# trades list
F.sort_values("date")[["date", "ticker", "close", "ret_1", "dv21", "q_rsi2", "o1", "c2", "r_close", "r_open"]].to_csv("results/trades_2010_2026.csv", index=False)

# chart
fig, axes = plt.subplots(2, 1, figsize=(11, 7.5), dpi=130, gridspec_kw={"height_ratios": [3, 1]}, sharex=True)
ax = axes[0]
for entry, col, c in (("вход по закрытию T (MOC)", "r_close", "#1e8449"), ("вход по открытию T+1 (MOO)", "r_open", "#2980b9")):
    d = daily_pnl(F, col, "pername"); ax.plot((1 + d).cumprod(), label=f"Dip-Buyer, {entry}, 5%/имя, после издержек", color=c, lw=1.8)
qd = q.pct_change(); qd = qd[qd.index >= ALL[0]]
ax.plot((1 + qd).cumprod(), label="QQQ buy & hold (для масштаба)", color="#7f8c8d", lw=1.0, alpha=.8)
ax.axvline(pd.Timestamp("2020-01-01"), color="red", ls="--", lw=1); ax.text(pd.Timestamp("2020-02-15"), 1.6, "правила зафиксированы\nна 2010-2019 → OOS", color="red", fontsize=8)
ax.set_yscale("log"); ax.grid(alpha=.3); ax.legend(fontsize=8.5, loc="upper left"); ax.set_ylabel("капитал (×, лог)")
ax.set_title("Dip-Buyer NASDAQ 48h: QQQ RSI(2)<10 → 10 самых ликвидных акций, упавших ≥3% в аптренде → выход через 2 сессии", fontsize=10)
ax2 = axes[1]
eqc = (1 + daily_pnl(F, "r_close", "pername")).cumprod(); ax2.fill_between(eqc.index, (eqc / eqc.cummax() - 1) * 100, 0, color="#c0392b", alpha=.6)
ax2.set_ylabel("просадка, %"); ax2.grid(alpha=.3)
plt.tight_layout(); plt.savefig("results/equity_2010_2026.png"); print("chart saved")
