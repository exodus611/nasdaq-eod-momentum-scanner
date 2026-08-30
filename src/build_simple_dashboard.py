#!/usr/bin/env python3
"""Build SIMPLE dashboard - TOP2 + accordion + local time (TLV) + RUNS link"""
import json, os
from datetime import datetime, timezone, timedelta
import numpy as np
import pandas as pd
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
OUT = os.path.join(ROOT, "output")
scan = pd.read_csv(os.path.join(OUT, "scan_results.csv"))
LAST = str(scan["date"].iloc[0])
scan = scan.sort_values("prob", ascending=False)
PICKS = scan.head(2)["ticker"].tolist()
META = {}
if os.path.exists(os.path.join(OUT, "meta.json")):
    META = json.load(open(os.path.join(OUT, "meta.json")))
fund = {}
if os.path.exists(os.path.join(DATA, "fundamentals.json")):
    fund = json.load(open(os.path.join(DATA, "fundamentals.json")))
SCAN_TOKEN = os.environ.get("SCAN_TRIGGER_TOKEN", "")
gen_utc_str = META.get('generated_utc', '')
gen_dt = None
try:
    gen_dt = datetime.fromisoformat(gen_utc_str.replace('Z','+00:00'))
    if gen_dt.tzinfo is None:
        gen_dt = gen_dt.replace(tzinfo=timezone.utc)
except:
    gen_dt = datetime.now(timezone.utc)
et_tz = timezone(timedelta(hours=-4))
tlv_tz = timezone(timedelta(hours=3))
gen_et = gen_dt.astimezone(et_tz)
gen_tlv = gen_dt.astimezone(tlv_tz)
now_utc = datetime.now(timezone.utc)
next_scan_utc = now_utc.replace(hour=19, minute=30, second=0, microsecond=0)
while True:
    if next_scan_utc <= now_utc:
        next_scan_utc += timedelta(days=1)
        continue
    if next_scan_utc.weekday() >= 5:
        next_scan_utc += timedelta(days=1)
        continue
    break
next_scan_et = next_scan_utc.astimezone(et_tz)
next_scan_tlv = next_scan_utc.astimezone(tlv_tz)
def fmt(dt):
    return dt.strftime("%d.%m %H:%M")
def pct(x, nd=1):
    return f"{x * 100:+.{nd}f}%" if x is not None and not (isinstance(x, float) and np.isnan(x)) else "—"
def num(x, nd=2):
    return f"{x:,.{nd}f}" if x is not None and not (isinstance(x, float) and np.isnan(x)) else "—"
def money(x):
    if x is None:
        return "—"
    try:
        return f"${float(x) / 1e9:,.1f}B"
    except:
        return "—"
def row(t):
    return scan[scan["ticker"] == t].iloc[0]
def level_band(t):
    e = float(row(t)["close"])
    return e, e * 1.02, e * 1.05, e * 0.97
def svg_candles(t, n_bars=60):
    try:
        r = row(t)
        entry, t2, t5, stop = level_band(t)
        hist = pd.read_csv(os.path.join(DATA, f"hist_{t}.csv"), parse_dates=["date"])
        hist = hist.sort_values("date")
        df = hist.tail(n_bars - 1).copy()
        last_bar = pd.DataFrame([{"date": pd.Timestamp(LAST), "open": r["open"], "high": r["high"], "low": r["low"], "close": r["close"], "volume": r["volume"]}])
        df = pd.concat([df, last_bar], ignore_index=True)
        df["sma50"] = df["close"].rolling(50).mean()
        W, H, pad_l, pad_r, pad_t, pad_b = 700, 260, 10, 60, 12, 24
        hi = max(df["high"].max(), t5, entry) * 1.01
        lo = min(df["low"].min(), stop) * 0.99
        rng = hi - lo
        def Y(v): return pad_t + (hi - v) / rng * (H - pad_t - pad_b)
        def X(i): return pad_l + (i + 0.5) / len(df) * (W - pad_l - pad_r)
        cw = (W - pad_l - pad_r) / len(df) * 0.62
        parts = [f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" style="width:100%;height:auto;background:#0d1117;border-radius:10px;display:block">']
        for g in np.linspace(lo, hi, 5):
            gy = Y(g)
            parts.append(f'<line x1="{pad_l}" y1="{gy:.1f}" x2="{W - pad_r}" y2="{gy:.1f}" stroke="#21262d" stroke-width="1"/>')
            parts.append(f'<text x="{W - pad_r + 6}" y="{gy + 4:.1f}" fill="#8b949e" font-size="10" font-family="Verdana">{g:.0f}</text>')
        for i, (_, rw) in enumerate(df.iterrows()):
            x = X(i)
            up = rw["close"] >= rw["open"]
            col = "#2ea043" if up else "#f85149"
            bt = Y(max(rw["open"], rw["close"]))
            bh = max(1.0, abs(Y(rw["open"]) - Y(rw["close"])))
            parts.append(f'<line x1="{x:.1f}" y1="{Y(rw["high"]):.1f}" x2="{x:.1f}" y2="{Y(rw["low"]):.1f}" stroke="{col}" stroke-width="1.2"/>')
            parts.append(f'<rect x="{x - cw / 2:.1f}" y="{bt:.1f}" width="{cw:.1f}" height="{bh:.1f}" fill="{col}" rx="1"/>')
        prev = None
        for i, (_, rw) in enumerate(df.iterrows()):
            if pd.isna(rw["sma50"]):
                prev = None
                continue
            y = Y(rw["sma50"])
            if prev is not None:
                parts.append(f'<line x1="{prev[0]:.1f}" y1="{prev[1]:.1f}" x2="{X(i):.1f}" y2="{y:.1f}" stroke="#d29922" stroke-width="1.2" stroke-dasharray="3 2" opacity="0.8"/>')
            prev = (X(i), y)
        for (v, col, lab, dash) in [(entry, "#ffffff", "вход", "2 2"), (t5, "#2ea043", "+5%", "4 3"), (t2, "#56d364", "+2%", "4 3"), (stop, "#f85149", "стоп", "4 3")]:
            y = Y(v)
            parts.append(f'<line x1="{pad_l}" y1="{y:.1f}" x2="{W - pad_r}" y2="{y:.1f}" stroke="{col}" stroke-width="1" stroke-dasharray="{dash}" opacity="0.8"/>')
            parts.append(f'<text x="{pad_l + 4}" y="{y - 4:.1f}" fill="{col}" font-size="9" font-family="Verdana">{lab} {v:.2f}</text>')
        parts.append("</svg>")
        return "".join(parts)
    except Exception as e:
        return f"<div style='color:#8b949e;font-size:12px'>График недоступен: {e}</div>"
def score_bar(p):
    w = int(round(min(max(p, 0), 1) * 100))
    return f'<div style="background:#21262d;border-radius:6px;height:10px;width:100%"><div style="background:linear-gradient(90deg,#2ea043,#56d364);width:{w}%;height:100%;border-radius:6px"></div></div>'
cards_html = ""
for idx, t in enumerate(PICKS):
    r = row(t)
    f = fund.get(t, {})
    entry, t2, t5, stop = level_band(t)
    gap_p = r.get("gap_sig_p")
    gap_s = f"{gap_p:.0%}" if gap_p is not None and not np.isnan(gap_p) else "—"
    open_attr = "open" if idx == 0 else ""
    cards_html += f"""
    <details {open_attr} style="background:#161b22;border:1px solid #30363d;border-radius:14px;margin-bottom:14px;overflow:hidden">
      <summary style="list-style:none;cursor:pointer;padding:16px 20px;display:flex;justify-content:space-between;align-items:center;gap:12px;user-select:none">
        <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap">
          <span style="font-size:22px;font-weight:800;color:#e6edf3">{t}</span>
          <span style="background:#12261a;color:#56d364;border:1px solid #238636;border-radius:6px;padding:2px 8px;font-size:12px;font-weight:700">TOP {idx+1} • {r['prob']:.3f}</span>
          <span style="color:#8b949e;font-size:12px">{f.get('longName','')[:30]}</span>
        </div>
        <div style="display:flex;align-items:center;gap:14px">
          <div style="text-align:right">
            <div style="font-size:18px;font-weight:800;color:#e6edf3">${num(r['close'])}</div>
            <div style="font-size:11px;color:{'#f85149' if (r.get('ret_1') or 0) < 0 else '#2ea043'}">{pct(r.get('ret_1'))}</div>
          </div>
          <div style="color:#8b949e;font-size:18px">⌄</div>
        </div>
      </summary>
      <div style="padding:0 20px 20px;border-top:1px solid #21262d">
        <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin-top:16px">
          <div style="background:#0d1117;border:1px solid #21262d;border-radius:10px;padding:12px"><div style="color:#8b949e;font-size:10px;text-transform:uppercase">Вероятность +2% за 48ч</div><div style="font-size:20px;font-weight:800;color:#56d364;margin:4px 0">{r['hit']:.0%}</div>{score_bar(r['prob'])}<div style="color:#8b949e;font-size:10px;margin-top:4px">скор {r['prob']:.3f}</div></div>
          <div style="background:#0d1117;border:1px solid #21262d;border-radius:10px;padding:12px"><div style="color:#8b949e;font-size:10px;text-transform:uppercase">Уровни (вход=закрытие)</div><div style="font-size:13px;margin-top:6px;line-height:1.6"><div style="display:flex;justify-content:space-between"><span style="color:#8b949e">Вход</span><b>${entry:.2f}</b></div><div style="display:flex;justify-content:space-between"><span style="color:#8b949e">Цель +2%</span><b style="color:#56d364">${t2:.2f}</b></div><div style="display:flex;justify-content:space-between"><span style="color:#8b949e">Цель +5%</span><b style="color:#2ea043">${t5:.2f}</b></div><div style="display:flex;justify-content:space-between"><span style="color:#8b949e">Стоп -3%</span><b style="color:#f85149">${stop:.2f}</b></div></div></div>
          <div style="background:#0d1117;border:1px solid #21262d;border-radius:10px;padding:12px"><div style="color:#8b949e;font-size:10px;text-transform:uppercase">Для слежения</div><div style="font-size:13px;margin-top:6px;line-height:1.6"><div style="display:flex;justify-content:space-between"><span style="color:#8b949e">P(гэп↑)</span><b style="color:#2ea043">{gap_s}</b></div><div style="display:flex;justify-content:space-between"><span style="color:#8b949e">RSI</span><b>{num(r.get('rsi14'))}</b></div><div style="display:flex;justify-content:space-between"><span style="color:#8b949e">Объем</span><b>{num(r.get('vol_ratio'))}×</b></div><div style="display:flex;justify-content:space-between"><span style="color:#8b949e">Капа</span><b>{money(f.get('marketCap'))}</b></div></div></div>
        </div>
        <div style="margin-top:14px">{svg_candles(t)}</div>
        <div style="color:#8b949e;font-size:10px;margin-top:4px">Свеча {LAST} до 15:30 ET (неполная). Вход по закрытию.</div>
      </div>
    </details>
    """
top5 = scan.head(5)
rows = ""
for i, (_, r) in enumerate(top5.iterrows(), 1):
    hl = "background:#12261a;" if r["ticker"] in PICKS else ""
    rows += f"<tr style='{hl}'><td style='padding:6px 8px'>{i}</td><td style='padding:6px 8px;font-weight:700'>{r['ticker']}</td><td style='padding:6px 8px;text-align:right'>${r['close']:.2f}</td><td style='padding:6px 8px;text-align:right;color:#56d364;font-weight:700'>{r['prob']:.3f}</td><td style='padding:6px 8px;text-align:right'>{r['hit']:.0%}</td></tr>"

WORKFLOW_URL = "https://github.com/exodus611/nasdaq-eod-momentum-scanner/actions/workflows/daily_scan.yml"
RUNS_URL = "https://github.com/exodus611/nasdaq-eod-momentum-scanner/actions"

if SCAN_TOKEN:
    run_btn = f"""
    <div style="display:flex;flex-direction:column;gap:6px;align-items:flex-end">
      <button onclick="runScan()" id="run-btn" style="background:#238636;color:#fff;border:none;border-radius:8px;padding:10px 18px;font-size:14px;font-weight:700;cursor:pointer">▶ Сканировать сейчас</button>
      <div style="display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end">
        <a href="{WORKFLOW_URL}" target="_blank" style="font-size:11px;color:#58a6ff;text-decoration:underline">▶ Запустить тут</a>
        <a href="{RUNS_URL}" target="_blank" style="font-size:11px;color:#8b949e;text-decoration:underline">📊 Статус Runs (running)</a>
      </div>
      <div id="run-status" style="font-size:12px;color:#8b949e;margin-top:2px;max-width:280px;text-align:right"></div>
    </div>
    <script>
    async function runScan(){{
      const btn = document.getElementById('run-btn');
      const st = document.getElementById('run-status');
      btn.disabled = true; btn.textContent = '⏳ Запускаю...';
      st.style.color = '#d29922'; st.textContent = 'Отправляю...';
      try {{
        const r = await fetch('https://api.github.com/repos/exodus611/nasdaq-eod-momentum-scanner/actions/workflows/daily_scan.yml/dispatches', {{
          method: 'POST',
          headers: {{'Authorization': 'Bearer ' + '{SCAN_TOKEN}', 'Accept': 'application/vnd.github+json', 'Content-Type': 'application/json'}},
          body: JSON.stringify({{ref: 'main'}})
        }});
        if (r.status === 204) {{
          st.style.color = '#2ea043'; st.innerHTML = '✅ Запущено! <a href="{RUNS_URL}" target="_blank" style="color:#58a6ff;text-decoration:underline">→ Смотреть running в Actions</a><br>~5-10 мин';
          btn.textContent = '✅ Запущено → Runs';
          window.open('{RUNS_URL}', '_blank');
          setTimeout(()=>{{ btn.disabled=false; btn.textContent='▶ Сканировать сейчас'; }}, 300000);
        }} else if (r.status === 422) {{
          st.style.color = '#d29922'; st.innerHTML = '⏳ Уже запущен! <a href="{RUNS_URL}" target="_blank" style="color:#58a6ff">→ Смотреть Runs (running)</a>';
          btn.textContent = '⏳ Уже запущен → Runs';
          window.open('{RUNS_URL}', '_blank');
          setTimeout(()=>{{ btn.disabled=false; btn.textContent='▶ Сканировать сейчас'; st.textContent=''; }}, 60000);
        }} else {{
          const txt = await r.text();
          st.style.color = '#f85149'; st.innerHTML = '❌ ' + r.status + ': ' + txt.slice(0,120) + '<br><a href="{WORKFLOW_URL}" target="_blank" style="color:#58a6ff">→ Запусти в Actions</a> | <a href="{RUNS_URL}" target="_blank" style="color:#58a6ff">Runs (running)</a>';
          btn.disabled = false; btn.textContent = '▶ Попробовать снова';
        }}
      }} catch(e) {{
        st.style.color = '#f85149'; st.innerHTML = '❌ ' + e.message + '<br><a href="{WORKFLOW_URL}" target="_blank" style="color:#58a6ff">→ Запусти в Actions</a> | <a href="{RUNS_URL}" target="_blank" style="color:#58a6ff">Runs</a>';
        btn.disabled = false;
      }}
    }}
    </script>
    """
else:
    run_btn = f"""<div style="display:flex;flex-direction:column;gap:6px;align-items:flex-end">
      <a href="{WORKFLOW_URL}" target="_blank" style="background:#1f6feb;color:#fff;text-decoration:none;border-radius:8px;padding:10px 18px;font-size:14px;font-weight:700;display:inline-block">▶ Сканировать (Actions)</a>
      <a href="{RUNS_URL}" target="_blank" style="background:#238636;color:#fff;border:none;border-radius:8px;padding:8px 14px;font-size:12px;font-weight:700;display:inline-block;text-decoration:none">📊 Running статус →</a>
      <div style="font-size:11px;color:#8b949e;max-width:260px;text-align:right">Верхняя - запустить скан<br>Нижняя зелёная - смотреть что бежит (running page)<br>2-й клик = "уже запущен"</div>
    </div>"""

html = f"""<!DOCTYPE html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>TOP 2 - EOD {LAST}</title>
<style>
  details {{ transition: all 0.2s; }}
  details[open] summary {{ border-bottom:1px solid #21262d; }}
  summary::-webkit-details-marker {{ display:none; }}
  summary {{ list-style:none; }}
  .time-pill {{ background:#0d1117;border:1px solid #21262d;border-radius:8px;padding:6px 10px;font-size:12px; }}
</style>
</head><body style="margin:0;background:#0d1117;color:#e6edf3;font-family:system-ui,Segoe UI,Roboto,sans-serif">
<div style="max-width:900px;margin:0 auto;padding:20px 16px 60px">
  <div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:12px;border-bottom:1px solid #30363d;padding-bottom:14px">
    <div>
      <div style="color:#58a6ff;font-size:11px;font-weight:600;letter-spacing:1px;text-transform:uppercase">NASDAQ EOD · TOP 2 · Аккордеон</div>
      <h1 style="margin:4px 0 2px;font-size:24px;font-weight:800">Две лучшие акции на сегодня</h1>
      <div style="color:#8b949e;font-size:13px">Сигнал {LAST} 15:30 ET → вход на закрытии → цель +2..+5% за 24-48ч</div>
    </div>
    <div style="text-align:right">{run_btn}</div>
  </div>
  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px;margin-top:14px">
    <div class="time-pill"><div style="color:#8b949e;font-size:10px;text-transform:uppercase">Последний сигнал</div><div style="font-weight:700;margin-top:2px">{LAST} 15:30 ET</div><div style="color:#8b949e;font-size:11px">15:30 ET = 22:30 Тель-Авив = 19:30 UTC</div></div>
    <div class="time-pill"><div style="color:#8b949e;font-size:10px;text-transform:uppercase">Обновлено (Тель-Авив)</div><div style="font-weight:700;margin-top:2px" id="tlv-time">{fmt(gen_tlv)}</div><div style="color:#8b949e;font-size:11px" id="local-time-js">ET {fmt(gen_et)} · UTC {gen_dt.strftime("%d.%m %H:%M")}</div></div>
    <div class="time-pill"><div style="color:#8b949e;font-size:10px;text-transform:uppercase">Следующий автоскан</div><div style="font-weight:700;margin-top:2px;color:#56d364">{fmt(next_scan_tlv)} Тель-Авив</div><div style="color:#8b949e;font-size:11px">{fmt(next_scan_et)} ET · {next_scan_utc.strftime("%d.%m %H:%M")} UTC</div></div>
    <div class="time-pill"><div style="color:#8b949e;font-size:10px;text-transform:uppercase">Вселенная</div><div style="font-weight:700;margin-top:2px">{META.get('universe_total','—'):,} → {META.get('scanned','—')} ликвидных</div><div style="color:#8b949e;font-size:11px">NASDAQ, без логов</div></div>
  </div>
  <script>
    try {{
      const utc = "{gen_utc_str}";
      if (utc) {{
        const d = new Date(utc);
        document.getElementById('local-time-js').textContent = d.toLocaleString('ru-RU', {{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit', timeZoneName:'short'}}) + " (браузер)";
        document.getElementById('tlv-time').textContent = d.toLocaleString('ru-RU', {{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}}) + " Тель-Авив";
      }}
    }} catch(e){{}}
  </script>
  <div style="margin-top:18px">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
      <h3 style="margin:0;font-size:14px;color:#8b949e;text-transform:uppercase;letter-spacing:0.5px">Акции - нажми чтобы развернуть (аккордеон)</h3>
      <div style="display:flex;gap:8px">
        <button onclick="document.querySelectorAll('details').forEach(d=>d.open=true)" style="background:#21262d;color:#8b949e;border:1px solid #30363d;border-radius:6px;padding:4px 8px;font-size:11px;cursor:pointer">Развернуть всё</button>
        <button onclick="document.querySelectorAll('details').forEach((d,i)=>d.open=i===0)" style="background:#21262d;color:#8b949e;border:1px solid #30363d;border-radius:6px;padding:4px 8px;font-size:11px;cursor:pointer">Свернуть</button>
      </div>
    </div>
    {cards_html}
  </div>
  <details style="background:#161b22;border:1px solid #30363d;border-radius:12px;margin-top:14px">
    <summary style="padding:14px 16px;cursor:pointer;font-weight:700;display:flex;justify-content:space-between;align-items:center"><span>📊 Топ-5 рейтинга (гармошка)</span><span style="color:#8b949e">⌄</span></summary>
    <div style="padding:0 16px 16px;border-top:1px solid #21262d">
      <table style="border-collapse:collapse;width:100%;font-size:13px;margin-top:10px"><thead><tr style="color:#8b949e;text-align:left;border-bottom:1px solid #30363d"><th>#</th><th>Тикер</th><th style="text-align:right">Цена</th><th style="text-align:right">Скор</th><th style="text-align:right">P(+2%)</th></tr></thead><tbody>{rows}</tbody></table>
      <div style="margin-top:10px;font-size:12px"><a href="dashboard.html">Полный дашборд →</a> | <a href="scan_results.csv">CSV →</a></div>
    </div>
  </details>
  <details style="background:#0d1117;border:1px solid #21262d;border-radius:12px;margin-top:10px">
    <summary style="padding:12px 16px;cursor:pointer;color:#8b949e;font-size:12px">ℹ️ Как следить + время сканирования</summary>
    <div style="padding:0 16px 16px;font-size:12px;color:#8b949e;line-height:1.6;border-top:1px solid #21262d;margin-top:0;padding-top:12px">
      Автоскан: <b style="color:#e6edf3">будни 15:30 ET = 22:30 Тель-Авив = 19:30 UTC</b> (зимой 21:30 UTC). Сигнал по неполной свече до 15:30, вход по закрытию 16:00 ET. Цель +2%/+5% за 24-48ч, стоп -3%. Следи за уровнями в карточках выше. Кнопка "Сканировать" теперь ведёт на Actions и автоматом открывает Runs (running) страницу.
    </div>
  </details>
  <div style="background:#2d1415;border:1px solid #da3633;border-radius:10px;padding:10px 14px;margin-top:14px;font-size:11px;color:#e6b9b9">⚠️ Не гарантия роста. P ~49% исторически, стоп -3%, позиция 1-2%. Не финсовет.</div>
</div></body></html>"""

import os
os.makedirs(OUT, exist_ok=True)
open(os.path.join(OUT, "simple.html"), "w", encoding="utf-8").write(html)
open(os.path.join(OUT, "index.html"), "w", encoding="utf-8").write(html)
print(f"accordion+RUNS dashboard: {len(html)} bytes TOP2 {PICKS}")
