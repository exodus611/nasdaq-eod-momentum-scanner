# Script + storyboard (EN master, 67 s)

Voice: `voice-00` (English, advertising). Captions are burned (X autoplays muted).
Timing comes from the actual narration files in `render/vo/en_0*.mp3`.

| t (s) | Scene | Voiceover (en_0N) | On-screen |
|---|---|---|---|
| 0–2.8 | intro | — | terminal over phone-macro plate: `git clone …`, `python bot.py run`, "[16:20 ET] scanning…" |
| 2.8 | claim | 01 "This is not a mock-up…" | "THIS IS NOT A MOCK-UP." + chips PAPER TRADING / NO ORDERS SENT |
| ~9.7 | dash | 02 "After the US close…" | real day-status + next-session cards, RSI gauge (QQQ 759.66 / 98.5 / 67) |
| ~17.5 | table | — | scanner table, rows slide in, picks INTC/STX highlighted, counter 67 |
| ~22.5 | numbers | 03 "89 sessions…" | count-ups 89/75/10/61 + filmstrip of last 30 daily_log sessions |
| ~30.2 | books | — | paper journal: open positions + closed tier-A trades, strategy vs control |
| ~35.4 | pipeline | 04 "No server, no subscription…" | GATE→WAIT→SCAN→COMMIT→DEPLOY lighting up; last run 0efab15 |
| ~43.7 | memory | 05 "It keeps working…" | NOTES.md / AGENTS.md / statefile.yml cards + agent flow line |
| ~54.4 | backtest | — | CAGR/DD/years/bp/win/time cards + honest caveats |
| ~59.8 | cta | 06 "Built from a phone…" | book + starter kit buttons + repo and dashboard URLs over book plate |

HUD always on: repo path (top-left), LIVE · PAPER TRADING (top-right), compliance line + progress bar (bottom).

## Open follow-ups (one re-render each)

- **RU dub:** swap `render/vo/en_0*.mp3` for RU files recorded with `voice-01`, add RU caption
  strings in `CAPTIONS`.
- **9:16 vertical:** add a layout mode in `render.py` (center 1080-wide column, stacked cards).
