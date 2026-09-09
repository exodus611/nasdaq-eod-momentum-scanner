import yfinance as yf, pandas as pd, numpy as np, time, os, gc
uni = pd.read_csv("data/universe_nasdaq.csv")
tickers = [t.replace("/", "-") for t in uni["symbol"].dropna().astype(str) if t.isascii()]
print("universe", len(tickers), flush=True)
os.makedirs("research/data/long", exist_ok=True)
CH = 100
for i in range(0, len(tickers), CH):
    out = f"research/data/long/part_{i:05d}.parquet"
    if os.path.exists(out):
        continue
    batch = tickers[i:i+CH]
    for attempt in range(3):
        try:
            t0 = time.time()
            d = yf.download(batch, start="2009-06-01", interval="1d", group_by="ticker", threads=True, progress=False, auto_adjust=True)
            frames = []
            for t in batch:
                try:
                    df = d[t].dropna(how="all")
                    if len(df) < 120: continue
                    df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
                    df.columns = ["open", "high", "low", "close", "volume"]
                    df = df[(df["close"] > 0) & (df["volume"] >= 0)]
                    df.index.name = "date"
                    df = df.reset_index()
                    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
                    for c in ["open", "high", "low", "close", "volume"]:
                        df[c] = df[c].astype("float32")
                    df["ticker"] = t
                    frames.append(df)
                except Exception:
                    pass
            if frames:
                pd.concat(frames, ignore_index=True).to_parquet(out)
            print(f"chunk {i//CH+1}: {len(frames)}/{len(batch)} in {time.time()-t0:.0f}s", flush=True)
            del d, frames; gc.collect()
            break
        except Exception as e:
            print("retry", i, e, flush=True); time.sleep(15)
    time.sleep(1.0)
b = yf.download(["QQQ", "SPY", "^VIX", "IWM"], start="2009-06-01", interval="1d", group_by="ticker", progress=False, auto_adjust=True, threads=False)
b.to_pickle("research/data/long/bench.pkl"); print("bench ok", flush=True)
