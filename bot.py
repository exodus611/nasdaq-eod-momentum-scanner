#!/usr/bin/env python3
"""
DIP-BUYER NASDAQ v2 — daily paper-trading scanner with a dashboard. No Telegram, no broker, no orders.

Rule v2 (2026-09-14):
  signal day : QQQ RSI(2) at the close < 10  (market oversold, "tier A")
  candidates : NASDAQ stocks, close > SMA200, today <= -3%, avg $volume(21d) >= 20M$, price >= 5$, ranked by liquidity
  entry      : NEXT OPEN, at most MAX_NEW (2) new names per session, up to MAX_POS (4) positions, PER_NAME (25%) of capital each
  exit       : NEXT OPEN after the first close ABOVE the stock's 10-day SMA, or after MAX_HOLD (20) sessions. No stops, no targets.
  2010-2026  : +181 bp/trade, 70% winners, ~34 trades/yr, avg hold 6.5 sessions, CAGR 15.2%, maxDD -23%, 15/17 years positive
               (2010-2016 out-of-sample: CAGR 20%, maxDD -15%, 7/7 years). See STRATEGY.md and research/v2_exit_test.py.
Two paper books with IDENTICAL rules are kept: "trade" (tier-A days only) and "everyday" (every day, no market filter).
The second exists to show live why the market filter matters (2010-2026 without it: +45 bp/trade, maxDD -60%, 11/17 years).

Usage:
  python bot.py run                              # daily job (after close)
  python bot.py run --asof 2026-08-20            # replay one past session (marked "replay")
  python bot.py backfill --from D1 --to D2       # replay a range with ONE download
  python bot.py test | rebuild-page | refresh-universe

Env: CAPITAL=100000  MAX_POS=4  PER_NAME=0.25  MAX_NEW=2  RSI_THR=10  EXIT_SMA=10  MAX_HOLD=20  REPO_URL  PAGES_URL
"""
import os, json, time, argparse, datetime as dt, urllib.request
from zoneinfo import ZoneInfo
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ET = ZoneInfo("America/New_York")

def _load_env():
    p = os.path.join(HERE, ".env")
    if os.path.exists(p):
        for line in open(p):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1); os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
_load_env()

CAPITAL = float(os.environ.get("CAPITAL", "100000"))
MAX_POS = int(os.environ.get("MAX_POS", "4"))
PER_NAME = float(os.environ.get("PER_NAME", str(round(1 / MAX_POS, 4))))
RSI_THR = float(os.environ.get("RSI_THR", "10"))
EXIT_SMA = int(os.environ.get("EXIT_SMA", "10")); MAX_HOLD = int(os.environ.get("MAX_HOLD", "20"))
MAX_NEW = int(os.environ.get("MAX_NEW", "2"))                                             # at most 2 new names per session
DIP, MIN_DVOL, MIN_PRICE = -0.03, 2e7, 5.0
COST = 0.0010                                              # round-trip cost assumed in paper P&L (10 bp)
REPO_URL = os.environ.get("REPO_URL", "").rstrip("/")
PAGES_URL = os.environ.get("PAGES_URL", "").strip()
if not PAGES_URL and REPO_URL.startswith("https://github.com/") and REPO_URL.count("/") == 4:
    _u, _r = REPO_URL.split("/")[3:5]; PAGES_URL = f"https://{_u}.github.io/{_r}/"
UNIVERSE = os.path.join(HERE, "data", "universe_nasdaq.csv")
STATE, DOCS = os.path.join(HERE, "state"), os.path.join(HERE, "docs")
SCANS = os.path.join(STATE, "scans")
POS, JOURNAL, DAILY = (os.path.join(STATE, f) for f in ("positions.json", "journal.csv", "daily_log.csv"))
LATEST, ATTEMPT = os.path.join(STATE, "latest.json"), os.path.join(STATE, "last_attempt.json")
README = os.path.join(HERE, "README.md")
for d in (STATE, DOCS, SCANS, os.path.join(HERE, "data")):
    os.makedirs(d, exist_ok=True)
BOOKS = {"trade": "Strategy (tier-A days only)", "everyday": "Control (every day, no market filter)"}
TIERS = {"A": dict(icon="🟢", label=f"SIGNAL A — market oversold (QQQ RSI2 < {RSI_THR:.0f}): buy", color="#1e8449", bg="#e9f7ef"),
         "B": dict(icon="🟡", label=f"weak market (QQQ RSI2 {RSI_THR:.0f}–30) — no new buys, manage open positions only", color="#9a7d0a", bg="#fdf6e3"),
         "C": dict(icon="⚪", label="normal day (QQQ RSI2 ≥ 30) — no new buys, manage open positions only", color="#57606a", bg="#f6f8fa"),
         "NO_DATA": dict(icon="⚠️", label="no data for this session", color="#c0392b", bg="#fdedec")}
JCOLS = ["book", "signal_date", "tier", "ticker", "entry_date", "entry_px", "shares", "exit_signal_date", "exit_date", "exit_px", "exit_reason", "hold", "ret_gross", "ret_net", "pnl_usd", "status", "mode"]


# ------------------------------------------------------------------ helpers
def now_et(): return dt.datetime.now(ET)
def log(*a): print(*a, flush=True)
def _isnan(x): return x is None or (isinstance(x, float) and np.isnan(x))
def d2s(d): return "" if _isnan(d) or not d else str(d)[:10]                       # 2026-09-18
def dlong(d):                                                                       # Sep 18, 2026
    if _isnan(d) or not d: return ""
    if isinstance(d, str): d = dt.date.fromisoformat(d[:10])
    return f"{d:%b %d, %Y}"
def usd(x, sign=False):
    if _isnan(x): return ""
    s = f"${abs(x):,.0f}"
    return (("+" if x > 0 else "-" if x < 0 else "") + s) if sign else (("-" if x < 0 else "") + s)
def tier_of(rsi): return "A" if rsi < RSI_THR else ("B" if rsi < 30 else "C")
def reason_text(r): return f"close above SMA{EXIT_SMA}" if str(r).startswith("SMA") else (f"{MAX_HOLD}-session limit" if r == "MAX_HOLD" else str(r))
def fmt_run_at(s):
    try: return dt.datetime.strptime(str(s).replace(" ET", ""), "%d.%m.%Y %H:%M").strftime("%Y-%m-%d %H:%M ET")
    except Exception: return str(s)

def rsi2(close):
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=0.5, adjust=False).mean()
    dn = (-d).clip(lower=0).ewm(alpha=0.5, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))

def load_universe():
    u = pd.read_csv(UNIVERSE); col = "symbol" if "symbol" in u.columns else u.columns[0]
    return sorted({str(t).replace("/", "-").strip() for t in u[col].dropna() if str(t).isascii()})

def refresh_universe():
    try:
        rows, offset = [], 0
        while True:
            url = f"https://api.nasdaq.com/api/screener/stocks?tableonly=true&limit=1000&offset={offset}&exchange=NASDAQ"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
            batch = json.loads(urllib.request.urlopen(req, timeout=30).read().decode()).get("data", {}).get("table", {}).get("rows", [])
            if not batch: break
            rows += batch; offset += len(batch)
            if len(batch) < 1000: break
        df = pd.DataFrame(rows)
        df["mcap"] = pd.to_numeric(df["marketCap"].str.replace(",", "").str.replace("$", ""), errors="coerce")
        df["price"] = pd.to_numeric(df["lastsale"].str.replace("$", "").str.replace(",", ""), errors="coerce")
        liq = df[(df.price >= 3) & (df.mcap >= 5e8)]
        if len(liq) > 800:
            liq[["symbol", "name"]].to_csv(UNIVERSE, index=False); log(f"universe refreshed: {len(liq)} names")
    except Exception as e:
        log("universe refresh failed, keeping cached list:", e)

def download(tickers, period="14mo"):
    import yfinance as yf
    out = {}
    for i in range(0, len(tickers), 150):
        batch = tickers[i:i + 150]
        for attempt in range(3):
            try:
                d = yf.download(batch, period=period, interval="1d", group_by="ticker", threads=True, progress=False, auto_adjust=True)
                for t in batch:
                    try:
                        x = d[t].dropna(subset=["Close"])
                        if len(x) >= 30: out[t] = x
                    except Exception: pass
                break
            except Exception as e:
                log("  retry", i, e); time.sleep(10)
    return out

def fetch_qqq(asof, wait):
    q = None
    for attempt in range(4):
        q = download(["QQQ"], period="14mo").get("QQQ")
        if q is None: time.sleep(30); continue
        if q.index[-1].date() >= asof or not wait or attempt == 3: break
        log(f"  no QQQ bar for {asof} yet (last {q.index[-1].date()}); waiting 5 min"); time.sleep(300)
    return q


# ------------------------------------------------------------------ scan
def scan(hist, today):
    rows = []
    for tk, d in hist.items():
        m = d.index.date <= today
        c, v = d["Close"][m], d["Volume"][m]
        if len(c) < 205 or c.index[-1].date() != today: continue
        ret1 = float(c.iloc[-1] / c.iloc[-2] - 1); sma200 = float(c.iloc[-200:].mean())
        dv21 = float((c.iloc[-22:-1] * v.iloc[-22:-1]).mean())
        if c.iloc[-1] >= MIN_PRICE and dv21 >= MIN_DVOL and c.iloc[-1] > sma200 and ret1 <= DIP:
            rows.append(dict(ticker=tk, close=round(float(c.iloc[-1]), 2), ret_1=round(ret1, 4), dvol_M=round(dv21 / 1e6), vs_sma200=round(float(c.iloc[-1] / sma200 - 1), 3),
                             sma10=round(float(c.iloc[-EXIT_SMA:].mean()), 2)))
    df = pd.DataFrame(rows, columns=["ticker", "close", "ret_1", "dvol_M", "vs_sma200", "sma10"])
    return df.sort_values("dvol_M", ascending=False).reset_index(drop=True)


# ------------------------------------------------------------------ state
def load_state():
    if os.path.exists(POS):
        s = json.load(open(POS))
        if "books" in s: return s
    return {"books": {"trade": [], "everyday": []}}
def save_state(s): json.dump(s, open(POS, "w"), indent=1, default=str, ensure_ascii=False)
def all_positions(s): return [dict(p, book=b) for b in BOOKS for p in s["books"][b]]
def journal_df(s=None):
    s = s or load_state(); rows = all_positions(s)
    j = pd.DataFrame(rows) if rows else pd.DataFrame(columns=JCOLS)
    for c in JCOLS:
        if c not in j.columns: j[c] = None
    return j
def journal_write(s): journal_df(s)[JCOLS].to_csv(JOURNAL, index=False)
def daily_df(): return pd.read_csv(DAILY) if os.path.exists(DAILY) else pd.DataFrame(columns=["date", "mode", "q_close", "q_ret", "q_rsi", "tier", "n_candidates", "picks", "buy", "sell", "hold"])
def daily_log(row): pd.DataFrame([row]).to_csv(DAILY, mode="a", header=not os.path.exists(DAILY), index=False)
def asof_done(asof): return os.path.exists(DAILY) and str(asof) in set(pd.read_csv(DAILY)["date"].astype(str))
def latest(): return json.load(open(LATEST)) if os.path.exists(LATEST) else None

def equity_curve(c):
    if len(c) == 0: return pd.Series(dtype=float)
    return CAPITAL + c.groupby("exit_date")["pnl_usd"].sum().sort_index().cumsum()

def stats(c):
    if len(c) == 0: return dict(n=0)
    eq = pd.concat([pd.Series([CAPITAL]), equity_curve(c)]); days = c.groupby("signal_date")["ret_net"].mean()
    return dict(n=int(len(c)), days=int(days.size), mean=float(c.ret_net.mean() * 100), median=float(c.ret_net.median() * 100), hit=float((c.ret_net > 0).mean() * 100),
                pnl=float(c.pnl_usd.sum()), pnl_pct=float(c.pnl_usd.sum() / CAPITAL * 100), maxdd=float((eq / eq.cummax() - 1).min() * 100),
                best=float(c.ret_net.max() * 100), worst=float(c.ret_net.min() * 100), hold=float(c.hold.astype(float).mean()))

def track_record(s):
    j = journal_df(s); c = j[j.status == "closed"].copy()
    out = {b: stats(c[c.book == b]) for b in BOOKS}
    for t in "ABC": out["everyday_" + t] = stats(c[(c.book == "everyday") & (c.tier == t)])
    for b in BOOKS:
        op = [p for p in s["books"][b] if p["status"] in ("open", "exiting") and p.get("upnl") is not None]
        out[b]["open_n"] = len(op); out[b]["open_pnl"] = float(sum(p["upnl"] * p["entry_px"] * p["shares"] for p in op))
    t = out["trade"]
    out["text"] = ("Strategy: no closed trades yet." if not t["n"] else
                   f"Strategy: {t['n']} trades · avg {t['mean']:+.2f}% · median {t['median']:+.2f}% · win rate {t['hit']:.0f}% · avg hold {t['hold']:.1f} sessions · "
                   f"P&L {usd(t['pnl'], True)} ({t['pnl_pct']:+.2f}% of {usd(CAPITAL)}) · max DD {t['maxdd']:.1f}%")
    if t.get("open_n"): out["text"] += f" · {t['open_n']} open (unrealized {usd(t['open_pnl'], True)})"
    e = out["everyday"]
    out["text_e"] = "" if not e["n"] else f"Control (every day, no market filter): {e['n']} trades · avg {e['mean']:+.2f}% · win rate {e['hit']:.0f}% · P&L {usd(e['pnl'], True)} · max DD {e['maxdd']:.1f}%"
    return out

def ev_text(e):
    if isinstance(e, str): return e
    tag = "" if e["book"] == "trade" else " [control book]"
    if e["kind"] == "fill": return f"📥 Bought at the open {dlong(e['date'])}{tag}: {e['ticker']} {e['shares']} sh @ {e['px']:.2f}"
    return (f"{'✅' if e['pnl'] > 0 else '❌'} Sold at the open {dlong(e['date'])}{tag}: {e['ticker']} {e['ret'] * 100:+.1f}% → {usd(e['pnl'], True)} "
            f"(held {e['hold']} sessions, exit: {reason_text(e['reason'])})")


# ------------------------------------------------------------------ core: process one completed session
def process(today, qq, hist, live, now, mode=None):
    td = [x.date() for x in qq.index]; i = len(td) - 1
    qc = qq["Close"]; q_rsi = float(rsi2(qc).iloc[-1]); q_ret = float(qc.iloc[-1] / qc.iloc[-2] - 1); q_close = float(qc.iloc[-1])
    tier = tier_of(q_rsi); mode = mode or ("live" if live else "replay")
    cands = scan(hist, today); S = load_state(); events = []

    def px(tk, col, day):
        d = hist.get(tk)
        if d is None: return None
        m = d.index.date == day
        return float(d[col][m].iloc[-1]) if m.any() else None
    def sma(tk, day, n):
        d = hist.get(tk)
        if d is None: return None
        c = d["Close"][d.index.date <= day]
        return float(c.iloc[-n:].mean()) if len(c) >= n else None

    acts = {b: dict(buy=[], sell=[], hold=[], filled=[], closed=[]) for b in BOOKS}
    for b in BOOKS:
        P = S["books"][b]
        # 1) fills at today's open (or at the open of the session after the signal, if the bot skipped days)
        for p in P:
            tk = p["ticker"]
            if p["status"] == "pending":
                sd = dt.date.fromisoformat(p["signal_date"])
                if sd not in td or td.index(sd) + 1 > i: continue
                ed = td[td.index(sd) + 1]; o = px(tk, "Open", ed)
                if o: p.update(entry_date=str(ed), entry_px=round(o, 4), shares=int(CAPITAL * PER_NAME / o), status="open"); acts[b]["filled"].append(p)
                else: p["status"] = "no_data"
            elif p["status"] == "exiting":
                xd = dt.date.fromisoformat(p["exit_signal_date"])
                if xd not in td or td.index(xd) + 1 > i: continue
                ed = td[td.index(xd) + 1]; o = px(tk, "Open", ed)
                if o:
                    r = o / p["entry_px"] - 1; rn = r - COST
                    p.update(exit_date=str(ed), exit_px=round(o, 4), ret_gross=round(r, 5), ret_net=round(rn, 5), pnl_usd=round(rn * p["entry_px"] * p["shares"], 2),
                             hold=td.index(ed) - td.index(dt.date.fromisoformat(p["entry_date"])), status="closed", upnl=None); acts[b]["closed"].append(p)
        # 2) exit signals at today's close
        for p in P:
            if p["status"] != "open": continue
            tk = p["ticker"]; ed = dt.date.fromisoformat(p["entry_date"]); held = i - td.index(ed) + 1
            c = px(tk, "Close", today); s10 = sma(tk, today, EXIT_SMA)
            p.update(last_px=c, held=held, sma10=s10, upnl=(c / p["entry_px"] - 1) if c else None)
            if (c and s10 and c > s10) or held >= MAX_HOLD:
                p.update(status="exiting", exit_signal_date=str(today), exit_reason=("SMA%d" % EXIT_SMA) if (c and s10 and c > s10) else "MAX_HOLD"); acts[b]["sell"].append(p)
            else:
                acts[b]["hold"].append(p)
        # 3) entries: signal at today's close -> pending -> fill at next open
        held_now = {p["ticker"] for p in P if p["status"] in ("pending", "open", "exiting")}
        slots = min(MAX_NEW, MAX_POS - len([p for p in P if p["status"] in ("pending", "open")]))
        if (b == "everyday" or tier == "A") and slots > 0:
            for r in cands.itertuples():
                if slots <= 0: break
                if r.ticker in held_now: continue
                p = dict(ticker=r.ticker, signal_date=str(today), tier=tier, status="pending", mode=mode, signal_close=r.close, ret_1=r.ret_1, dvol_M=r.dvol_M,
                         usd=round(CAPITAL * PER_NAME), shares_est=int(CAPITAL * PER_NAME / r.close))
                P.append(p); acts[b]["buy"].append(p); slots -= 1
    # events (structured; rendered by ev_text — trade book first)
    for b in BOOKS:
        for p in acts[b]["filled"]: events.append(dict(kind="fill", book=b, ticker=p["ticker"], shares=p["shares"], px=p["entry_px"], date=p["entry_date"]))
        for p in acts[b]["closed"]: events.append(dict(kind="close", book=b, ticker=p["ticker"], ret=p["ret_net"], pnl=p["pnl_usd"], date=p["exit_date"], hold=p["hold"], reason=p["exit_reason"]))
    save_state(S); journal_write(S)
    T = acts["trade"]
    L = dict(run_at=f"{now:%Y-%m-%d %H:%M} ET", mode=mode, sig_date=str(today), q_close=round(q_close, 2), q_ret=round(q_ret, 4), q_rsi=round(q_rsi, 1), tier=tier, status=tier,
             n_candidates=int(len(cands)), candidates=cands.head(40).to_dict("records"), picks=cands.head(MAX_NEW).to_dict("records"),
             buy=[dict(ticker=p["ticker"], close=p["signal_close"], ret_1=p["ret_1"], dvol_M=p["dvol_M"], usd=p["usd"], shares_est=p["shares_est"]) for p in T["buy"]],
             sell=[dict(ticker=p["ticker"], shares=p["shares"], entry_px=p["entry_px"], last_px=p.get("last_px"), upnl=p.get("upnl"), held=p.get("held"), reason=p.get("exit_reason")) for p in T["sell"]],
             hold=[dict(ticker=p["ticker"], shares=p["shares"], entry_px=p["entry_px"], last_px=p.get("last_px"), upnl=p.get("upnl"), held=p.get("held"), sma10=p.get("sma10")) for p in T["hold"]],
             everyday=dict(buy=[p["ticker"] for p in acts["everyday"]["buy"]], sell=[p["ticker"] for p in acts["everyday"]["sell"]], hold=[p["ticker"] for p in acts["everyday"]["hold"]]),
             events=events, track=track_record(S), params=dict(max_pos=MAX_POS, per_name=PER_NAME, max_new=MAX_NEW, rsi_thr=RSI_THR, exit_sma=EXIT_SMA, max_hold=MAX_HOLD))
    json.dump(L, open(LATEST, "w"), ensure_ascii=False, indent=1, default=str)
    json.dump(L, open(os.path.join(SCANS, f"{today}.json"), "w"), ensure_ascii=False, default=str)
    daily_log(dict(date=str(today), mode=mode, q_close=round(q_close, 2), q_ret=round(q_ret, 4), q_rsi=round(q_rsi, 1), tier=tier, n_candidates=len(cands),
                   picks=" ".join(cands.head(MAX_NEW).ticker), buy=" ".join(p["ticker"] for p in T["buy"]), sell=" ".join(p["ticker"] for p in T["sell"]), hold=" ".join(p["ticker"] for p in T["hold"])))
    log("\n" + summary_text(L) + "\n")
    return L


def summary_text(L):
    T = TIERS[L["tier"]]
    out = [f"📊 {dlong(L['sig_date'])} (after the close)  QQQ {L['q_close']:.2f} {L['q_ret'] * 100:+.2f}%  RSI(2) = {L['q_rsi']:.1f}  →  {T['icon']} {T['label']}"] + [ev_text(e) for e in L["events"]]
    for b in L["buy"]: out.append(f"➡️ BUY AT TOMORROW'S OPEN: {b['ticker']:<6} close {b['close']:>8.2f}  today {b['ret_1']*100:+.1f}%  turnover ${b['dvol_M']:,.0f}M/day  → {PER_NAME:.0%} of capital ≈ {usd(b['usd'])} (~{b['shares_est']} sh)")
    for s in L["sell"]: out.append(f"🔴 SELL AT TOMORROW'S OPEN: {s['ticker']} {s['shares']} sh (entry {s['entry_px']:.2f}, last {s['last_px']:.2f}, {s['upnl']*100:+.1f}%, {s['held']} sessions, {reason_text(s['reason'])})")
    for h in L["hold"]: out.append(f"⏳ HOLD: {h['ticker']} {h['shares']} sh (entry {h['entry_px']:.2f}, last {h['last_px']:.2f}, {h['upnl']*100:+.1f}%, {h['held']} sessions; sell after a close above SMA{EXIT_SMA} = {h['sma10']:.2f})")
    if not L["buy"] and not L["sell"] and not L["hold"]: out.append("No positions, nothing to do tomorrow.")
    out.append(L["track"]["text"])
    if L["track"]["text_e"]: out.append(L["track"]["text_e"])
    return "\n".join(out)


# ------------------------------------------------------------------ entry points
def run(asof=None):
    live, now = asof is None, now_et(); strict = True
    if live:
        asof = now.date()
        if now.weekday() >= 5 or now.hour * 60 + now.minute < 16 * 60 + 10:
            asof, strict = asof - dt.timedelta(days=1), False
            log(f"market not closed yet / weekend — processing the last completed session (<= {asof})")
    if asof_done(asof): log(f"{asof}: already processed — nothing to do"); return
    if asof > last_completed_session_date(): log(f"{asof}: session not finished yet — refusing to use a partial bar"); return
    qqq = fetch_qqq(asof, live and strict)
    qq = qqq[qqq.index.date <= asof] if qqq is not None else None
    if qq is None or len(qq) < 5: log("QQQ data unavailable"); return
    last = qq.index[-1].date()
    if not strict and asof_done(last): log(f"{last}: already processed — nothing to do"); return
    if last != asof and strict:
        if live:
            json.dump(dict(run_at=f"{now:%Y-%m-%d %H:%M} ET", asof=str(asof), status="NO_DATA",
                           note=f"No daily bar for {dlong(asof)} yet (last: {dlong(last)}) — market holiday or data lag. Nothing to do."), open(ATTEMPT, "w"), ensure_ascii=False)
            build_page(); log(f"{asof}: no daily bar yet (last {last}) — holiday or data lag; nothing to do")
        else:
            log(f"{asof} is not a trading day (last bar {last}) -> skip")
        return
    if os.path.exists(ATTEMPT): os.remove(ATTEMPT)
    tickers = load_universe(); log(f"{last}: QQQ RSI(2)={float(rsi2(qq['Close']).iloc[-1]):.1f} | universe {len(tickers)} | downloading…")
    hist = download(tickers)
    for d in missing_sessions(qq, last):                       # sessions the bot missed (outage / failed run) are caught up first, in order
        if d != last: log(f"catch-up: {d}")
        process(d, qq[qq.index.date <= d], hist, live, now, mode=(None if d == last else "catch-up"))
    build_page()

def missing_sessions(qq, last, cap=5):
    """All sessions after the last processed one up to `last` (max `cap`), so a missed day is not lost."""
    dl = daily_df()
    if not len(dl): return [last]
    lastdone = max(dt.date.fromisoformat(str(d)) for d in dl["date"])
    todo = [x.date() for x in qq.index if lastdone < x.date() <= last]
    return todo[-cap:] or [last]

def last_completed_session_date():
    """Never use a partial (intraday) bar: before 16:10 ET today's bar is not final."""
    now = now_et()
    return now.date() if now.hour * 60 + now.minute >= 16 * 60 + 10 else now.date() - dt.timedelta(days=1)

def backfill(d1, d2):
    d2 = min(d2, last_completed_session_date())
    qqq = download(["QQQ"], period="14mo")["QQQ"]
    tickers = load_universe(); log(f"backfill {d1}..{d2} | universe {len(tickers)} | downloading once…")
    hist = download(tickers); days = [x.date() for x in qqq.index if d1 <= x.date() <= d2]
    for d in days:
        if asof_done(d): log(f"{d}: already processed"); continue
        process(d, qqq[qqq.index.date <= d], hist, False, now_et())
    build_page(); log(f"backfill done: {len(days)} sessions")

def test():
    q = download(["QQQ"], period="6mo").get("QQQ")
    if q is None: log("❌ QQQ download failed"); raise SystemExit(1)
    r = float(rsi2(q["Close"]).iloc[-1])
    log(f"✅ data OK: QQQ last bar {q.index[-1].date()} close {float(q['Close'].iloc[-1]):.2f}, RSI(2) = {r:.1f} → tier {tier_of(r)}; now {now_et():%Y-%m-%d %H:%M} ET")
    build_page(); log("✅ dashboard rebuilt: docs/index.html")


# ------------------------------------------------------------------ dashboard (docs/index.html) + README block
CSS = """
*{box-sizing:border-box}body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;max-width:1060px;margin:0 auto;padding:18px 14px 40px;color:#1f2328;background:#fff;line-height:1.45}
h1{font-size:22px;margin:0 0 4px}h2{font-size:17px;margin:26px 0 8px;border-bottom:1px solid #d8dee4;padding-bottom:4px}h3{font-size:15px;margin:14px 0 6px}
.muted{color:#57606a;font-size:13px}.card{border:1px solid #d0d7de;border-radius:10px;padding:14px 16px;margin:12px 0;background:#fff}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}@media(max-width:760px){.grid{grid-template-columns:1fr}}
.status{font-size:18px;font-weight:700}.kv{display:flex;flex-wrap:wrap;gap:6px 22px;margin-top:8px;font-size:14px}.kv b{font-size:16px}
table{border-collapse:collapse;width:100%;font-size:13px;margin:6px 0}th,td{border:1px solid #d8dee4;padding:5px 8px;text-align:left;white-space:nowrap}th{background:#f6f8fa;font-weight:600}
tr.pick td{background:#e9f7ef;font-weight:600}tr.strat td{background:#f0fff4;font-weight:700}.pos{color:#1e8449}.neg{color:#c0392b}
.tag{display:inline-block;font-size:11px;padding:1px 6px;border-radius:10px;background:#eaeef2;color:#57606a;margin-left:4px}
.act{font-size:15px;padding-left:20px}.act li{margin:6px 0}.bar{position:relative;height:10px;background:linear-gradient(90deg,#1e8449 0 10%,#eaeef2 10% 100%);border-radius:5px;margin:8px 0 2px}
.bar i{position:absolute;top:-4px;width:4px;height:18px;background:#1f2328;border-radius:2px}.wrap{overflow-x:auto}.ev{margin:6px 0;padding:8px 12px;background:#f6f8fa;border-radius:8px}
.big{font-size:21px;font-weight:800;letter-spacing:.4px}
"""
def _cls(x): return "pos" if x > 0 else "neg"
def _pct(x, d=2): return "" if _isnan(x) else f"{x * 100:+.{d}f}%"
def _num(x, d=2): return "" if _isnan(x) else f"{x:,.{d}f}"

def build_page():
    L, S, dl = latest(), load_state(), daily_df(); j = journal_df(S)
    att = json.load(open(ATTEMPT)) if os.path.exists(ATTEMPT) else None
    tr = track_record(S); strat = f"{REPO_URL}/blob/main/STRATEGY.md" if REPO_URL else "#"; upd = f"{now_et():%Y-%m-%d %H:%M} ET"
    parts = [f"<h1>Dip-Buyer NASDAQ v2 — paper trading</h1><div class='muted'>Mean-reversion scanner for NASDAQ stocks. Runs once a day after the US close, keeps a paper journal at real open prices "
             f"and publishes this page. No orders are sent — the output is a set of instructions for the next session. Updated {upd}"
             + (f" · <a href='{REPO_URL}'>repository</a>" if REPO_URL else "") + (f" · <a href='{strat}'>strategy &amp; backtest</a>" if REPO_URL else "") + "</div>"]
    if att: parts.append(f"<div class='card' style='background:#fdf6e3;border-color:#e6c65a'>⚠️ Attempt {fmt_run_at(att['run_at'])}: {att['note']}</div>")
    if L is None:
        parts.append("<div class='card'>No runs yet.</div>")
    else:
        T = TIERS[L["tier"]]; rsi = max(0.0, min(100.0, float(L["q_rsi"])))
        parts.append("<div class='grid'>")
        parts.append(f"<div class='card' style='background:{T['bg']};border-color:{T['color']}'><div class='muted'>Scan for {dlong(L['sig_date'])} (after the close)"
                     + (f" <span class='tag'>{L['mode']}</span>" if L["mode"] != "live" else "") + f"</div><div class='status' style='color:{T['color']}'>{T['icon']} {T['label']}</div>"
                     f"<div class='kv'><span>QQQ <b>{L['q_close']:.2f}</b> <span class='{_cls(L['q_ret'])}'>{_pct(L['q_ret'])}</span></span><span>RSI(2) <b>{L['q_rsi']:.1f}</b></span>"
                     f"<span>passed the filter <b>{L['n_candidates']}</b></span></div><div class='bar'><i style='left:calc({rsi:.1f}% - 2px)'></i></div><div class='muted'>QQQ RSI(2): green zone &lt; {RSI_THR:.0f} = buy day</div></div>")
        acts = []
        for b in L["buy"]: acts.append(f"<li>🟢 <span class='big'>BUY {b['ticker']}</span> at the open — {PER_NAME:.0%} of capital ≈ {usd(b['usd'])} (~{b['shares_est']} sh; close {b['close']:.2f}, today {_pct(b['ret_1'],1)})</li>")
        for s in L["sell"]: acts.append(f"<li>🔴 <span class='big'>SELL {s['ticker']}</span> at the open — {s['shares']} sh, entry {s['entry_px']:.2f}, last {s['last_px']:.2f} (<span class='{_cls(s['upnl'])}'>{_pct(s['upnl'],1)}</span>), {s['held']} sessions, reason: {reason_text(s['reason'])}</li>")
        for h in L["hold"]: acts.append(f"<li>⏳ <b>HOLD {h['ticker']}</b> — {h['shares']} sh, entry {h['entry_px']:.2f}, last {h['last_px']:.2f} (<span class='{_cls(h['upnl'])}'>{_pct(h['upnl'],1)}</span>), {h['held']} sessions; sell at the open after the first close above SMA{EXIT_SMA} = {h['sma10']:.2f}</li>")
        if not acts: acts.append("<li>No positions, nothing to do tomorrow. Waiting for a day with QQQ RSI(2) &lt; %d.</li>" % RSI_THR)
        parts.append("<div class='card'><div class='muted'>Next session — strategy actions</div><ul class='act'>" + "".join(acts) + "</ul></div></div>")
        if L["events"]: parts.append("<h2>Events of this run</h2>" + "".join(f"<div class='ev'>{ev_text(e)}</div>" for e in L["events"]))
        parts.append(f"<h2>Scanner output — {dlong(L['sig_date'])}</h2>")
        if not L["candidates"]: parts.append("<div class='muted'>No stock passed the filter (close &gt; SMA200, day ≤ −3%, turnover ≥ $20M/day, price ≥ $5).</div>")
        else:
            bought = {b["ticker"] for b in L["buy"]}
            rows = "".join(f"<tr class='{'pick' if c['ticker'] in bought else ''}'><td>{i + 1}</td><td>{c['ticker']}</td><td>{c['close']:.2f}</td><td class='{_cls(c['ret_1'])}'>{_pct(c['ret_1'], 1)}</td>"
                           f"<td>{c['dvol_M']:,.0f}</td><td>{_pct(c['vs_sma200'], 0)}</td><td>{c.get('sma10', '')}</td></tr>" for i, c in enumerate(L["candidates"]))
            note = ("Strategy buys are highlighted." if bought else
                    ("Not a tier-A day — the strategy buys nothing; the list is for watching (the control book buys the top names by turnover from it)." if L["tier"] != "A" else "Tier-A day, but no free slots."))
            parts.append(f"<div class='muted'>Passed the filter: {L['n_candidates']} (first {len(L['candidates'])} shown, ranked by 21-day average turnover). {note}</div>"
                         f"<div class='wrap'><table><tr><th>#</th><th>ticker</th><th>close</th><th>day</th><th>turnover, $M/day</th><th>vs SMA200</th><th>SMA{EXIT_SMA}</th></tr>{rows}</table></div>")
    # positions
    parts.append("<h2>Open positions (paper)</h2>")
    op = [p for p in all_positions(S) if p["status"] in ("pending", "open", "exiting")]
    if not op: parts.append("<div class='muted'>None.</div>")
    else:
        rows = ""
        for p in sorted(op, key=lambda p: (p["book"] != "trade", p["signal_date"])):
            what = {"pending": "buy at the next open", "exiting": "sell at the next open", "open": f"holding; sell after a close above SMA{EXIT_SMA}" + (f" = {p['sma10']:.2f}" if p.get("sma10") else "")}[p["status"]]
            rows += (f"<tr><td>{BOOKS[p['book']]}</td><td>{d2s(p['signal_date'])} {p.get('tier','')}</td><td><b>{p['ticker']}</b></td><td>{d2s(p.get('entry_date'))}</td><td>{_num(p.get('entry_px'))}</td><td>{p.get('shares') or ''}</td>"
                     f"<td>{_num(p.get('last_px'))}</td><td class='{_cls(p['upnl']) if p.get('upnl') is not None else ''}'>{_pct(p.get('upnl'), 1)}</td><td>{p.get('held', '')}</td><td>{what}</td></tr>")
        parts.append(f"<div class='wrap'><table><tr><th>book</th><th>signal</th><th>ticker</th><th>entry</th><th>entry px</th><th>shares</th><th>last</th><th>P&amp;L</th><th>sessions</th><th>next</th></tr>{rows}</table></div>")
    # results
    def srow(name, s, cls=""):
        if not s.get("n"): return f"<tr class='{cls}'><td>{name}</td><td>0</td><td colspan='7' class='muted'>no closed trades yet</td></tr>"
        return (f"<tr class='{cls}'><td>{name}</td><td>{s['n']}</td><td class='{_cls(s['mean'])}'>{s['mean']:+.2f}%</td><td class='{_cls(s['median'])}'>{s['median']:+.2f}%</td><td>{s['hit']:.0f}%</td><td>{s['hold']:.1f}</td>"
                f"<td class='{_cls(s['pnl'])}'>{usd(s['pnl'], True)}</td><td class='{_cls(s['pnl_pct'])}'>{s['pnl_pct']:+.2f}%</td><td>{s['maxdd']:.1f}%</td></tr>")
    parts.append("<h2>Results (paper)</h2><div class='wrap'><table><tr><th>book</th><th>trades</th><th>avg</th><th>median</th><th>win rate</th><th>avg hold</th><th>P&amp;L</th><th>% of capital</th><th>max DD</th></tr>"
                 + srow(f"<b>Strategy — buys only on tier-A days (QQQ RSI2 &lt; {RSI_THR:.0f})</b>", tr["trade"], "strat") + srow("Control — every day, no market filter (same entry/exit rules)", tr["everyday"])
                 + "".join(srow(f"&nbsp;&nbsp;&nbsp;of which entered on tier-{t} days", tr["everyday_" + t]) for t in "ABC") + "</table></div>"
                 f"<div class='muted'>Backtest 2010–2026 (after 10 bp costs): strategy +181 bp/trade, 70% winners, ~34 trades/yr, CAGR 15.2%, max DD −23%, 15 of 17 years positive; "
                 f"the same rules every day without the market filter: +45 bp/trade, max DD −60%, 11 of 17 years. The same thing is tracked here forward on real prices — compare.</div>")
    cl = j[j.status == "closed"]
    if len(cl):
        eqs = [("Strategy", equity_curve(cl[cl.book == "trade"]), "#1e8449"), ("Control", equity_curve(cl[cl.book == "everyday"]), "#8b949e")]
        allv = [CAPITAL] + [v for _, e, _ in eqs for v in e.values]; lo, hi = min(allv), max(allv); rng = (hi - lo) or 1
        y0 = 150 - (CAPITAL - lo) / rng * 130; svg = f"<line x1='0' y1='{y0:.0f}' x2='640' y2='{y0:.0f}' stroke='#d8dee4' stroke-dasharray='4'/>"
        for k, (name, e, col) in enumerate(eqs):
            if len(e) == 0: continue
            vals = [CAPITAL] + list(e.values); xs = np.linspace(8, 632, len(vals)); ys = [150 - (v - lo) / rng * 130 for v in vals]
            svg += f"<polyline fill='none' stroke='{col}' stroke-width='2' points='{' '.join(f'{x:.0f},{y:.0f}' for x, y in zip(xs, ys))}'/><text x='{470 + k * 90}' y='14' font-size='11' fill='{col}'>■ {name}</text>"
        parts.append(f"<svg width='640' height='170' style='max-width:100%;background:#fff;border:1px solid #d8dee4;border-radius:8px'>{svg}<text x='6' y='14' font-size='11' fill='#57606a'>{usd(hi)}</text><text x='6' y='164' font-size='11' fill='#57606a'>{usd(lo)}</text></svg>")
        rows = ""
        for r in cl.sort_values(["exit_date", "book"], ascending=[False, True]).itertuples():
            rows += (f"<tr><td>{'<b>strategy</b>' if r.book == 'trade' else 'control'}</td><td>{d2s(r.signal_date)} {r.tier}{f' <span class=tag>{r.mode}</span>' if r.mode != 'live' else ''}</td><td><b>{r.ticker}</b></td>"
                     f"<td>{d2s(r.entry_date)}</td><td>{_num(r.entry_px)}</td><td>{d2s(r.exit_date)}</td><td>{_num(r.exit_px)}</td><td>{int(r.hold)}</td><td>{reason_text(r.exit_reason)}</td>"
                     f"<td class='{_cls(r.ret_net)}'>{_pct(r.ret_net)}</td><td class='{_cls(r.pnl_usd)}'>{usd(r.pnl_usd, True)}</td></tr>")
        parts.append(f"<h3>Closed trades</h3><div class='wrap'><table><tr><th>book</th><th>signal</th><th>ticker</th><th>entry</th><th>entry px</th><th>exit</th><th>exit px</th><th>sessions</th><th>exit reason</th><th>net</th><th>P&amp;L</th></tr>{rows}</table></div>"
                     f"<div class='muted'>net = after {COST * 1e4:.0f} bp round-trip costs; position size {PER_NAME:.0%} of capital ({usd(CAPITAL)}) per name, max {MAX_POS} positions.</div>")
    if len(dl):
        rows = "".join(f"<tr><td>{d2s(r.date)}{f' <span class=tag>{r.mode}</span>' if r.mode != 'live' else ''}</td><td>{_num(r.q_close)}</td><td class='{_cls(r.q_ret)}'>{_pct(r.q_ret)}</td><td>{r.q_rsi}</td><td>{TIERS.get(r.tier, {}).get('icon', '')} {r.tier}</td>"
                       f"<td>{'' if pd.isna(r.n_candidates) else int(r.n_candidates)}</td><td>{r.picks if isinstance(r.picks, str) else ''}</td><td><b>{r.buy if isinstance(r.buy, str) else ''}</b></td><td>{r.sell if isinstance(r.sell, str) else ''}</td><td>{r.hold if isinstance(r.hold, str) else ''}</td></tr>"
                       for r in dl.sort_values("date", ascending=False).head(60).itertuples())
        parts.append(f"<h2>Scan log (last 60 of {len(dl)})</h2><div class='wrap'><table><tr><th>date</th><th>QQQ</th><th>day</th><th>RSI(2)</th><th>tier</th><th>passed filter</th><th>top of filter</th><th>buy</th><th>sell</th><th>holding</th></tr>{rows}</table></div>")
    parts.append(f"<h2>Rule v2</h2><div class='card'><b>When:</b> QQQ RSI(2) at the close &lt; {RSI_THR:.0f}. <b>What:</b> NASDAQ stocks with close &gt; SMA200, day ≤ −3%, turnover ≥ $20M/day → most liquid first, at most {MAX_NEW} new per day, up to {MAX_POS} positions at {PER_NAME:.0%} of capital each. "
                 f"<b>Entry:</b> next open. <b>Exit:</b> the open after the first close above the stock's SMA{EXIT_SMA}, {MAX_HOLD} sessions max. No stops, no targets.<br>"
                 f"Why: v1 exited after a fixed 48 hours and cut the rebound in half (+81 bp/trade, 58% winners). The SMA{EXIT_SMA} exit lets it play out: +181 bp, 70%. "
                 f"Verified on 2010–2016 (years not used to choose the exit): CAGR 20%, 7 of 7 years positive. Details and the full grid — <a href='{strat}'>STRATEGY.md</a>.</div>")
    # Where this comes from: the page is the landing point for the QR code and the short
    # link printed in the book, so it must lead back to the book and to the free starter
    # kit. Plain string, no interpolation: nothing here can break the f-strings above.
    parts.append("<h2>Where this comes from</h2><div class='card'>"
                 "This scanner is the working example from the book "
                 "<b>Never Start from Scratch: Give Your Projects a Memory That Never Forgets</b> "
                 "by Daniel Marlow — built from a phone, and kept running because the repository "
                 "remembers the project between sessions. "
                 "<a href='https://www.amazon.com/dp/B0HKVZ3RSG'>The book on Amazon</a> &middot; "
                 "<a href='https://exodus611.github.io/project-memory-starter-kit/'>Free starter kit</a> "
                 "(one file, one block — the whole method, nothing else to install)."
                 "<br>Paper trading only: no orders are sent, and nothing on this page is "
                 "financial advice."
                 "<br>If the method worked for you, a one-line review on the book's Amazon "
                 "page helps more than anything else.</div>")
    html = f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Dip-Buyer NASDAQ v2 — paper trading</title><style>{CSS}</style></head><body>{''.join(parts)}</body></html>"
    open(os.path.join(DOCS, "index.html"), "w").write(html)
    update_readme(L, tr)


def update_readme(L, tr):
    if not os.path.exists(README): return
    s = open(README).read(); a, b = "<!-- DASHBOARD:START -->", "<!-- DASHBOARD:END -->"
    if a not in s or b not in s: return
    link = PAGES_URL or "docs/index.html"
    if L is None: block = f"### 📊 Dashboard\nNo runs yet. Full dashboard: {link}\n"
    else:
        T = TIERS[L["tier"]]
        lines = [f"### 📊 Scan {dlong(L['sig_date'])} (after the close) — {T['icon']} {T['label']}" + (f" *({L['mode']})*" if L["mode"] != "live" else ""),
                 f"QQQ **{L['q_close']:.2f}** ({_pct(L['q_ret'])}) · RSI(2) **{L['q_rsi']:.1f}** · passed the filter: {L['n_candidates']}", ""]
        for x in L["buy"]: lines.append(f"- 🟢 **BUY {x['ticker']}** at the open — {PER_NAME:.0%} of capital ≈ {usd(x['usd'])} (~{x['shares_est']} sh; close {x['close']:.2f}, today {_pct(x['ret_1'],1)})")
        for x in L["sell"]: lines.append(f"- 🔴 **SELL {x['ticker']}** at the open — {x['shares']} sh, entry {x['entry_px']:.2f}, last {x['last_px']:.2f} ({_pct(x['upnl'],1)}), {x['held']} sessions, reason: {reason_text(x['reason'])}")
        for x in L["hold"]: lines.append(f"- ⏳ **HOLD {x['ticker']}** — entry {x['entry_px']:.2f}, last {x['last_px']:.2f} ({_pct(x['upnl'],1)}), {x['held']} sessions; sell after a close above SMA{EXIT_SMA} = {x['sma10']:.2f}")
        if not L["buy"] and not L["sell"] and not L["hold"]: lines.append("- No positions, nothing to do tomorrow.")
        lines += ["", f"**{tr['text']}**  "] + ([f"{tr['text_e']}  "] if tr["text_e"] else []) + [f"Full dashboard: {link} · updated {fmt_run_at(L['run_at'])}"]
        block = "\n".join(lines) + "\n"
    s = s[:s.index(a) + len(a)] + "\n" + block + s[s.index(b):]
    open(README, "w").write(s)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["run", "backfill", "test", "rebuild-page", "refresh-universe"])
    ap.add_argument("--asof", default=None); ap.add_argument("--from", dest="d1", default=None); ap.add_argument("--to", dest="d2", default=None)
    a = ap.parse_args()
    if a.mode == "test": test()
    elif a.mode == "rebuild-page": build_page(); log("docs/index.html + README block rebuilt")
    elif a.mode == "refresh-universe": refresh_universe()
    elif a.mode == "backfill": backfill(dt.date.fromisoformat(a.d1), dt.date.fromisoformat(a.d2 or str(now_et().date())))
    else: run(dt.date.fromisoformat(a.asof) if a.asof else None)
