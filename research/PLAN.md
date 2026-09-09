# Research protocol (written BEFORE looking at results, to avoid data-snooping)

Universe: current NASDAQ members with px>=3, mcap>=500M (survivorship bias present -> favors long-side,
mean-reversion setups on "survivors"; must discount results accordingly and prefer liquid names).

Data: daily OHLCV 2009-06 .. 2026-09 (yfinance, adjusted).

Split:
  - IN-SAMPLE (design):     2010-01 .. 2019-12   (10 years, includes 2011, 2015-16, 2018 selloffs)
  - OUT-OF-SAMPLE (verify):  2020-01 .. 2026-09   (~6.7 years, includes COVID crash, 2022 bear, 2025-26)
  Rules: everything (thresholds, ranking, hold, filters) is chosen on IS only. OOS is run ONCE per
  final candidate. If a candidate fails OOS I report it as failed, I do not "fix" it and re-run.

Execution assumptions (conservative):
  - Signal computed after close of day T (full daily bar). Entry at OPEN of T+1 (MOO order).
  - Exit at CLOSE of T+2 (48h) by default; also report T+1 close (24h).
  - Cost: 15 bp round trip for names with $vol21 >= $20M, 30 bp otherwise (spread+slippage+commission).
  - Position sizing: equal weight across day's signals, max N names, capital split over overlapping cohorts.
  - No shorting (retail/IBKR borrow issues), no leverage.

Candidate families (from literature, not from this data):
  A. Short-term reversal / liquidity provision (Lehmann 1990, Jegadeesh 1990, Nagel 2012):
     large 1-day (or intraday) drop in liquid stock, no news gap -> 1-3 day bounce.
  B. Overnight premium / intraday reversal (Lou-Polk-Skouras 2019; Berkman 2012): buy close, sell open.
  C. Post-earnings announcement drift proxy: gap-up on huge volume with strong close -> continuation.
  D. Index/ETF mean reversion: QQQ/TQQQ RSI(2)-type (Connors) - lower capacity issues, single instrument.
  E. Market-wide panic: when breadth (share of stocks down >4%) is extreme -> buy basket next open.

Success criteria (OOS): net avg return/trade > 0 with t>2.5 on daily P&L; positive in >= 60% of years;
maxDD tolerable; capacity: median $vol of traded names >= $20M.

# PRE-REGISTERED RULES (locked on IS 2010-2019 before running OOS 2020-2026)

Family that survived IS: conditional mean reversion ("market oversold + stock dip in uptrend").
Everything else (unconditional reversal, breakouts, gaps, overnight, TOM) is net negative IS -> discarded.

P1 (primary):
  market trigger: QQQ RSI(2) < 10 at close of day T
  stock filter:   close > SMA200, ret_1 <= -3%, dv21 >= $20M, price >= $5
  selection:      up to 10 names/day, ranked by most negative ret_1
  entry:          open T+1 (MOO);  exit: close T+2 (MOC)  [48h]
  sizing:         equal weight, day's cohort = 50% of capital (two overlapping cohorts), no leverage
P2: as P1 but ranked by highest dv21 (most liquid)            - capacity variant
P3: as P1 with no cap (all qualifying names)                  - diversification variant
P4: as P1 plus QQQ > SMA200 regime filter                     - conservative variant
M1: QQQ only: RSI(2)<10 -> buy QQQ open T+1, sell close T+2   - market-only benchmark
Also report P1 with entry at close T (15:55) and with hold 3 as sensitivity (not selected).

Pass criteria OOS: net_bp > 0 and t_daily > 2 for P1 or P3; years_pos >= 5/7.
