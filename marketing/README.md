# marketing/ — ad package for *Never Start from Scratch*

Sell the **method in the book** using this repository as living proof. Everything on screen in the
rendered video is rebuilt from real output of this repo — no invented numbers.

## Deliverables

| File | What it is |
|---|---|
| `deliverables/never-start-from-scratch-x-16x9.mp4` | The finished X/Twitter video. 1920×1080, 30 fps, H.264+AAC, ~67 s, EN voice, burned captions, procedural music bed. |
| `video-prompts.md` | AI-video / still prompt pack (Sora 2, Veo 3, Runway Gen-4, Kling) for a premium re-shoot, plus the master grade and negative prompts. |
| `script-storyboard.md` | Timed EN script + shot-by-shot storyboard mapped to the render. |
| `compliance.md` | The on-screen compliance line and what it covers. |
| `assets/*.png` | Cinematic plates used by the renderer (phone macro, book-and-phone). |

## Reproducing the video

```bash
pip install --break-system-packages imageio-ffmpeg Pillow numpy   # render toolchain
python3 marketing/render/render.py          # full render -> deliverables/
python3 marketing/render/render.py --smoke  # 16 s pipeline test
```

The renderer (`render/render.py`) reads `state/latest.json`, `state/daily_log.csv`,
`state/journal.csv`, `state/positions.json`, `results/`, `git log` and the memory files, then
composites every frame with Pillow and encodes with the bundled ffmpeg. Narration is in
`render/vo/en_0*.mp3`; the music bed is synthesized deterministically in-process (royalty-free).
**Never hand-edit an MP4** — change the code and re-render.

## Where every number comes from

| On screen | Source |
|---|---|
| QQQ 759.66 +0.46%, RSI(2) 98.5, tier C, 67 candidates, picks INTC/STX | `state/latest.json` |
| 89 sessions, 10 tier-A, 61 tier-C | `state/daily_log.csv` |
| 75 journal entries | `state/journal.csv` |
| Open: AMGN −1.8 / REGN −0.2 / SNDK −3.7 / NBIS +5.3 | `state/positions.json` |
| Closed: CRWD +19.4%, SNDK +10.0%, NVDA +8.3%, MU −8.8%, SNDK −11.3% | `state/positions.json` |
| Strategy 15 tr +$2,883 DD −4.5% · Control 55 tr +$21,375 DD −9.0% | `state/latest.json` `track` |
| Backtest 15.2% CAGR, −22.9% DD, 15/17 yrs, +181 bp, 70% win, 22% time | `STRATEGY.md` / `results/v2_variants_2010_2026.csv` |
| last run 0efab15 “scan: 2026-10-06 16:51 ET” | `git log` |

## Status — 2026-10-07

Delivered: EN 16:9 master. Open: RU dub (voice registered as `voice-01`), 9:16 vertical cut.
Both are one re-render away (see `script-storyboard.md`).
