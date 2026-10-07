# Dip-Buyer NASDAQ v2 — project memory

Working example for the book *Never Start from Scratch: Give Your Projects a Memory That Never Forgets* (Daniel Marlow, ASIN B0HKVZ3RSG). Read this file first, then inspect the paths named below.

## Goal

Every trading day after the US close, decide automatically whether today is a buy day and, if so, name up to two NASDAQ stocks to buy at the next open; manage open positions until their exit; publish a live dashboard. **Paper trading only — no orders are ever sent.**

Definition of done for a session: the scan for the session is in `state/scans/<date>.json`, the journal and dashboard are updated and pushed, and `state/daily_log.csv` contains the date.

## Current state and known problems — verified 2026-10-07

- **Working.** Scanner + paper journal + dashboard generator in `bot.py`. 89 sessions stored, `state/scans/2026-06-01.json` → `state/scans/2026-10-06.json`; `state/daily_log.csv` 89 rows; `state/journal.csv` 75 entries; 10 tier-A days logged. Latest run `state/latest.json` → `run_at 2026-10-06 16:49 ET`, tier C, QQQ 759.66 (+0.46%), RSI(2) 98.5, 67 candidates, no strategy buys.
- **Working.** `.github/workflows/daily.yml` runs the scan, commits `state docs README.md data/universe_nasdaq.csv`, and publishes `docs/` to GitHub Pages. Last commit `0efab15` "scan: 2026-10-06 16:51 ET". Dashboard: https://exodus611.github.io/nasdaq-eod-momentum-scanner/
- **Known problem (accepted).** GitHub cron is late (2h20m observed 2026-09-11). Mitigation is in the workflow: early slots wait inside the runner until 16:20 ET; `state/daily_log.csv` prevents double processing.
- **Known problem (accepted).** Backtest uses today's NASDAQ constituents → survivorship bias. Documented in `STRATEGY.md` §4 and shown on the dashboard.
- **Uncertain / unverified.** Live edge: only 15 strategy trades in the live journal since 2026-09-10 — far below the 40–50 trades needed to judge anything.
- **New 2026-10-07.** Ad package + rendered X/Twitter video were prepared, then **removed from this public repo** per owner: they belong in the private repo `never-start-from-scratch-video`.
- **Known problem (2026-10-07).** `.github/workflows/statefile.yml` is validated locally, but the Arena GitHub App token lacks the `workflows` permission, so pushing it is refused by GitHub. Commit/push that one file from a token with `workflows` scope (or grant the app the permission), then this item closes. Everything else pushed as `c791177`.
- **Known problem (2026-10-07).** The private video repo `never-start-from-scratch-video` cannot be created by the app token (`createRepository` not granted). The owner must create it (private) — or grant the scope — then the staged package in `~/never-start-from-scratch-video/` is pushed there. The app token can read/write existing repos but not create new ones.

## Repository map

| Path | What it is |
|---|---|
| `bot.py` | Scanner, paper journal, dashboard generator. `run --asof`, `backfill`, `refresh-universe`, `test`. |
| `.github/workflows/daily.yml` | Daily run + Pages deploy. Fires on `main` push, schedule, `workflow_dispatch`. |
| `docs/index.html` | Generated dashboard (committed artifact, Pages source). |
| `state/` | `latest.json`, `journal.csv`, `daily_log.csv`, `positions.json`, `scans/<date>.json`. |
| `state_v1/` | Frozen v1 journal (Aug 10 – Sep 11, 2026, fixed 48 h exit). |
| `research/` | All research code. `PLAN.md` = pre-registered rules written before looking at results. |
| `results/` | Backtest CSV/PNG evidence. `v2_variants_2010_2026.csv` is the main grid. |
| `STRATEGY.md` / `.ru.md` | Rules, numbers, what was rejected and why. |
| `README.md` / `.ru.md` | Entry point + dashboard block (`DASHBOARD:START/END`). |
| `marketing/` | **Removed 2026-10-07.** The ad package + video live in a separate **private** repo `never-start-from-scratch-video` (see Known problems). Do not re-add video/ad assets to this public repo. |

## Decisions and failed approaches

- **2026-09 — v2 exit rule.** Changed from v1's fixed 48 h to "first close above the stock's SMA10, 20 sessions max": +81 → +181 bp/trade, 58% → 70% winners. Chosen on 2016–2026, checked once on 2010–2016.
- **2026-09 — dropped tier B and every "trade every day" rule.** They lose money on 2010–2016 (control book max DD −60%). Not to be retried without new evidence.
- **2026-09 — rejected outright:** stops (fire at the bottom of the rebound), 52-week-high breakouts, TQQQ on RSI2 < 10, overnight holds, turn of month, VIX rules. Full list: `STRATEGY.md` §3.
- **2026-09 — no cron punctuality assumption.** Early slots that wait inside the runner replaced late-firing crons.
- **2026-10-07 — memory system installed.** `NOTES.md` + `AGENTS.md` pushed. `.github/workflows/statefile.yml` (statefile v0.2.3, pinned SHA `8e9dc90f98ee181b885fec72ce7f771b66d60057`, `strict: true`, 14-day freshness) is present and validated **locally** but not yet pushed — see Known problems.
- **2026-10-07 — `releasecheck` deliberately not installed.** No build command and no release artifact directory: `docs/index.html` is generated by `bot.py` and published directly by `daily.yml`. Install it only if a real build/release step appears.

## Next three tasks

1. Create the private repo `never-start-from-scratch-video` (owner action — token lacks `createRepository`), push the staged package from `~/never-start-from-scratch-video/`, then add the RU dub and 9:16 cut there.
2. Grow the live journal toward 40–50 strategy trades before drawing any conclusion; keep the control book running as the honest benchmark.
3. Decide whether to add the `close < SMA10` entry condition (+1% CAGR in research, currently rejected to avoid one more parameter).

## External services

| Service | Purpose |
|---|---|
| GitHub Actions | Runs the daily scan, commits, deploys Pages. No secrets used. |
| GitHub Pages | Hosts the public dashboard. |
| Yahoo Finance via `yfinance` | Daily OHLCV. Free, no guarantees; missing bar → the bot says so and does nothing. |
| Amazon KDP | Distribution of the book this repository demonstrates. |

No tokens, keys, or credentials are stored in this repository. `.env` is git-ignored; `.env.example` is a template with no real values.

## Recent sessions

- **2026-10-07** — Installed project memory (`NOTES.md`, `AGENTS.md`; `statefile.yml` validated locally, push blocked by `workflows` permission). Prepared the ad package + rendered X/Twitter video, then removed it from this public repo at owner's request; it now waits in `~/never-start-from-scratch-video/` for a private repo. Evidence: this file, `git log` on the arena branch.
- **2026-10-06** — Daily scan ran, tier C, no strategy buys; dashboard updated (commit `0efab15`).
