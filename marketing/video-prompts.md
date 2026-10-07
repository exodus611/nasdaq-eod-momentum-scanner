# AI-video prompt pack — premium re-shoot

The delivered MP4 is the reference cut. Use these prompts to re-shoot the two cinematic plates
and any B-roll with a generative video model (Sora 2 / Veo 3 / Runway Gen-4 / Kling 2.x).
Keep the **master grade** identical across all shots so they cut together with the data UI.

## Master grade / consistency sheet (paste into every prompt)

`Cinematic high-end fintech commercial. Deep navy (#060910) shadows, single warm amber practical
light, subtle teal rim light and teal-amber accents. Anamorphic lens, shallow depth of field,
gentle haze, fine film grain, muted color grade, 35mm. No readable text, no letters, no logos,
no brand marks, no numbers on any screen.`

## Negative prompt (all models)

`cartoon, anime, 3d render look, oversaturated, lens flare abuse, watermark, logo, readable text,
subtitles, ui overlay, stock-photo feel, plastic skin, extra fingers, distorted hands,
flickering, temporal aliasing, jitter, low resolution`

## Plate 1 — night desk / phone (intro)

`Wide shot, a person alone at a dark minimal desk late at night, seen from behind and slightly to
the side, face lit only by the cold glow of a smartphone held in one hand; phone shows abstract
blurred lines of code. Closed laptop, cup, scattered papers. [master grade]. Slow push-in.
--ar 16:9`

## Plate 2 — phone macro (behind terminal)

`Extreme macro of a modern smartphone screen in a dark room, abstract dark code editor with a
single blinking cursor and soft teal/amber syntax glow, all text illegible. Fingertip near the
glass, reflections, bokeh of warm city lights far behind. [master grade]. Subtle handheld drift.
--ar 16:9`

## Plate 3 — book and phone (CTA)

`Overhead three-quarter shot on a dark walnut desk: closed book with a plain unbranded navy cover
beside a smartphone whose screen glows with abstract code; notebook and pen beside them. Warm amber
key light from the left, faint dust in the air. [master grade]. Slow orbit. --ar 16:9`

## Optional B-roll (only if re-shooting the data scenes)

- `Macro of a serverless desk setup: a phone, a paper journal with pen-drawn candlesticks,
  [master grade].` (books scene)
- `Abstract dark data stream: thin teal light threads converging into a single glowing document,
  [master grade].` (memory scene)

## Usage notes

- Generate plates at the highest available resolution, then let `render/render.py` place them as
  background layers (see `plate()`); the data UI is always rendered locally for accuracy.
- Never ask a video model to draw the dashboard or numbers — they must stay pixel-perfect from
  `state/`. AI text is unreliable; real figures come from the repo.
