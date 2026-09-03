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

    # ---- post-download validation: never let a corrupt file poison the cache ----
    if incremental:
        files = [f for f in os.listdir(DATA_DIR) if f.startswith("hist_") and f.endswith(".csv")]
        bad, removed = 0, 0
        for f in files:
            t = f[5:-4]
            ok, why = validate_file(os.path.join(DATA_DIR, f))
            if not ok:
                bad += 1
                print(f"  INVALID {t}: {why} -> repairing")
                if repair_ticker(t):
                    continue
                os.remove(os.path.join(DATA_DIR, f))
                if t in done:
                    done.discard(t)
                removed += 1
                print(f"  REMOVED {t} (repair failed)")
        if bad:
            json.dump(sorted(done), open(f"{DATA_DIR}/history_index.json", "w"))
            print(f"validation: {bad} bad files, {removed} removed")
        else:
            print(f"validation: all {len(files)} hist files OK")

    print("DONE", len(done))




def validate_file(path, max_age_days=15):
    """Sanity-check a hist CSV. Returns (ok, reason)."""
    import numpy as np
    try:
        df = pd.read_csv(path, parse_dates=["date"])
    except Exception as e:
        return False, f"unreadable: {e}"
    if len(df) < 100:
        return False, f"too short ({len(df)} rows)"
    need = ["date", "open", "high", "low", "close", "volume"]
    if any(c not in df.columns for c in need):
        return False, f"missing cols {set(need) - set(df.columns)}"
    numcols = [c for c in need if c != "date"]
    tail = df[numcols].tail(60)
    if not np.isfinite(tail.astype(float).values).all():
        return False, "non-finite values in tail"
    if tail["close"].isna().any():
        return False, "NaN close in tail"
    d = df["date"]
    if d.duplicated().any() or not d.is_monotonic_increasing:
        return False, "dates not unique/ascending"
    if len(df) > 1 and (df["high"] < df["low"] - 1e-9).any():
        return False, "high < low"
    age = (pd.Timestamp.utcnow().tz_localize(None) - d.max()).days
    if age > max_age_days:
        return False, f"stale ({age}d old)"
    return True, "ok"


def repair_ticker(t):
    """Full re-download for one ticker; return True if file is healthy."""
    import time as _t
    try:
        df = yf.download(t, period=PERIOD, interval="1d", progress=False, auto_adjust=True)
        if df is None or len(df) < 100:
            return False
        df = df.dropna()
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
        df.columns = ["open", "high", "low", "close", "volume"]
        df.index.name = "date"
        df = df.reset_index()
        path = f"{DATA_DIR}/hist_{t}.csv"
        df.to_csv(path, index=False)
        ok, why = validate_file(path)
        print(f"  repair {t}: {ok} ({why})")
        return ok
    except Exception as e:
        print(f"  repair {t} failed: {e}")
        return False

if __name__ == "__main__":
    main()
