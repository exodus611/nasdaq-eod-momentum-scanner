#!/usr/bin/env python3
"""
DIP-BUYER NASDAQ 48h — daily paper-trading scanner with a dashboard. No Telegram, no broker, no orders.

Runs ONCE per trading day after the US close (GitHub Actions, ~16:40 ET). EVERY day it outputs 2 picks:
  filter : NASDAQ stocks, close > SMA200, today <= -3%, avg $volume(21d) >= 20M$, price >= 5$  -> the 2 most liquid
  tier   : by QQQ RSI(2) at the close   A: < 10 (market oversold)   B: 10-30 (weak)   C: >= 30 (normal day)
  trade  : A and B -> BUY next open, SELL at the close of the session after entry.  C -> watch only (paper journal
           keeps tracking it so the dashboard shows the P&L of every tier separately).
  10-year test 2016-2026 (top-2 by liquidity, next open -> close T+2, after 15 bp costs):
           A +54 bp/trade (419 tr)   B +24 bp (791)   C -28 bp (3206)   every day unconditionally -11 bp (4416)

Usage:
  python bot.py run                              # daily job (after close)
  python bot.py run --asof 2026-08-20            # replay one past session (marked "replay")
  python bot.py backfill --from D1 --to D2       # replay a range with ONE download (fast)
  python bot.py test | rebuild-page | refresh-universe

Env: CAPITAL=100000  PER_NAME=0.10  TOP_N=2  TIER_A=10  TIER_B=30  REPO_URL  PAGES_URL
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
PER_NAME = float(os.environ.get("PER_NAME", "0.10"))      # 10% of capital per name
TOP_N = int(os.environ.get("TOP_N", "2"))
TIER_A = float(os.environ.get("TIER_A", os.environ.get("RSI_THR", "10")))
TIER_B = float(os.environ.get("TIER_B", "30"))
DIP, MIN_DVOL, MIN_PRICE = -0.03, 2e7, 5.0
COST = 0.0015                                              # round-trip cost assumed in paper P&L (15 bp)
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

TIERS = {
    "A": dict(icon="🟢", name="A", label=f"СИГНАЛ A — рынок перепродан (QQQ RSI2 < {TIER_A:.0f})", color="#1e8449", bg="#e9f7ef", trade=True,
              bt="+54 б.п./сделку, 53% прибыльных за 10 лет"),
    "B": dict(icon="🟡", name="B", label=f"СИГНАЛ B — рынок слабый (QQQ RSI2 {TIER_A:.0f}–{TIER_B:.0f})", color="#9a7d0a", bg="#fdf6e3", trade=True,
              bt="+24 б.п./сделку, 53% прибыльных — слабее, но плюс"),
    "C": dict(icon="⚪", name="C", label=f"НАБЛЮДЕНИЕ C — обычный день (QQQ RSI2 ≥ {TIER_B:.0f})", color="#57606a", bg="#f6f8fa", trade=False,
              bt="−28 б.п./сделку, 48% прибыльных — в минус, не торгуем"),
    "NO_STOCK": dict(icon="⚫", name="—", label="ни одна акция не прошла фильтр", color="#57606a", bg="#f6f8fa", trade=False, bt=""),
    "NO_DATA": dict(icon="⚠️", name="—", label="нет данных за день", color="#c0392b", bg="#fdedec", trade=False, bt=""),
}
JCOLS = ["signal_date", "tier", "trade", "entry_date", "ticker", "shares", "entry_px", "exit_date", "exit_px", "ret_gross", "ret_net", "pnl_usd", "status", "mode"]


# ------------------------------------------------------------------ helpers
def now_et(): return dt.datetime.now(ET)
def log(*a): print(*a, flush=True)
def d2s(d): return f"{d:%d.%m.%Y}" if not isinstance(d, str) else f"{dt.date.fromisoformat(d):%d.%m.%Y}"
def tier_of(rsi): return "A" if rsi < TIER_A else ("B" if rsi < TIER_B else "C")

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
            rows.append(dict(ticker=tk, close=round(float(c.iloc[-1]), 2), ret_1=round(ret1, 4), dvol_M=round(dv21 / 1e6), vs_sma200=round(float(c.iloc[-1] / sma200 - 1), 3)))
    df = pd.DataFrame(rows, columns=["ticker", "close", "ret_1", "dvol_M", "vs_sma200"])
    return df.sort_values("dvol_M", ascending=False).reset_index(drop=True)


# ------------------------------------------------------------------ state
def load_pos(): return json.load(open(POS)) if os.path.exists(POS) else {"cohorts": []}
def save_pos(p): json.dump(p, open(POS, "w"), indent=1, default=str, ensure_ascii=False)
def journal_df():
    j = pd.read_csv(JOURNAL) if os.path.exists(JOURNAL) else pd.DataFrame(columns=JCOLS)
    for c in JCOLS:
        if c not in j.columns: j[c] = None
    if len(j): j["trade"] = j["trade"].astype(str).str.lower().isin(["true", "1"])
    return j
def journal_write(j): j[JCOLS].to_csv(JOURNAL, index=False)
def daily_df(): return pd.read_csv(DAILY) if os.path.exists(DAILY) else pd.DataFrame(columns=["date", "mode", "q_close", "q_ret", "q_rsi", "tier", "status", "picks", "n_candidates"])
def daily_log(row): pd.DataFrame([row]).to_csv(DAILY, mode="a", header=not os.path.exists(DAILY), index=False)
def asof_done(asof): return os.path.exists(DAILY) and str(asof) in set(pd.read_csv(DAILY)["date"].astype(str))
def latest(): return json.load(open(LATEST)) if os.path.exists(LATEST) else None

def equity_curve(c):
    if len(c) == 0: return pd.Series(dtype=float)
    return CAPITAL + c.groupby("exit_date")["pnl_usd"].sum().sort_index().cumsum()

def stats(c):
    if len(c) == 0: return dict(n=0)
    coh = c.groupby("signal_date")["ret_net"].mean(); eq = pd.concat([pd.Series([CAPITAL]), equity_curve(c)])
    return dict(n=int(len(c)), cohorts=int(coh.size), mean=float(c.ret_net.mean() * 100), median=float(c.ret_net.median() * 100), hit=float((c.ret_net > 0).mean() * 100),
                coh_pos=int((coh > 0).sum()), pnl=float(c.pnl_usd.sum()), pnl_pct=float(c.pnl_usd.sum() / CAPITAL * 100), maxdd=float((eq / eq.cummax() - 1).min() * 100),
                best=float(c.ret_net.max() * 100), worst=float(c.ret_net.min() * 100))

def track_record(j):
    c = j[j.status == "closed"]
    out = {"AB": stats(c[c.trade == True]), "ALL": stats(c)}
    for t in "ABC": out[t] = stats(c[c.tier == t])
    s = out["AB"]
    out["text"] = ("Стратегия (A+B): закрытых сделок пока нет." if not s["n"] else
                   f"Стратегия (A+B): {s['n']} сделок / {s['cohorts']} дней · средняя {s['mean']:+.2f}% · медиана {s['median']:+.2f}% · прибыльных {s['hit']:.0f}% · "
                   f"P&L {s['pnl']:+,.0f}$ ({s['pnl_pct']:+.2f}% от {CAPITAL:,.0f}$) · max DD {s['maxdd']:.1f}%")
    c3 = out["C"]
    out["text_c"] = "" if not c3["n"] else f"Наблюдение (C, не торгуем): {c3['n']} сделок · средняя {c3['mean']:+.2f}% · прибыльных {c3['hit']:.0f}% · P&L {c3['pnl']:+,.0f}$"
    return out


# ------------------------------------------------------------------ core: process one completed session
def process(today, qq, hist, live, now):
    td = [x.date() for x in qq.index]
    qc = qq["Close"]; q_rsi = float(rsi2(qc).iloc[-1]); q_ret = float(qc.iloc[-1] / qc.iloc[-2] - 1); q_close = float(qc.iloc[-1])
    tier = tier_of(q_rsi); T = TIERS[tier]
    pos, j = load_pos(), journal_df()
    cands = scan(hist, today); picks = cands.head(TOP_N)
    mode, events, buy, sell = ("live" if live else "replay"), [], [], []

    def px(tk, col, day):
        d = hist.get(tk)
        if d is None: return None
        m = d.index.date == day
        return float(d[col][m].iloc[-1]) if m.any() else None

    # 1) entries: cohorts whose signal was the previous session are filled at that session's open
    for c in pos["cohorts"]:
        if c["status"] != "pending": continue
        sd = dt.date.fromisoformat(c["signal_date"])
        if sd not in td or td.index(today) - td.index(sd) < 1: continue
        entry_day = td[td.index(sd) + 1]; rows = []
        for n in c["names"]:
            n["entry_date"] = str(entry_day); n["entry_px"] = px(n["ticker"], "Open", entry_day)
            n["shares"] = int(CAPITAL * PER_NAME / n["entry_px"]) if n["entry_px"] else None
            rows.append(dict(signal_date=c["signal_date"], tier=c.get("tier", "A"), trade=bool(c.get("trade", True)), entry_date=str(entry_day), ticker=n["ticker"], shares=n["shares"],
                             entry_px=n["entry_px"], exit_date=None, exit_px=None, ret_gross=None, ret_net=None, pnl_usd=None, status="open" if n["entry_px"] else "no_data", mode=c.get("mode", mode)))
        c["status"] = "open"
        j = pd.DataFrame(rows, columns=JCOLS) if len(j) == 0 else pd.concat([j.astype(object), pd.DataFrame(rows, columns=JCOLS).astype(object)], ignore_index=True)
        ic = TIERS[c.get("tier", "A")]["icon"]
        events.append(f"{ic} {c.get('tier', 'A')}: {'куплено' if c.get('trade', True) else 'наблюдение, paper-вход'} по открытию {entry_day:%d.%m}: " +
                      ", ".join(f"{n['ticker']} {n['shares']} шт @ {n['entry_px']:.2f}" for n in c["names"] if n["entry_px"]))

    # 2) exits: close of the session AFTER the entry session (T = signal, T+1 = entry at open, T+2 = exit at close)
    for c in pos["cohorts"]:
        if c["status"] != "open": continue
        ed = dt.date.fromisoformat(c["names"][0]["entry_date"])
        if ed not in td: continue
        k = td.index(today) - td.index(ed)
        if k == 0:
            sell.append(dict(signal_date=c["signal_date"], tier=c.get("tier", "A"), trade=bool(c.get("trade", True)), entry_date=str(ed),
                             names=[dict(ticker=n["ticker"], shares=n.get("shares"), entry_px=n.get("entry_px")) for n in c["names"]]))
        elif k >= 1:
            exit_day = td[td.index(ed) + 1]; rets = []
            for n in c["names"]:
                xp = px(n["ticker"], "Close", exit_day)
                if xp and n.get("entry_px"):
                    r = xp / n["entry_px"] - 1; rn = r - COST; pnl = rn * n["entry_px"] * n["shares"]
                    m = (j.signal_date == c["signal_date"]) & (j.ticker == n["ticker"])
                    j.loc[m, ["exit_date", "exit_px", "ret_gross", "ret_net", "pnl_usd", "status"]] = [str(exit_day), round(xp, 4), round(r, 5), round(rn, 5), round(pnl, 2), "closed"]
                    n.update(exit_px=round(xp, 4), ret_net=round(rn, 5), pnl_usd=round(pnl, 2)); rets.append(rn)
            c["status"] = "closed"; c["exit_date"] = str(exit_day)
            if rets:
                tot = sum(n.get("pnl_usd", 0) for n in c["names"]); ic = TIERS[c.get("tier", "A")]["icon"]
                events.append(f"{'✅' if tot > 0 else '❌'} {ic} {c.get('tier', 'A')} {d2s(c['signal_date'])} закрыта {exit_day:%d.%m} по закрытию: " +
                              ", ".join(f"{n['ticker']} {n.get('ret_net', 0) * 100:+.1f}%" for n in c["names"]) + f" → {tot:+,.0f}$" +
                              ("" if c.get("trade", True) else " (наблюдение)") + ("" if k == 1 else " (закрыта с опозданием — бот не запускался)"))

    # 3) today's picks: EVERY day with candidates opens a cohort, tagged with the market tier
    if len(picks):
        pos["cohorts"].append(dict(signal_date=str(today), status="pending", tier=tier, trade=T["trade"], q_rsi=round(q_rsi, 2), mode=mode,
                                   names=[dict(ticker=r.ticker, signal_close=r.close, ret_1=r.ret_1, dvol_M=r.dvol_M) for r in picks.itertuples()]))
        buy = [dict(ticker=r.ticker, close=r.close, ret_1=r.ret_1, dvol_M=r.dvol_M, vs_sma200=r.vs_sma200, usd=round(CAPITAL * PER_NAME), shares_est=int(CAPITAL * PER_NAME / r.close)) for r in picks.itertuples()]
        status = tier
    else:
        status = "NO_STOCK"

    save_pos(pos); journal_write(j)
    L = dict(run_at=f"{now:%d.%m.%Y %H:%M} ET", mode=mode, sig_date=str(today), q_close=round(q_close, 2), q_ret=round(q_ret, 4), q_rsi=round(q_rsi, 1),
             tier=tier, trade=T["trade"], tier_a=TIER_A, tier_b=TIER_B, top_n=TOP_N, status=status, n_candidates=int(len(cands)),
             picks=picks.to_dict("records"), candidates=cands.head(40).to_dict("records"), buy=buy, sell=sell, events=events,
             positions=[dict(signal_date=c["signal_date"], tier=c.get("tier", "A"), trade=bool(c.get("trade", True)), status=c["status"], mode=c.get("mode", "live"), names=c["names"])
                        for c in pos["cohorts"] if c["status"] in ("pending", "open")],
             track=track_record(j))
    json.dump(L, open(LATEST, "w"), ensure_ascii=False, indent=1, default=str)
    json.dump(L, open(os.path.join(SCANS, f"{today}.json"), "w"), ensure_ascii=False, default=str)
    daily_log(dict(date=str(today), mode=mode, q_close=round(q_close, 2), q_ret=round(q_ret, 4), q_rsi=round(q_rsi, 1), tier=tier, status=status,
                   picks=" ".join(picks.ticker) if len(picks) else "", n_candidates=len(cands)))
    log("\n" + summary_text(L) + "\n")
    return L


def summary_text(L):
    T = TIERS[L["status"]]
    out = [f"📊 {d2s(L['sig_date'])} (после закрытия)  QQQ {L['q_close']:.2f} {L['q_ret'] * 100:+.2f}%  RSI(2) = {L['q_rsi']:.1f}  →  {T['icon']} {T['label']}"]
    out += L["events"]
    if L["buy"]:
        head = (f"➡️ КУПИТЬ ЗАВТРА ПО ОТКРЫТИЮ, по {PER_NAME:.0%} капитала (≈{CAPITAL * PER_NAME:,.0f}$) каждую; продать по закрытию следующего дня после входа:" if L["trade"] else
                "👀 Пики дня (наблюдение, только paper — в такие дни стратегия исторически в минусе):")
        out.append(head)
        out += [f"   {b['ticker']:<6} закрытие {b['close']:>8.2f}  сегодня {b['ret_1'] * 100:+.1f}%  оборот {b['dvol_M']:,.0f}M$/д  (~{b['shares_est']} шт)" for b in L["buy"]]
    for s in L["sell"]:
        out.append(f"⏰ ЗАВТРА ПО ЗАКРЫТИЮ {'ПРОДАТЬ' if s['trade'] else 'закрывается наблюдение'} {TIERS[s['tier']]['icon']} {s['tier']} {d2s(s['signal_date'])}: " +
                   ", ".join(f"{n['ticker']} {n['shares']} шт" for n in s["names"]))
    out.append(L["track"]["text"])
    if L["track"]["text_c"]: out.append(L["track"]["text_c"])
    return "\n".join(out)


# ------------------------------------------------------------------ entry points
def run(asof=None):
    live, now = asof is None, now_et()
    strict = True                      # strict = we expect a bar for exactly `asof`
    if live:
        asof = now.date()
        if now.weekday() >= 5 or now.hour * 60 + now.minute < 16 * 60 + 10:
            asof, strict = asof - dt.timedelta(days=1), False      # market not closed yet / weekend -> last completed session
            log(f"market not closed yet / weekend — processing the last completed session (<= {asof})")
    if asof_done(asof): log(f"{asof}: already processed — nothing to do"); return
    qqq = fetch_qqq(asof, live and strict)
    qq = qqq[qqq.index.date <= asof] if qqq is not None else None
    if qq is None or len(qq) < 5: log("QQQ data unavailable"); return
    last = qq.index[-1].date()
    if not strict and asof_done(last): log(f"{last}: already processed — nothing to do"); return
    if last != asof and strict:
        if live:
            json.dump(dict(run_at=f"{now:%d.%m.%Y %H:%M} ET", asof=str(asof), status="NO_DATA",
                           note=f"Нет дневного бара за {asof:%d.%m.%Y} (последний {last:%d.%m.%Y}) — биржевой праздник или задержка данных. Ничего не делаем."), open(ATTEMPT, "w"), ensure_ascii=False)
            build_page(); log(f"{asof}: no daily bar yet (last {last}) — holiday or data lag; nothing to do")
        else:
            log(f"{asof} is not a trading day (last bar {last}) -> skip")
        return
    if os.path.exists(ATTEMPT): os.remove(ATTEMPT)
    tickers = load_universe(); log(f"{last}: QQQ RSI(2)={float(rsi2(qq['Close']).iloc[-1]):.1f} | universe {len(tickers)} | downloading…")
    process(last, qq, download(tickers), live, now)
    build_page()


def backfill(d1, d2):
    qqq = download(["QQQ"], period="14mo")["QQQ"]
    tickers = load_universe(); log(f"backfill {d1}..{d2} | universe {len(tickers)} | downloading once…")
    hist = download(tickers)
    days = [x.date() for x in qqq.index if d1 <= x.date() <= d2]
    for d in days:
        if asof_done(d): log(f"{d}: already processed"); continue
        process(d, qqq[qqq.index.date <= d], hist, False, now_et())
    build_page(); log(f"backfill done: {len(days)} sessions")


def test():
    q = download(["QQQ"], period="6mo").get("QQQ")
    if q is None: log("❌ QQQ download failed"); raise SystemExit(1)
    r = float(rsi2(q["Close"]).iloc[-1])
    log(f"✅ data OK: QQQ last bar {q.index[-1].date()} close {float(q['Close'].iloc[-1]):.2f}, RSI(2) = {r:.1f} → tier {tier_of(r)}; now {now_et():%d.%m %H:%M} ET")
    build_page(); log("✅ dashboard rebuilt: docs/index.html")


# ------------------------------------------------------------------ dashboard (docs/index.html) + README block
CSS = """
*{box-sizing:border-box}body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;max-width:1040px;margin:0 auto;padding:18px 14px 40px;color:#1f2328;background:#fff;line-height:1.45}
h1{font-size:22px;margin:0 0 4px}h2{font-size:17px;margin:26px 0 8px;border-bottom:1px solid #d8dee4;padding-bottom:4px}h3{font-size:15px;margin:14px 0 6px}
.muted{color:#57606a;font-size:13px}.card{border:1px solid #d0d7de;border-radius:10px;padding:14px 16px;margin:12px 0;background:#fff}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}@media(max-width:760px){.grid{grid-template-columns:1fr}}
.status{font-size:19px;font-weight:700}.kv{display:flex;flex-wrap:wrap;gap:6px 22px;margin-top:8px;font-size:14px}.kv b{font-size:16px}
table{border-collapse:collapse;width:100%;font-size:13px;margin:6px 0}th,td{border:1px solid #d8dee4;padding:5px 8px;text-align:left;white-space:nowrap}th{background:#f6f8fa;font-weight:600}
tr.pick td{background:#e9f7ef;font-weight:600}tr.pickc td{background:#eef1f4;font-weight:600}tr.strat td{background:#f0fff4;font-weight:700}.pos{color:#1e8449}.neg{color:#c0392b}
.tag{display:inline-block;font-size:11px;padding:1px 6px;border-radius:10px;background:#eaeef2;color:#57606a;margin-left:4px}
.act{font-size:15px;padding-left:20px}.act li{margin:5px 0}.bar{position:relative;height:10px;background:linear-gradient(90deg,#1e8449 0 10%,#e6c65a 10% 30%,#eaeef2 30% 100%);border-radius:5px;margin:8px 0 2px}
.bar i{position:absolute;top:-4px;width:4px;height:18px;background:#1f2328;border-radius:2px}.wrap{overflow-x:auto}.ev{margin:6px 0;padding:8px 12px;background:#f6f8fa;border-radius:8px}
.big{font-size:22px;font-weight:800;letter-spacing:.5px}
"""

def _cls(x): return "pos" if x > 0 else "neg"
def _pct(x, d=2): return "" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x * 100:+.{d}f}%"
def _num(x, d=2): return "" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:,.{d}f}"
def _tier(t): return f"{TIERS.get(t, TIERS['C'])['icon']} {t}"

def build_page():
    L, j, dl = latest(), journal_df(), daily_df()
    att = json.load(open(ATTEMPT)) if os.path.exists(ATTEMPT) else None
    tr = track_record(j)
    strat = f"{REPO_URL}/blob/main/STRATEGY.md" if REPO_URL else "#"
    upd = f"{now_et():%d.%m.%Y %H:%M} ET"
    parts = [f"<h1>Dip-Buyer NASDAQ 48h — paper trading</h1><div class='muted'>Сканер запускается раз в день после закрытия США и каждый день выдаёт 2 бумаги с меткой тира. Ордера не исполняются — только вывод сканера и бумажный журнал. Обновлено {upd}"
             + (f" · <a href='{REPO_URL}'>репозиторий</a>" if REPO_URL else "") + "</div>"]
    if att:
        parts.append(f"<div class='card' style='background:#fdf6e3;border-color:#e6c65a'>⚠️ Попытка {att['run_at']}: {att['note']}</div>")
    if L is None:
        parts.append("<div class='card'>Запусков ещё не было. Первый результат появится после первого прогона (Actions → Run workflow, или автоматически после закрытия рынка).</div>")
    else:
        T = TIERS[L["status"]]; rsi = max(0.0, min(100.0, float(L["q_rsi"])))
        parts.append("<div class='grid'>")
        parts.append(f"<div class='card' style='background:{T['bg']};border-color:{T['color']}'><div class='muted'>Сканирование за {d2s(L['sig_date'])} (после закрытия)"
                     + (" <span class='tag'>replay</span>" if L["mode"] == "replay" else "") + f"</div><div class='status' style='color:{T['color']}'>{T['icon']} {T['label']}</div>"
                     f"<div class='kv'><span>QQQ <b>{L['q_close']:.2f}</b> <span class='{_cls(L['q_ret'])}'>{_pct(L['q_ret'])}</span></span>"
                     f"<span>RSI(2) <b>{L['q_rsi']:.1f}</b></span><span>кандидатов по фильтру <b>{L['n_candidates']}</b></span></div>"
                     f"<div class='bar'><i style='left:calc({rsi:.1f}% - 2px)'></i></div><div class='muted'>RSI(2) QQQ: зелёная зона &lt; {L['tier_a']:.0f} = A, жёлтая {L['tier_a']:.0f}–{L['tier_b']:.0f} = B, серая = C. {T['bt']}</div></div>")
        acts = []
        if L["buy"] and L["trade"]:
            for b in L["buy"]:
                acts.append(f"<li>🟢 <span class='big'>КУПИТЬ {b['ticker']}</span> по открытию — {PER_NAME:.0%} капитала ≈ {b['usd']:,.0f}$ (~{b['shares_est']} шт по закрытию {b['close']:.2f})</li>")
            acts.append("<li class='muted'>продать — по закрытию следующего дня после входа; без стопов и целей</li>")
        elif L["buy"]:
            acts.append("<li>👀 <b>Пики дня (наблюдение):</b> " + ", ".join(f"<span class='big'>{b['ticker']}</span> ({b['close']:.2f}, {_pct(b['ret_1'], 1)})" for b in L["buy"]) +
                        f"<div class='muted'>Не торгуем: в дни с QQQ RSI(2) ≥ {L['tier_b']:.0f} такие сделки за 10 лет дали −28 б.п./сделку. Ведём на бумаге — итог по тиру C см. в «Результатах».</div></li>")
        for s in L["sell"]:
            acts.append(f"<li>{'🔴 <b>ПРОДАТЬ по закрытию</b>' if s['trade'] else '⚪ закрывается наблюдение'} {_tier(s['tier'])} {d2s(s['signal_date'])}: " +
                        ", ".join(f"{n['ticker']} {n['shares']} шт (вход {n['entry_px']:.2f})" for n in s["names"] if n.get("entry_px")) + "</li>")
        if not acts: acts.append("<li>Ничего не делаем.</li>")
        parts.append("<div class='card'><div class='muted'>Действия на следующую сессию</div><ul class='act'>" + "".join(acts) + "</ul></div></div>")
        if L["events"]:
            parts.append("<h2>События этого запуска</h2>" + "".join(f"<div class='ev'>{e}</div>" for e in L["events"]))
        parts.append(f"<h2>Вывод сканера — {d2s(L['sig_date'])}</h2>")
        if not L["candidates"]:
            parts.append("<div class='muted'>Ни одна акция не прошла фильтр (close &gt; SMA200, день ≤ −3%, оборот ≥ 20M$/д, цена ≥ 5$).</div>")
        else:
            cls = "pick" if L["trade"] else "pickc"
            rows = "".join(f"<tr class='{cls if i < L['top_n'] else ''}'><td>{i + 1}</td><td>{c['ticker']}</td><td>{c['close']:.2f}</td>"
                           f"<td class='{_cls(c['ret_1'])}'>{_pct(c['ret_1'], 1)}</td><td>{c['dvol_M']:,.0f}</td><td>{_pct(c['vs_sma200'], 0)}</td></tr>" for i, c in enumerate(L["candidates"]))
            parts.append(f"<div class='muted'>Прошли фильтр: {L['n_candidates']} (показаны первые {len(L['candidates'])}, по среднему обороту за 21 день). Выделены топ-{L['top_n']} — пики дня.</div>"
                         f"<div class='wrap'><table><tr><th>#</th><th>тикер</th><th>закрытие</th><th>день</th><th>оборот, M$/д</th><th>над SMA200</th></tr>{rows}</table></div>")
        parts.append("<h2>Открытые позиции (paper)</h2>")
        if not L["positions"]: parts.append("<div class='muted'>Нет.</div>")
        else:
            rows = ""
            for c in L["positions"]:
                what = "вход по открытию следующей сессии" if c["status"] == "pending" else "выход по закрытию следующей сессии"
                names = ", ".join(f"{n['ticker']}" + (f" {n['shares']} шт @ {n['entry_px']:.2f}" if n.get("entry_px") else "") for n in c["names"])
                rows += f"<tr><td>{d2s(c['signal_date'])}</td><td>{_tier(c['tier'])}{'' if c['trade'] else ' <span class=tag>наблюдение</span>'}</td><td>{c['status']}</td><td>{names}</td><td>{what}</td></tr>"
            parts.append(f"<div class='wrap'><table><tr><th>сигнал</th><th>тир</th><th>статус</th><th>имена</th><th>что дальше</th></tr>{rows}</table></div>")
    # results by tier
    def srow(name, s, cls=""):
        if not s.get("n"): return f"<tr class='{cls}'><td>{name}</td><td>0</td><td colspan='6' class='muted'>пока нет закрытых сделок</td></tr>"
        return (f"<tr class='{cls}'><td>{name}</td><td>{s['n']}</td><td class='{_cls(s['mean'])}'>{s['mean']:+.2f}%</td><td class='{_cls(s['median'])}'>{s['median']:+.2f}%</td><td>{s['hit']:.0f}%</td>"
                f"<td class='{_cls(s['pnl'])}'>{s['pnl']:+,.0f}$</td><td class='{_cls(s['pnl_pct'])}'>{s['pnl_pct']:+.2f}%</td><td>{s['maxdd']:.1f}%</td></tr>")
    parts.append("<h2>Результаты (paper) по тирам</h2><div class='wrap'><table><tr><th>тир</th><th>сделок</th><th>средняя</th><th>медиана</th><th>прибыльных</th><th>P&amp;L</th><th>% капитала</th><th>max DD</th></tr>"
                 + srow("<b>Стратегия = A + B (торгуем)</b>", tr["AB"], "strat") + srow("🟢 A — QQQ RSI2 &lt; %d" % TIER_A, tr["A"]) + srow("🟡 B — RSI2 %d–%d" % (TIER_A, TIER_B), tr["B"])
                 + srow("⚪ C — наблюдение, не торгуем", tr["C"]) + srow("Все пики подряд (если бы торговали каждый день)", tr["ALL"]) + "</table></div>"
                 f"<div class='muted'>Бэктест 2016–2026, топ-2 по обороту, вход по открытию, выход через 48 ч, после издержек: A +54 б.п./сделку · B +24 · C −28 · каждый день без разбора −11. "
                 f"Здесь то же самое считается вперёд на реальных ценах — сравнивайте.</div>")
    cl = j[j.status == "closed"]
    if len(cl):
        eqs = [("Стратегия A+B", equity_curve(cl[cl.trade == True]), "#1e8449"), ("Все пики (A+B+C)", equity_curve(cl), "#8b949e")]
        allv = [CAPITAL] + [v for _, e, _ in eqs for v in e.values]; lo, hi = min(allv), max(allv); rng = (hi - lo) or 1
        y0 = 150 - (CAPITAL - lo) / rng * 130; svg = f"<line x1='0' y1='{y0:.0f}' x2='640' y2='{y0:.0f}' stroke='#d8dee4' stroke-dasharray='4'/>"
        for k, (name, e, col) in enumerate(eqs):
            if len(e) == 0: continue
            vals = [CAPITAL] + list(e.values); xs = np.linspace(8, 632, len(vals)); ys = [150 - (v - lo) / rng * 130 for v in vals]
            svg += f"<polyline fill='none' stroke='{col}' stroke-width='2' points='{' '.join(f'{x:.0f},{y:.0f}' for x, y in zip(xs, ys))}'/><text x='{420 + k * 110}' y='14' font-size='11' fill='{col}'>■ {name}</text>"
        parts.append(f"<svg width='640' height='170' style='max-width:100%;background:#fff;border:1px solid #d8dee4;border-radius:8px'>{svg}<text x='6' y='14' font-size='11' fill='#57606a'>{hi:,.0f}$</text><text x='6' y='164' font-size='11' fill='#57606a'>{lo:,.0f}$</text></svg>")
    if len(j):
        rows = ""
        for r in j.sort_values(["signal_date", "ticker"], ascending=[False, True]).itertuples():
            rn = None if pd.isna(r.ret_net) else float(r.ret_net); pnl = None if pd.isna(r.pnl_usd) else float(r.pnl_usd)
            rows += (f"<tr><td>{d2s(r.signal_date)}{' <span class=tag>replay</span>' if r.mode == 'replay' else ''}</td><td>{_tier(r.tier)}{'' if r.trade else ' <span class=tag>набл.</span>'}</td><td><b>{r.ticker}</b></td>"
                     f"<td>{d2s(r.entry_date) if isinstance(r.entry_date, str) else ''}</td><td>{_num(r.entry_px)}</td><td>{'' if pd.isna(r.shares) else int(r.shares)}</td>"
                     f"<td>{d2s(r.exit_date) if isinstance(r.exit_date, str) else ''}</td><td>{_num(r.exit_px)}</td>"
                     f"<td class='{_cls(rn) if rn is not None else ''}'>{_pct(rn)}</td><td class='{_cls(pnl) if pnl is not None else ''}'>{'' if pnl is None else f'{pnl:+,.0f}$'}</td><td>{r.status}</td></tr>")
        parts.append(f"<h3>Сделки</h3><div class='wrap'><table><tr><th>сигнал</th><th>тир</th><th>тикер</th><th>вход</th><th>цена входа (open)</th><th>шт</th><th>выход</th><th>цена выхода (close)</th><th>net</th><th>P&amp;L</th><th>статус</th></tr>{rows}</table></div>"
                     f"<div class='muted'>net = после {COST * 1e4:.0f} б.п. издержек за круг; размер {PER_NAME:.0%} капитала ({CAPITAL:,.0f}$) на имя, одинаковый для всех тиров.</div>")
    if len(dl):
        rows = "".join(f"<tr><td>{d2s(r.date)}{' <span class=tag>replay</span>' if r.mode == 'replay' else ''}</td><td>{_num(r.q_close)}</td><td class='{_cls(r.q_ret)}'>{_pct(r.q_ret)}</td><td>{r.q_rsi}</td>"
                       f"<td>{_tier(r.tier) if isinstance(r.tier, str) else ''}</td><td><b>{r.picks if isinstance(r.picks, str) else ''}</b></td><td>{'' if pd.isna(r.n_candidates) else int(r.n_candidates)}</td></tr>"
                       for r in dl.sort_values("date", ascending=False).head(60).itertuples())
        parts.append(f"<h2>Журнал сканирований (последние 60 из {len(dl)})</h2><div class='wrap'><table><tr><th>дата</th><th>QQQ</th><th>день</th><th>RSI(2)</th><th>тир</th><th>пики дня</th><th>кандидатов</th></tr>{rows}</table></div>")
    parts.append(f"<h2>Правило</h2><div class='card'>Каждый день после закрытия: акции NASDAQ с close &gt; SMA200, день ≤ −3%, оборот ≥ 20M$/д, цена ≥ 5$ → <b>{TOP_N} самых ликвидных</b> = пики дня. "
                 f"Тир по QQQ RSI(2): <b>A</b> &lt; {TIER_A:.0f} и <b>B</b> {TIER_A:.0f}–{TIER_B:.0f} — торгуем: купить по открытию следующей сессии, продать по закрытию сессии после дня входа, {PER_NAME:.0%} капитала на имя, без стопов и целей. "
                 f"<b>C</b> ≥ {TIER_B:.0f} — только наблюдаем.<br>Серии из 5–7 убыточных подряд — норма; судить раньше 40–50 сделок нельзя. Подробности — <a href='{strat}'>STRATEGY.md</a>.</div>")
    html = f"<!doctype html><html lang='ru'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Dip-Buyer NASDAQ 48h — paper</title><style>{CSS}</style></head><body>{''.join(parts)}</body></html>"
    open(os.path.join(DOCS, "index.html"), "w").write(html)
    update_readme(L, tr)


def update_readme(L, tr):
    if not os.path.exists(README): return
    s = open(README).read(); a, b = "<!-- DASHBOARD:START -->", "<!-- DASHBOARD:END -->"
    if a not in s or b not in s: return
    link = PAGES_URL or "docs/index.html"
    if L is None:
        block = f"### 📊 Дашборд\nЗапусков ещё не было. Полный дашборд: {link}\n"
    else:
        T = TIERS[L["status"]]
        lines = [f"### 📊 Скан {d2s(L['sig_date'])} (после закрытия) — {T['icon']} {T['label']}" + (" *(replay)*" if L["mode"] == "replay" else ""),
                 f"QQQ **{L['q_close']:.2f}** ({_pct(L['q_ret'])}) · RSI(2) **{L['q_rsi']:.1f}** · кандидатов по фильтру: {L['n_candidates']}", ""]
        if L["buy"]:
            lines += [(f"**➡️ КУПИТЬ по открытию следующей сессии, по {PER_NAME:.0%} капитала (≈{CAPITAL * PER_NAME:,.0f}$) каждую; продать по закрытию следующего дня после входа:**" if L["trade"] else
                       "**👀 Пики дня — наблюдение, не торгуем (тир C: за 10 лет −28 б.п./сделку):**"), "",
                      "| тикер | закрытие | день | оборот, M$/д | над SMA200 |", "|---|---|---|---|---|"]
            lines += [f"| **{x['ticker']}** | {x['close']:.2f} | {_pct(x['ret_1'], 1)} | {x['dvol_M']:,.0f} | {_pct(x['vs_sma200'], 0)} |" for x in L["buy"]]
            lines.append("")
        for x in L["sell"]:
            lines.append(f"**⏰ {'ПРОДАТЬ по закрытию следующей сессии' if x['trade'] else 'Закрывается наблюдение'}** {x['tier']} {d2s(x['signal_date'])}: " + ", ".join(f"{n['ticker']} {n['shares']} шт" for n in x["names"]) + "  ")
        lines += [f"**{tr['text']}**  "] + ([f"{tr['text_c']}  "] if tr["text_c"] else []) + [f"Полный дашборд: {link} · обновлено {L['run_at']}"]
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
