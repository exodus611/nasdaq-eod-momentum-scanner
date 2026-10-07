# AGENTS.md — how to work in this repository

Project memory lives in **`NOTES.md`**. Read it first; it is the source of truth for state, decisions and next tasks.

## Start of a session

1. Read `NOTES.md`, then `README.md` and `STRATEGY.md`.
2. Inspect the evidence before claiming anything: `state/latest.json`, `state/daily_log.csv` (tail), `state/journal.csv` (tail), `git log -5`, `git status`.
3. Report what the evidence supports, what is stale, and the proposed task. Wait for confirmation before substantial work.

## Work rules

- **Paper trading only.** Never add code that places, simulates broker credentials for, or sends real orders. No API keys for brokers.
- **The strategy is frozen unless research says otherwise.** Rules: `STRATEGY.md` §1. Changing thresholds, exits or sizing requires a new row in `results/` and an entry in `NOTES.md` → Decisions.
- **No data snooping.** `research/PLAN.md` is pre-registered: choose on in-sample, run out-of-sample **once**, report a failure as a failure. Do not "fix and re-run".
- **The bot must be honest on screen.** If the daily bar has not arrived, say so on the dashboard and do nothing. Never invent or forward-fill prices.
- `state/daily_log.csv` is the source of truth for which sessions were processed. Do not process a session twice.
- `docs/index.html` and `README.md` between `<!-- DASHBOARD:START/END -->` are **generated**. Edit `bot.py`, not the output.
- `state_v1/` is frozen history. Read-only.
- Keep every public claim consistent with the caveats in `STRATEGY.md` §4 (survivorship bias, free data, ~34 trades/year, 2020 −2.4% and 2022 −7.1%).

## Checkpoint (at most four lines)

Write to `NOTES.md` → Recent sessions on any material decision, failed approach, state change or impending context loss:
`event · evidence/result · decision + reason · exact next action`.

## Closing

Update `NOTES.md` (current state with date, decisions, next three tasks), inspect the **actual** diff, then commit only task-owned files. Never commit `state/` changes made outside a real scan run.

## Security

- Never write tokens, passwords, private keys, or personal data into any file, commit, fixture, log or memory entry.
- The workflow uses only the built-in `GITHUB_TOKEN`; keep it that way.
- Before committing, review staged + untracked content for secrets. Report path + category only, never the matching value.
- If a secret may already be committed: stop, warn that rotation and history cleanup are required. Deleting the line is not enough.

## Repository-specific commands

```bash
python bot.py test                                  # self-check
python bot.py run --asof 2026-08-20                 # process one past session
python bot.py backfill --from 2026-06-01 --to 2026-09-12
python research/v2_exit_test.py                     # regenerates the results grid
```

Dependencies: `requirements.txt` (yfinance, pandas, numpy). Marketing renders additionally need `imageio-ffmpeg`, `Pillow`, `numpy` — see `marketing/README.md`.

## Marketing (`marketing/`)

The ad sells the **method in the book**, using this repository as proof. Rules:
- Only real numbers from `results/` or `state/`. No invented performance, no promises.
- Every deliverable carries the compliance line: paper trading, backtest ≠ future results, not financial advice.
- Rendered output is reproducible from `marketing/render/` — never hand-edit an MP4.
