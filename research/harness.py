"""Shared research harness: load panel (compact), execution model, portfolio stats."""
import glob, numpy as np, pandas as pd
pd.set_option("display.width", 220)

COLS = ["date", "ticker", "close", "ret_1", "gap", "intra", "ret_5", "ret_21", "ret_126", "close_pos", "sma200", "sma50", "sma10",
        "dv21", "atr14", "vol20", "vratio", "hh252", "ll20", "rsi2", "rsi14", "down_streak",
        "o1", "o2", "c1", "c2", "c3", "c5", "l1", "l2", "h1", "h2"]

def load(start="2010-01-01", end="2019-12-31", cols=COLS):
    parts = [pd.read_parquet(p, columns=cols) for p in sorted(glob.glob("research/data/long/feat/f_*.parquet"))]
    h = pd.concat(parts, ignore_index=True)
    h = h[(h.date >= start) & (h.date <= end)]
    mk = pd.read_parquet("research/data/long/market.parquet").reset_index()
    h = h.merge(mk, on="date", how="left")
    # cross-sectional helpers
    h["liq_rank"] = h.groupby("date")["dv21"].rank(ascending=False)
    return h.reset_index(drop=True)

def cost_of(dv21):
    """Round-trip cost assumption in return units."""
    return np.where(dv21 >= 2e7, 0.0015, 0.0030)

def trade_ret(d, entry="open", hold=2, stop=None):
    """Return per-trade NET return.
    entry='open': buy open T+1; entry='close': buy close T (15:55 MOC-style).
    hold=1 -> exit close T+1; hold=2 -> close T+2; hold=3 -> close T+3.
    stop: fractional stop from entry (e.g. -0.05) evaluated on daily lows with 30bp slippage; None = no stop."""
    E = (1 + d["o1"].values) if entry == "open" else np.ones(len(d))
    exitc = {1: "c1", 2: "c2", 3: "c3", 5: "c5"}[hold]
    r = (1 + d[exitc].values) / E - 1
    if stop is not None:
        lows = [(1 + d["l1"].values) / E - 1, (1 + d["l2"].values) / E - 1]
        low = np.minimum.reduce(lows[:min(hold, 2)])
        hit = low <= stop
        r = np.where(hit, stop - 0.003, r)
    return r - cost_of(d["dv21"].values)

def portfolio(d, r, hold=2, cap=None, rank_col=None, ascending=True, label=""):
    """Equal weight within day (up to cap names), capital split across `hold` overlapping cohorts.
    Returns dict of stats + daily series. Days with no signal earn 0 (cash)."""
    d = d.copy(); d["r"] = r
    if cap is not None:
        key = rank_col if rank_col else "r"  # if no rank col, cap is applied randomly-ish (by order)
        if rank_col:
            d["rk"] = d.groupby("date")[rank_col].rank(ascending=ascending, method="first")
        else:
            d["rk"] = d.groupby("date").cumcount() + 1
        d = d[d.rk <= cap]
    daily = d.groupby("date")["r"].mean() / hold
    alld = pd.Index(sorted(set(_ALL_DATES)))
    daily = daily.reindex(alld[(alld >= d.date.min()) & (alld <= d.date.max())]).fillna(0.0)
    eq = (1 + daily).cumprod()
    dd = (eq / eq.cummax() - 1).min()
    yrs = (daily.index[-1] - daily.index[0]).days / 365.25
    cagr = eq.iloc[-1] ** (1 / yrs) - 1
    sh = daily.mean() / daily.std() * np.sqrt(252) if daily.std() > 0 else 0
    per_year = d.groupby(d.date.dt.year)["r"].mean() * 1e4
    tr = d["r"]
    t_daily = daily.mean() / (daily.std() / np.sqrt(len(daily)))
    return dict(label=label, trades=len(d), per_day=round(d.groupby("date").size().mean(), 1), active_days=round((d.groupby("date").size().reindex(daily.index).notna()).mean(), 2),
                net_bp=round(tr.mean() * 1e4, 1), med_bp=round(tr.median() * 1e4, 1), hit=round((tr > 0).mean(), 3),
                t_daily=round(t_daily, 2), sharpe=round(sh, 2), cagr=round(cagr * 100, 1), maxdd=round(dd * 100, 1),
                years_pos=f"{int((per_year > 0).sum())}/{len(per_year)}", med_dv=round(d.dv21.median() / 1e6, 0)), daily, per_year

_ALL_DATES = pd.read_parquet("research/data/long/market.parquet").index

def show(rows):
    print(pd.DataFrame(rows).to_string(index=False))
