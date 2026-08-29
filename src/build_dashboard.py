#!/usr/bin/env python3
"""Build the standalone HTML dashboard (inline CSS/SVG, no external assets)."""
import json, os
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
OUT = os.path.join(ROOT, "output")

FRIDAY = "2026-08-28"

# ---------------------------------------------------------------- data ----
scan = pd.read_csv(os.path.join(OUT, "scan_results.csv"))
fund = json.load(open(os.path.join(DATA, "fundamentals.json")))

PICKS = ["MRVL", "IREN"]

def level_band(ticker):
    r = scan[scan["ticker"] == ticker].iloc[0]
    entry = r["friday_close"]
    return entry, entry * 1.02, entry * 1.05, entry * 0.97

# ------------------------------------------------------------ svg chart ----
def svg_candles(ticker, n_bars=64):
    r = scan[scan["ticker"] == ticker].iloc[0]
    entry, t2, t5, stop = level_band(ticker)
    hist = pd.read_csv(os.path.join(DATA, f"hist_{ticker}.csv"), parse_dates=["date"])
    hist = hist.sort_values("date")
    df = hist.tail(n_bars - 1).copy()
    fri = pd.DataFrame([{
        "date": pd.Timestamp(FRIDAY), "open": r["friday_open"], "high": r["friday_high"],
        "low": r["friday_low"], "close": r["friday_close"], "volume": r["friday_volume"]}])
    df = pd.concat([df, fri], ignore_index=True)
    df["sma50"] = df["close"].rolling(50).mean()

    W, H, pad_l, pad_r, pad_t, pad_b = 780, 300, 10, 70, 12, 26
    hi = max(df["high"].max(), t5, entry) * 1.01
    lo = min(df["low"].min(), stop) * 0.99
    rng = hi - lo
    def Y(v): return pad_t + (hi - v) / rng * (H - pad_t - pad_b)
    def X(i): return pad_l + (i + 0.5) / len(df) * (W - pad_l - pad_r)

    cw = (W - pad_l - pad_r) / len(df) * 0.62
    parts = [f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" style="width:100%;height:auto;background:#0d1117;border-radius:10px;display:block">']
    # grid
    for g in np.linspace(lo, hi, 6):
        gy = Y(g)
        parts.append(f'<line x1="{pad_l}" y1="{gy:.1f}" x2="{W-pad_r}" y2="{gy:.1f}" stroke="#21262d" stroke-width="1"/>')
        parts.append(f'<text x="{W-pad_r+6}" y="{gy+4:.1f}" fill="#8b949e" font-size="10" font-family="Verdana">{g:.0f}</text>')

    # candles
    for i, (_, row) in enumerate(df.iterrows()):
        x = X(i)
        up = row["close"] >= row["open"]
        col = "#2ea043" if up else "#f85149"
        body_top = Y(max(row["open"], row["close"]))
        body_h = max(1.0, abs(Y(row["open"]) - Y(row["close"])))
        parts.append(f'<line x1="{x:.1f}" y1="{Y(row["high"]):.1f}" x2="{x:.1f}" y2="{Y(row["low"]):.1f}" stroke="{col}" stroke-width="1.2"/>')
        parts.append(f'<rect x="{x-cw/2:.1f}" y="{body_top:.1f}" width="{cw:.1f}" height="{body_h:.1f}" fill="{col}" rx="1"/>')
        if i % 10 == 9 or i == len(df) - 1:
            lab = row["date"].strftime("%d.%m")
            parts.append(f'<text x="{x:.1f}" y="{H-8:.1f}" fill="#8b949e" font-size="9.5" font-family="Verdana" text-anchor="middle">{lab}</text>')

    # sma50
    prev = None
    for i, (_, row) in enumerate(df.iterrows()):
        if np.isnan(row["sma50"]):
            prev = None; continue
        y = Y(row["sma50"])
        if prev is not None:
            parts.append(f'<line x1="{prev[0]:.1f}" y1="{prev[1]:.1f}" x2="{X(i):.1f}" y2="{y:.1f}" stroke="#d29922" stroke-width="1.4" stroke-dasharray="3 2" opacity="0.9"/>')
        prev = (X(i), y)

    # levels
    for (v, col, lab, dash) in [(entry, "#ffffff", "вход", "2 2"), (t5, "#2ea043", "+5%", "4 3"),
                                (t2, "#56d364", "+2%", "4 3"), (stop, "#f85149", "стоп −3%", "4 3")]:
        y = Y(v)
        parts.append(f'<line x1="{pad_l}" y1="{y:.1f}" x2="{W-pad_r}" y2="{y:.1f}" stroke="{col}" stroke-width="1.1" stroke-dasharray="{dash}" opacity="0.85"/>')
        parts.append(f'<text x="{pad_l+4}" y="{y-4:.1f}" fill="{col}" font-size="9.5" font-family="Verdana">{lab} {v:.2f}</text>')

    parts.append("</svg>")
    return "".join(parts)

# ------------------------------------------------------------- helpers ----
def pct(x, nd=1):
    return f"{x*100:+.{nd}f}%" if x is not None and not (isinstance(x, float) and np.isnan(x)) else "—"

def num(x, nd=2, suf=""):
    return f"{x:,.{nd}f}{suf}" if x is not None and not (isinstance(x, float) and np.isnan(x)) else "—"

def money(x):
    if x is None: return "—"
    b = float(x) / 1e9
    return f"${b:,.1f}B"

def verdict(ticker):
    r = scan[scan["ticker"] == ticker].iloc[0]
    f = fund.get(ticker, {})
    return {
        "ticker": ticker,
        "name": f.get("longName", ticker),
        "sector": f.get("sector", "—"),
        "industry": f.get("industry", "—"),
        "close": r["friday_close"],
        "prob": r["prob"], "hit": r["hit"], "avg_best": r["avg_best"],
        "avg_fwd2": r["avg_fwd2"], "avg_worst": r["avg_worst"],
        "ret1": r["ret_1"], "ret5": r["ret_5"], "ret21": r["ret_21"],
        "rsi": r["rsi14"], "atr": r["atr14_pct"], "volr": r["vol_ratio"],
        "pos": r["friday_close_pos"], "vwap": r["close_vs_vwap"],
        "vs50": r["px_sma50"], "vs200": r["px_sma200"], "dist52": r["dist_52w_high"],
        "dv": r["dollar_vol21"], "gap": r["gap"],
        "mcap": f.get("marketCap"), "pe_fwd": f.get("forwardPE"),
        "rev_g": f.get("revenueGrowth"), "gm": f.get("grossMargins"),
        "pm": f.get("profitMargins"), "rec": f.get("recommendationKey"),
        "target": f.get("targetMeanPrice"), "n_analysts": f.get("numberOfAnalystOpinions"),
        "beta": f.get("beta"),
    }

def score_bar(p):
    w = int(round(p * 100))
    return (f'<div style="background:#21262d;border-radius:6px;height:14px;width:100%;overflow:hidden">'
            f'<div style="background:linear-gradient(90deg,#2ea043,#56d364);width:{w}%;height:100%;border-radius:6px"></div></div>')

# -------------------------------------------------------------- monthly ----
monthly = [
    ("Окт 25", 0.457, 0.321), ("Ноя 25", 0.449, 0.334), ("Дек 25", 0.473, 0.278),
    ("Янв 26", 0.488, 0.353), ("Фев 26", 0.502, 0.349), ("Мар 26", 0.499, 0.304),
    ("Апр 26", 0.538, 0.398), ("Май 26", 0.511, 0.362), ("Июн 26", 0.488, 0.406),
    ("Июл 26", 0.483, 0.353), ("Авг 26", 0.477, 0.324),
]

def svg_monthly():
    W, H, pad_l, pad_r, pad_t, pad_b = 760, 240, 46, 14, 16, 30
    mx = 0.6
    bw = (W - pad_l - pad_r) / len(monthly)
    parts = [f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" style="width:100%;height:auto;background:#0d1117;border-radius:10px;display:block">']
    for g in np.linspace(0, mx, 7):
        gy = pad_t + (mx - g) / mx * (H - pad_t - pad_b)
        parts.append(f'<line x1="{pad_l}" y1="{gy:.1f}" x2="{W-pad_r}" y2="{gy:.1f}" stroke="#21262d" stroke-width="1"/>')
        parts.append(f'<text x="{pad_l-4}" y="{gy+4:.1f}" fill="#8b949e" font-size="10" font-family="Verdana" text-anchor="end">{g:.0%}</text>')
    for i, (lab, s, b) in enumerate(monthly):
        x = pad_l + i * bw
        hS = (H - pad_t - pad_b) * s / mx
        hB = (H - pad_t - pad_b) * b / mx
        parts.append(f'<rect x="{x+bw*0.18}" y="{pad_t+(H-pad_t-pad_b)-hS:.1f}" width="{bw*0.28}" height="{hS:.1f}" fill="#2ea043" rx="2"/>')
        parts.append(f'<rect x="{x+bw*0.54}" y="{pad_t+(H-pad_t-pad_b)-hB:.1f}" width="{bw*0.28}" height="{hB:.1f}" fill="#8b949e" opacity="0.6" rx="2"/>')
        if i % 2 == 0 or i == len(monthly) - 1:
            parts.append(f'<text x="{x+bw/2:.1f}" y="{H-8:.1f}" fill="#8b949e" font-size="9.5" font-family="Verdana" text-anchor="middle">{lab}</text>')
    parts.append("</svg>")
    return "".join(parts)

# ------------------------------------------------------------- narrative ----
NARR = {
 "MRVL": {
  "story": ("<b>«Продажа на новостях» после сильного отчёта.</b> Marvell отчиталась в четверг вечером лучше ожиданий "
            "(выручка +37% до $2,74 млрд, EPS $0,94 при консенсусе $0,92, прогноз на Q3 $3,15 млрд выше оценок $3,03 млрд, "
            "цель по FY2028 поднята до ~$18 млрд). Но после Google-сделки ожидания были настолько разогреты, что акция "
            "в пятницу упала на 10% — инвесторы хотели деталей по FY2028, которых не дали. Пятница закрылась у минимума "
            "дня на объёме 1,9× от среднего: продавец истощён, диспозиция технически перепроданная, при этом долгосрочный "
            "тренд (выше SMA200 на +46%) не повреждён."),
  "base": ("Отскок от перепроданности после отсечки — статистически самый вероятный сценарий: возврат к уровню "
           "закрытия четверга ($228–232). Цель +2…+3% за 1–2 сессии."),
  "bull": ("Понедельник открывается без продолжения падения (гэп вверх или флэт) и закрывается выше $222 — тогда "
           "открывается путь к $228–230 (+5%) и выше, к средней целевой цене аналитиков $269 (+24% на горизонте недель)."),
  "bear": ("Пробой пятничного минимума $211 — сценарий продолжения распродажи на фоне разочарования в прогнозе; "
           "срабатывает стоп −3%."),
 },
 "IREN": {
  "story": ("<b>Трансформация из биткоин-майнера в AI-облако, дорогая, но идущая по плану.</b> В четверг вечером IREN "
            "отчиталась за FY2026: AI-cloud выручка впервые превысила майнинговую ($70,5 млн против $66,7 млн, рост вдвое "
            "кв/кв), но скорректированный EBITDA рухнул на 68% кв/кв, а чистый убыток составил $684 млн (включая списание "
            "$450 млн) — рынок наказал акцию падением −12,5% в пятницу. Долгосрочный фундамент сильный: контракты Microsoft "
            "($9,7 млрд) и Nvidia, $4 млрд законтрактованного годового run-rate на 2026 год, заморозка новых дата-центров в "
            "Техасе играет на руку действующим операторам. Бернстайн: рейтинг outperform, цель $100."),
  "base": ("Волатильный отскок от перепроданности: акция на −54% от 52-недельного максимума, RSI 40, закрытие у "
           "минимума дня на повышенном объёме. Цель +2…+3% за 1–2 сессии."),
  "bull": ("Закрытие понедельника выше $36,5 открывает путь к $37,2 (+5%) и выше. Позитив: рост AI-cloud выручки, "
           "операционная готовность контрактов MSFT/NVDA."),
  "bear": ("Пробой $34,4 (минимум пятницы) — продолжение падения на фоне слабой маржинальности и больших капзатрат; "
           "срабатывает стоп −3%."),
 },
}

# ================================================================ HTML ====
cards_html = ""
for t in PICKS:
    v = verdict(t); n = NARR[t]
    entry, t2, t5, stop = level_band(t)
    f = fund.get(t, {})
    rec_ru = {"strong_buy": "Сильная покупка", "buy": "Покупка", "hold": "Держать",
              "neutral": "Нейтрально"}.get(v["rec"], v["rec"] or "—")
    cards_html += f"""
    <div style="background:#161b22;border:1px solid #30363d;border-radius:14px;padding:22px;margin-bottom:22px">
      <div style="display:flex;flex-wrap:wrap;justify-content:space-between;align-items:baseline;gap:10px">
        <div>
          <span style="font-size:26px;font-weight:700;color:#e6edf3">{t}</span>
          <span style="color:#8b949e;font-size:14px;margin-left:10px">{v["name"]}</span>
          <span style="color:#8b949e;font-size:12px;margin-left:8px">{v["sector"]} · {v["industry"]}</span>
        </div>
        <div style="text-align:right">
          <span style="font-size:28px;font-weight:700;color:#e6edf3">${num(v["close"])}</span>
          <span style="font-size:13px;color:#f85149"> {pct(v["ret1"])} (пт)</span>
        </div>
      </div>

      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:14px;margin-top:16px">
        <div style="background:#0d1117;border:1px solid #21262d;border-radius:10px;padding:14px">
          <div style="color:#8b949e;font-size:11px;text-transform:uppercase;letter-spacing:0.5px">Скор модели (0–1)</div>
          <div style="font-size:22px;font-weight:700;color:#56d364;margin:4px 0">{v["prob"]:.3f}</div>
          {score_bar(v["prob"])}
          <div style="color:#8b949e;font-size:11px;margin-top:6px">P(рост ≥2% за 48ч)</div>
        </div>
        <div style="background:#0d1117;border:1px solid #21262d;border-radius:10px;padding:14px">
          <div style="color:#8b949e;font-size:11px;text-transform:uppercase;letter-spacing:0.5px">Ожидания модели на 48ч (по калибровке)</div>
          <table style="width:100%;font-size:13px;margin-top:6px">
            <tr><td style="color:#8b949e">Попадание ≥2%</td><td style="text-align:right;color:#2ea043;font-weight:700">{v["hit"]:.0%}</td></tr>
            <tr><td style="color:#8b949e">Среднее лучшее движение</td><td style="text-align:right;color:#2ea043;font-weight:700">{pct(v["avg_best"])}</td></tr>
            <tr><td style="color:#8b949e">Средний результат 2-го дня</td><td style="text-align:right;color:#e6edf3;font-weight:700">{pct(v["avg_fwd2"])}</td></tr>
            <tr><td style="color:#8b949e">Худший случай</td><td style="text-align:right;color:#f85149;font-weight:700">{pct(v["avg_worst"])}</td></tr>
          </table>
        </div>
        <div style="background:#0d1117;border:1px solid #21262d;border-radius:10px;padding:14px">
          <div style="color:#8b949e;font-size:11px;text-transform:uppercase;letter-spacing:0.5px">Уровни на 24–48ч</div>
          <table style="width:100%;font-size:13px;margin-top:6px">
            <tr><td style="color:#8b949e">Вход (пт, close)</td><td style="text-align:right;color:#e6edf3;font-weight:700">${entry:.2f}</td></tr>
            <tr><td style="color:#8b949e">Цель 1 (+2%)</td><td style="text-align:right;color:#56d364;font-weight:700">${t2:.2f}</td></tr>
            <tr><td style="color:#8b949e">Цель 2 (+5%)</td><td style="text-align:right;color:#2ea043;font-weight:700">${t5:.2f}</td></tr>
            <tr><td style="color:#8b949e">Стоп (−3%)</td><td style="text-align:right;color:#f85149;font-weight:700">${stop:.2f}</td></tr>
          </table>
        </div>
        <div style="background:#0d1117;border:1px solid #21262d;border-radius:10px;padding:14px">
          <div style="color:#8b949e;font-size:11px;text-transform:uppercase;letter-spacing:0.5px">Техническое состояние (пт)</div>
          <table style="width:100%;font-size:13px;margin-top:6px">
            <tr><td style="color:#8b949e">RSI(14)</td><td style="text-align:right;color:#e6edf3;font-weight:700">{num(v["rsi"])}</td></tr>
            <tr><td style="color:#8b949e">Объём vs 20д</td><td style="text-align:right;color:#d29922;font-weight:700">{num(v["volr"])}×</td></tr>
            <tr><td style="color:#8b949e">Позиция закрытия</td><td style="text-align:right;color:#e6edf3;font-weight:700">{v["pos"]:.0%} дня</td></tr>
            <tr><td style="color:#8b949e">vs VWAP пятницы</td><td style="text-align:right;color:#e6edf3;font-weight:700">{pct(v["vwap"])}</td></tr>
            <tr><td style="color:#8b949e">vs SMA50 / SMA200</td><td style="text-align:right;color:#e6edf3;font-weight:700">{pct(v["vs50"],0)} / {pct(v["vs200"],0)}</td></tr>
            <tr><td style="color:#8b949e">От 52н. макс.</td><td style="text-align:right;color:#e6edf3;font-weight:700">{pct(v["dist52"])}</td></tr>
            <tr><td style="color:#8b949e">Волат. ATR(14)</td><td style="text-align:right;color:#e6edf3;font-weight:700">{pct(v["atr"])}</td></tr>
          </table>
        </div>
        <div style="background:#0d1117;border:1px solid #21262d;border-radius:10px;padding:14px">
          <div style="color:#8b949e;font-size:11px;text-transform:uppercase;letter-spacing:0.5px">Фундаментал</div>
          <table style="width:100%;font-size:13px;margin-top:6px">
            <tr><td style="color:#8b949e">Капитализация</td><td style="text-align:right;color:#e6edf3;font-weight:700">{money(v["mcap"])}</td></tr>
            <tr><td style="color:#8b949e">Forward P/E</td><td style="text-align:right;color:#e6edf3;font-weight:700">{num(v["pe_fwd"])}</td></tr>
            <tr><td style="color:#8b949e">Рост выручки (г/г)</td><td style="text-align:right;color:#2ea043;font-weight:700">{pct(v["rev_g"])}</td></tr>
            <tr><td style="color:#8b949e">Валовая маржа</td><td style="text-align:right;color:#e6edf3;font-weight:700">{pct(v["gm"])}</td></tr>
            <tr><td style="color:#8b949e">Чистая маржа</td><td style="text-align:right;color:#e6edf3;font-weight:700">{pct(v["pm"])}</td></tr>
            <tr><td style="color:#8b949e">Рекомендация</td><td style="text-align:right;color:#58a6ff;font-weight:700">{rec_ru}</td></tr>
            <tr><td style="color:#8b949e">Аналитиков</td><td style="text-align:right;color:#e6edf3;font-weight:700">{v["n_analysts"] or "—"}</td></tr>
            <tr><td style="color:#8b949e">Сред. таргет</td><td style="text-align:right;color:#e6edf3;font-weight:700">${num(v["target"])} ({pct(v["target"]/v["close"]-1,0)} к цене)</td></tr>
          </table>
        </div>
      </div>

      <div style="background:#0d1117;border:1px solid #21262d;border-radius:10px;padding:14px;margin-top:14px">
        <div style="color:#58a6ff;font-size:13px;font-weight:700;margin-bottom:6px">📰 Состояние и драйверы</div>
        <div style="color:#c9d1d9;font-size:13.5px;line-height:1.55">{n["story"]}</div>
      </div>

      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:10px;margin-top:12px">
        <div style="background:#0d2818;border:1px solid #238636;border-radius:10px;padding:12px">
          <div style="color:#2ea043;font-size:12px;font-weight:700">🎯 Базовый сценарий</div>
          <div style="color:#c9d1d9;font-size:12.5px;margin-top:4px;line-height:1.5">{n["base"]}</div>
        </div>
        <div style="background:#0d2818;border:1px solid #238636;border-radius:10px;padding:12px">
          <div style="color:#56d364;font-size:12px;font-weight:700">🚀 Бычий сценарий</div>
          <div style="color:#c9d1d9;font-size:12.5px;margin-top:4px;line-height:1.5">{n["bull"]}</div>
        </div>
        <div style="background:#2d1415;border:1px solid #da3633;border-radius:10px;padding:12px">
          <div style="color:#f85149;font-size:12px;font-weight:700">⚠️ Медвежий сценарий</div>
          <div style="color:#c9d1d9;font-size:12.5px;margin-top:4px;line-height:1.5">{n["bear"]}</div>
        </div>
      </div>

      <div style="margin-top:14px">{svg_candles(t)}</div>
    </div>"""

# top-10 table
top10 = scan.head(10).copy()
rows_html = ""
for i, (_, r) in enumerate(top10.iterrows(), 1):
    hl = "background:#12261a;" if r["ticker"] in PICKS else ""
    rows_html += f"""<tr style="{hl}">
      <td style="padding:8px 10px;color:#8b949e">{i}</td>
      <td style="padding:8px 10px;font-weight:700;color:#e6edf3">{r["ticker"]}</td>
      <td style="padding:8px 10px;color:#e6edf3;text-align:right">${r["friday_close"]:.2f}</td>
      <td style="padding:8px 10px;color:#56d364;text-align:right;font-weight:700">{r["prob"]:.3f}</td>
      <td style="padding:8px 10px;color:#2ea043;text-align:right">{r["hit"]:.0%}</td>
      <td style="padding:8px 10px;color:#e6edf3;text-align:right">{pct(r["avg_best"])}</td>
      <td style="padding:8px 10px;color:{'#f85149' if r['ret_1']<0 else '#2ea043'};text-align:right">{pct(r["ret_1"])}</td>
      <td style="padding:8px 10px;color:#e6edf3;text-align:right">{num(r["rsi14"])}</td>
      <td style="padding:8px 10px;color:#d29922;text-align:right">{num(r["vol_ratio"])}×</td>
      <td style="padding:8px 10px;color:#e6edf3;text-align:right">{r["friday_close_pos"]:.0%}</td>
    </tr>"""

html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>EOD Momentum Scanner — NASDAQ · сигнал 28.08.2026</title>
</head>
<body style="margin:0;background:#0d1117;color:#e6edf3;font-family:'Segoe UI',Roboto,Helvetica,Arial,sans-serif">
<div style="max-width:1080px;margin:0 auto;padding:28px 18px 60px">

  <div style="display:flex;flex-wrap:wrap;justify-content:space-between;align-items:flex-end;gap:12px;border-bottom:1px solid #30363d;padding-bottom:18px">
    <div>
      <div style="color:#58a6ff;font-size:12px;font-weight:600;letter-spacing:1.2px;text-transform:uppercase">Algotrading · NASDAQ</div>
      <h1 style="margin:6px 0 2px;font-size:30px;font-weight:800">EOD Momentum Scanner</h1>
      <div style="color:#8b949e;font-size:14px">Покупка на закрытии дня → цель <b style="color:#e6edf3">+2…+5%</b> за 24–48 часов</div>
    </div>
    <div style="text-align:right">
      <div style="background:#161b22;border:1px solid #30363d;border-radius:10px;padding:10px 16px;font-size:13px">
        <div style="color:#8b949e">Сигнал от</div>
        <div style="font-size:16px;font-weight:700;color:#e6edf3">пт 28.08.2026 (закрытие)</div>
        <div style="color:#8b949e;font-size:12px;margin-top:2px">горизонт: пн 31.08 → вт 01.09</div>
      </div>
    </div>
  </div>

  <div style="background:#1c2a12;border:1px solid #238636;border-radius:12px;padding:14px 18px;margin:18px 0;font-size:13.5px;color:#c9d1d9;line-height:1.6">
    <b style="color:#56d364">Рекомендация на эту неделю:</b> в приоритете <b>MRVL</b> и <b>IREN</b> — обе закрыли пятницу с сильной перепроданностью
    после публикации отчётов (−10% и −12,5%), обе в топе сканера по вероятности отскока ≥2% в течение 1–2 сессий, обе с подтверждённым
    фундаментальным драйвером (AI-чипы Google/Amazon у Marvell; AI-облако Microsoft/Nvidia у IREN).
    Скор MRVL — 0,509, IREN — 0,516 (медиана всего рынка — 0,34).
  </div>

  {cards_html}

  <div style="background:#161b22;border:1px solid #30363d;border-radius:14px;padding:22px;margin-top:28px">
    <h2 style="margin:0 0 14px;font-size:20px">Полный рейтинг сканера (топ-10 из 60)</h2>
    <div style="overflow-x:auto">
    <table style="border-collapse:collapse;width:100%;font-size:13px;min-width:760px">
      <thead>
        <tr style="color:#8b949e;text-align:left;border-bottom:1px solid #30363d">
          <th style="padding:8px 10px">#</th><th style="padding:8px 10px">Тикер</th>
          <th style="padding:8px 10px;text-align:right">Цена пт</th>
          <th style="padding:8px 10px;text-align:right">Скор</th>
          <th style="padding:8px 10px;text-align:right">P(≥2%)</th>
          <th style="padding:8px 10px;text-align:right">Ср.лучшее</th>
          <th style="padding:8px 10px;text-align:right">Пт (день)</th>
          <th style="padding:8px 10px;text-align:right">RSI</th>
          <th style="padding:8px 10px;text-align:right">Объём</th>
          <th style="padding:8px 10px;text-align:right">Позиция</th>
        </tr>
      </thead>
      <tbody>{rows_html}</tbody>
    </table>
    </div>
    <div style="color:#8b949e;font-size:12px;margin-top:10px">Зелёная подсветка — выбранные фавориты. «Позиция» — где акция закрылась относительно дневного диапазона (0% = минимум дня, 100% = максимум).</div>
  </div>

  <div style="background:#161b22;border:1px solid #30363d;border-radius:14px;padding:22px;margin-top:28px">
    <h2 style="margin:0 0 8px;font-size:20px">Проверка стратегии (бэктест, вне выборки)</h2>
    <div style="color:#8b949e;font-size:13px;margin-bottom:14px">Walk-forward: модель обучается на прошлом, тестируется на следующем месяце. 11 месяцев вне выборки (окт 2025 – авг 2026), ~1500 акций NASDAQ.</div>
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin-bottom:16px">
      <div style="background:#0d1117;border:1px solid #21262d;border-radius:10px;padding:14px;text-align:center">
        <div style="color:#8b949e;font-size:11px;text-transform:uppercase">Попадание ≥2% за 48ч</div>
        <div style="font-size:26px;font-weight:800;color:#2ea043">48,8%</div>
        <div style="color:#8b949e;font-size:12px">база рынка: 34,4%</div>
      </div>
      <div style="background:#0d1117;border:1px solid #21262d;border-radius:10px;padding:14px;text-align:center">
        <div style="color:#8b949e;font-size:11px;text-transform:uppercase">Среднее лучшее движение</div>
        <div style="font-size:26px;font-weight:800;color:#2ea043">+2,9%</div>
        <div style="color:#8b949e;font-size:12px">база рынка: +1,4%</div>
      </div>
      <div style="background:#0d1117;border:1px solid #21262d;border-radius:10px;padding:14px;text-align:center">
        <div style="color:#8b949e;font-size:11px;text-transform:uppercase">Средний результат 2-го дня</div>
        <div style="font-size:26px;font-weight:800;color:#56d364">+0,9%</div>
        <div style="color:#8b949e;font-size:12px">база рынка: +0,3%</div>
      </div>
      <div style="background:#0d1117;border:1px solid #21262d;border-radius:10px;padding:14px;text-align:center">
        <div style="color:#8b949e;font-size:11px;text-transform:uppercase">Худший случай (средний)</div>
        <div style="font-size:26px;font-weight:800;color:#f85149">−1,5%</div>
        <div style="color:#8b949e;font-size:12px">стоп −3% защищает</div>
      </div>
    </div>
    <div style="color:#c9d1d9;font-size:13px;margin:10px 0 6px">Точность стратегии по месяцам (зелёный — стратегия, серый — база рынка):</div>
    {svg_monthly()}
    <div style="color:#c9d1d9;font-size:13px;line-height:1.6;margin-top:12px">
      Стратегия опережала базу рынка <b style="color:#2ea043">во все 11 месяцев</b> вне выборки. Результат — на акциях, отобранных
      по скору модели (топ-10% в день). Калибровка показывает: при скоре ~0,51 реальная частота роста ≥2% за 48ч — 57%.
    </div>
  </div>

  <div style="background:#161b22;border:1px solid #30363d;border-radius:14px;padding:22px;margin-top:28px">
    <h2 style="margin:0 0 12px;font-size:20px">Как работает сканер</h2>
    <ol style="color:#c9d1d9;font-size:13.5px;line-height:1.7;padding-left:20px;margin:0">
      <li><b>Юниверс:</b> 1500+ ликвидных акций NASDAQ (цена ≥ $5, дневной оборот ≥ $5 млн).</li>
      <li><b>Признаки на конец дня (24 шт.):</b> моментум 1/2/3/5/10/21 день, свечная геометрия (позиция закрытия в диапазоне, тени, тело), гэпы, RSI(14), положение к SMA50/SMA200, тренд EMA20/50, волатильность ATR/ADR, отношение объёма к 20-дневному, расстояние до 52-недельных экстремумов, серия дней, ликвидность.</li>
      <li><b>Модель:</b> градиентный бустинг (sklearn HistGradientBoosting), обучается на 2 годах истории (~450 тыс. примеров). Метка: «выросла ≥2% хотя бы в один из 2 следующих дней».</li>
      <li><b>Отбор:</b> топ по скору с проверкой ликвидности; для топ-60 дополнительно реконструируется пятничная свеча из внутридневных баров (закрытие, VWAP, позиция в диапазоне, последний час) и добавляется в признаки.</li>
      <li><b>Выход:</b> 1–2 фаворита с полным разбором + рейтинг всех кандидатов.</li>
    </ol>
  </div>

  <div style="background:#2d1415;border:1px solid #da3633;border-radius:12px;padding:14px 18px;margin-top:28px;font-size:12.5px;color:#e6b9b9;line-height:1.6">
    ⚠️ <b>Дисклеймер.</b> Никакой алгоритм не может <i>гарантировать</i> рост на 2–5% за 24–48 часов — рынок стохастичен. Приведённые вероятности
    (скор, попадание, ожидаемое движение) — статистические оценки на исторических данных, они ухудшаются при смене рыночного режима.
    Это исследовательский инструмент, не индивидуальная инвестиционная рекомендация. Объём позиции — не более 1–2% капитала на сделку,
    обязательный стоп −3%. Историческая точность 48–57% означает, что почти каждая вторая сделка не достигает цели — управление риском обязано это переживать.
  </div>

  <div style="color:#8b949e;font-size:12px;margin-top:20px;text-align:center">
    EOD Momentum Scanner · данные: Nasdaq.com screener + Yahoo Finance · генерация: {FRIDAY} · следующее обновление: после закрытия пн 31.08
  </div>
</div>
</body>
</html>"""

os.makedirs(OUT, exist_ok=True)
with open(os.path.join(OUT, "dashboard.html"), "w", encoding="utf-8") as f:
    f.write(html)
print("dashboard written:", os.path.join(OUT, "dashboard.html"), len(html), "bytes")
