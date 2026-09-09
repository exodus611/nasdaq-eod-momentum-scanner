#!/usr/bin/env python3
"""
DIP-BUYER NASDAQ 48h  —  готовый сканер / генератор ордеров.

ПРАВИЛА (зафиксированы на 2010-2019, проверены на 2020-2026 без изменений):
  ТРИГГЕР РЫНКА : RSI(2) индекса QQQ по закрытию дня T  < 10   (рынок перепродан за 2 дня)
  ФИЛЬТР АКЦИИ  : close > SMA200  (долгосрочный аптренд)
                  дневное изменение close/close_prev <= -3%  (акция упала сегодня)
                  средний оборот 21д >= $20M, цена >= $5
  ВЫБОР         : 10 самых ЛИКВИДНЫХ (по обороту) из прошедших фильтр
  ВХОД          : по закрытию дня T (MOC, ордер ставится ~15:50 ET по предварительной оценке)
                  ИЛИ по открытию T+1 (MOO) — хуже примерно на 20-30 б.п./сделку, но проще
  ВЫХОД         : по закрытию дня T+2 (MOC). Без стопов, без целей. Держать ровно 2 сессии.
  РАЗМЕР        : 5% капитала на имя (макс. 10 имён = 50% капитала на когорту).
                  Если сигнал два дня подряд — вторая когорта ещё 50%. Больше двух когорт
                  одновременно быть не может (держим 2 сессии). Без плеча.
  БЕЗ СИГНАЛА   : ничего не делаем (в рынке ~10% времени).

Запуск:
    pip install yfinance pandas numpy
    python dip_buyer.py                # после закрытия: сигнал по завершённому дню T -> ордера MOO на T+1
    python dip_buyer.py --live         # 15:45-15:55 ET: оценка по текущим ценам -> ордера MOC сегодня
    python dip_buyer.py --universe my_tickers.txt   # свой список (по умолчанию: data/nasdaq_universe.csv
                                                    # из репо exodus611 или встроенный список топ-ликвидных)
"""
import os, sys, time, argparse, datetime as dt
import numpy as np, pandas as pd

RSI_THR = 10.0
DIP = -0.03
MIN_DVOL = 2e7
MIN_PRICE = 5.0
MAX_NAMES = 10
WEIGHT = 0.05

# Fallback universe: liquid NASDAQ names (used only if no universe file is found)
FALLBACK = """AAPL MSFT NVDA AMZN META GOOGL GOOG TSLA AVGO COST NFLX AMD PEP ADBE CSCO TMUS QCOM INTC INTU TXN AMAT CMCSA
AMGN HON ISRG BKNG MU LRCX ADI VRTX PANW ADP REGN GILD SBUX MDLZ KLAC MELI SNPS CDNS CRWD MAR ASML PYPL ABNB CTAS ORLY
MRVL CSX NXPI FTNT PCAR ROP MNST WDAY ADSK DASH CPRT AEP PAYX ROST ODFL FAST KDP CHTR EA DDOG TTD IDXX BKR GEHC VRSK
XEL EXC KHC CTSH CCEP FANG TEAM ON CSGP ANSS ZS DXCM CDW BIIB LULU WBD ILMN GFS MDB MRNA WBA ARM SMCI COIN PLTR APP
AXON TTWO ALGN ENPH ZM OKTA DOCU RIVN LCID SOFI HOOD MSTR IREN APLD AAOI NBIS CRDO ALAB ASTS RKLB SNDK""".split()


def rsi2(close: pd.Series) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=0.5, adjust=False).mean()
    dn = (-d).clip(lower=0).ewm(alpha=0.5, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def load_universe(path):
    if path and os.path.exists(path):
        if path.endswith(".csv"):
            u = pd.read_csv(path)
            col = "symbol" if "symbol" in u.columns else u.columns[0]
            return [str(t).replace("/", "-") for t in u[col].dropna()]
        return [l.strip() for l in open(path) if l.strip()]
    for cand in ("data/universe_nasdaq.csv", "universe_nasdaq.csv"):
        if os.path.exists(cand):
            return load_universe(cand)
    print("[i] universe file not found -> using built-in list of liquid NASDAQ names")
    return FALLBACK


def download(tickers, period="14mo"):
    import yfinance as yf
    frames = {}
    for i in range(0, len(tickers), 150):
        batch = tickers[i:i + 150]
        for attempt in range(3):
            try:
                d = yf.download(batch, period=period, interval="1d", group_by="ticker", threads=True, progress=False, auto_adjust=True)
                for t in batch:
                    try:
                        x = d[t].dropna(how="all")
                        if len(x) >= 210:
                            frames[t] = x
                    except Exception:
                        pass
                break
            except Exception as e:
                print("  retry", i, e); time.sleep(10)
    return frames


def live_quotes(tickers):
    """Current (intraday) price + today's volume so far, for the 15:50 estimate."""
    import yfinance as yf
    out = {}
    for i in range(0, len(tickers), 150):
        batch = tickers[i:i + 150]
        try:
            d = yf.download(batch, period="1d", interval="1m", group_by="ticker", threads=True, progress=False, auto_adjust=False)
            for t in batch:
                try:
                    x = d[t].dropna(subset=["Close"])
                    out[t] = (float(x["Close"].iloc[-1]), float(x["Volume"].sum()), x.index[-1])
                except Exception:
                    pass
        except Exception as e:
            print("  live batch failed", e)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="intraday estimate for MOC entry today (run 15:45-15:55 ET)")
    ap.add_argument("--universe", default=None)
    ap.add_argument("--capital", type=float, default=100000.0)
    args = ap.parse_args()

    tickers = load_universe(args.universe)
    print(f"universe: {len(tickers)} tickers | downloading daily history ...", flush=True)
    hist = download(tickers)
    qqq = download(["QQQ"])["QQQ"]
    print(f"history ok for {len(hist)} names | last daily bar: {qqq.index[-1].date()}")

    # ---------------- market trigger
    qc = qqq["Close"].copy()
    if args.live:
        lq = live_quotes(["QQQ"])
        if "QQQ" not in lq:
            sys.exit("no live QQQ quote")
        px, _, ts = lq["QQQ"]
        if qc.index[-1].date() == pd.Timestamp(ts).date():
            qc.iloc[-1] = px  # yfinance may already include today's partial bar
        else:
            qc.loc[pd.Timestamp(ts).normalize()] = px
        print(f"LIVE mode: QQQ now {px:.2f} at {ts}")
    r = rsi2(qc)
    q_rsi = float(r.iloc[-1])
    sig_date = qc.index[-1].date()
    print(f"\nQQQ RSI(2) on {sig_date}: {q_rsi:.1f}   (trigger < {RSI_THR:.0f})   QQQ 1d: {qc.iloc[-1]/qc.iloc[-2]-1:+.2%}")
    if q_rsi >= RSI_THR:
        margin = "close call — re-check at 15:55" if q_rsi < 15 else ""
        print(f"=> NO SIGNAL. Do nothing today. {margin}")
        return

    # ---------------- stock filter
    lq = live_quotes(list(hist.keys())) if args.live else {}
    rows = []
    for t, d in hist.items():
        c = d["Close"].copy(); v = d["Volume"].copy()
        if args.live:
            if t not in lq:
                continue
            px, vol_today, ts = lq[t]
            if c.index[-1].date() == pd.Timestamp(ts).date():
                c.iloc[-1] = px
            else:
                c.loc[pd.Timestamp(ts).normalize()] = px; v.loc[pd.Timestamp(ts).normalize()] = vol_today
        if len(c) < 205 or c.index[-1].date() != sig_date:
            continue
        ret1 = c.iloc[-1] / c.iloc[-2] - 1
        sma200 = c.iloc[-200:].mean()
        dv21 = float((c.iloc[-22:-1] * v.iloc[-22:-1]).mean())   # exclude today's partial volume
        if c.iloc[-1] >= MIN_PRICE and dv21 >= MIN_DVOL and c.iloc[-1] > sma200 and ret1 <= DIP:
            rows.append(dict(ticker=t, price=round(float(c.iloc[-1]), 2), ret_1=round(float(ret1), 4), above_sma200=round(float(c.iloc[-1] / sma200 - 1), 3), dvol_M=round(dv21 / 1e6, 0)))
    if not rows:
        print("=> market trigger ON but no stock passed the filter. Fallback: nothing (or buy QQQ itself — historically ~+30bp/48h on these days).")
        return
    S = pd.DataFrame(rows).sort_values("dvol_M", ascending=False).head(MAX_NAMES).reset_index(drop=True)
    S["weight"] = WEIGHT
    S["dollars"] = (args.capital * WEIGHT).round(0)
    S["shares"] = (S["dollars"] / S["price"]).astype(int)
    S["entry"] = "MOC today" if args.live else "MOO next session"
    exit_note = "MOC on T+2 (2nd session after entry day)" if args.live else "MOC on the 2nd session after the entry session"
    S["exit"] = exit_note
    pd.set_option("display.width", 200)
    print(f"\n=== SIGNAL {sig_date}: BUY {len(S)} names, {WEIGHT:.0%} of capital each (total {len(S)*WEIGHT:.0%}) ===")
    print(S.to_string(index=False))
    print(f"\nExit rule: sell everything from this cohort at the CLOSE of the 2nd trading session after entry. No stops, no targets.")
    print("If tomorrow triggers again -> open a second cohort with another 50%. Never more than 2 cohorts.")
    os.makedirs("output", exist_ok=True)
    S.to_csv(f"output/dip_buyer_{sig_date}.csv", index=False)
    print(f"saved output/dip_buyer_{sig_date}.csv")


if __name__ == "__main__":
    main()
