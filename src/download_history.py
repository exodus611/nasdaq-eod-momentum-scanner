#!/usr/bin/env python3
"""Download 2y daily OHLCV for the NASDAQ universe, chunked & resumable."""
import os, sys, time, json
import pandas as pd
import yfinance as yf

DATA_DIR = "data"
PERIOD = "2y"
CHUNK = 200

def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    uni = pd.read_csv(f"{DATA_DIR}/nasdaq_universe.csv")
    tickers = uni["symbol"].tolist()
    print(f"universe: {len(tickers)} tickers")

    done = set()
    if os.path.exists(f"{DATA_DIR}/history_index.json"):
        done = set(json.load(open(f"{DATA_DIR}/history_index.json")))
    todo = [t for t in tickers if t not in done]
    print(f"already done: {len(done)}, todo: {len(todo)}")

    for i in range(0, len(todo), CHUNK):
        batch = todo[i:i + CHUNK]
        t0 = time.time()
        try:
            data = yf.download(batch, period=PERIOD, interval="1d", group_by="ticker",
                               threads=True, progress=False, auto_adjust=True)
            saved = 0
            for t in batch:
                try:
                    df = data[t].dropna()
                    if len(df) < 100:
                        continue
                    df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
                    df.columns = ["open", "high", "low", "close", "volume"]
                    df.index.name = "date"
                    df.to_csv(f"{DATA_DIR}/hist_{t}.csv")
                    done.add(t)
                    saved += 1
                except Exception as e:
                    print(f"  {t}: ERR {e}")
        except Exception as e:
            print(f"batch {i} failed: {e}")
            time.sleep(5)
            continue
        json.dump(sorted(done), open(f"{DATA_DIR}/history_index.json", "w"))
        print(f"chunk {i//CHUNK+1}: saved {saved}/{len(batch)} in {time.time()-t0:.0f}s, total done {len(done)}")
        time.sleep(1)

    print("DONE", len(done))

if __name__ == "__main__":
    main()
