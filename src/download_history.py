#!/usr/bin/env python3
"""Download/refresh daily OHLCV history for the NASDAQ universe.

- Full mode: 2 years of daily bars per ticker (first run).
- Incremental mode: if a ticker's CSV exists, only fetch the last month and
  merge new rows (fast daily refresh for CI).
Resumable: saves progress to data/history_index.json.
"""
import os, sys, time, json
import pandas as pd
import yfinance as yf

DATA_DIR = "data"
PERIOD = "2y"
CHUNK = 200
INCR_PERIOD = "1mo"


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    uni = pd.read_csv(f"{DATA_DIR}/nasdaq_universe.csv")
    tickers = uni["symbol"].tolist()
    print(f"universe: {len(tickers)} tickers")

    done = set()
    if os.path.exists(f"{DATA_DIR}/history_index.json"):
        done = set(json.load(open(f"{DATA_DIR}/history_index.json")))

    todo = [t for t in tickers if t not in done]
    print(f"done: {len(done)}, todo full-download: {len(todo)}")

    incremental = os.environ.get("INCREMENTAL", "0") == "1"

    if todo:
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
            print(f"chunk {i // CHUNK + 1}: saved {saved}/{len(batch)} in {time.time() - t0:.0f}s, total {len(done)}")
            time.sleep(1)

    if incremental:
        # догрузка последнего месяца для существующих файлов
        files = [f for f in os.listdir(DATA_DIR) if f.startswith("hist_") and f.endswith(".csv")]
        print(f"incremental refresh for {len(files)} tickers ...")
        t0 = time.time()
        tick = [f[5:-4] for f in files]
        for i in range(0, len(tick), CHUNK):
            batch = tick[i:i + CHUNK]
            try:
                data = yf.download(batch, period=INCR_PERIOD, interval="1d", group_by="ticker",
                                   threads=True, progress=False, auto_adjust=True)
                for t in batch:
                    try:
                        new = data[t].dropna()
                        if len(new) == 0:
                            continue
                        new = new[["Open", "High", "Low", "Close", "Volume"]].copy()
                        new.columns = ["open", "high", "low", "close", "volume"]
                        new.index.name = "date"
                        path = f"{DATA_DIR}/hist_{t}.csv"
                        if os.path.exists(path):
                            old = pd.read_csv(path, parse_dates=["date"]).set_index("date")
                            merged = pd.concat([old, new]).groupby(level=0).last().sort_index()
                            merged.to_csv(path)
                        else:
                            new.to_csv(path)
                    except Exception:
                        continue
            except Exception as e:
                print(f"incr batch {i} failed: {e}")
                time.sleep(3)
        print(f"incremental refresh done in {time.time() - t0:.0f}s")

    print("DONE", len(done))


if __name__ == "__main__":
    main()
