#!/usr/bin/env python3
"""
DIP-BUYER NASDAQ 48h — paper-trading scanner with a dashboard. No Telegram, no broker, no orders.

Runs ONCE per trading day after the US close (GitHub Actions, ~16:40 ET):
  1. QQQ RSI(2) at today's close < 10 ?                          -> market oversold = signal day
  2. NASDAQ stocks: close > SMA200, today <= -3%, avg $volume(21d) >= 20M$, price >= 5$
  3. The TWO most liquid of them  ->  BUY at next open, SELL at the close of the session after the entry session
  4. Paper journal at actual open/close prices, P&L, dashboard docs/index.html (GitHub Pages) + block in README.md

Usage:
  python bot.py run                     # daily job (after close)
  python bot.py run --asof 2026-08-20   # replay a past day (rows are marked "replay")
  python bot.py run --asof ... --fast   # replay: skip the full scan when nothing can happen (no signal, no positions)
  python bot.py test                    # data check (QQQ last bar + RSI) and dashboard rebuild
  python bot.py rebuild-page            # regenerate docs/index.html + README block from state/
  python bot.py refresh-universe        # refresh data/universe_nasdaq.csv from nasdaq.com

Env: CAPITAL=100000  PER_NAME=0.10  RSI_THR=10  TOP_N=2  REPO_URL  PAGES_URL
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
PER_NAME = float(os.environ.get("PER_NAME", "0.10"))      # 10% of capital per name -> 2 names = 20% per cohort
RSI_THR = float(os.environ.get("RSI_THR", "10"))
TOP_N = int(os.environ.get("TOP_N", "2"))
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
STATUS = {"SIGNAL": ("🟢", "СИГНАЛ — рынок перепродан", "#1e8449", "#e9f7ef"),
          "NO_STOCK": ("🟡", "рынок перепродан, но ни одна акция не прошла фильтр", "#9a7d0a", "#fdf6e3"),
          "NONE": ("⚪", "сигнала нет", "#57606a", "#f6f8fa"),
          "NO_DATA": ("⚠️", "нет данных за день", "#c0392b", "#fdedec")}
JCOLS = ["signal_date", "entry_date", "ticker", "shares", "entry_px", "exit_date", "exit_px", "ret_gross", "ret_net", "pnl_usd", "status", "mode"]


# ------------------------------------------------------------------ helpers
def now_et(): return dt.datetime.now(ET)
def log(*a): print(*a, flush=True)
def d2s(d): return f"{d:%d.%m.%Y}" if not isinstance(d, str) else f"{dt.date.fromisoformat(d):%d.%m.%Y}"

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
        q = download(["QQQ"], period="6mo").get("QQQ")
        if q is None: time.sleep(30); continue
        have = q.index[-1].date()
        if have >= asof or not wait or attempt == 3: break
        log(f"  no QQQ bar for {asof} yet (last {have}); waiting 5 min"); time.sleep(300)
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
    return j
def journal_write(j): j[JCOLS].to_csv(JOURNAL, index=False)
def daily_df(): return pd.read_csv(DAILY) if os.path.exists(DAILY) else pd.DataFrame(columns=["date", "mode", "q_close", "q_ret", "q_rsi", "status", "picks", "n_candidates"])
def daily_log(row): pd.DataFrame([row]).to_csv(DAILY, mode="a", header=not os.path.exists(DAILY), index=False)
def asof_done(asof): return os.path.exists(DAILY) and str(asof) in set(pd.read_csv(DAILY)["date"].astype(str))
def latest(): return json.load(open(LATEST)) if os.path.exists(LATEST) else None

def equity_curve(j):
    c = j[j.status == "closed"]
    if len(c) == 0: return pd.Series(dtype=float)
    pnl = c.groupby("exit_date")["pnl_usd"].sum().sort_index()
    return CAPITAL + pnl.cumsum()

def track_record(j):
    c = j[j.status == "closed"]
    if len(c) == 0: return dict(n=0, text="Закрытых сделок пока нет.")
    coh = c.groupby("signal_date")["ret_net"].mean(); eq = pd.concat([pd.Series([CAPITAL]), equity_curve(j)])
    d = dict(n=int(len(c)), cohorts=int(coh.size), mean=float(c.ret_net.mean() * 100), median=float(c.ret_net.median() * 100), hit=float((c.ret_net > 0).mean() * 100),
             coh_pos=int((coh > 0).sum()), pnl=float(c.pnl_usd.sum()), pnl_pct=float(c.pnl_usd.sum() / CAPITAL * 100), maxdd=float((eq / eq.cummax() - 1).min() * 100),
             best=float(c.ret_net.max() * 100), worst=float(c.ret_net.min() * 100))
    d["text"] = (f"Paper: {d['n']} сделок / {d['cohorts']} когорт · средняя сделка {d['mean']:+.2f}% · медиана {d['median']:+.2f}% · прибыльных {d['hit']:.0f}% · "
                 f"когорт в плюсе {d['coh_pos']}/{d['cohorts']} · P&L {d['pnl']:+,.0f}$ ({d['pnl_pct']:+.2f}% от {CAPITAL:,.0f}$) · max DD {d['maxdd']:.1f}%")
    return d


# ------------------------------------------------------------------ main daily job
def run(asof=None, fast=False):
    live, now = asof is None, now_et()
    strict = True                      # strict = we expect a bar for exactly `asof`
    if live:
        asof = now.date()
        if now.weekday() >= 5 or now.hour * 60 + now.minute < 16 * 60 + 10:
            # weekend or market not closed yet (manual run): process the last COMPLETED session instead,
            # never today's partial bar
            asof, strict = asof - dt.timedelta(days=1), False
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
    today, td = last, [x.date() for x in qq.index]
    qc = qq["Close"]; q_rsi = float(rsi2(qc).iloc[-1]); q_ret = float(qc.iloc[-1] / qc.iloc[-2] - 1); q_close = float(qc.iloc[-1])
    pos, j = load_pos(), journal_df()
    signal = q_rsi < RSI_THR
    has_pos = any(c["status"] in ("pending", "open") for c in pos["cohorts"])
    need_scan = (not fast) or signal or has_pos
    hist, cands = {}, None
    if need_scan:
        tickers = load_universe(); log(f"{asof}: QQQ RSI(2)={q_rsi:.1f} | universe {len(tickers)} | downloading…")
        hist = download(tickers); cands = scan(hist, today)
    else:
        log(f"{asof}: QQQ RSI(2)={q_rsi:.1f}, no positions — fast replay, scan skipped")
    picks = cands.head(TOP_N) if cands is not None else pd.DataFrame(columns=["ticker", "close", "ret_1", "dvol_M", "vs_sma200"])
    mode, events, buy, sell = ("live" if live else "replay"), [], [], []

    def px(tk, col, day):
        d = hist.get(tk)
        if d is None: return None
        m = d.index.date == day
        return float(d[col][m].iloc[-1]) if m.any() else None

    # 1) entries: cohorts whose signal was the previous session are filled at today's open
    for c in pos["cohorts"]:
        if c["status"] != "pending": continue
        sd = dt.date.fromisoformat(c["signal_date"])
        if sd not in td or td.index(today) - td.index(sd) < 1: continue
        entry_day = td[td.index(sd) + 1]; rows = []
        for n in c["names"]:
            n["entry_date"] = str(entry_day); n["entry_px"] = px(n["ticker"], "Open", entry_day)
            n["shares"] = int(CAPITAL * PER_NAME / n["entry_px"]) if n["entry_px"] else None
            rows.append(dict(signal_date=c["signal_date"], entry_date=str(entry_day), ticker=n["ticker"], shares=n["shares"], entry_px=n["entry_px"], exit_date=None, exit_px=None,
                             ret_gross=None, ret_net=None, pnl_usd=None, status="open" if n["entry_px"] else "no_data", mode=c.get("mode", mode)))
        c["status"] = "open"
        j = pd.DataFrame(rows, columns=JCOLS) if len(j) == 0 else pd.concat([j, pd.DataFrame(rows, columns=JCOLS)], ignore_index=True)
        events.append(f"📥 Куплено по открытию {entry_day:%d.%m} (paper): " + ", ".join(f"{n['ticker']} {n['shares']} шт @ {n['entry_px']:.2f}" for n in c["names"] if n["entry_px"]))

    # 2) exits: close of the session AFTER the entry session (T = signal, T+1 = entry at open, T+2 = exit at close)
    for c in pos["cohorts"]:
        if c["status"] != "open": continue
        ed = dt.date.fromisoformat(c["names"][0]["entry_date"])
        if ed not in td: continue
        k = td.index(today) - td.index(ed)
        if k == 0:
            sell.append(dict(signal_date=c["signal_date"], entry_date=str(ed), names=[dict(ticker=n["ticker"], shares=n.get("shares"), entry_px=n.get("entry_px")) for n in c["names"]]))
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
                tot = sum(n.get("pnl_usd", 0) for n in c["names"])
                events.append(f"{'✅' if tot > 0 else '❌'} Когорта {d2s(c['signal_date'])} закрыта {exit_day:%d.%m} по закрытию: " +
                              ", ".join(f"{n['ticker']} {n.get('ret_net', 0) * 100:+.1f}%" for n in c["names"]) + f" → {tot:+,.0f}$" + ("" if k == 1 else " (закрыта с опозданием — бот не запускался)"))

    # 3) today's signal
    if signal and len(picks):
        pos["cohorts"].append(dict(signal_date=str(today), status="pending", q_rsi=round(q_rsi, 2), mode=mode,
                                   names=[dict(ticker=r.ticker, signal_close=r.close, ret_1=r.ret_1, dvol_M=r.dvol_M) for r in picks.itertuples()]))
        buy = [dict(ticker=r.ticker, close=r.close, ret_1=r.ret_1, dvol_M=r.dvol_M, vs_sma200=r.vs_sma200, usd=round(CAPITAL * PER_NAME), shares_est=int(CAPITAL * PER_NAME / r.close)) for r in picks.itertuples()]
        status = "SIGNAL"
    elif signal: status = "NO_STOCK"
    else: status = "NONE"

    save_pos(pos); journal_write(j)
    L = dict(run_at=f"{now:%d.%m.%Y %H:%M} ET", mode=mode, asof=str(asof), sig_date=str(today), q_close=round(q_close, 2), q_ret=round(q_ret, 4), q_rsi=round(q_rsi, 1),
             rsi_thr=RSI_THR, top_n=TOP_N, status=status, scanned=bool(need_scan), n_candidates=(None if cands is None else int(len(cands))),
             picks=picks.to_dict("records"), candidates=(cands.head(40).to_dict("records") if cands is not None else []), buy=buy, sell=sell, events=events,
             positions=[dict(signal_date=c["signal_date"], status=c["status"], mode=c.get("mode", "live"), names=c["names"]) for c in pos["cohorts"] if c["status"] in ("pending", "open")],
             track=track_record(j))
    json.dump(L, open(LATEST, "w"), ensure_ascii=False, indent=1, default=str)
    if need_scan: json.dump(L, open(os.path.join(SCANS, f"{today}.json"), "w"), ensure_ascii=False, default=str)
    daily_log(dict(date=str(today), mode=mode, q_close=round(q_close, 2), q_ret=round(q_ret, 4), q_rsi=round(q_rsi, 1), status=status,
                   picks=" ".join(picks.ticker) if len(picks) else "", n_candidates=(None if cands is None else len(cands))))
    build_page()
    log("\n" + summary_text(L) + "\n")


def summary_text(L):
    ico, label = STATUS[L["status"]][:2]
    out = [f"📊 {d2s(L['sig_date'])} (после закрытия)  QQQ {L['q_close']:.2f} {L['q_ret'] * 100:+.2f}%  RSI(2) = {L['q_rsi']:.1f}  (сигнал при < {L['rsi_thr']:.0f})  →  {ico} {label}"]
    out += L["events"]
    if L["buy"]:
        out.append(f"➡️ КУПИТЬ ЗАВТРА ПО ОТКРЫТИЮ, по {PER_NAME:.0%} капитала (≈{CAPITAL * PER_NAME:,.0f}$) каждую:")
        out += [f"   {b['ticker']:<6} закрытие {b['close']:>8.2f}  сегодня {b['ret_1'] * 100:+.1f}%  оборот {b['dvol_M']:,.0f}M$/д  (~{b['shares_est']} шт)" for b in L["buy"]]
        out.append("   ПРОДАТЬ — ПО ЗАКРЫТИЮ СЛЕДУЮЩЕГО ДНЯ ПОСЛЕ ВХОДА. Без стопов, без целей.")
    for s in L["sell"]:
        out.append(f"⏰ ЗАВТРА ПО ЗАКРЫТИЮ ПРОДАТЬ когорту {d2s(s['signal_date'])}: " + ", ".join(f"{n['ticker']} {n['shares']} шт" for n in s["names"]))
    if not L["buy"] and not L["sell"]: out.append("Завтра ничего не делаем.")
    out.append(L["track"]["text"])
    return "\n".join(out)


# ------------------------------------------------------------------ dashboard (docs/index.html) + README block
CSS = """
*{box-sizing:border-box}body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;max-width:1040px;margin:0 auto;padding:18px 14px 40px;color:#1f2328;background:#fff;line-height:1.45}
h1{font-size:22px;margin:0 0 4px}h2{font-size:17px;margin:26px 0 8px;border-bottom:1px solid #d8dee4;padding-bottom:4px}h3{font-size:15px;margin:14px 0 6px}
.muted{color:#57606a;font-size:13px}.card{border:1px solid #d0d7de;border-radius:10px;padding:14px 16px;margin:12px 0;background:#fff}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}@media(max-width:760px){.grid{grid-template-columns:1fr}}
.status{font-size:19px;font-weight:700}.kv{display:flex;flex-wrap:wrap;gap:6px 22px;margin-top:8px;font-size:14px}.kv b{font-size:16px}
table{border-collapse:collapse;width:100%;font-size:13px;margin:6px 0}th,td{border:1px solid #d8dee4;padding:5px 8px;text-align:left;white-space:nowrap}th{background:#f6f8fa;font-weight:600}
tr.pick td{background:#e9f7ef;font-weight:600}.pos{color:#1e8449}.neg{color:#c0392b}.tag{display:inline-block;font-size:11px;padding:1px 6px;border-radius:10px;background:#eaeef2;color:#57606a;margin-left:4px}
.act{font-size:15px}.act li{margin:4px 0}.bar{position:relative;height:10px;background:linear-gradient(90deg,#1e8449 0 10%,#eaeef2 10% 100%);border-radius:5px;margin:6px 0 2px}
.bar i{position:absolute;top:-4px;width:4px;height:18px;background:#1f2328;border-radius:2px}.wrap{overflow-x:auto}.ev{margin:6px 0;padding:8px 12px;background:#f6f8fa;border-radius:8px}
"""

def _cls(x): return "pos" if x > 0 else "neg"
def _pct(x, d=2): return "" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x * 100:+.{d}f}%"
def _num(x, d=2): return "" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:,.{d}f}"

def build_page():
    L, j, dl = latest(), journal_df(), daily_df()
    att = json.load(open(ATTEMPT)) if os.path.exists(ATTEMPT) else None
    tr = track_record(j)
    strat = f"{REPO_URL}/blob/main/STRATEGY.md" if REPO_URL else "#"
    upd = f"{now_et():%d.%m.%Y %H:%M} ET"
    parts = [f"<h1>Dip-Buyer NASDAQ 48h — paper trading</h1><div class='muted'>Сканер запускается раз в день после закрытия США. Ордера не исполняются — только вывод сканера и бумажный журнал. Обновлено {upd}"
             + (f" · <a href='{REPO_URL}'>репозиторий</a>" if REPO_URL else "") + "</div>"]
    if att:
        parts.append(f"<div class='card' style='background:#fdf6e3;border-color:#e6c65a'>⚠️ Попытка {att['run_at']}: {att['note']}</div>")
    if L is None:
        parts.append("<div class='card'>Запусков ещё не было. Первый результат появится после первого прогона (Actions → Run workflow, или автоматически после закрытия рынка).</div>")
    else:
        ico, label, col, bg = STATUS[L["status"]]
        rsi = max(0.0, min(100.0, float(L["q_rsi"])))
        parts.append("<div class='grid'>")
        parts.append(f"<div class='card' style='background:{bg};border-color:{col}'><div class='muted'>Сканирование за {d2s(L['sig_date'])} (после закрытия)"
                     + (" <span class='tag'>replay</span>" if L["mode"] == "replay" else "") + f"</div><div class='status' style='color:{col}'>{ico} {label}</div>"
                     f"<div class='kv'><span>QQQ <b>{L['q_close']:.2f}</b> <span class='{_cls(L['q_ret'])}'>{_pct(L['q_ret'])}</span></span>"
                     f"<span>RSI(2) <b>{L['q_rsi']:.1f}</b> <span class='muted'>сигнал при &lt; {L['rsi_thr']:.0f}</span></span>"
                     f"<span>кандидатов по фильтру <b>{'—' if L['n_candidates'] is None else L['n_candidates']}</b></span></div>"
                     f"<div class='bar'><i style='left:calc({rsi:.1f}% - 2px)'></i></div><div class='muted'>RSI(2) QQQ: 0 … 100, зелёная зона — сигнал</div></div>")
        acts = []
        for b in L["buy"]:
            acts.append(f"<li>🟢 <b>КУПИТЬ {b['ticker']}</b> по открытию — {PER_NAME:.0%} капитала ≈ {b['usd']:,.0f}$ (~{b['shares_est']} шт по закрытию {b['close']:.2f})</li>")
        if L["buy"]: acts.append("<li class='muted'>продать — по закрытию следующего дня после входа; без стопов и целей</li>")
        for s in L["sell"]:
            acts.append(f"<li>🔴 <b>ПРОДАТЬ по закрытию</b> когорту {d2s(s['signal_date'])}: " + ", ".join(f"{n['ticker']} {n['shares']} шт (вход {n['entry_px']:.2f})" for n in s["names"] if n.get("entry_px")) + "</li>")
        if not acts: acts.append("<li>Ничего не делаем.</li>")
        parts.append("<div class='card'><div class='muted'>Действия на следующую сессию</div><ul class='act'>" + "".join(acts) + "</ul></div></div>")
        if L["events"]:
            parts.append("<h2>События этого запуска</h2>" + "".join(f"<div class='ev'>{e}</div>" for e in L["events"]))
        # scan table
        parts.append(f"<h2>Вывод сканера — {d2s(L['sig_date'])}</h2>")
        if not L["scanned"]:
            parts.append("<div class='muted'>Полный скан в этот день не выполнялся (быстрый реплей: рынок не перепродан, позиций нет).</div>")
        elif not L["candidates"]:
            parts.append("<div class='muted'>Ни одна акция не прошла фильтр (close &gt; SMA200, день ≤ −3%, оборот ≥ 20M$/д, цена ≥ 5$).</div>")
        else:
            cap = ("Топ-{n} по обороту — это сегодняшние покупки." if L["status"] == "SIGNAL" else
                   "Рынок не перепродан, сигнала нет — это просто вывод фильтра. Торгуем только когда RSI(2) QQQ &lt; {thr}; тогда берём топ-{n} по обороту.").format(n=L["top_n"], thr=int(L["rsi_thr"]))
            rows = "".join(f"<tr class='{'pick' if (i < L['top_n'] and L['status'] == 'SIGNAL') else ''}'><td>{i + 1}</td><td>{c['ticker']}</td><td>{c['close']:.2f}</td>"
                           f"<td class='{_cls(c['ret_1'])}'>{_pct(c['ret_1'], 1)}</td><td>{c['dvol_M']:,.0f}</td><td>{_pct(c['vs_sma200'], 0)}</td></tr>" for i, c in enumerate(L["candidates"]))
            parts.append(f"<div class='muted'>Прошли фильтр: {L['n_candidates']} (показаны первые {len(L['candidates'])}, отсортировано по среднему обороту за 21 день). {cap}</div>"
                         f"<div class='wrap'><table><tr><th>#</th><th>тикер</th><th>закрытие</th><th>день</th><th>оборот, M$/д</th><th>над SMA200</th></tr>{rows}</table></div>")
        # positions
        parts.append("<h2>Открытые позиции (paper)</h2>")
        if not L["positions"]: parts.append("<div class='muted'>Нет.</div>")
        else:
            rows = ""
            for c in L["positions"]:
                what = "вход по открытию следующей сессии" if c["status"] == "pending" else "выход по закрытию следующей сессии"
                names = ", ".join(f"{n['ticker']}" + (f" {n['shares']} шт @ {n['entry_px']:.2f}" if n.get("entry_px") else "") for n in c["names"])
                rows += f"<tr><td>{d2s(c['signal_date'])}</td><td>{c['status']}</td><td>{names}</td><td>{what}</td></tr>"
            parts.append(f"<div class='wrap'><table><tr><th>сигнал</th><th>статус</th><th>имена</th><th>что дальше</th></tr>{rows}</table></div>")
    # results
    parts.append(f"<h2>Результаты (paper)</h2><div class='card'><b>{tr['text']}</b>" +
                 (f"<div class='muted'>лучшая сделка {tr['best']:+.1f}%, худшая {tr['worst']:+.1f}%</div>" if tr["n"] else "") + "</div>")
    eq = equity_curve(j)
    if len(eq) >= 1:
        vals = [CAPITAL] + list(eq.values); xs = np.linspace(8, 632, len(vals)); lo, hi = min(vals), max(vals); rng = (hi - lo) or 1
        ys = [150 - (v - lo) / rng * 130 for v in vals]; pts = " ".join(f"{x:.0f},{y:.0f}" for x, y in zip(xs, ys)); y0 = 150 - (CAPITAL - lo) / rng * 130
        parts.append(f"<svg width='640' height='170' style='max-width:100%;background:#fff;border:1px solid #d8dee4;border-radius:8px'><line x1='0' y1='{y0:.0f}' x2='640' y2='{y0:.0f}' stroke='#d8dee4' stroke-dasharray='4'/>"
                     f"<polyline fill='none' stroke='{'#1e8449' if vals[-1] >= CAPITAL else '#c0392b'}' stroke-width='2' points='{pts}'/><text x='6' y='14' font-size='11' fill='#57606a'>{hi:,.0f}$</text>"
                     f"<text x='6' y='164' font-size='11' fill='#57606a'>{lo:,.0f}$</text><text x='560' y='14' font-size='11' fill='#57606a'>{len(eq)} выходов</text></svg>")
    if len(j):
        rows = ""
        for r in j.sort_values(["signal_date", "ticker"], ascending=[False, True]).itertuples():
            rn = None if pd.isna(r.ret_net) else float(r.ret_net); pnl = None if pd.isna(r.pnl_usd) else float(r.pnl_usd)
            rows += (f"<tr><td>{d2s(r.signal_date)}{' <span class=tag>replay</span>' if r.mode == 'replay' else ''}</td><td><b>{r.ticker}</b></td><td>{d2s(r.entry_date) if isinstance(r.entry_date, str) else ''}</td>"
                     f"<td>{_num(r.entry_px)}</td><td>{'' if pd.isna(r.shares) else int(r.shares)}</td><td>{d2s(r.exit_date) if isinstance(r.exit_date, str) else ''}</td><td>{_num(r.exit_px)}</td>"
                     f"<td class='{_cls(rn) if rn is not None else ''}'>{_pct(rn)}</td><td class='{_cls(pnl) if pnl is not None else ''}'>{'' if pnl is None else f'{pnl:+,.0f}$'}</td><td>{r.status}</td></tr>")
        parts.append(f"<h3>Сделки</h3><div class='wrap'><table><tr><th>сигнал</th><th>тикер</th><th>вход</th><th>цена входа (open)</th><th>шт</th><th>выход</th><th>цена выхода (close)</th><th>net</th><th>P&amp;L</th><th>статус</th></tr>{rows}</table></div>"
                     f"<div class='muted'>net = после {COST * 1e4:.0f} б.п. издержек за круг; размер {PER_NAME:.0%} капитала ({CAPITAL:,.0f}$) на имя.</div>")
    if len(dl):
        sig = dl[dl.status == "SIGNAL"].sort_values("date", ascending=False)
        if len(sig):
            rows = "".join(f"<tr><td>{d2s(r.date)}</td><td>{_num(r.q_close)}</td><td class='{_cls(r.q_ret)}'>{_pct(r.q_ret)}</td><td>{r.q_rsi}</td><td><b>{r.picks}</b></td><td>{'' if pd.isna(r.n_candidates) else int(r.n_candidates)}</td></tr>" for r in sig.itertuples())
            parts.append(f"<h2>Сигнальные дни ({len(sig)})</h2><div class='wrap'><table><tr><th>дата</th><th>QQQ</th><th>день</th><th>RSI(2)</th><th>пики</th><th>кандидатов</th></tr>{rows}</table></div>")
        rows = "".join(f"<tr><td>{d2s(r.date)}{' <span class=tag>replay</span>' if r.mode == 'replay' else ''}</td><td>{_num(r.q_close)}</td><td class='{_cls(r.q_ret)}'>{_pct(r.q_ret)}</td><td>{r.q_rsi}</td>"
                       f"<td>{STATUS.get(r.status, ('', r.status))[0]} {r.status}</td><td>{r.picks if isinstance(r.picks, str) else ''}</td><td>{'' if pd.isna(r.n_candidates) else int(r.n_candidates)}</td></tr>"
                       for r in dl.sort_values("date", ascending=False).head(40).itertuples())
        parts.append(f"<h2>Журнал запусков (последние 40 из {len(dl)})</h2><div class='wrap'><table><tr><th>дата</th><th>QQQ</th><th>день</th><th>RSI(2)</th><th>статус</th><th>пики / топ-{TOP_N} фильтра</th><th>кандидатов</th></tr>{rows}</table></div>")
    parts.append(f"<h2>Правило</h2><div class='card'>QQQ RSI(2) &lt; {RSI_THR:.0f} по закрытию → акции NASDAQ: close &gt; SMA200, день ≤ −3%, оборот ≥ 20M$/д, цена ≥ 5$ → <b>{TOP_N} самых ликвидных</b> → "
                 f"купить по открытию следующей сессии, продать по закрытию сессии после дня входа. {PER_NAME:.0%} капитала на имя, без стопов и целей.<br>"
                 f"<b>Ожидание по бэктесту 2010–2026 (топ-2, вход по открытию, после издержек):</b> +57 б.п./сделку, медиана +0.4%, прибыльных 56%, ~47 сделок и ~24 сигнальных дня в году, 14 из 17 лет в плюсе; "
                 f"при 10%/имя max DD −5.9%. Серии из 5–7 убыточных подряд — норма. Подробности — <a href='{strat}'>STRATEGY.md</a>.</div>")
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
        ico, label = STATUS[L["status"]][:2]
        lines = [f"### 📊 Последнее сканирование: {d2s(L['sig_date'])} (после закрытия) — {ico} {label}" + (" *(replay)*" if L["mode"] == "replay" else ""),
                 f"QQQ **{L['q_close']:.2f}** ({_pct(L['q_ret'])}) · RSI(2) **{L['q_rsi']:.1f}** (сигнал при < {L['rsi_thr']:.0f}) · кандидатов по фильтру: {'—' if L['n_candidates'] is None else L['n_candidates']}", ""]
        if L["buy"]:
            lines += [f"**➡️ КУПИТЬ по открытию следующей сессии, по {PER_NAME:.0%} капитала (≈{CAPITAL * PER_NAME:,.0f}$) каждую; продать по закрытию следующего дня после входа:**", "",
                      "| тикер | закрытие | день | оборот, M$/д | над SMA200 |", "|---|---|---|---|---|"]
            lines += [f"| **{x['ticker']}** | {x['close']:.2f} | {_pct(x['ret_1'], 1)} | {x['dvol_M']:,.0f} | {_pct(x['vs_sma200'], 0)} |" for x in L["buy"]]
            lines.append("")
        for x in L["sell"]:
            lines.append(f"**⏰ ПРОДАТЬ по закрытию следующей сессии** когорту {d2s(x['signal_date'])}: " + ", ".join(f"{n['ticker']} {n['shares']} шт" for n in x["names"]) + "  ")
        if not L["buy"] and not L["sell"]: lines.append("**Завтра:** ничего не делаем.  ")
        if L["candidates"] and L["status"] != "SIGNAL":
            top = ", ".join(f"{c['ticker']} ({_pct(c['ret_1'], 1)}, {c['dvol_M']:,.0f}M$)" for c in L["candidates"][:5])
            lines.append(f"Топ фильтра по обороту (не сигнал, просто вывод сканера): {top}  ")
        lines += [f"**{tr['text']}**  ", f"Полный дашборд: {link} · обновлено {L['run_at']}"]
        block = "\n".join(lines) + "\n"
    s = s[:s.index(a) + len(a)] + "\n" + block + s[s.index(b):]
    open(README, "w").write(s)


def test():
    q = download(["QQQ"], period="6mo").get("QQQ")
    if q is None: log("❌ QQQ download failed"); raise SystemExit(1)
    log(f"✅ data OK: QQQ last bar {q.index[-1].date()} close {float(q['Close'].iloc[-1]):.2f}, RSI(2) = {float(rsi2(q['Close']).iloc[-1]):.1f} (signal < {RSI_THR:.0f}); now {now_et():%d.%m %H:%M} ET")
    build_page(); log("✅ dashboard rebuilt: docs/index.html")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["run", "test", "rebuild-page", "refresh-universe"])
    ap.add_argument("--asof", default=None); ap.add_argument("--fast", action="store_true")
    a = ap.parse_args()
    if a.mode == "test": test()
    elif a.mode == "rebuild-page": build_page(); log("docs/index.html + README block rebuilt")
    elif a.mode == "refresh-universe": refresh_universe()
    else: run(dt.date.fromisoformat(a.asof) if a.asof else None, a.fast)
