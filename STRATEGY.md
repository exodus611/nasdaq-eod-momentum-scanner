# Dip-Buyer NASDAQ v2 — the strategy and why it looks like this

*[Русская версия](STRATEGY.ru.md)*

> **The short version.** The signal is the same as in v1 (market oversold + a liquid stock dropping inside an uptrend). What changed is the **exit**: not "sell after 48 hours" but **hold until the first close above the stock's 10-day SMA** (20 sessions max). On 2010–2026 that is +181 bp per trade instead of +81, 70% winners instead of 58%, 15.2% a year while being in the market 22% of the time, max drawdown −23%. The exit rule was chosen on 2016–2026 and then checked once on 2010–2016: 20% a year there, 7 of 7 years positive. Everything that buys "every day" — with no market filter or with a soft one — falls apart on 2010–2016; that was tested and is shown in numbers below.

---

## 1. Rules v2 (exactly as tested and as the bot runs them)

| | |
|---|---|
| **When (tier-A day)** | RSI(2) of the **QQQ** index at the close **< 10**. ~20–30 such days a year, in clusters of 1–3 |
| **What** | NASDAQ stocks: close > SMA200 · down ≤ **−3%** today · 21-day average turnover ≥ **$20M** · price ≥ $5 → **most liquid first**, at most **2 new per day** |
| **Positions** | up to **4 at a time**, **25% of capital** each. No leverage |
| **Entry** | next **open** |
| **Exit** | first **close above SMA10** of the stock → sell at the **next open**. Safety limit: no longer than **20 sessions**. **No stops, no targets** |
| **No signal / no free slots** | do nothing. Open positions are simply managed until their exit |

Average hold is 6.5 sessions (median 6; 23% of trades close within 1–2 sessions, 48% within ≤ 5, 2% reach the 20-session limit). This is no longer "24–48 hours", and that is deliberate: the 48-hour exit was v1's main problem.

## 2. Numbers (June 2010 – Sep 2026, after 10 bp round-trip costs, entry at the open)

`research/v2_exit_test.py` → `results/v2_variants_2010_2026.csv`; trades — `results/v2_trades_2010_2026.csv`; by year — `results/v2_by_year_2010_2026.csv`.

| variant | CAGR | max DD | Sharpe | years positive | trades/yr | win rate | avg trade | median | hold |
|---|---|---|---|---|---|---|---|---|---|
| **v2 — full period 2010–2026** | **15.2%** | **−22.9%** | 0.81 | **15/17** | 34 | 70% | **+181 bp** | +247 | 6.5 |
| v2 — **out-of-sample 2010–2016** (rule chosen on 2016–2026) | 20.0% | −15.3% | 1.31 | 7/7 | 36 | 72% | +210 | +273 | 6.4 |
| v2 — in-sample 2016–2026 | 12.4% | −22.9% | 0.63 | 9/11 | 32 | 67% | +161 | +218 | 6.5 |
| v1: same signal, exit after 48 h | 8.8% | −18.5% | 0.69 | 14/17 | 47 | 58% | +81 | +68 | 2.0 |
| exit close > SMA5 | 10.5% | −19.9% | 0.69 | 13/17 | 36 | 68% | +123 | +180 | 4.1 |
| exit stock RSI2 > 60 (max 10) | 11.3% | −19.0% | 0.74 | 15/17 | 36 | 70% | +129 | +191 | 4.1 |
| v2 with 30 bp costs | 13.3% | −23.5% | 0.73 | 12/17 | 34 | 69% | +161 | +227 | 6.5 |
| v2, 10% of capital per name | 6.1% | −9.3% | 0.80 | 15/17 | 34 | 70% | +181 | +247 | 6.5 |
| v2, 15% per name | 9.2% | −13.8% | 0.80 | 15/17 | 34 | 70% | +181 | +247 | 6.5 |
| v2, 6 positions at 16.7% | 12.2% | −18.6% | 0.80 | 14/17 | 41 | 69% | +179 | +246 | 6.5 |
| v2 without the "2 new per day" cap (up to 4 at once) | 18.5% | −29.8% | 0.89 | 15/17 | 41 | 68% | +181 | +216 | 6.5 |
| **control: the same every day, no market filter** | 14.5% | **−60.2%** | 0.56 | 11/17 | 168 | 63% | +45 | +130 | 5.6 |
| control: tier-B days only (QQQ RSI2 10–30) | 7.4% | −52.9% | 0.42 | 10/17 | 62 | 65% | +59 | +164 | 5.8 |
| control: tier-C days only (RSI2 ≥ 30) | 10.9% | −61.7% | 0.47 | 9/17 | 155 | 62% | +40 | +127 | 5.6 |
| control: A+B (RSI2 < 30) + SMA5 exit — the candidate rejected out-of-sample | 11.3% | −42.9% | 0.56 | 11/17 | 84 | 65% | +62 | +154 | 4.1 |
| ↳ the same on 2010–2016 | **−0.3%** | −31.5% | 0.07 | 3/7 | 78 | 61% | +5 | +112 | 4.5 |

For reference, QQQ buy-and-hold over the same period: 19.5% a year, max DD −35%, in the market 100% of the time. v2 is in the market 22% of the time on average (at least one position on 38% of sessions).

By year (v2):

| year | return | trades | win rate | avg trade | max DD within the year |
|---|---|---|---|---|---|
| 2010 (from June) | +7.0% | 19 | 63% | +148 bp | −12.8% |
| 2011 | +33.1% | 47 | 74% | +275 | −13.6% |
| 2012 | +1.7% | 40 | 70% | +38 | −15.3% |
| 2013 | +6.9% | 20 | 75% | +136 | −8.5% |
| 2014 | +26.9% | 31 | 74% | +318 | −8.2% |
| 2015 | +42.1% | 49 | 78% | +294 | −6.2% |
| 2016 | +14.8% | 31 | 65% | +183 | −9.5% |
| 2017 | +14.9% | 28 | 71% | +232 | −5.5% |
| 2018 | +0.7% | 34 | 59% | +34 | −17.2% |
| 2019 | +10.0% | 24 | 67% | +163 | −11.3% |
| 2020 | **−2.4%** | 16 | 62% | −34 | −19.1% |
| 2021 | +10.4% | 28 | 71% | +152 | −22.9% |
| 2022 | **−7.1%** | 57 | 65% | +17 | −22.6% |
| 2023 | +13.0% | 27 | 59% | +67 | −13.0% |
| 2024 | +1.0% | 29 | 72% | +144 | −13.3% |
| 2025 | +57.8% | 39 | 74% | +460 | −20.9% |
| 2026 (to September) | +22.9% | 32 | 72% | +309 | −19.7% |

Trade distribution: the worst 5% are below −10.3%, a quarter below −0.9%, median +2.5%, a quarter above +5.1%, the best 5% above +10.3%. Worst trade in 17 years: −44%. Streaks of 4–6 losers in a row are normal.

## 3. What was wrong with v1 and why v2 is what it is

**v1** (signal A + exit after 48 hours) backtested at +54…+81 bp per trade, but with 10% per name that is ~2% a year — indistinguishable from zero on an account. On top of that, tier B (RSI2 10–30) was added so that "there are trades every day". The 2010–2016 check showed that tier B and every "every day" rule lose money there — their profit on 2016–2026 was a fit to one bull period. That is the answer to "why doesn't it work": half of the trades were taken on a rule with no edge, and the other half were closed too early.

Searched on 2016–2026 and then checked on 2010–2016 (portfolio simulation everywhere, 10 bp, details in `research/`):

- **Exit.** Fixed 1/2/3/5 sessions — worst of all. Exit on a close above SMA5 — better, above SMA10 — better still, on the stock's RSI2 > 60 — in between. A holding limit of 10 or 20 sessions is about the same, 5 is worse. A minimum hold of 2–3 sessions is worse (the quick 1-session exits average +244 bp; they must not be forbidden).
- **Market signal.** QQQ RSI2 < 10 is the only threshold that holds in both periods. < 15, < 30, < 5 are worse. Tier-B and tier-C days on their own: max DD −53% and −62%.
- **Stock filter.** A drop of ≤ −3% is better than −2%; > SMA200 is needed; ranking by liquidity beats ranking by the size of the drop. An extra entry condition "close < SMA10" adds +1% CAGR — not included, to avoid adding a parameter for one percent.
- **Stops** cut the result (the stop fires at the bottom of the rebound) — there are none.
- **Sizing.** The average trade is the same at any size, but annual returns depend on it heavily: 10% per name → 6% a year at −9% DD; 25% → 15% at −23%. 25% was chosen (4 positions = all capital in the worst case, no leverage). For a quieter ride use the `PER_NAME=0.15` variable (9% a year, −14% DD).
- **The "2 new per day" cap** stays by the original requirement (no more than 2 names per day). Without it: 18.5% a year but −30% DD.
- **Rejected outright** (losing, or DD > 40% on one of the periods): buying on the stock's own RSI2 < 5 without a market filter; 5-day drop ≤ −10%; 52-week-high breakouts; continuation after a strong up day; pullbacks in an uptrend; weekly loser/leader rotations; TQQQ on RSI2 < 10; overnight holds; turn of the month; VIX rules.

## 4. Honest caveats

- The backtest uses today's NASDAQ constituents (~1,500 names, no delisted ones). The most liquid names are selected, so the survivorship effect is small, but live results may be 10–20 bp/trade worse.
- Data: Yahoo Finance (`yfinance`), free and without guarantees.
- ~34 trades a year. The strategy cannot be judged before 40–50 trades (≈ 1.5 years) — anything less is statistical noise. The first trades in the live journal from Sep 10, 2026 only demonstrate the mechanics.
- The strategy buys falling stocks on sell-off days and holds without a stop. It **must** look stupid from time to time (2020: −2%, 2022: −7%) — otherwise it would not pay.
- The "every day" book on the dashboard is a control. If it beats the strategy over a year, that was a bull year without sell-offs; over 17 years it is twice as bad in drawdown and worse by years.
