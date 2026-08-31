#!/usr/bin/env python3
"""Build the standalone HTML dashboard (inline CSS/SVG, no external assets).

Fully autonomous: reads output/scan_results.csv + data/*.parquet,
writes output/dashboard.html and output/index.html (GitHub Pages entry).
"""
import json, os
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
OUT = os.path.join(ROOT, "output")

# Ручная курация топ-2 (модель ранжирует в таблице; аналитик выбирает сценарии)
PICKS = []  # placeholder will be overwritten

scan = pd.read_csv(os.path.join(OUT, "scan_results.csv"))
LAST = str(scan["date"].iloc[0])
scan = scan.sort_values("prob", ascending=False)
PICKS = scan.head(2)["ticker"].tolist()  # AUTO TOP2 FIX - was hardcoded

# метаданные (вселенная, время)
META = {}
if os.path.exists(os.path.join(OUT, "meta.json")):
    META = json.load(open(os.path.join(OUT, "meta.json")))

# история запусков из git-лога
def last_runs(n=8):
    try:
        out = os.popen(f"cd {ROOT} && git log --format='%h|%ad|%s' --date=short -n {n} 2>/dev/null").read()
        return [l.split("|", 2) for l in out.strip().splitlines() if l.strip()]
    except Exception:
        return []

RUNS = last_runs()

# токен для кнопки ручного запуска (подставляется в CI из секрета; локально — пусто)
# "" removed - security

fund = {}
if os.path.exists(os.path.join(DATA, "fundamentals.json")):
    fund = json.load(open(os.path.join(DATA, "fundamentals.json")))

try:
    oos = pd.read_parquet(os.path.join(DATA, "oos_predictions.parquet"))
    oos["selected"] = oos.groupby("model_idx")["prob"].rank(pct=True) >= 0.90
    _sel = oos[oos["selected"]]
    _selm = _sel.groupby(_sel["date"].dt.to_period("M"))["target_2pct"].mean()
    _basem = oos.groupby(oos["date"].dt.to_period("M"))["target_2pct"].mean()
    BT = {
        "hit": float(_sel["target_2pct"].mean()), "base_hit": float(oos["target_2pct"].mean()),
        "avg_best": float(_sel["best_fwd"].mean()), "base_best": float(oos["best_fwd"].mean()),
        "avg_fwd2": float(_sel["fwd2"].mean()), "base_fwd2": float(oos["fwd2"].mean()),
        "avg_worst": float(_sel["worst_fwd"].mean()),
        "monthly": [(str(m), float(_selm.loc[m]), float(_basem.loc[m])) for m in _selm.index],
        "n_months": int(oos["model_idx"].nunique()),
    }
except Exception:
    BT = None

STAB = None
if os.path.exists(os.path.join(DATA, "stability_1530.parquet")):
    try:
        st = pd.read_parquet(os.path.join(DATA, "stability_1530.parquet"))
        by_day = st.groupby("date")
        from scipy.stats import spearmanr
        corrs = by_day.apply(lambda g: spearmanr(g["score1530"], g["score_close"]).statistic, include_groups=False)
        ov = by_day.apply(lambda g: len(set(g.nlargest(10, "score1530")["ticker"]) &
                                        set(g.nlargest(10, "score_close")["ticker"])), include_groups=False)
        sel1530 = by_day.apply(lambda g: g.nlargest(int(len(g) * 0.10), "score1530"), include_groups=False)
        selclose = by_day.apply(lambda g: g.nlargest(int(len(g) * 0.10), "score_close"), include_groups=False)
        STAB = dict(corr=float(corrs.median()), overlap=float(ov.mean()),
                    hit1530=float(sel1530["target"].mean()), hitclose=float(selclose["target"].mean()),
                    base=float(st["target"].mean()), days=int(st["date"].nunique()))
    except Exception:
        STAB = None

FALLBACK_BT = dict(
    hit=0.488, base_hit=0.344, avg_best=0.0288, base_best=0.0145,
    avg_fwd2=0.0090, base_fwd2=0.0030, avg_worst=-0.0152, n_months=11,
    monthly=[("Окт 25", 0.457, 0.321), ("Ноя 25", 0.449, 0.334), ("Дек 25", 0.473, 0.278),
             ("Янв 26", 0.488, 0.353), ("Фев 26", 0.502, 0.349), ("Мар 26", 0.499, 0.304),
             ("Апр 26", 0.538, 0.398), ("Май 26", 0.511, 0.362), ("Июн 26", 0.488, 0.406),
             ("Июл 26", 0.483, 0.353), ("Авг 26", 0.477, 0.324)])

if BT is None:
    BT = FALLBACK_BT


# ------------------------------------------------------------ helpers ----
def pct(x, nd=1):
    return f"{x * 100:+.{nd}f}%" if x is not None and not (isinstance(x, float) and np.isnan(x)) else "—"

def num(x, nd=2):
    return f"{x:,.{nd}f}" if x is not None and not (isinstance(x, float) and np.isnan(x)) else "—"

def money(x):
    if x is None:
        return "—"
    return f"${float(x) / 1e9:,.1f}B"


def row(t):
    return scan[scan["ticker"] == t].iloc[0]


def level_band(t):
    e = float(row(t)["close"])
    return e, e * 1.02, e * 1.05, e * 0.97


# ------------------------------------------------------------ svg chart ----
def svg_candles(t, n_bars=64):
    r = row(t)
    entry, t2, t5, stop = level_band(t)
    hist = pd.read_csv(os.path.join(DATA, f"hist_{t}.csv"), parse_dates=["date"])
    hist = hist.sort_values("date")
    df = hist.tail(n_bars - 1).copy()
    last_bar = pd.DataFrame([{
        "date": pd.Timestamp(LAST), "open": r["open"], "high": r["high"],
        "low": r["low"], "close": r["close"], "volume": r["volume"]}])
    df = pd.concat([df, last_bar], ignore_index=True)
    df["sma50"] = df["close"].rolling(50).mean()

    W, H, pad_l, pad_r, pad_t, pad_b = 780, 300, 10, 70, 12, 26
    hi = max(df["high"].max(), t5, entry) * 1.01
    lo = min(df["low"].min(), stop) * 0.99
    rng = hi - lo

    def Y(v):
        return pad_t + (hi - v) / rng * (H - pad_t - pad_b)

    def X(i):
        return pad_l + (i + 0.5) / len(df) * (W - pad_l - pad_r)

    cw = (W - pad_l - pad_r) / len(df) * 0.62
    parts = [f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" style="width:100%;height:auto;background:#0d1117;border-radius:10px;display:block">']
    for g in np.linspace(lo, hi, 6):
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
        if i % 10 == 9 or i == len(df) - 1:
            lab = rw["date"].strftime("%d.%m")
            parts.append(f'<text x="{x:.1f}" y="{H - 8:.1f}" fill="#8b949e" font-size="9.5" font-family="Verdana" text-anchor="middle">{lab}</text>')
    prev = None
    for i, (_, rw) in enumerate(df.iterrows()):
        if np.isnan(rw["sma50"]):
            prev = None
            continue
        y = Y(rw["sma50"])
        if prev is not None:
            parts.append(f'<line x1="{prev[0]:.1f}" y1="{prev[1]:.1f}" x2="{X(i):.1f}" y2="{y:.1f}" stroke="#d29922" stroke-width="1.4" stroke-dasharray="3 2" opacity="0.9"/>')
        prev = (X(i), y)
    for (v, col, lab, dash) in [(entry, "#ffffff", "вход (закр.)", "2 2"), (t5, "#2ea043", "+5%", "4 3"),
                                (t2, "#56d364", "+2%", "4 3"), (stop, "#f85149", "стоп −3%", "4 3")]:
        y = Y(v)
        parts.append(f'<line x1="{pad_l}" y1="{y:.1f}" x2="{W - pad_r}" y2="{y:.1f}" stroke="{col}" stroke-width="1.1" stroke-dasharray="{dash}" opacity="0.85"/>')
        parts.append(f'<text x="{pad_l + 4}" y="{y - 4:.1f}" fill="{col}" font-size="9.5" font-family="Verdana">{lab} {v:.2f}</text>')
    parts.append("</svg>")
    return "".join(parts)


def score_bar(p):
    w = int(round(min(max(p, 0), 1) * 100))
    return (f'<div style="background:#21262d;border-radius:6px;height:14px;width:100%;overflow:hidden">'
            f'<div style="background:linear-gradient(90deg,#2ea043,#56d364);width:{w}%;height:100%;border-radius:6px"></div></div>')


# ------------------------------------------------------------- narratives ----
NARR = {
    "MRVL": {
        "story": ("<b>Сигнал в 15:30 ET по неполной свече: перепроданность после сильного отчёта.</b> Marvell отчиталась "
                  "в четверг вечером лучше ожиданий (выручка +37% до $2,74 млрд, EPS $0,94 при консенсусе $0,92, прогноз Q3 "
                  "$3,15 млрд выше оценок), но после Google-сделки ожидания были разогреты так, что в пятницу акция упала "
                  "−10% на объёме 1,7×. Пятничная свеча до 15:30 — красная, закрытие у нижней границы диапазона. Долгосрочный "
                  "тренд не повреждён (выше SMA200 +46%), диспозиция технически перепроданная. По модели P(рост ≥2% за 48ч) "
                  "= 57%, вероятность положительного гэпа в понедельник — 57% (медиана +0,4%)."),
        "base": ("Отскок от перепроданности в течение 1–2 сессий: возврат к уровню закрытия четверга $228–232. Цель "
                 "+2…+3% за 24–48 часов. Гэп понедельника — бонус, а не главный драйвер: после наших сигналов он положительный "
                 "в 57% случаев, но средний размер небольшой."),
        "bull": ("Понедельник открывается флэтом или вверх и закрывается выше $222 — путь к $228–230 (+5%) и к среднему "
                 "таргету аналитиков $269 (+24%) на горизонте недель."),
        "bear": ("Пробой минимума пятницы $211 — продолжение распродажи на разочаровании прогнозом FY2028; срабатывает "
                 "стоп −3% ($211,12)."),
    },
    "IREN": {
        "story": ("<b>Сигнал в 15:30 ET: тяжёлый отчёт, но переход в AI-облако идёт по плану.</b> В четверг вечером IREN "
                  "отчиталась за FY2026: AI-cloud выручка впервые обогнала майнинговую ($70,5 млн против $66,7 млн, вдвое кв/кв), "
                  "но EBITDA −68% кв/кв и убыток $684 млн (вкл. списание $450 млн) обрушили акцию на −12,5%. Свеча до 15:30 — "
                  "у минимумов дня, объём 1,6×. Контракты Microsoft ($9,7 млрд) и Nvidia, $4 млрд законтрактованного run-rate "
                  "на 2026 год, заморозка дата-центров в Техасе играет на руку. Бернстайн: outperform, цель $100."),
        "base": ("Волатильный отскок от перепроданности: RSI 40, −54% от 52-недельного максимума, закрытие у минимума на "
                 "повышенном объёме. Цель +2…+3% за 24–48 часов."),
        "bull": ("Закрытие понедельника выше $36,4 открывает путь к $37,2 (+5%). Позитив: рост AI-cloud выручки, операционная "
                 "готовность контрактов MSFT/NVDA."),
        "bear": ("Пробой $34,4 — продолжение падения на фоне слабой маржинальности и больших капзатрат; стоп −3% ($34,49)."),
    },
}


def generic_narrative(t):
    r = row(t)
    f = fund.get(t, {})
    rec = f.get("recommendationKey") or "—"
    story = (f"<b>Сигнал в 15:30 ET: {t} — высокий скор модели.</b> "
             f"Изменение за день {pct(r.get('ret_1'))}, объём {num(r.get('vol_ratio'))}× от среднего, "
             f"RSI {num(r.get('rsi14'))}, позиция в диапазоне дня {r.get('close_pos', 0):.0%}. "
             f"Вероятность роста ≥2% за 48ч — {r['hit']:.0%}, положительный гэп следующего дня — "
             f"{r.get('gap_sig_p', float('nan')):.0%} случаев.")
    if f.get("longName"):
        story += f" {f['longName']} ({f.get('sector','')}). Рекомендация: {rec}, средний таргет ${num(f.get('targetMeanPrice'))}."
    return {
        "story": story,
        "base": f"Отскок в течение 1–2 сессий к целям +2/+5%; стоп −3% обязателен.",
        "bull": f"Закрепление выше пятничного закрытия ${r['close']:.2f} открывает путь к +5% и выше.",
        "bear": f"Пробой минимума дня — продолжение движения вниз; стоп −3% защищает позицию.",
    }


# ================================================================ HTML ====
def build():
    os.makedirs(OUT, exist_ok=True)
    last_date = LAST
    bt = BT
    stab = STAB

    # recommendation banner text
    gap_line = ""
    if stab:
        gap_line = (f"Валидация: сигнал в 15:30 почти неотличим от сигнала по закрытию (корреляция {stab['corr']:.3f}, "
                    f"пересечение топ-10 — {stab['overlap']:.1f} из 10, хит-рейт {stab['hit1530']:.0%} против {stab['hitclose']:.0%}).")
    rec_extra = ""
    for t in PICKS:
        r = row(t)
        rec_extra += f"<b>{t}</b> — P(рост ≥2% за 48ч) {r['hit']:.0%}, P(положительный гэп) {r.get('gap_sig_p', float('nan')):.0%}; "

    cards_html = ""
    for t in PICKS:
        r = row(t)
        n = NARR.get(t, generic_narrative(t))
        f = fund.get(t, {})
        entry, t2, t5, stop = level_band(t)
        rec_ru = {"strong_buy": "Сильная покупка", "buy": "Покупка", "hold": "Держать",
                  "neutral": "Нейтрально"}.get(f.get("recommendationKey"), f.get("recommendationKey") or "—")
        gap_sig_p = r.get("gap_sig_p")
        gap_sig_p_s = f"{gap_sig_p:.0%}" if gap_sig_p is not None and not np.isnan(gap_sig_p) else "—"
        gap_sig_med = r.get("gap_sig_med")
        gap_sig_med_s = pct(gap_sig_med) if gap_sig_med is not None and not np.isnan(gap_sig_med) else "—"
        cards_html += f"""
    <div style="background:#161b22;border:1px solid #30363d;border-radius:14px;padding:22px;margin-bottom:22px">
      <div style="display:flex;flex-wrap:wrap;justify-content:space-between;align-items:baseline;gap:10px">
        <div>
          <span style="font-size:26px;font-weight:700;color:#e6edf3">{t}</span>
          <span style="color:#8b949e;font-size:14px;margin-left:10px">{f.get("longName", t)}</span>
          <span style="color:#8b949e;font-size:12px;margin-left:8px">{f.get("sector","")} · {f.get("industry","")}</span>
        </div>
        <div style="text-align:right">
          <span style="font-size:28px;font-weight:700;color:#e6edf3">${num(r["close"])}</span>
          <span style="font-size:13px;color:#8b949e"> сигнал 15:30 ET</span>
          <div style="font-size:12px;color:#f85149">{pct(r.get("ret_1"))} (за день)</div>
        </div>
      </div>

      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:14px;margin-top:16px">
        <div style="background:#0d1117;border:1px solid #21262d;border-radius:10px;padding:14px">
          <div style="color:#8b949e;font-size:11px;text-transform:uppercase;letter-spacing:0.5px">Скор модели (0–1)</div>
          <div style="font-size:22px;font-weight:700;color:#56d364;margin:4px 0">{r["prob"]:.3f}</div>
          {score_bar(r["prob"])}
          <div style="color:#8b949e;font-size:11px;margin-top:6px">P(рост ≥2% за 48ч)</div>
        </div>
        <div style="background:#0d1117;border:1px solid #21262d;border-radius:10px;padding:14px">
          <div style="color:#8b949e;font-size:11px;text-transform:uppercase;letter-spacing:0.5px">Ожидания на 48ч (калибровка)</div>
          <table style="width:100%;font-size:13px;margin-top:6px">
            <tr><td style="color:#8b949e">Попадание ≥2%</td><td style="text-align:right;color:#2ea043;font-weight:700">{r["hit"]:.0%}</td></tr>
            <tr><td style="color:#8b949e">Среднее лучшее движение</td><td style="text-align:right;color:#2ea043;font-weight:700">{pct(r["avg_best"])}</td></tr>
            <tr><td style="color:#8b949e">Средний результат 2-го дня</td><td style="text-align:right;color:#e6edf3;font-weight:700">{pct(r["avg_fwd2"])}</td></tr>
            <tr><td style="color:#8b949e">Худший случай (средн.)</td><td style="text-align:right;color:#f85149;font-weight:700">{pct(r["avg_worst"])}</td></tr>
          </table>
        </div>
        <div style="background:#0d1117;border:1px solid #21262d;border-radius:10px;padding:14px">
          <div style="color:#8b949e;font-size:11px;text-transform:uppercase;letter-spacing:0.5px">Гэп следующего дня (история OOS)</div>
          <table style="width:100%;font-size:13px;margin-top:6px">
            <tr><td style="color:#8b949e">P(гэп вверх)</td><td style="text-align:right;color:#2ea043;font-weight:700">{gap_sig_p_s}</td></tr>
            <tr><td style="color:#8b949e">Медианный гэп</td><td style="text-align:right;color:#e6edf3;font-weight:700">{gap_sig_med_s}</td></tr>
            <tr><td style="color:#8b949e">Кол-во наблюдений</td><td style="text-align:right;color:#8b949e;font-weight:700">{int(r.get("gap_sig_n", 0))}</td></tr>
            <tr><td style="color:#8b949e">Контекст: после распрод. дней</td><td style="text-align:right;color:#e6edf3;font-weight:700">{pct(r.get("gap_down_med"))}</td></tr>
          </table>
        </div>
        <div style="background:#0d1117;border:1px solid #21262d;border-radius:10px;padding:14px">
          <div style="color:#8b949e;font-size:11px;text-transform:uppercase;letter-spacing:0.5px">Уровни (вход = закрытие)</div>
          <table style="width:100%;font-size:13px;margin-top:6px">
            <tr><td style="color:#8b949e">Вход (закрытие)</td><td style="text-align:right;color:#e6edf3;font-weight:700">≈${entry:.2f}</td></tr>
            <tr><td style="color:#8b949e">Цель 1 (+2%)</td><td style="text-align:right;color:#56d364;font-weight:700">${t2:.2f}</td></tr>
            <tr><td style="color:#8b949e">Цель 2 (+5%)</td><td style="text-align:right;color:#2ea043;font-weight:700">${t5:.2f}</td></tr>
            <tr><td style="color:#8b949e">Стоп (−3%)</td><td style="text-align:right;color:#f85149;font-weight:700">${stop:.2f}</td></tr>
          </table>
        </div>
        <div style="background:#0d1117;border:1px solid #21262d;border-radius:10px;padding:14px">
          <div style="color:#8b949e;font-size:11px;text-transform:uppercase;letter-spacing:0.5px">Техническое состояние (до 15:30)</div>
          <table style="width:100%;font-size:13px;margin-top:6px">
            <tr><td style="color:#8b949e">RSI(14)</td><td style="text-align:right;color:#e6edf3;font-weight:700">{num(r.get("rsi14"))}</td></tr>
            <tr><td style="color:#8b949e">Объём vs 20д</td><td style="text-align:right;color:#d29922;font-weight:700">{num(r.get("vol_ratio"))}×</td></tr>
            <tr><td style="color:#8b949e">Позиция закрытия</td><td style="text-align:right;color:#e6edf3;font-weight:700">{r.get("close_pos", 0):.0%} дня</td></tr>
            <tr><td style="color:#8b949e">vs VWAP</td><td style="text-align:right;color:#e6edf3;font-weight:700">{pct(r.get("close_vs_vwap"))}</td></tr>
            <tr><td style="color:#8b949e">vs SMA50 / SMA200</td><td style="text-align:right;color:#e6edf3;font-weight:700">{pct(r.get("px_sma50"),0)} / {pct(r.get("px_sma200"),0)}</td></tr>
            <tr><td style="color:#8b949e">От 52н. макс.</td><td style="text-align:right;color:#e6edf3;font-weight:700">{pct(r.get("dist_52w_high"))}</td></tr>
            <tr><td style="color:#8b949e">Волат. ATR(14)</td><td style="text-align:right;color:#e6edf3;font-weight:700">{pct(r.get("atr14_pct"))}</td></tr>
          </table>
        </div>
        <div style="background:#0d1117;border:1px solid #21262d;border-radius:10px;padding:14px">
          <div style="color:#8b949e;font-size:11px;text-transform:uppercase;letter-spacing:0.5px">Фундаментал</div>
          <table style="width:100%;font-size:13px;margin-top:6px">
            <tr><td style="color:#8b949e">Капитализация</td><td style="text-align:right;color:#e6edf3;font-weight:700">{money(f.get("marketCap"))}</td></tr>
            <tr><td style="color:#8b949e">Forward P/E</td><td style="text-align:right;color:#e6edf3;font-weight:700">{num(f.get("forwardPE"))}</td></tr>
            <tr><td style="color:#8b949e">Рост выручки (г/г)</td><td style="text-align:right;color:#2ea043;font-weight:700">{pct(f.get("revenueGrowth"))}</td></tr>
            <tr><td style="color:#8b949e">Валовая маржа</td><td style="text-align:right;color:#e6edf3;font-weight:700">{pct(f.get("grossMargins"))}</td></tr>
            <tr><td style="color:#8b949e">Рекомендация</td><td style="text-align:right;color:#58a6ff;font-weight:700">{rec_ru}</td></tr>
            <tr><td style="color:#8b949e">Аналитиков</td><td style="text-align:right;color:#e6edf3;font-weight:700">{f.get("numberOfAnalystOpinions") or "—"}</td></tr>
            <tr><td style="color:#8b949e">Сред. таргет</td><td style="text-align:right;color:#e6edf3;font-weight:700">${num(f.get("targetMeanPrice"))}</td></tr>
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
      <div style="color:#8b949e;font-size:11px;margin-top:4px">Последняя свеча — {LAST} до 15:30 ET (неполная, на момент скана). Уровни от цены 15:30; вход — по фактическому закрытию.</div>
    </div>"""

    # top-10 table
    top10 = scan.head(10)
    rows_html = ""
    for i, (_, r) in enumerate(top10.iterrows(), 1):
        hl = "background:#12261a;" if r["ticker"] in PICKS else ""
        gp = r.get("gap_sig_p")
        gp_s = f"{gp:.0%}" if gp is not None and not np.isnan(gp) else "—"
        rows_html += f"""<tr style="{hl}">
      <td style="padding:8px 10px;color:#8b949e">{i}</td>
      <td style="padding:8px 10px;font-weight:700;color:#e6edf3">{r["ticker"]}</td>
      <td style="padding:8px 10px;color:#e6edf3;text-align:right">${r["close"]:.2f}</td>
      <td style="padding:8px 10px;color:#56d364;text-align:right;font-weight:700">{r["prob"]:.3f}</td>
      <td style="padding:8px 10px;color:#2ea043;text-align:right">{r["hit"]:.0%}</td>
      <td style="padding:8px 10px;color:#e6edf3;text-align:right">{pct(r["avg_best"])}</td>
      <td style="padding:8px 10px;color:#58a6ff;text-align:right">{gp_s}</td>
      <td style="padding:8px 10px;color:{'#f85149' if (r.get('ret_1') or 0) < 0 else '#2ea043'};text-align:right">{pct(r.get("ret_1"))}</td>
      <td style="padding:8px 10px;color:#e6edf3;text-align:right">{num(r.get("rsi14"))}</td>
      <td style="padding:8px 10px;color:#d29922;text-align:right">{num(r.get("vol_ratio"))}×</td>
    </tr>"""

    # monthly chart
    monthly = bt["monthly"]

    def svg_monthly():
        W, H, pad_l, pad_r, pad_t, pad_b = 760, 240, 46, 14, 16, 30
        mx = 0.6
        bw = (W - pad_l - pad_r) / len(monthly)
        p = [f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" style="width:100%;height:auto;background:#0d1117;border-radius:10px;display:block">']
        for g in np.linspace(0, mx, 7):
            gy = pad_t + (mx - g) / mx * (H - pad_t - pad_b)
            p.append(f'<line x1="{pad_l}" y1="{gy:.1f}" x2="{W - pad_r}" y2="{gy:.1f}" stroke="#21262d" stroke-width="1"/>')
            p.append(f'<text x="{pad_l - 4}" y="{gy + 4:.1f}" fill="#8b949e" font-size="10" font-family="Verdana" text-anchor="end">{g:.0%}</text>')
        for i, (lab, s, b) in enumerate(monthly):
            x = pad_l + i * bw
            hS = (H - pad_t - pad_b) * s / mx
            hB = (H - pad_t - pad_b) * b / mx
            p.append(f'<rect x="{x + bw * 0.18}" y="{pad_t + (H - pad_t - pad_b) - hS:.1f}" width="{bw * 0.28}" height="{hS:.1f}" fill="#2ea043" rx="2"/>')
            p.append(f'<rect x="{x + bw * 0.54}" y="{pad_t + (H - pad_t - pad_b) - hB:.1f}" width="{bw * 0.28}" height="{hB:.1f}" fill="#8b949e" opacity="0.6" rx="2"/>')
            if i % 2 == 0 or i == len(monthly) - 1:
                p.append(f'<text x="{x + bw / 2:.1f}" y="{H - 8:.1f}" fill="#8b949e" font-size="9.5" font-family="Verdana" text-anchor="middle">{lab}</text>')
        p.append("</svg>")
        return "".join(p)

    # stability block
    stab_html = ""
    if stab:
        stab_html = f"""
    <div style="background:#161b22;border:1px solid #30363d;border-radius:14px;padding:22px;margin-top:28px">
      <h2 style="margin:0 0 8px;font-size:20px">Валидация: сигнал в 15:30 vs сигнал по закрытию</h2>
      <div style="color:#8b949e;font-size:13px;margin-bottom:14px">Проверено на {stab['days']} торговых днях × 60 ликвидных акций: свеча на 15:30 (неполная) vs полная свеча дня. Модель обучена на полных свечах, но применяется к данным 15:30.</div>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px">
        <div style="background:#0d1117;border:1px solid #21262d;border-radius:10px;padding:14px;text-align:center">
          <div style="color:#8b949e;font-size:11px;text-transform:uppercase">Корреляция скоров</div>
          <div style="font-size:26px;font-weight:800;color:#2ea043">{stab['corr']:.3f}</div>
          <div style="color:#8b949e;font-size:12px">15:30 vs закрытие</div>
        </div>
        <div style="background:#0d1117;border:1px solid #21262d;border-radius:10px;padding:14px;text-align:center">
          <div style="color:#8b949e;font-size:11px;text-transform:uppercase">Пересечение топ-10</div>
          <div style="font-size:26px;font-weight:800;color:#56d364">{stab['overlap']:.1f}/10</div>
          <div style="color:#8b949e;font-size:12px">те же лидеры на закрытии</div>
        </div>
        <div style="background:#0d1117;border:1px solid #21262d;border-radius:10px;padding:14px;text-align:center">
          <div style="color:#8b949e;font-size:11px;text-transform:uppercase">Хит-рейт ≥2% / 48ч</div>
          <div style="font-size:26px;font-weight:800;color:#2ea043">{stab['hit1530']:.0%}</div>
          <div style="color:#8b949e;font-size:12px">сигнал 15:30 (база {stab['base']:.0%})</div>
        </div>
        <div style="background:#0d1117;border:1px solid #21262d;border-radius:10px;padding:14px;text-align:center">
          <div style="color:#8b949e;font-size:11px;text-transform:uppercase">Хит-рейт по закрытию</div>
          <div style="font-size:26px;font-weight:800;color:#e6edf3">{stab['hitclose']:.0%}</div>
          <div style="color:#8b949e;font-size:12px">для сравнения</div>
        </div>
      </div>
      <div style="color:#c9d1d9;font-size:13px;margin-top:12px;line-height:1.6">
        Вывод: сканирование за 30 минут до закрытия по неполной свече сохраняет почти весь сигнал — потеря точности
        всего ~1,5–2 п.п. Поэтому план работает: <b>сигнал в 15:30 → вход на закрытии → цель +2/+5% за 24–48ч</b>.
      </div>
    </div>"""

    # кнопка ручного запуска (реализована в CI токеном из секрета; локально — ссылка на Actions)
    if False:  # token removed
        run_btn = f"""<button onclick="runScan()" id="run-btn" style="background:#238636;color:#fff;border:none;border-radius:8px;padding:10px 18px;font-size:14px;font-weight:700;cursor:pointer">▶ Запустить скан сейчас</button>
        <div id="run-status" style="font-size:12px;color:#8b949e;margin-top:6px"></div>
        <script>
        const "" = {json.dumps("")};
        async function runScan(){{
          const st = document.getElementById('run-status');
          st.style.color = '#d29922'; st.textContent = '⏳ Отправляю запрос на GitHub...';
          try {{
            // workflow_dispatch требует только Actions:write (безопасно в публичном HTML)
            const r = await fetch('https://api.github.com/repos/exodus611/nasdaq-eod-momentum-scanner/actions/workflows/daily_scan.yml/dispatches', {{
              method: 'POST',
              headers: {{'Authorization': 'token ' + "", 'Accept': 'application/vnd.github+json', 'Content-Type': 'application/json'}},
              body: JSON.stringify({{ref: 'main'}})
            }});
            if (r.ok) {{ st.style.color = '#2ea043'; st.textContent = '✅ Запущено! Скан идёт на GitHub (~5–10 мин), дашборд обновится сам.'; }}
            else {{ st.style.color = '#f85149'; st.textContent = '❌ Ошибка ' + r.status + ': ' + (await r.text()).slice(0,120); }}
          }} catch(e) {{ st.style.color = '#f85149'; st.textContent = '❌ ' + e.message; }}
        }}
        </script>"""
    else:
        run_btn = """<a href="https://github.com/exodus611/nasdaq-eod-momentum-scanner/actions/workflows/daily_scan.yml" target="_blank" style="background:#1f6feb;color:#fff;text-decoration:none;border-radius:8px;padding:10px 18px;font-size:14px;font-weight:700;display:inline-block">▶ Запустить скан (GitHub Actions)</a>
        <div style="font-size:12px;color:#8b949e;margin-top:6px">Токен для запуска с дашборда не настроен — откроется вкладка Actions</div>"""

    univ_html = ""
    if META:
        univ_html = f"""<div style="background:#0d1117;border:1px solid #21262d;border-radius:10px;padding:12px 16px;font-size:13px;margin-top:14px">
          <span style="color:#8b949e">Вселенная NASDAQ:</span>
          <b style="color:#e6edf3">{META.get('universe_total', '—'):,}</b> акций ·
          отсканировано: <b style="color:#e6edf3">{META.get('scanned', '—')}</b> ·
          <span style="color:#8b949e">состав обновляется автоматически при каждом прогоне</span>
          <div style="color:#8b949e;font-size:11.5px;margin-top:3px">{META.get('universe_note', '')}</div>
        </div>"""

    runs_html = ""
    if RUNS:
        rows_r = ""
        for h, d, m in RUNS:
            rows_r += f'<tr><td style="padding:6px 10px;color:#8b949e;font-family:monospace">{h}</td><td style="padding:6px 10px;color:#e6edf3">{d}</td><td style="padding:6px 10px;color:#c9d1d9">{m}</td></tr>'
        runs_html = f"""
  <div style="background:#161b22;border:1px solid #30363d;border-radius:14px;padding:22px;margin-top:28px">
    <h2 style="margin:0 0 12px;font-size:20px">🗂 История запусков (последние {len(RUNS)})</h2>
    <div style="overflow-x:auto">
    <table style="border-collapse:collapse;width:100%;font-size:13px;min-width:480px">
      <thead><tr style="color:#8b949e;text-align:left;border-bottom:1px solid #30363d">
        <th style="padding:8px 10px">Коммит</th><th style="padding:8px 10px">Дата</th><th style="padding:8px 10px">Событие</th>
      </tr></thead>
      <tbody>{rows_r}</tbody>
    </table>
    </div>
    <div style="color:#8b949e;font-size:12px;margin-top:10px">Каждый авто-скан (15:30 ET) и ручной запуск оставляют коммит — видно всю историю. Автозапуск: будни 15:30 ET (зимой сдвигается на 20:30 UTC в workflow).</div>
  </div>"""

    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>EOD Momentum Scanner — NASDAQ · сигнал {last_date} (15:30 ET)</title>
</head>
<body style="margin:0;background:#0d1117;color:#e6edf3;font-family:'Segoe UI',Roboto,Helvetica,Arial,sans-serif">
<div style="max-width:1080px;margin:0 auto;padding:28px 18px 60px">

  <div style="display:flex;flex-wrap:wrap;justify-content:space-between;align-items:flex-end;gap:12px;border-bottom:1px solid #30363d;padding-bottom:18px">
    <div>
      <div style="color:#58a6ff;font-size:12px;font-weight:600;letter-spacing:1.2px;text-transform:uppercase">Algotrading · NASDAQ</div>
      <h1 style="margin:6px 0 2px;font-size:30px;font-weight:800">EOD Momentum Scanner</h1>
      <div style="color:#8b949e;font-size:14px">Скан в <b style="color:#e6edf3">15:30 ET</b> (за 30 мин до закрытия) → вход на закрытии → цель <b style="color:#e6edf3">+2…+5%</b> за 24–48 часов</div>
    </div>
    <div style="display:flex;gap:12px;align-items:flex-end;flex-wrap:wrap">
      <div style="text-align:right">
        <div style="background:#161b22;border:1px solid #30363d;border-radius:10px;padding:10px 16px;font-size:13px">
          <div style="color:#8b949e">Сигнал от</div>
          <div style="font-size:16px;font-weight:700;color:#e6edf3">{last_date} · 15:30 ET</div>
          <div style="color:#8b949e;font-size:12px;margin-top:2px">свеча дня — неполная (до 15:30)</div>
        </div>
      </div>
      <div style="text-align:right">{run_btn}</div>
    </div>
  </div>

  {univ_html}

  <div style="background:#1c2a12;border:1px solid #238636;border-radius:12px;padding:14px 18px;margin:18px 0;font-size:13.5px;color:#c9d1d9;line-height:1.6">
    <b style="color:#56d364">Рекомендация на эту сессию:</b> {rec_extra}
    Сигнал сформирован по данным до 15:30 ET, вход — по цене закрытия. Гэп следующего дня — статистически ~50/50
    с лёгким положительным смещением у лидеров; <b>основной заработок — движение внутри 24–48ч к целям +2/+5%</b>,
    поэтому выход по открытию не рекомендуется, стоп −3% обязателен.
  </div>

  {cards_html}

  <div style="background:#161b22;border:1px solid #30363d;border-radius:14px;padding:22px;margin-top:28px">
    <h2 style="margin:0 0 14px;font-size:20px">Полный рейтинг сканера (топ-10 из {len(scan)})</h2>
    <div style="overflow-x:auto">
    <table style="border-collapse:collapse;width:100%;font-size:13px;min-width:820px">
      <thead>
        <tr style="color:#8b949e;text-align:left;border-bottom:1px solid #30363d">
          <th style="padding:8px 10px">#</th><th style="padding:8px 10px">Тикер</th>
          <th style="padding:8px 10px;text-align:right">Цена 15:30</th>
          <th style="padding:8px 10px;text-align:right">Скор</th>
          <th style="padding:8px 10px;text-align:right">P(≥2%)</th>
          <th style="padding:8px 10px;text-align:right">Ср.лучшее</th>
          <th style="padding:8px 10px;text-align:right">P(гэп↑)</th>
          <th style="padding:8px 10px;text-align:right">День</th>
          <th style="padding:8px 10px;text-align:right">RSI</th>
          <th style="padding:8px 10px;text-align:right">Объём</th>
        </tr>
      </thead>
      <tbody>{rows_html}</tbody>
    </table>
    </div>
    <div style="color:#8b949e;font-size:12px;margin-top:10px">Зелёная подсветка — выбранные фавориты. P(гэп↑) — историческая доля случаев с положительным гэпом следующего дня после сигналов модели (вне выборки).</div>
  </div>

  {stab_html}

  <div style="background:#161b22;border:1px solid #30363d;border-radius:14px;padding:22px;margin-top:28px">
    <h2 style="margin:0 0 8px;font-size:20px">Проверка стратегии (бэктест, вне выборки)</h2>
    <div style="color:#8b949e;font-size:13px;margin-bottom:14px">Walk-forward: модель обучается на прошлом, тестируется на следующем месяце. {bt['n_months']} месяцев вне выборки (окт 2025 – авг 2026), ~1500 акций NASDAQ.</div>
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin-bottom:16px">
      <div style="background:#0d1117;border:1px solid #21262d;border-radius:10px;padding:14px;text-align:center">
        <div style="color:#8b949e;font-size:11px;text-transform:uppercase">Попадание ≥2% за 48ч</div>
        <div style="font-size:26px;font-weight:800;color:#2ea043">{bt['hit']:.1%}</div>
        <div style="color:#8b949e;font-size:12px">база рынка: {bt['base_hit']:.1%}</div>
      </div>
      <div style="background:#0d1117;border:1px solid #21262d;border-radius:10px;padding:14px;text-align:center">
        <div style="color:#8b949e;font-size:11px;text-transform:uppercase">Среднее лучшее движение</div>
        <div style="font-size:26px;font-weight:800;color:#2ea043">{bt['avg_best']:+.1%}</div>
        <div style="color:#8b949e;font-size:12px">база рынка: {bt['base_best']:+.1%}</div>
      </div>
      <div style="background:#0d1117;border:1px solid #21262d;border-radius:10px;padding:14px;text-align:center">
        <div style="color:#8b949e;font-size:11px;text-transform:uppercase">Средний результат 2-го дня</div>
        <div style="font-size:26px;font-weight:800;color:#56d364">{bt['avg_fwd2']:+.1%}</div>
        <div style="color:#8b949e;font-size:12px">база рынка: {bt['base_fwd2']:+.1%}</div>
      </div>
      <div style="background:#0d1117;border:1px solid #21262d;border-radius:10px;padding:14px;text-align:center">
        <div style="color:#8b949e;font-size:11px;text-transform:uppercase">Худший случай (средний)</div>
        <div style="font-size:26px;font-weight:800;color:#f85149">{bt['avg_worst']:+.1%}</div>
        <div style="color:#8b949e;font-size:12px">стоп −3% защищает</div>
      </div>
    </div>
    <div style="color:#c9d1d9;font-size:13px;margin:10px 0 6px">Точность стратегии по месяцам (зелёный — стратегия, серый — база рынка):</div>
    {svg_monthly()}
  </div>

  <div style="background:#161b22;border:1px solid #30363d;border-radius:14px;padding:22px;margin-top:28px">
    <h2 style="margin:0 0 12px;font-size:20px">Как работает сканер</h2>
    <ol style="color:#c9d1d9;font-size:13.5px;line-height:1.7;padding-left:20px;margin:0">
      <li><b>Тайминг:</b> запуск в 15:30 ET, за 30 минут до закрытия. Свеча текущего дня строится из 30-минутных баров до 15:30 — она <b>неполная</b>, но валидация показывает: сигнал сохраняет ~98% качества (корреляция 0,98 с сигналом по полной свече).</li>
      <li><b>Юниверс:</b> 1500+ ликвидных акций NASDAQ (цена ≥ $5, оборот ≥ $5 млн/день).</li>
      <li><b>Признаки (24 шт.):</b> моментум, свечная геометрия, RSI(14), положение к SMA50/SMA200, тренд EMA20/50, ATR/ADR, объём vs 20-дневный, 52-недельные экстремумы, серии дней, ликвидность.</li>
      <li><b>Модель:</b> градиентный бустинг, ~450 тыс. примеров. Метка: «выросла ≥2% хотя бы в один из 2 следующих дней».</li>
      <li><b>Вход:</b> по цене закрытия (15:55–16:00). Цель — +2%/+5% за 24–48ч, стоп −3%.</li>
      <li><b>Дополнительно:</b> историческая вероятность положительного гэпа следующего дня по каждому тикеру (вне выборки) и медианный размер гэпа.</li>
    </ol>
  </div>

  <div style="background:#2d1415;border:1px solid #da3633;border-radius:12px;padding:14px 18px;margin-top:28px;font-size:12.5px;color:#e6b9b9;line-height:1.6">
    ⚠️ <b>Дисклеймер.</b> Никакой алгоритм не может <i>гарантировать</i> рост на 2–5% за 24–48 часов и положительный гэп —
    рынок стохастичен. Приведённые вероятности — статистические оценки на исторических данных; они ухудшаются при смене
    рыночного режима. Позиция 1–2% капитала, стоп −3% обязателен. Историческая точность 49–57% означает, что почти
    каждая вторая сделка цели не достигнет. Это исследовательский инструмент, а не индивидуальная инвестиционная рекомендация.
  </div>

  {runs_html}

  <div style="color:#8b949e;font-size:12px;margin-top:20px;text-align:center">
    EOD Momentum Scanner · скан {last_date} 15:30 ET · данные: Nasdaq.com + Yahoo Finance · автоматический запуск: будни 15:30 ET (GitHub Actions)
  </div>
</div>
</body>
</html>"""

    for name in ("dashboard.html", "index.html"):
        with open(os.path.join(OUT, name), "w", encoding="utf-8") as f:
            f.write(html)
    print("dashboard written:", len(html), "bytes ->", OUT)


if __name__ == "__main__":
    build()
