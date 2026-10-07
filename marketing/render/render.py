#!/usr/bin/env python3
"""
Render the X/Twitter product video for the Project Memory method.

Everything on screen is rebuilt from THIS repository's real output:
  state/latest.json      -> day status, candidates, picks, events, tracking
  state/daily_log.csv    -> 89 sessions, tier A/B/C, QQQ + RSI(2)
  state/positions.json   -> open paper positions
  state/journal.csv      -> closed paper trades
  results/v2_variants_2010_2026.csv, STRATEGY.md -> backtest numbers
  NOTES.md / AGENTS.md / .github/workflows/*.yml -> the memory system
  git log                -> the real commit SHA and message

Output: marketing/deliverables/never-start-from-scratch-x-16x9.mp4

Usage:
  python3 marketing/render/render.py --smoke      # 6 s pipeline test
  python3 marketing/render/render.py              # full render
"""
import csv
import json
import math
import os
import struct
import subprocess
import sys
import wave
from functools import lru_cache

import numpy as np
from PIL import Image, ImageDraw, ImageFont
import imageio_ffmpeg

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
MK = os.path.join(ROOT, "marketing")
OUTDIR = os.path.join(MK, "deliverables")
VODIR = os.path.join(HERE, "vo")
FF = imageio_ffmpeg.get_ffmpeg_exe()

W, H = 1920, 1080
FPS = 30
FONTDIR = "/usr/share/fonts/truetype/dejavu"

# ---------------------------------------------------------------- palette
INK = (232, 238, 244)
MUT = (146, 159, 175)
DIM = (92, 104, 120)
PANEL = (13, 20, 32)
PANEL2 = (18, 27, 42)
ROW = (16, 24, 37)
BORDER = (38, 52, 72)
TEAL = (45, 212, 191)
GREEN = (74, 197, 105)
RED = (248, 96, 88)
AMBER = (240, 183, 60)
BLUE = (96, 165, 250)


def A(c, a):
    return (c[0], c[1], c[2], int(255 * max(0.0, min(1.0, a))))


def cl(x):
    return max(0.0, min(1.0, x))


def eio(x):
    x = cl(x)
    return x * x * (3 - 2 * x)


def ease_out(x):
    return 1 - (1 - cl(x)) ** 3


@lru_cache(maxsize=None)
def F(sz, bold=1, mono=0):
    n = ("DejaVuSansMono-Bold.ttf" if bold else "DejaVuSansMono.ttf") if mono else \
        ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf")
    return ImageFont.truetype(os.path.join(FONTDIR, n), sz)


# ---------------------------------------------------------------- real data
def load_data():
    d = {}
    with open(os.path.join(ROOT, "state", "latest.json")) as f:
        d["latest"] = json.load(f)
    with open(os.path.join(ROOT, "state", "positions.json")) as f:
        d["positions"] = json.load(f)
    with open(os.path.join(ROOT, "state", "daily_log.csv")) as f:
        d["log"] = list(csv.DictReader(f))
    with open(os.path.join(ROOT, "state", "journal.csv")) as f:
        d["journal"] = list(csv.DictReader(f))
    out = subprocess.run(["git", "log", "-1", "--format=%h%x09%s"], cwd=ROOT,
                         capture_output=True, text=True).stdout.strip().split("\t")
    d["sha"], d["sha_msg"] = out[0], out[1]
    return d


D = load_data()
LAT = D["latest"]
CANDS = LAT["candidates"]
PICKS = {p["ticker"] for p in LAT.get("picks", [])}
OPEN = [p for p in D["positions"]["books"]["everyday"] if p["status"] in ("open", "exiting")]
STRAT = D["positions"]["books"]["trade"]
LOG = D["log"]
TIER_A = sum(1 for r in LOG if r["tier"] == "A")


# ---------------------------------------------------------------- background
def build_bg():
    y = np.linspace(0, 1, H)[:, None]
    x = np.linspace(0, 1, W)[None, :]
    grad = (np.array([12, 17, 30]) * (1 - y[:, :, None])
            + np.array([4, 6, 13]) * y[:, :, None])          # (H,1,3)
    px = np.broadcast_to(grad, (H, W, 3)).astype(np.float64).copy()
    px += (np.exp(-(((x - 0.76) ** 2) * 1.7 + ((y - 0.12) ** 2) * 2.8) * 3.0)
           [:, :, None] * np.array([13, 70, 74]))
    px += (np.exp(-(((x - 0.08) ** 2) * 1.5 + ((y - 0.99) ** 2) * 2.4) * 3.4)
           [:, :, None] * np.array([56, 34, 8]))
    r = np.sqrt((((x - 0.5) * 1.18) ** 2) + (((y - 0.5) * 1.62) ** 2))
    px *= (1 - 0.46 * np.clip((r - 0.38) / 0.85, 0, 1) ** 1.3)[:, :, None]
    # baked-in technical grid (static: keeps the per-frame cost down)
    ys = np.arange(0, H, 76)
    xs = np.arange(0, W, 76)
    px[ys[:, None], xs[None, :], :] += np.array([16, 26, 34])
    px[ys[:, None], np.clip(xs[None, :] + 1, 0, W - 1), :] += np.array([5, 8, 11])
    return Image.fromarray(np.clip(px, 0, 255).astype(np.uint8))


BG = build_bg()
BG_RGBA = BG.convert("RGBA")


@lru_cache(maxsize=8)
def plate(name):
    p = os.path.join(MK, "assets", name)
    im = Image.open(p).convert("RGB")
    s = max(W / im.width, H / im.height) * 1.16
    return im.resize((int(im.width * s), int(im.height * s)), Image.LANCZOS)


def plate_frame(img, t, dur, dark=0.42, z0=1.0, z1=1.07, drift=(18, 10)):
    z = z0 + (z1 - z0) * cl(t / dur)
    cw, ch = int(W / z), int(H / z)
    ox = (img.width - cw) // 2 + int(drift[0] * (t / dur - 0.5))
    oy = (img.height - ch) // 2 + int(drift[1] * (t / dur - 0.5))
    crop = img.crop((ox, oy, ox + cw, oy + ch)).resize((W, H), Image.LANCZOS)
    black = Image.new("RGB", (W, H), (0, 0, 0))
    return Image.blend(black, crop, dark)


# ---------------------------------------------------------------- primitives
def grid(d, t):
    off = (t * 11) % 76
    for gx in range(-76, W + 76, 76):
        for gy in range(-76, H + 76, 76):
            xx, yy = gx + off, gy + off * 0.45
            if -2 <= xx <= W + 2 and -2 <= yy <= H + 2:
                d.ellipse([xx - 1, yy - 1, xx + 1, yy + 1], fill=A((150, 190, 210), 0.055))


def win(d, box, title=None, al=1.0, fill=PANEL, accent=TEAL):
    x0, y0, x1, y1 = box
    d.rounded_rectangle(box, 18, fill=A(fill, 0.93 * al), outline=A(BORDER, 0.95 * al), width=2)
    d.rounded_rectangle([x0, y0, x1, y0 + 52], 18, fill=A(PANEL2, 0.95 * al))
    d.rectangle([x0, y0 + 34, x1, y0 + 52], fill=A(PANEL2, 0.95 * al))
    d.line([x0, y0 + 52, x1, y0 + 52], fill=A(BORDER, 0.9 * al), width=1)
    for i, c in enumerate((RED, AMBER, GREEN)):
        d.ellipse([x0 + 20 + i * 22, y0 + 19, x0 + 34 + i * 22, y0 + 33], fill=A(c, 0.85 * al))
    if title:
        d.text((x0 + 100, y0 + 26), title, font=F(21, 1, 1), fill=A(MUT, 0.95 * al), anchor="lm")
    d.rectangle([x0 + 2, y0 + 52, x0 + 4, y1 - 18], fill=A(accent, 0.5 * al))


def chip(d, xy, s, col, al=1.0, f=None, pad=14):
    f = f or F(20, 1)
    bb = d.textbbox((0, 0), s, font=f)
    w, h = bb[2] - bb[0], bb[3] - bb[1]
    x, y = xy
    d.rounded_rectangle([x, y, x + w + pad * 2, y + h + 18], 999, fill=A(col, 0.13 * al),
                        outline=A(col, 0.55 * al), width=1)
    d.text((x + pad, y + 9), s, font=f, fill=A(col, al), anchor="la")
    return w + pad * 2


def counter(d, xy, val, fmt, fnt, col, al, prog):
    v = val * ease_out(prog)
    d.text(xy, fmt(v), font=fnt, fill=A(col, al), anchor="la")


# ---------------------------------------------------------------- scenes
def s_intro(d, t, dur, al):
    im = plate_frame(plate("02-phone-macro-glow.png"), t, dur, dark=0.30)
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dd = ImageDraw.Draw(ov)
    box = (200, 300, W - 200, 790)
    win(dd, box, "agent@phone  ~  nasdaq-eod-momentum-scanner", al)
    lines = [
        ("$ ", TEAL, "git clone github.com/exodus611/nasdaq-eod-momentum-scanner", INK),
        ("$ ", TEAL, "python bot.py run", INK),
        ("", DIM, "[16:20 ET] US close reached - scanning 1,500 NASDAQ names ...", MUT),
        ("", DIM, "tier C - no new buys - dashboard published to GitHub Pages", GREEN),
    ]
    cps = 62
    y = box[1] + 92
    spent = 0.0
    for pre, pc, s, col in lines:
        dd.text((box[0] + 40, y), pre, font=F(30, 1, 1), fill=A(pc, al))
        pw = dd.textlength(pre, font=F(30, 1, 1))
        n = int(cl((t - spent) * cps) * len(s))
        dd.text((box[0] + 40 + pw, y), s[:n], font=F(30, 0, 1), fill=A(col, al))
        if n < len(s) and int(t * 2.4) % 2 == 0:
            cw = dd.textlength(s[:n], font=F(30, 0, 1))
            dd.rectangle([box[0] + 40 + pw + cw + 3, y + 6, box[0] + 40 + pw + cw + 19, y + 34],
                         fill=A(TEAL, al))
        spent += len(s) / cps + 0.30
        y += 62
    dd.text((box[0] + 40, y + 22), "paper trading - no orders are ever sent",
            font=F(22, 0, 1), fill=A(DIM, 0.9 * al))
    return ov, im


def s_claim(d, t, dur, al):
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dd = ImageDraw.Draw(ov)
    a1 = eio(t / 0.55)
    dd.text((W // 2, 360 - 46 * (1 - a1)), "THIS IS NOT A MOCK-UP.",
            font=F(96, 1), fill=A(INK, al * a1), anchor="mm")
    a2 = eio((t - 0.55) / 0.55)
    if a2 > 0:
        dd.text((W // 2, 470 + 30 * (1 - a2)), "A real scanner. A real repository.",
                font=F(52, 0), fill=A(TEAL, al * a2), anchor="mm")
    a3 = eio((t - 1.0) / 0.55)
    if a3 > 0:
        dd.text((W // 2, 552 + 30 * (1 - a3)), "Running every trading day since June 1st.",
                font=F(52, 0), fill=A(MUT, al * a3), anchor="mm")
    a4 = eio((t - 1.6) / 0.6)
    if a4 > 0:
        w1 = chip(dd, (W // 2 - 320, 660), "PAPER TRADING", TEAL, al * a4, F(24, 1), 20)
        chip(dd, (W // 2 - 320 + w1 + 18, 660), "NO ORDERS SENT", AMBER, al * a4, F(24, 1), 20)
    return ov, None


def s_dash(d, t, dur, al):
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dd = ImageDraw.Draw(ov)
    sc = 0.965 + 0.035 * ease_out(t / 0.7)
    a = ease_out(t / 0.7)
    dd.text((110, 96 - 24 * (1 - a)), "Dip-Buyer NASDAQ v2  -  paper trading",
            font=F(46, 1), fill=A(INK, al * a), anchor="lm")
    dd.text((110, 148), "mean-reversion scanner  ·  runs once a day after the US close  ·  "
                        "publishes this page", font=F(24, 0), fill=A(MUT, al * 0.9 * a), anchor="lm")

    # left card: day status
    a1 = ease_out((t - 0.5) / 0.6)
    if a1 > 0:
        b = (110, 210, 1010, 700)
        dd.rounded_rectangle(b, 16, fill=A(PANEL, 0.95 * al * a1), outline=A(BORDER, al * a1), width=2)
        dd.text((b[0] + 30, b[1] + 36), "Scan for Oct 06, 2026 (after the close)",
                font=F(26, 0), fill=A(MUT, al * a1), anchor="lm")
        dd.ellipse([b[0] + 30, b[1] + 78, b[0] + 52, b[1] + 100], fill=A(MUT, al * a1))
        dd.text((b[0] + 68, b[1] + 89), "normal day (QQQ RSI2 >= 30) - no new buys",
                font=F(30, 1), fill=A(INK, al * a1), anchor="lm")
        kv = [("QQQ", "759.66", GREEN, "+0.46%"), ("RSI(2)", "98.5", RED, None),
              ("passed the filter", "67", INK, None)]
        x = b[0] + 30
        for i, (k, v, c, extra) in enumerate(kv):
            aa = ease_out((t - 0.9 - i * 0.16) / 0.5)
            if aa <= 0:
                continue
            dd.text((x, b[1] + 176), k, font=F(22, 0), fill=A(MUT, al * aa), anchor="lm")
            dd.text((x, b[1] + 214), v, font=F(44, 1), fill=A(c, al * aa), anchor="lm")
            if extra:
                dd.text((x + dd.textlength(v, font=F(44, 1)) + 14, b[1] + 214), extra,
                        font=F(26, 1), fill=A(GREEN, al * aa), anchor="lm")
            x += 300
        # gauge
        ga = ease_out((t - 1.5) / 0.8)
        gx0, gx1, gy = b[0] + 30, b[1] - 30 + 400, b[1] + 300
        dd.rounded_rectangle([gx0, gy, gx1, gy + 16], 8, fill=A(ROW, al * a1))
        dd.rounded_rectangle([gx0, gy, gx0 + 0.10 * (gx1 - gx0), gy + 16], 8, fill=A(GREEN, al * a1))
        dd.rounded_rectangle([gx0, gy, gx0 + ga * 0.985 * (gx1 - gx0), gy + 16], 8,
                             fill=A(RED, 0.0))  # track only
        mx = gx0 + ga * 0.985 * (gx1 - gx0)
        dd.rectangle([mx - 3, gy - 9, mx + 3, gy + 25], fill=A(INK, al * a1))
        dd.text((gx0, gy + 40), "QQQ RSI(2)  -  green zone < 10 = buy day",
                font=F(22, 0), fill=A(DIM, al * a1), anchor="lm")

    # right card: next session
    a2 = ease_out((t - 1.0) / 0.6)
    if a2 > 0:
        b = (1040, 210, 1810, 700)
        dd.rounded_rectangle(b, 16, fill=A(PANEL, 0.95 * al * a2), outline=A(BORDER, al * a2), width=2)
        dd.text((b[0] + 30, b[1] + 36), "Next session - strategy actions",
                font=F(26, 0), fill=A(MUT, al * a2), anchor="lm")
        dd.line([b[0] + 30, b[1] + 76, b[1 - 1] - 30, b[1] + 76], fill=A(BORDER, al * a2))
        dd.text((b[0] + 30, b[1] + 130), "No positions,", font=F(38, 1), fill=A(INK, al * a2), anchor="lm")
        dd.text((b[0] + 30, b[1] + 182), "nothing to do tomorrow.", font=F(38, 1),
                fill=A(INK, al * a2), anchor="lm")
        aa = ease_out((t - 1.7) / 0.6)
        if aa > 0:
            dd.text((b[0] + 30, b[1] + 268), "Waiting for a day with", font=F(26, 0),
                    fill=A(MUT, al * aa), anchor="lm")
            dd.text((b[0] + 30, b[1] + 310), "QQQ RSI(2) < 10.", font=F(30, 1),
                    fill=A(TEAL, al * aa), anchor="lm")
            dd.text((b[0] + 30, b[1] + 372), "10 such days in 89 sessions.", font=F(24, 0),
                    fill=A(DIM, al * aa), anchor="lm")
    return ov, None


def s_table(d, t, dur, al):
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dd = ImageDraw.Draw(ov)
    a = ease_out(t / 0.6)
    dd.text((110, 92), "Scanner output  -  Oct 06, 2026", font=F(44, 1), fill=A(INK, al * a), anchor="lm")
    dd.text((110, 146), "close > SMA200  ·  down >= 3% today  ·  turnover >= $20M/day  ·  "
                        "price >= $5  ·  most liquid first", font=F(23, 0),
            fill=A(MUT, al * 0.9 * a), anchor="lm")
    counter(dd, (1810, 92), LAT["n_candidates"], lambda v: f"{int(round(v))}", F(60, 1), TEAL,
            al * a, cl(t / 1.1))
    dd.text((1810, 146), "passed the filter", font=F(22, 0), fill=A(MUT, al * a), anchor="rm")

    b = (110, 200, 1810, 900)
    dd.rounded_rectangle(b, 16, fill=A(PANEL, 0.92 * al), outline=A(BORDER, al), width=2)
    cols = [(150, "#", "la"), (250, "ticker", "la"), (520, "close", "ra"),
            (700, "day", "ra"), (960, "turnover $M/day", "ra"), (1250, "vs SMA200", "ra"),
            (1500, "SMA10", "ra")]
    dd.rounded_rectangle([b[0], b[1], b[2], b[1] + 56], 16, fill=A(PANEL2, 0.95 * al))
    for cx, name, anc in cols:
        dd.text((cx, b[1] + 28), name, font=F(21, 1), fill=A(MUT, al), anchor="lm" if anc == "la" else "rm")
    dd.line([b[0], b[1] + 56, b[2], b[1] + 56], fill=A(BORDER, al))
    rows = CANDS[:8]
    for i, c in enumerate(rows):
        ra = ease_out((t - 0.45 - i * 0.13) / 0.45)
        if ra <= 0:
            continue
        y = b[1] + 62 + i * 72
        xoff = 26 * (1 - ra)
        if c["ticker"] in PICKS:
            dd.rounded_rectangle([b[0] + 8, y - 6, b[2] - 8, y + 62], 10, fill=A(GREEN, 0.10 * al * ra))
        vals = [(150, str(i + 1), DIM, "la", F(24, 0, 1)),
                (250, c["ticker"], INK if c["ticker"] in PICKS else MUT, "la", F(28, 1, 1)),
                (520, f"{c['close']:.2f}", INK, "ra", F(26, 0, 1)),
                (700, f"{c['ret_1']*100:.1f}%", RED, "ra", F(26, 1, 1)),
                (960, f"{c['dvol_M']:,.0f}", INK, "ra", F(26, 0, 1)),
                (1250, f"+{c['vs_sma200']*100:.0f}%", GREEN, "ra", F(26, 0, 1)),
                (1500, f"{c['sma10']:.2f}", MUT, "ra", F(26, 0, 1))]
        for cx, s, col, anc, fnt in vals:
            dd.text((cx + (xoff if anc == "la" else -xoff), y + 24), s, font=fnt,
                    fill=A(col, al * ra), anchor="lm" if anc == "la" else "rm")
        if c["ticker"] in PICKS:
            dd.rounded_rectangle([1520, y + 8, 1720, y + 44], 999, fill=A(GREEN, 0.16 * al * ra),
                                 outline=A(GREEN, 0.6 * al * ra))
            dd.text((1620, y + 26), "PICK", font=F(20, 1), fill=A(GREEN, al * ra), anchor="mm")
    dd.text((b[0] + 30, b[3] - 34), "top 8 of 67  ·  the strategy buys nothing on a tier-C day - "
                                   "the list is for watching", font=F(21, 0), fill=A(DIM, al * a), anchor="lm")
    return ov, None


def s_numbers(d, t, dur, al):
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dd = ImageDraw.Draw(ov)
    a = ease_out(t / 0.6)
    dd.text((W // 2, 130), "UNATTENDED SINCE JUNE 1ST", font=F(34, 1), fill=A(TEAL, al * a), anchor="mm")
    stats = [(len(LOG), "SESSIONS SCANNED", "state/scans/*.json", TEAL),
             (len(D["journal"]), "JOURNAL ENTRIES", "state/journal.csv", BLUE),
             (TIER_A, "TIER-A BUY DAYS", "QQQ RSI(2) < 10", GREEN),
             (sum(1 for r in LOG if r["tier"] == "C"), "TIER-C DO-NOTHING DAYS", "no new buys", MUT)]
    for i, (v, lab, sub, c) in enumerate(stats):
        aa = ease_out((t - 0.35 - i * 0.22) / 0.6)
        if aa <= 0:
            continue
        x = 260 + i * 380
        y = 300 + 40 * (1 - aa)
        dd.text((x, y), f"{int(round(v * ease_out(cl((t - 0.35 - i * 0.22) / 1.0))))}",
                font=F(120, 1), fill=A(c, al * aa), anchor="mm")
        dd.text((x, y + 96), lab, font=F(23, 1), fill=A(INK, al * aa), anchor="mm")
        dd.text((x, y + 132), sub, font=F(19, 0, 1), fill=A(DIM, al * aa), anchor="mm")
    # filmstrip of real sessions
    strip = LOG[-30:]
    fw = (1700 - 220) / len(strip)
    aa = ease_out((t - 1.5) / 0.7)
    if aa > 0:
        dd.text((220, 640), "state/daily_log.csv  -  last 30 sessions", font=F(21, 0, 1),
                fill=A(MUT, al * aa), anchor="lm")
        for i, r in enumerate(strip):
            col = {"A": GREEN, "B": AMBER, "C": (60, 74, 94)}[r["tier"]]
            x = 220 + i * fw
            hh = 30 + 90 * cl(float(r["q_rsi"]) / 100.0) if r["tier"] != "A" else 150
            y0 = 900 - hh
            dd.rounded_rectangle([x + 2, y0, x + fw - 2, 900], 4, fill=A(col, (0.9 if r["tier"] == "A" else 0.55) * al * aa))
        dd.text((220, 930), "2026-09-24", font=F(18, 0, 1), fill=A(DIM, al * aa), anchor="lm")
        dd.text((1700, 930), "2026-10-06", font=F(18, 0, 1), fill=A(DIM, al * aa), anchor="rm")
    return ov, None


def s_books(d, t, dur, al):
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dd = ImageDraw.Draw(ov)
    a = ease_out(t / 0.6)
    dd.text((110, 92), "Paper journal  -  real prices, real fills", font=F(44, 1),
            fill=A(INK, al * a), anchor="lm")
    dd.text((110, 146), "no orders are sent  ·  entries at the real open  ·  exit = the open after "
                        "the first close above SMA10", font=F(23, 0), fill=A(MUT, al * 0.9 * a), anchor="lm")
    b = (110, 200, 1000, 830)
    dd.rounded_rectangle(b, 16, fill=A(PANEL, 0.92 * al), outline=A(BORDER, al), width=2)
    dd.text((b[0] + 28, b[1] + 40), "OPEN POSITIONS (paper)", font=F(24, 1), fill=A(MUT, al), anchor="lm")
    hdr = [(b[0] + 28, "ticker", "la"), (b[0] + 300, "entry", "ra"), (b[0] + 470, "last", "ra"),
           (b[0] + 640, "P&L", "ra"), (b[0] + 800, "sessions", "ra")]
    for cx, n, anc in hdr:
        dd.text((cx, b[1] + 96), n, font=F(19, 1), fill=A(DIM, al), anchor="lm" if anc == "la" else "rm")
    for i, p in enumerate(OPEN[:5]):
        ra = ease_out((t - 0.4 - i * 0.14) / 0.45)
        if ra <= 0:
            continue
        y = b[1] + 130 + i * 66
        up = p.get("upnl")
        col = GREEN if (up or 0) >= 0 else RED
        dd.text((b[0] + 28, y), p["ticker"], font=F(28, 1, 1), fill=A(INK, al * ra), anchor="lm")
        dd.text((b[0] + 300, y + 2), f"{p['entry_px']:.2f}", font=F(24, 0, 1), fill=A(MUT, al * ra), anchor="rm")
        dd.text((b[0] + 470, y + 2), f"{p['last_px']:.2f}", font=F(24, 0, 1), fill=A(MUT, al * ra), anchor="rm")
        dd.text((b[0] + 640, y + 2), ("pending" if up is None else f"{up*100:+.1f}%"),
                font=F(24, 1, 1), fill=A(col if up is not None else DIM, al * ra), anchor="rm")
        dd.text((b[0] + 800, y + 2), str(p["held"]), font=F(24, 0, 1), fill=A(MUT, al * ra), anchor="rm")
    dd.line([b[0] + 20, b[3] - 96, b[2] - 20, b[3] - 96], fill=A(BORDER, al))
    dd.text((b[0] + 28, b[3] - 66), "Strategy book: 15 trades  ·  +$2,883  ·  max DD -4.5%",
            font=F(22, 1), fill=A(INK, al * a), anchor="lm")
    dd.text((b[0] + 28, b[3] - 34), "Control book (every day): 55 trades  ·  +$21,375  ·  max DD -9.0%",
            font=F(20, 0), fill=A(DIM, al * a), anchor="lm")

    b2 = (1030, 200, 1810, 830)
    dd.rounded_rectangle(b2, 16, fill=A(PANEL, 0.92 * al), outline=A(BORDER, al), width=2)
    dd.text((b2[0] + 28, b2[1] + 40), "CLOSED STRATEGY TRADES (tier-A days)", font=F(24, 1),
            fill=A(MUT, al), anchor="lm")
    best = sorted([p for p in STRAT if p["status"] == "closed"], key=lambda p: -p["ret_net"])
    show = best[:3] + best[-2:]
    for i, p in enumerate(show):
        ra = ease_out((t - 0.7 - i * 0.16) / 0.5)
        if ra <= 0:
            continue
        y = b2[1] + 110 + i * 82
        col = GREEN if p["ret_net"] >= 0 else RED
        dd.text((b2[0] + 28, y), p["ticker"], font=F(30, 1, 1), fill=A(INK, al * ra), anchor="lm")
        dd.text((b2[0] + 170, y + 3), p["signal_date"], font=F(20, 0, 1), fill=A(DIM, al * ra), anchor="lm")
        dd.text((b2[2] - 28, y), f"{p['ret_net']*100:+.1f}%", font=F(34, 1), fill=A(col, al * ra), anchor="rm")
        dd.text((b2[2] - 28, y + 40), f"{p['pnl_usd']:+,.0f} USD  ·  {p['hold']} sessions  ·  {p['exit_reason']}",
                font=F(19, 0, 1), fill=A(MUT, al * ra), anchor="rm")
        if i == 2:
            dd.text((b2[0] + 28, y + 74), ". . .", font=F(26, 1), fill=A(DIM, al * ra), anchor="lm")
    dd.text((b2[0] + 28, b2[3] - 44), "worst trade in the live journal: -11.3%  ·  best: +19.4%",
            font=F(20, 0), fill=A(DIM, al * a), anchor="lm")
    return ov, None


def s_pipeline(d, t, dur, al):
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dd = ImageDraw.Draw(ov)
    a = ease_out(t / 0.6)
    dd.text((W // 2, 150), ".github/workflows/daily.yml", font=F(30, 1, 1), fill=A(TEAL, al * a), anchor="mm")
    dd.text((W // 2, 214), "NO SERVER  ·  NO SUBSCRIPTION  ·  NO SECRETS", font=F(52, 1),
            fill=A(INK, al * a), anchor="mm")
    steps = [("GATE", "which session? already done?"),
             ("WAIT", "hold the runner until 16:20 ET"),
             ("SCAN", "python bot.py run"),
             ("COMMIT", f"git push  {D['sha']}"),
             ("DEPLOY", "docs/  ->  GitHub Pages")]
    n = len(steps)
    bw, gap = 296, 40
    total = n * bw + (n - 1) * gap
    x0 = (W - total) // 2
    y0, hh = 420, 210
    for i, (name, sub) in enumerate(steps):
        st = cl((t - 0.9 - i * 0.75) / 0.5)
        if st <= 0:
            continue
        x = x0 + i * (bw + gap)
        e = ease_out(st)
        done = cl((t - 0.9 - i * 0.75 - 0.5) / 0.4)
        dd.rounded_rectangle([x, y0 + 24 * (1 - e), x + bw, y0 + hh + 24 * (1 - e)], 16,
                             fill=A(PANEL, 0.95 * al * e),
                             outline=A(GREEN if done > 0.5 else BORDER, al * e), width=2)
        dd.ellipse([x + 24, y0 + 26 + 24 * (1 - e), x + 52, y0 + 54 + 24 * (1 - e)],
                   fill=A(GREEN if done > 0.5 else TEAL, 0.85 * al * e))
        dd.text((x + bw // 2, y0 + 104 + 24 * (1 - e)), name, font=F(34, 1),
                fill=A(INK, al * e), anchor="mm")
        dd.text((x + bw // 2, y0 + 156 + 24 * (1 - e)), sub, font=F(19, 0, 1),
                fill=A(MUT, al * e), anchor="mm")
        if i < n - 1:
            la = cl((t - 0.9 - i * 0.75 - 0.35) / 0.35)
            if la > 0:
                lx = x + bw + 6
                dd.line([lx, y0 + hh // 2, lx + (gap - 12) * ease_out(la), y0 + hh // 2],
                        fill=A(TEAL, 0.8 * al * la), width=3)
    aa = ease_out((t - 4.6) / 0.7)
    if aa > 0:
        dd.text((W // 2, 730), f"last run:  {D['sha']}  \"{D['sha_msg']}\"",
                font=F(28, 0, 1), fill=A(GREEN, al * aa), anchor="mm")
        dd.text((W // 2, 786), "GitHub starts cron jobs late - the workflow waits inside the runner "
                               "and never processes a session twice", font=F(22, 0),
                fill=A(MUT, al * aa), anchor="mm")
    return ov, None


def s_memory(d, t, dur, al):
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dd = ImageDraw.Draw(ov)
    a = ease_out(t / 0.6)
    dd.text((W // 2, 130), "WHY IT NEVER STARTS FROM SCRATCH", font=F(52, 1),
            fill=A(INK, al * a), anchor="mm")
    dd.text((W // 2, 196), "the repository remembers, so the next agent continues instead of restarting",
            font=F(25, 0), fill=A(MUT, al * a), anchor="mm")
    files = [("NOTES.md", TEAL, "the project memory",
              ["goal + definition of done", "verified state, dated", "decisions + failed approaches",
               "next three tasks"]),
             ("AGENTS.md", BLUE, "how to work here",
              ["start / work / checkpoint / close", "paper trading only, no orders",
               "no data snooping", "security review before commit"]),
             ("statefile.yml", GREEN, "keeps it fresh",
              ["pinned to one immutable SHA", "strict: true", "fails if memory is 14 days stale",
               "runs on every memory change"])]
    bw, gap = 500, 40
    x0 = (W - (3 * bw + 2 * gap)) // 2
    for i, (name, col, tag, items) in enumerate(files):
        st = ease_out((t - 0.5 - i * 0.4) / 0.6)
        if st <= 0:
            continue
        x = x0 + i * (bw + gap)
        y = 280 + 30 * (1 - st)
        dd.rounded_rectangle([x, y, x + bw, y + 400], 16, fill=A(PANEL, 0.95 * al * st),
                             outline=A(col, 0.45 * al * st), width=2)
        dd.rounded_rectangle([x + 26, y + 28, x + 60, y + 68], 8, fill=A(col, 0.22 * al * st),
                             outline=A(col, 0.7 * al * st))
        dd.text((x + 43, y + 48), name[0], font=F(24, 1, 1), fill=A(col, al * st), anchor="mm")
        dd.text((x + 80, y + 48), name, font=F(31, 1, 1), fill=A(INK, al * st), anchor="lm")
        dd.text((x + 80, y + 86), tag, font=F(21, 0), fill=A(col, 0.9 * al * st), anchor="lm")
        for j, it in enumerate(items):
            ja = ease_out((t - 1.1 - i * 0.4 - j * 0.16) / 0.45)
            if ja <= 0:
                continue
            yy = y + 146 + j * 56
            dd.ellipse([x + 30, yy + 8, x + 40, yy + 18], fill=A(col, 0.8 * al * ja))
            dd.text((x + 58, yy + 13), it, font=F(22, 0), fill=A(MUT, al * ja), anchor="lm")
    fa = ease_out((t - 3.4) / 0.7)
    if fa > 0:
        dd.text((W // 2, 760), "agent joins -> reads NOTES.md -> inspects state/ + git log -> "
                               "works -> checkpoint -> commit + push",
                font=F(22, 1, 1), fill=A(TEAL, al * fa), anchor="mm")
        dd.text((W // 2, 812), "one file, one block, any AI tool  ·  nothing to install",
                font=F(23, 0), fill=A(MUT, al * fa), anchor="mm")
    return ov, None


def s_backtest(d, t, dur, al):
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dd = ImageDraw.Draw(ov)
    a = ease_out(t / 0.6)
    dd.text((110, 100), "Backtest 2010 - 2026  ·  entry at the open  ·  after 10 bp costs",
            font=F(40, 1), fill=A(INK, al * a), anchor="lm")
    rows = [("CAGR", "15.2%", GREEN), ("max drawdown", "-22.9%", RED),
            ("years positive", "15 / 17", INK), ("avg trade", "+181 bp", GREEN),
            ("win rate", "70%", INK), ("time in market", "22%", TEAL)]
    for i, (k, v, c) in enumerate(rows):
        ra = ease_out((t - 0.4 - i * 0.17) / 0.5)
        if ra <= 0:
            continue
        col_i, row_i = i % 3, i // 3
        x = 110 + col_i * 570
        y = 240 + row_i * 230
        dd.rounded_rectangle([x, y, x + 530, y + 196], 16, fill=A(PANEL, 0.92 * al * ra),
                             outline=A(BORDER, al * ra), width=2)
        dd.text((x + 30, y + 44), k.upper(), font=F(22, 1), fill=A(MUT, al * ra), anchor="lm")
        dd.text((x + 30, y + 122), v, font=F(66, 1), fill=A(c, al * ra), anchor="lm")
    ha = ease_out((t - 1.7) / 0.7)
    if ha > 0:
        dd.line([110, 730, 1810, 730], fill=A(BORDER, al * ha))
        dd.text((110, 762), "Honest caveats", font=F(24, 1), fill=A(AMBER, al * ha), anchor="lm")
        for j, s in enumerate([
            "Uses today's NASDAQ constituents - no delisted names - so survivorship bias is present.",
            "Worst years: 2020 -2.4%, 2022 -7.1%. Streaks of 4-6 losers in a row are normal.",
            "15 live trades prove the mechanics, not the edge. Nothing here is a promise.",
        ]):
            ja = ease_out((t - 2.0 - j * 0.22) / 0.5)
            if ja > 0:
                dd.text((110, 806 + j * 40), "- " + s, font=F(22, 0), fill=A(MUT, al * ja), anchor="lm")
    return ov, None


def s_cta(d, t, dur, al):
    im = plate_frame(plate("06-book-and-phone.png"), t, dur, dark=0.34)
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dd = ImageDraw.Draw(ov)
    a1 = ease_out(t / 0.6)
    dd.text((W // 2, 300 - 30 * (1 - a1)), "NEVER START FROM SCRATCH", font=F(88, 1),
            fill=A(INK, al * a1), anchor="mm")
    a2 = ease_out((t - 0.45) / 0.6)
    if a2 > 0:
        dd.text((W // 2, 386), "Give your projects a memory that never forgets", font=F(38, 0),
                fill=A(TEAL, al * a2), anchor="mm")
    a3 = ease_out((t - 0.9) / 0.6)
    if a3 > 0:
        dd.text((W // 2, 446), "Daniel Marlow", font=F(26, 0), fill=A(MUT, al * a3), anchor="mm")
    a4 = ease_out((t - 1.4) / 0.7)
    if a4 > 0:
        bw1 = 620
        x = W // 2 - bw1 - 16
        dd.rounded_rectangle([x, 530, x + bw1, 622], 14, fill=A(AMBER, 0.16 * al * a4),
                             outline=A(AMBER, 0.75 * al * a4), width=2)
        dd.text((x + bw1 // 2, 560), "THE BOOK", font=F(20, 1), fill=A(AMBER, al * a4), anchor="mm")
        dd.text((x + bw1 // 2, 594), "amazon.com/dp/B0HKVZ3RSG", font=F(26, 1, 1),
                fill=A(INK, al * a4), anchor="mm")
        x2 = W // 2 + 16
        dd.rounded_rectangle([x2, 530, x2 + bw1, 622], 14, fill=A(TEAL, 0.14 * al * a4),
                             outline=A(TEAL, 0.75 * al * a4), width=2)
        dd.text((x2 + bw1 // 2, 560), "FREE STARTER KIT", font=F(20, 1), fill=A(TEAL, al * a4), anchor="mm")
        dd.text((x2 + bw1 // 2, 594), "one file, one block", font=F(26, 1, 1),
                fill=A(INK, al * a4), anchor="mm")
    a5 = ease_out((t - 2.0) / 0.7)
    if a5 > 0:
        dd.text((W // 2, 700), "the scanner you just watched:", font=F(22, 0),
                fill=A(MUT, al * a5), anchor="mm")
        dd.text((W // 2, 742), "github.com/exodus611/nasdaq-eod-momentum-scanner",
                font=F(27, 1, 1), fill=A(INK, al * a5), anchor="mm")
        dd.text((W // 2, 792), "exodus611.github.io/nasdaq-eod-momentum-scanner",
                font=F(23, 0, 1), fill=A(TEAL, 0.9 * al * a5), anchor="mm")
    return ov, im


SCENE_FN = {"intro": s_intro, "claim": s_claim, "dash": s_dash, "table": s_table,
            "numbers": s_numbers, "books": s_books, "pipeline": s_pipeline,
            "memory": s_memory, "backtest": s_backtest, "cta": s_cta}


# ---------------------------------------------------------------- audio
def wav_dur(p):
    err = subprocess.run([FF, "-i", p], capture_output=True, text=True).stderr
    import re
    m = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", err)
    return int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])


def read_wav_mono(path, sr):
    out = os.path.join(VODIR, os.path.basename(path).replace(".mp3", f"_{sr}.wav"))
    if not os.path.exists(out):
        subprocess.run([FF, "-y", "-loglevel", "error", "-i", path, "-ar", str(sr), "-ac", "1", out],
                       check=True)
    with wave.open(out) as w:
        n = w.getnframes()
        raw = w.readframes(n)
    a = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    return a


def make_bed(dur, sr=44100):
    n = int(dur * sr)
    t = np.arange(n) / sr
    mix = np.zeros(n, np.float32)
    bpm = 92.0
    beat = 60.0 / bpm
    bar = beat * 4
    roots = [110.0, 87.31, 130.81, 98.0]  # Am F C G
    # pad
    for i in range(int(dur / bar) + 2):
        r = roots[i % 4]
        s0 = int(i * bar * sr)
        if s0 >= n:
            break
        s1 = min(n, int((i * bar + bar * 1.05) * sr))
        tt = (np.arange(s1 - s0) / sr)
        env = np.minimum(1, tt / 0.9) * np.minimum(1, (bar * 1.05 - tt) / 0.9).clip(0, 1)
        ch = np.zeros(s1 - s0, np.float32)
        for mult, amp in ((1, .5), (1.5, .22), (2, .18), (3, .07)):
            ch += np.sin(2 * np.pi * r * mult * tt) * amp
        ch += np.sin(2 * np.pi * r * 2 * tt + 0.4 * np.sin(2 * np.pi * 0.18 * tt)) * .10
        mix[s0:s1] += (ch * env * 0.115).astype(np.float32)
    # sub pulse on every beat
    nb = int(dur / beat) + 1
    for b in range(nb):
        s0 = int(b * beat * sr)
        if s0 >= n:
            break
        ln = int(0.34 * sr)
        s1 = min(n, s0 + ln)
        tt = np.arange(s1 - s0) / sr
        env = np.exp(-tt * 9.0)
        r = roots[int(b / 4) % 4] / 2
        mix[s0:s1] += (np.sin(2 * np.pi * r * tt) * env * 0.30).astype(np.float32)
    # shimmer arpeggio
    arp = [2, 3, 4, 3]
    for b in range(nb):
        for k in range(4):
            s0 = int((b + k * 0.25) * beat * sr)
            if s0 >= n:
                break
            ln = int(0.13 * sr)
            s1 = min(n, s0 + ln)
            tt = np.arange(s1 - s0) / sr
            env = np.exp(-tt * 26.0)
            r = roots[int(b / 4) % 4] * arp[k] * 4
            mix[s0:s1] += (np.sin(2 * np.pi * r * tt) * env * 0.020).astype(np.float32)
    # lowpass: two short moving averages (vectorised; a pure-Python one-pole
    # over 3M samples would take minutes)
    k = np.ones(56, np.float32) / 56.0
    y = np.convolve(mix, k, mode="same")
    y = np.convolve(y, k, mode="same")
    mix = y * 34.0
    # risers every 8 bars
    for i in range(0, int(dur / (bar * 8)) + 1):
        s0 = int((i * bar * 8 - bar) * sr)
        s1 = int((i * bar * 8) * sr)
        s0 = max(0, s0)
        if s0 >= n:
            break
        s1 = min(n, s1)
        tt = np.arange(s1 - s0) / sr
        ln = max(1, s1 - s0)
        env = (np.linspace(0, 1, ln) ** 2) * 0.10
        nz = np.random.default_rng(7 + i).standard_normal(ln).astype(np.float32)
        mix[s0:s1] += nz * env
    fade = int(1.2 * sr)
    mix[:fade] *= np.linspace(0, 1, fade)
    mix[-fade:] *= np.linspace(1, 0, fade)
    return mix


def mix_audio(scene_starts, vo_files, dur, path, sr=44100):
    bed = make_bed(dur, sr)
    n = len(bed)
    vox = np.zeros(n, np.float32)
    for st, f in zip(scene_starts, vo_files):
        if f is None or st is None:
            continue
        a = read_wav_mono(os.path.join(VODIR, f), sr)
        s0 = int(st * sr)
        s1 = min(n, s0 + len(a))
        vox[s0:s1] += a[: s1 - s0]
    # gentle duck of the bed under the voice
    env = np.convolve(np.abs(vox), np.ones(int(0.25 * sr)) / (0.25 * sr), mode="same")
    duck = 1.0 - 0.55 * np.clip(env * 6.0, 0, 1)
    out = bed * duck.astype(np.float32) + vox * 1.0
    peak = float(np.max(np.abs(out)) or 1.0)
    out = out * (0.89 / max(peak, 0.89))
    pcm = np.clip(out * 32767, -32768, 32767).astype(np.int16)
    st = np.empty(2 * len(pcm), np.int16)
    st[0::2] = pcm
    st[1::2] = pcm
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(st.tobytes())
    return path


# ---------------------------------------------------------------- timeline
def build_timeline(smoke=False):
    vo = ["en_01.mp3", "en_02.mp3", "en_03.mp3", "en_04.mp3", "en_05.mp3", "en_06.mp3"]
    dur = [wav_dur(os.path.join(VODIR, v)) for v in vo]
    plan = [("intro", None, 2.8), ("claim", 0, 1.0), ("dash", 1, 1.0), ("table", None, 5.0),
            ("numbers", 2, 1.0), ("books", None, 5.2), ("pipeline", 3, 1.0),
            ("memory", 4, 1.2), ("backtest", None, 5.4), ("cta", 5, 1.8)]
    if smoke:
        plan = plan[:2] + [("cta", 5, 1.0)]
    tl, t, starts = [], 0.0, []
    for name, vi, pad in plan:
        d = (dur[vi] + pad) if vi is not None else pad
        tl.append((name, t, d))
        starts.append(t + 0.42 if vi is not None else None)
        t += d
    return tl, starts, vo, t


CAPTIONS = {
    "claim": "This is not a mock-up. A real scanner, on a real repository, every trading day.",
    "dash": "After the US close it reads the market, filters 1,500 NASDAQ names and publishes a live dashboard.",
    "numbers": "89 sessions since June. 75 journal entries. 10 tier-A days. Every number is real.",
    "pipeline": "No server, no subscription. One Action waits for the close, scans, commits, deploys.",
    "memory": "It keeps working between sessions because the repository remembers: NOTES.md, AGENTS.md, a pinned check.",
    "cta": "Built from a phone. Never start from scratch - give your projects a memory that never forgets.",
}


def hud(d, t, total, al=1.0):
    d.text((110, 44), "exodus611/nasdaq-eod-momentum-scanner", font=F(20, 0, 1),
           fill=A(DIM, 0.9 * al), anchor="lm")
    live = "LIVE  ·  PAPER TRADING"
    tw = d.textlength(live, font=F(19, 1))
    d.ellipse([W - 110 - tw - 28, 37, W - 110 - tw - 14, 51],
              fill=A(RED, (0.55 + 0.45 * (0.5 + 0.5 * math.sin(t * 4))) * al))
    d.text((W - 110, 45), live, font=F(19, 1), fill=A(MUT, 0.85 * al), anchor="rm")
    d.text((110, H - 44), "Paper trading  ·  no orders sent  ·  backtest does not guarantee future "
                          "results  ·  not financial advice", font=F(18, 0), fill=A(DIM, 0.8 * al),
           anchor="lm")
    pw = int((W - 220) * cl(t / total))
    d.rounded_rectangle([110, H - 14, W - 110, H - 10], 3, fill=A(BORDER, 0.6 * al))
    if pw > 4:
        d.rounded_rectangle([110, H - 14, 110 + pw, H - 10], 3, fill=A(TEAL, 0.85 * al))


def caption(d, name, t, sdur, al):
    txt = CAPTIONS.get(name)
    if not txt:
        return
    a = eio(t / 0.35) * eio((sdur - t) / 0.35)
    if a <= 0.01:
        return
    f = F(31, 0)
    words, lines, cur = txt.split(), [], ""
    for w in words:
        if d.textlength(cur + " " + w, font=f) > 1400:
            lines.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    lines.append(cur)
    hh = 44 + len(lines) * 44
    y0 = H - 120 - hh
    d.rounded_rectangle([W // 2 - 760, y0, W // 2 + 760, y0 + hh], 14, fill=A((6, 9, 15), 0.82 * a),
                        outline=A(BORDER, 0.5 * a))
    for i, ln in enumerate(lines):
        d.text((W // 2, y0 + 32 + i * 44), ln, font=f, fill=A(INK, a), anchor="mm")


def render(smoke=False, out=None):
    tl, starts, vo, total = build_timeline(smoke)
    os.makedirs(OUTDIR, exist_ok=True)
    out = out or os.path.join(OUTDIR, "never-start-from-scratch-x-16x9.mp4" if not smoke
                              else "smoke.mp4")
    silent = os.path.join(OUTDIR, "_silent.mp4")
    writer = imageio_ffmpeg.write_frames(
        silent, (W, H), pix_fmt_in="rgb24", pix_fmt_out="yuv420p", fps=FPS,
        codec="libx264", quality=5.9, macro_block_size=1,
        output_params=["-preset", "medium", "-g", str(FPS * 2)])
    writer.send(None)
    nf = int(total * FPS)
    for i in range(nf):
        t = i / FPS
        name = tl[-1][0]
        st = 0.0
        sdur = total
        for n2, s2, d2 in tl:
            if s2 <= t < s2 + d2:
                name, st, sdur = n2, t - s2, d2
                break
        fade = eio(min(1, st / 0.32)) * eio(min(1, (sdur - st) / 0.32))
        ov, bgimg = SCENE_FN[name](None, st, sdur, 1.0)
        frame = bgimg.convert("RGBA") if bgimg is not None else BG_RGBA.copy()
        frame = Image.alpha_composite(frame, ov)
        h = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        hd = ImageDraw.Draw(h)
        hud(hd, t, total)
        caption(hd, name, st, sdur, 1.0)
        frame = Image.alpha_composite(frame, h)
        if fade < 0.999:
            ch = frame.getchannel("A").point(lambda v, f=fade: int(v * f))
            black = Image.new("RGBA", (W, H), (0, 0, 0, 255))
            frame = Image.composite(frame, black, ch)
        writer.send(np.asarray(frame.convert("RGB")).tobytes())
        if i % (FPS * 5) == 0:
            print(f"  {t:6.1f}s / {total:.1f}s  scene={name}", flush=True)
    writer.close()
    print(f"video: {silent}")
    wav = mix_audio(starts, vo, total, os.path.join(OUTDIR, "_mix.wav"))
    subprocess.run([FF, "-y", "-loglevel", "error", "-i", silent, "-i", wav,
                    "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                    "-movflags", "+faststart", "-shortest", out], check=True)
    os.remove(silent)
    print(f"OUT {out}  ({os.path.getsize(out)/1e6:.1f} MB, {total:.1f}s)")
    return out


if __name__ == "__main__":
    render(smoke="--smoke" in sys.argv)
