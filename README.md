# Dip-Buyer NASDAQ v2 — paper trading

*[Русская версия](README.ru.md)*

A mean-reversion scanner for NASDAQ stocks. Once a day, after the US close, it checks one market condition and — only when it is met — names **up to two stocks** to buy at the next open. Open positions are managed until the exit (first close above the 10-day SMA → sell at the next open). No orders are sent. The result is a **live dashboard** (GitHub Pages) plus the block below; a paper journal at real open prices is kept in this repository.

**Dashboard: https://exodus611.github.io/nasdaq-eod-momentum-scanner/**

<!-- DASHBOARD:START -->
### 📊 Scan Sep 21, 2026 (after the close) — ⚪ normal day (QQQ RSI2 ≥ 30) — no new buys, manage open positions only
QQQ **741.47** (+2.77%) · RSI(2) **97.9** · passed the filter: 14

- No positions, nothing to do tomorrow.

**Strategy: 15 trades · avg +0.75% · median -0.28% · win rate 47% · avg hold 5.1 sessions · P&L +$2,883 (+2.88% of $100,000) · max DD -4.5%**  
Control (every day, no market filter): 40 trades · avg +2.47% · win rate 60% · P&L +$24,178 · max DD -9.0%  
Full dashboard: https://exodus611.github.io/nasdaq-eod-momentum-scanner/ · updated 2026-09-21 16:20 ET
<!-- DASHBOARD:END -->

## Rule v2

| | |
|---|---|
| **When (tier-A day)** 🟢 | QQQ RSI(2) at the close **< 10** — the market is oversold. ~20–30 days a year, in clusters of 1–3 |
| **What** | NASDAQ stocks: close above SMA200, down **≥ 3%** today, average turnover ≥ $20M/day, price ≥ $5 → **most liquid first**, at most **2 new per day** |
| **Positions** | up to **4 at a time**, **25% of capital** each, no leverage |
| **Entry** | next **open** |
| **Exit** | the first **close above the stock's SMA10** → sell at the **next open**; hard limit 20 sessions. **No stops, no targets** |
| **Tier B/C days** ⚪ | QQQ RSI(2) ≥ 10 — **no new buys**, open positions are managed only. The list of stocks that passed the filter is shown for watching |

What changed versus v1 and why — in [STRATEGY.md](STRATEGY.md). In short: the signal is the same, but the fixed 48-hour exit cut the rebound in half (+81 bp/trade, 58% winners); the SMA10 exit lets it play out (+181 bp, 70%). Tier B and every "trade every day" rule lose money on 2010–2016 — they are gone.

## What to expect (2010–2026, entry at the open, after 10 bp costs)

| | CAGR | max DD | years positive | trades/yr | win rate | avg trade | avg hold |
|---|---|---|---|---|---|---|---|
| **v2** — full period | **15.2%** | **−23%** | **15/17** | 34 | 70% | **+181 bp** | 6.5 sessions |
| v2 — out-of-sample 2010–2016 | 20.0% | −15% | 7/7 | 36 | 72% | +210 | 6.4 |
| v1 (same signal, fixed 48 h exit) | 8.8% | −19% | 14/17 | 47 | 58% | +81 | 2.0 |
| same rules every day, no market filter | 14.5% | **−60%** | 11/17 | 168 | 63% | +45 | 5.6 |

In the market 22% of the time on average. Worst years: 2022 −7%, 2020 −2%. Worst trade −44%. Streaks of 4–6 losers in a row are normal; nothing can be judged before 40–50 trades (≈ 1.5 years). All trades: [results/v2_trades_2010_2026.csv](results/v2_trades_2010_2026.csv), variants: [results/v2_variants_2010_2026.csv](results/v2_variants_2010_2026.csv), by year: [results/v2_by_year_2010_2026.csv](results/v2_by_year_2010_2026.csv).

## Setup

Already deployed in this repository. Dashboard: **https://exodus611.github.io/nasdaq-eod-momentum-scanner/** (published by the workflow itself via GitHub Pages).

1. Manual run: **Actions → "Dip-Buyer daily scan" → Run workflow** (mode `run`). A `scan: …` commit appears in 2–3 minutes; the block above and the dashboard update.
2. If the workflow cannot push: **Settings → Actions → General → Workflow permissions → "Read and write permissions"** → Save.
3. Optional: Settings → Secrets and variables → Actions → Variables: `CAPITAL` (100000), `PER_NAME` (0.25), `MAX_POS` (4), `MAX_NEW` (2), `RSI_THR` (10), `EXIT_SMA` (10), `MAX_HOLD` (20), `PAGES_URL`.

Everything else is automatic: the scan runs at **16:20 ET**, the journal commit and dashboard update follow 2–3 minutes later. GitHub starts cron jobs up to 2–3 hours late, so runners are started ahead of time (from noon ET) and wait for the close inside; fallback slots exist after the close. A session missed for any reason is caught up by the next run automatically (marked `catch-up`).

## What the dashboard shows

- **Day status:** QQQ, RSI(2), tier-A day or not, RSI gauge.
- **Next-session actions:** BUY (ticker, amount, ~shares) / SELL (at the open, reason) / HOLD (current P&L, SMA10 exit level).
- **Scanner output:** every stock that passed the filter that day, ranked by turnover.
- **Two books:** the strategy (buys only on tier-A days) and a control book "every day, no market filter" with the same entry/exit rules — so you can see live whether the market filter earns its keep.
- **Open positions, closed trades, equity, scan log.**

Each scan is also stored as `state/scans/<date>.json`, the trade journal as `state/journal.csv`, the run log as `state/daily_log.csv`. The v1 journal (Aug 10 – Sep 11, 2026, fixed 48 h exit) is preserved in `state_v1/`.

## Files

- `bot.py` — scanner + paper journal + dashboard. `python bot.py run --asof 2026-08-20` — process one past session; `python bot.py backfill --from 2026-06-01 --to 2026-09-12` — replay a range with a single download (marked `replay`).
- `research/v2_exit_test.py` — exit / sizing / control grid on 2010–2026 (tables above); `research/build_long.py` — builds the 17-year price panel.
- `.github/workflows/daily.yml` — daily run after the close (+ dashboard publishing to Pages).
- The previous scanner (momentum / pre-move, 10 names) is preserved in full in the [`legacy-scanner`](../../tree/legacy-scanner) branch.
- `results/` — backtests (v2 and the older v1 / 10-name variants), `research/` — all research code.

## Honest caveats

- Data: Yahoo Finance via `yfinance`, free and without guarantees. If the daily bar has not arrived, the bot says so on the dashboard and does nothing; it can be re-run manually (Run workflow → `run`).
- The backtest uses today's NASDAQ constituents (no delisted names). For the most liquid names the survivorship effect is small, but live results may be 10–20 bp/trade worse.
- The strategy buys falling stocks on sell-off days and holds without a stop. It **must** look stupid from time to time — otherwise it would not pay.
