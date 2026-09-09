"""Compact feature panel 2009-2026, built per-ticker (constant memory on a 2GB box)."""
import glob, gc, os, numpy as np, pandas as pd

def feats(d):
    d = d.sort_values("date").reset_index(drop=True)
    c, o, hi, lo, v = d["close"].astype("float64"), d["open"].astype("float64"), d["high"].astype("float64"), d["low"].astype("float64"), d["volume"].astype("float64")
    pc = c.shift(1)
    f = pd.DataFrame({"date": d["date"], "ticker": d["ticker"].iloc[0], "close": c, "open": o})
    f["ret_1"] = c / pc - 1
    f["gap"] = o / pc - 1
    f["intra"] = c / o - 1
    f["ret_5"] = c.pct_change(5); f["ret_21"] = c.pct_change(21); f["ret_126"] = c.pct_change(126)
    rng = (hi - lo).replace(0, np.nan)
    f["close_pos"] = (c - lo) / rng
    f["sma200"] = c.rolling(200, min_periods=150).mean(); f["sma50"] = c.rolling(50).mean(); f["sma10"] = c.rolling(10).mean()
    f["dv21"] = (c * v).rolling(21).mean()
    tr = pd.concat([hi - lo, (hi - pc).abs(), (lo - pc).abs()], axis=1).max(axis=1)
    f["atr14"] = tr.rolling(14).mean() / c
    f["vol20"] = f["ret_1"].rolling(20).std()
    f["vratio"] = v / v.rolling(20).mean().shift(1)
    f["hh252"] = hi.rolling(252, min_periods=200).max().shift(1)
    f["ll20"] = lo.rolling(20).min().shift(1)
    d1 = c.diff()
    for n in (2, 14):
        au = d1.clip(lower=0).ewm(alpha=1/n, min_periods=n, adjust=False).mean()
        ad = (-d1).clip(lower=0).ewm(alpha=1/n, min_periods=n, adjust=False).mean()
        f[f"rsi{n}"] = 100 - 100 / (1 + au / ad.replace(0, np.nan))
    dn = (d1 < 0).astype(int)
    f["down_streak"] = dn.groupby((dn != dn.shift()).cumsum()).cumsum() * dn
    f["o1"] = o.shift(-1) / c - 1; f["o2"] = o.shift(-2) / c - 1
    f["c1"] = c.shift(-1) / c - 1; f["c2"] = c.shift(-2) / c - 1; f["c3"] = c.shift(-3) / c - 1; f["c5"] = c.shift(-5) / c - 1
    f["l1"] = lo.shift(-1) / c - 1; f["l2"] = lo.shift(-2) / c - 1
    f["h1"] = hi.shift(-1) / c - 1; f["h2"] = hi.shift(-2) / c - 1
    f = f[(f["dv21"] >= 5e6) & (f["close"] >= 5)]
    num = f.columns.difference(["date", "ticker"])
    f[num] = f[num].astype("float32")
    return f

os.makedirs("research/data/long/feat", exist_ok=True)
for p in sorted(glob.glob("research/data/long/part_*.parquet")):
    out = p.replace("part_", "feat/f_")
    if os.path.exists(out):
        continue
    raw = pd.read_parquet(p)
    fs = [feats(g) for _, g in raw.groupby("ticker", sort=False) if len(g) >= 260]
    pd.concat(fs, ignore_index=True).to_parquet(out)
    print(os.path.basename(out), sum(len(x) for x in fs), flush=True)
    del raw, fs; gc.collect()

# market context
b = pd.read_pickle("research/data/long/bench.pkl")
q = b["QQQ"].copy(); q.index = pd.to_datetime(q.index).tz_localize(None)
vix = b["^VIX"]["Close"]; vix.index = pd.to_datetime(vix.index).tz_localize(None)
mk = pd.DataFrame(index=q.index)
mk["q_ret1"] = q["Close"].pct_change()
mk["q_above200"] = q["Close"] > q["Close"].rolling(200).mean()
mk["q_above50"] = q["Close"] > q["Close"].rolling(50).mean()
mk["q_o1"] = q["Open"].shift(-1) / q["Close"] - 1
mk["q_c1o1"] = q["Close"].shift(-1) / q["Open"].shift(-1) - 1
mk["q_c2o1"] = q["Close"].shift(-2) / q["Open"].shift(-1) - 1
dq = q["Close"].diff(); upq = dq.clip(lower=0).ewm(alpha=0.5, adjust=False).mean(); dnq = (-dq).clip(lower=0).ewm(alpha=0.5, adjust=False).mean()
mk["q_rsi2"] = 100 - 100 / (1 + upq / dnq.replace(0, np.nan))
mk["vix"] = vix.reindex(q.index).ffill()
mk["q_ret5"] = q["Close"].pct_change(5)
# breadth from the panel (streamed)
agg = []
for p in sorted(glob.glob("research/data/long/feat/f_*.parquet")):
    f = pd.read_parquet(p, columns=["date", "ret_1"])
    agg.append(f.assign(d4=(f.ret_1 <= -0.04).astype("int32"), up=(f.ret_1 > 0).astype("int32"), n=1).groupby("date")[["d4", "up", "n"]].sum())
br = pd.concat(agg).groupby(level=0).sum()
mk["pct_down4"] = (br["d4"] / br["n"]).reindex(mk.index)
mk["pct_up"] = (br["up"] / br["n"]).reindex(mk.index)
mk["n_univ"] = br["n"].reindex(mk.index)
mk.index.name = "date"
mk.to_parquet("research/data/long/market.parquet")
print(mk.dropna().tail(3).T)
