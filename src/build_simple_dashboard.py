#!/usr/bin/env python3
"""Build SIMPLE dashboard - only top 2 picks + tracking, minimal stats."""
import json, os
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
for t in PICKS:
    r = row(t)
    f = fund.get(t, {})
    entry, t2, t5, stop = level_band(t)
    gap_p = r.get("gap_sig_p")
    gap_s = f"{gap_p:.0%}" if gap_p is not None and not np.isnan(gap_p) else "—"
    cards_html += f"""
    <div style="background:#161b22;border:1px solid #30363d;border-radius:14px;padding:20px;margin-bottom:20px">
      <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px">
        <div><span style="font-size:28px;font-weight:800;color:#e6edf3">{t}</span><span style="color:#8b949e;font-size:13px;margin-left:10px">{f.get('longName', t)}</span></div>
        <div style="text-align:right"><div style="font-size:26px;font-weight:800;color:#e6edf3">${num(r['close'])}</div><div style="font-size:12px;color:{'#f85149' if (r.get('ret_1') or 0) < 0 else '#2ea043'}">{pct(r.get('ret_1'))} сегодня</div></div>
      </div>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin-top:16px">
        <div style="background:#0d1117;border:1px solid #21262d;border-radius:10px;padding:12px"><div style="color:#8b949e;font-size:10px;text-transform:uppercase">Вероятность +2% за 48ч</div><div style="font-size:20px;font-weight:800;color:#56d364;margin:4px 0">{r['hit']:.0%}</div>{score_bar(r['prob'])}<div style="color:#8b949e;font-size:10px;margin-top:4px">скор {r['prob']:.3f}</div></div>
        <div style="background:#0d1117;border:1px solid #21262d;border-radius:10px;padding:12px"><div style="color:#8b949e;font-size:10px;text-transform:uppercase">Уровни</div><div style="font-size:13px;margin-top:6px;line-height:1.6"><div style="display:flex;justify-content:space-between"><span style="color:#8b949e">Вход</span><b>${entry:.2f}</b></div><div style="display:flex;justify-content:space-between"><span style="color:#8b949e">Цель +2%</span><b style="color:#56d364">${t2:.2f}</b></div><div style="display:flex;justify-content:space-between"><span style="color:#8b949e">Цель +5%</span><b style="color:#2ea043">${t5:.2f}</b></div><div style="display:flex;justify-content:space-between"><span style="color:#8b949e">Стоп -3%</span><b style="color:#f85149">${stop:.2f}</b></div></div></div>
        <div style="background:#0d1117;border:1px solid #21262d;border-radius:10px;padding:12px"><div style="color:#8b949e;font-size:10px;text-transform:uppercase">Гэп след. дня</div><div style="font-size:13px;margin-top:6px;line-height:1.6"><div style="display:flex;justify-content:space-between"><span style="color:#8b949e">P(вверх)</span><b style="color:#2ea043">{gap_s}</b></div><div style="display:flex;justify-content:space-between"><span style="color:#8b949e">RSI</span><b>{num(r.get('rsi14'))}</b></div><div style="display:flex;justify-content:space-between"><span style="color:#8b949e">Объем</span><b>{num(r.get('vol_ratio'))}×</b></div><div style="display:flex;justify-content:space-between"><span style="color:#8b949e">Капа</span><b>{money(f.get('marketCap'))}</b></div></div></div>
      </div>
      <div style="margin-top:14px">{svg_candles(t)}</div>
      <div style="color:#8b949e;font-size:10px;margin-top:4px">Свеча {LAST} до 15:30 ET (неполная). Вход по закрытию.</div>
    </div>
    """
top5 = scan.head(5)
rows = ""
for i, (_, r) in enumerate(top5.iterrows(), 1):
    hl = "background:#12261a;" if r["ticker"] in PICKS else ""
    rows += f"<tr style='{hl}'><td style='padding:6px 8px'>{i}</td><td style='padding:6px 8px;font-weight:700'>{r['ticker']}</td><td style='padding:6px 8px;text-align:right'>${r['close']:.2f}</td><td style='padding:6px 8px;text-align:right;color:#56d364;font-weight:700'>{r['prob']:.3f}</td><td style='padding:6px 8px;text-align:right'>{r['hit']:.0%}</td></tr>"
ACTIONS_URL = "https://github.com/exodus611/nasdaq-eod-momentum-scanner/actions/workflows/daily_scan.yml"
if SCAN_TOKEN:
    run_btn = f"""
    <div style="display:flex;flex-direction:column;gap:6px;align-items:flex-end">
      <button onclick="runScan()" id="run-btn" style="background:#238636;color:#fff;border:none;border-radius:8px;padding:10px 18px;font-size:14px;font-weight:700;cursor:pointer">▶ Сканировать сейчас</button>
      <a href="{ACTIONS_URL}" target="_blank" style="font-size:11px;color:#8b949e;text-decoration:underline">или открыть Actions → Run workflow</a>
      <div id="run-status" style="font-size:12px;color:#8b949e;margin-top:2px;max-width:280px;text-align:right"></div>
    </div>
    <script>
    async function runScan(){{
      const btn = document.getElementById('run-btn');
      const st = document.getElementById('run-status');
      btn.disabled = true; btn.textContent = '⏳ Запускаю...';
      st.style.color = '#d29922'; st.textContent = 'Отправляю запрос...';
      try {{
        const r = await fetch('https://api.github.com/repos/exodus611/nasdaq-eod-momentum-scanner/actions/workflows/daily_scan.yml/dispatches', {{
          method: 'POST',
          headers: {{'Authorization': 'Bearer ' + '{SCAN_TOKEN}', 'Accept': 'application/vnd.github+json', 'Content-Type': 'application/json'}},
          body: JSON.stringify({{ref: 'main'}})
        }});
        if (r.status === 204) {{
          st.style.color = '#2ea043'; st.textContent = '✅ Запущено! ~5-10 мин. Не жми второй раз - уже идёт.';
          btn.textContent = '✅ Запущено';
          setTimeout(()=>{{ btn.disabled=false; btn.textContent='▶ Сканировать сейчас'; }}, 300000);
        }} else if (r.status === 422) {{
          st.style.color = '#d29922'; st.textContent = '⏳ Скан уже запущен! Подожди 5 мин.';
          btn.textContent = '⏳ Уже запущен';
          setTimeout(()=>{{ btn.disabled=false; btn.textContent='▶ Сканировать сейчас'; st.textContent=''; }}, 60000);
        }} else if (r.status === 401) {{
          st.style.color = '#f85149'; st.textContent = '❌ Токен невалидный.';
          btn.disabled = false; btn.textContent = '▶ Попробовать снова';
        }} else {{
          const txt = await r.text();
          st.style.color = '#f85149'; st.innerHTML = '❌ Ошибка ' + r.status + ': ' + txt.slice(0,120) + '<br><a href="{ACTIONS_URL}" target="_blank" style="color:#58a6ff">Открой Actions →</a>';
          btn.disabled = false; btn.textContent = '▶ Попробовать снова';
        }}
      }} catch(e) {{
        st.style.color = '#f85149'; st.innerHTML = '❌ ' + e.message + '<br><a href="{ACTIONS_URL}" target="_blank" style="color:#58a6ff">Открой Actions →</a>';
        btn.disabled = false;
      }}
    }}
    </script>
    """
else:
    run_btn = f"""<div style="display:flex;flex-direction:column;gap:6px;align-items:flex-end">
      <a href="{ACTIONS_URL}" target="_blank" style="background:#1f6feb;color:#fff;text-decoration:none;border-radius:8px;padding:10px 18px;font-size:14px;font-weight:700;display:inline-block">▶ Сканировать (Actions)</a>
      <div style="font-size:11px;color:#8b949e;max-width:240px;text-align:right">Откроет Actions → Run workflow.<br>Автоскан каждый день 15:30 ET.<br>Если жмёшь 2 раза - второй раз "уже запущен", это нормально.</div>
    </div>"""
html = f"""<!DOCTYPE html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>TOP 2 - EOD {LAST}</title></head><body style="margin:0;background:#0d1117;color:#e6edf3;font-family:system-ui,Segoe UI,Roboto,sans-serif"><div style="max-width:900px;margin:0 auto;padding:24px 16px 60px"><div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px;border-bottom:1px solid #30363d;padding-bottom:16px"><div><div style="color:#58a6ff;font-size:11px;font-weight:600;letter-spacing:1px;text-transform:uppercase">NASDAQ EOD · TOP 2</div><h1 style="margin:4px 0 2px;font-size:26px;font-weight:800">Две лучшие акции на сегодня</h1><div style="color:#8b949e;font-size:13px">Сигнал {LAST} 15:30 ET → вход на закрытии → цель +2..+5% за 24-48ч</div></div><div style="text-align:right">{run_btn}</div></div><div style="background:#0d1117;border:1px solid #21262d;border-radius:10px;padding:10px 14px;font-size:12px;margin-top:14px;display:flex;justify-content:space-between;flex-wrap:wrap;gap:8px"><span><span style="color:#8b949e">Вселенная:</span> <b>{META.get('universe_total', '—'):,} NASDAQ</b> → <b>{META.get('scanned', '—')}</b> ликвидных</span><span><span style="color:#8b949e">Обновлено:</span> <b>{META.get('generated_utc', '')[:16]}</b></span></div><div style="margin-top:18px">{cards_html}</div><div style="background:#161b22;border:1px solid #30363d;border-radius:12px;padding:16px;margin-top:20px"><h3 style="margin:0 0 10px;font-size:16px">Топ-5 рейтинга</h3><table style="border-collapse:collapse;width:100%;font-size:13px"><thead><tr style="color:#8b949e;text-align:left;border-bottom:1px solid #30363d"><th>#</th><th>Тикер</th><th style="text-align:right">Цена</th><th style="text-align:right">Скор</th><th style="text-align:right">P(+2%)</th></tr></thead><tbody>{rows}</tbody></table><div style="margin-top:10px;font-size:12px"><a href="dashboard.html">Полный дашборд с статистикой →</a> | <a href="scan_results.csv">CSV →</a></div></div><div style="background:#2d1415;border:1px solid #da3633;border-radius:10px;padding:12px 14px;margin-top:20px;font-size:11px;color:#e6b9b9">⚠️ Не гарантия роста. P ~49% исторически, стоп -3%, позиция 1-2%. Не финсовет.</div></div></body></html>"""
import os
os.makedirs(OUT, exist_ok=True)
open(os.path.join(OUT, "simple.html"), "w", encoding="utf-8").write(html)
open(os.path.join(OUT, "index.html"), "w", encoding="utf-8").write(html)
print(f"simple dashboard: {len(html)} bytes TOP2 {PICKS}")
