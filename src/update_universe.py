#!/usr/bin/env python3
"""Refresh the NASDAQ universe list from the Nasdaq.com screener (liquid names)."""
import json, os, time
import urllib.request
import pandas as pd

DATA_DIR = "data"


def fetch(offset, limit=1000):
    url = f"https://api.nasdaq.com/api/screener/stocks?tableonly=true&limit={limit}&offset={offset}&exchange=NASDAQ"
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json, text/plain, */*",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def main():
    rows, offset = [], 0
    while True:
        data = fetch(offset)
        batch = data.get("data", {}).get("table", {}).get("rows", [])
        if not batch:
            break
        rows.extend(batch)
        offset += len(batch)
        if len(batch) < 1000:
            break
        time.sleep(0.3)
    df = pd.DataFrame(rows)

    def mcap(s):
        try:
            return float(s.replace(",", "").replace("$", ""))
        except Exception:
            return float("nan")

    def price(s):
        try:
            return float(s.replace("$", "").replace(",", ""))
        except Exception:
            return float("nan")

    df["mcap"] = df["marketCap"].apply(mcap)
    df["price"] = df["lastsale"].apply(price)
    df["pct"] = pd.to_numeric(df["pctchange"].str.replace("%", "").str.replace("--", "nan"), errors="coerce")
    liquid = df[(df["price"] >= 3) & (df["mcap"] >= 5e8)].sort_values("mcap", ascending=False)
    os.makedirs(DATA_DIR, exist_ok=True)
    liquid[["symbol", "name"]].to_csv(f"{DATA_DIR}/nasdaq_universe.csv", index=False)
    print("universe updated:", len(liquid), "tickers")


if __name__ == "__main__":
    main()
