# Compliance

Persistent on-screen line (bottom of every frame, muted):

> Paper trading · no orders sent · backtest does not guarantee future results · not financial advice

It covers, honestly, everything the video shows:

- **Paper trading / no orders sent** — `bot.py` never places orders; the journal is at real open
  prices but is simulated. (README.md)
- **Backtest ≠ future** — 2010–2026 figures are a backtest on today's NASDAQ constituents, so
  survivorship bias is present; worst years 2020 −2.4%, 2022 −7.1%; streaks of 4–6 losers are
  normal. (STRATEGY.md §4)
- **Not financial advice** — mirrors the book's own disclaimer.

The live journal shows only ~15 strategy trades since 2026-09-10; the video labels them as
demonstrating the mechanics, not proving the edge. Do not add any claim of profit, guarantee, or
"beating the market" in edits or captions.
