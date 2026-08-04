#!/usr/bin/env python3
"""Regenerate demo.gif — the pet climbing the whole tree, hitting the level
ceiling, and rebirthing with a shiny recolour.

Reads evolution_data.json and reuses the engine's own shiny_palette, so the
recolour in the demo is the one the pet actually does rather than a lookalike.
Re-run after any art change.

    python3 tools/make_demo.py            # needs Pillow

Lives in the repo on purpose: the previous generator was a throwaway in a temp
directory, so the day the art changed there was nothing left to regenerate with.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    raise SystemExit("this needs Pillow:  python3 -m pip install --user Pillow")

import digimon_lib as dl        # noqa: E402
import digimon_sprites as sprites  # noqa: E402

W, H = 540, 260
SCALE = 11                      # sprite pixel -> gif pixels
ART_X, ART_Y = 30, 40
TEXT_X = 250
BG = (14, 17, 32)
PANEL = (22, 26, 46)
FG = (223, 231, 245)
MUTED = (139, 155, 180)
GOLD = (255, 204, 51)
HOLD = 3                        # animation frames per stage
MS = 260                        # per-frame delay


def clip(text, limit=38):
    """Truncate on a word boundary. A hard character cut left taglines reading
    'Very few get her', which is worse than an ellipsis."""
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return (cut or text[:limit]).rstrip(",.;:") + "\u2026"


def font(size, bold=False):
    for path in ("/System/Library/Fonts/Menlo.ttc",
                 "/System/Library/Fonts/Supplemental/Andale Mono.ttf",
                 "/Library/Fonts/Arial.ttf"):
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


F_BIG, F_MID, F_SMALL = font(22), font(14), font(12)


def draw_sprite(dr, frame, palette, ox, oy):
    for y, row in enumerate(frame):
        for x, ch in enumerate(row):
            hexv = palette.get(ch)
            if not hexv:
                continue
            c = tuple(int(hexv[i:i + 2], 16) for i in (1, 3, 5))
            dr.rectangle([ox + x * SCALE, oy + y * SCALE,
                          ox + (x + 1) * SCALE - 1, oy + (y + 1) * SCALE - 1], fill=c)


def draw_bar(dr, x, y, w, h, frac, tint):
    segs, gap = 20, 2
    sw = (w - gap * (segs - 1)) / segs
    filled = int(max(0.0, min(1.0, frac)) * segs)
    for i in range(segs):
        x0 = x + i * (sw + gap)
        col = tint if i < filled else (48, 54, 82)
        dr.rectangle([x0, y, x0 + sw - 1, y + h], fill=col)


def compose(stage, palette, frame_idx, level, cap, frac, prestige, note=None):
    img = Image.new("RGB", (W, H), BG)
    dr = ImageDraw.Draw(img)
    dr.rectangle([16, 16, W - 16, H - 16], fill=PANEL)

    frames = sprites.sprite_frames(stage)
    draw_sprite(dr, frames[frame_idx % len(frames)], palette, ART_X, ART_Y)

    star = " " + dl.prestige_symbol(prestige) if prestige else ""
    dr.text((TEXT_X, 46), stage["name"] + star, font=F_BIG, fill=FG)
    dr.text((TEXT_X, 78), f'{stage["stage"].upper()}', font=F_SMALL, fill=GOLD)
    dr.text((TEXT_X, 100), f"Lv.{level} / {cap}", font=F_MID, fill=FG)
    draw_bar(dr, TEXT_X, 128, 240, 10, frac, GOLD if prestige else (95, 211, 255))
    dr.text((TEXT_X, 150), f'"{clip(stage["tagline"])}"', font=F_SMALL, fill=MUTED)
    if note:
        dr.text((TEXT_X, 186), note, font=F_MID, fill=GOLD)
    return img


def build():
    data = dl.load_evolution_data()
    dl.validate_sprites(data)
    base = data["palette"]
    stages = data["stages"]
    cap_top = data["cap_tiers"][-1]
    frames = []

    # climb the tree
    for stage in stages:
        cap = dl.current_cap(stage["min"], data["cap_tiers"])
        for k in range(HOLD):
            level = stage["min"] + (stage["max"] - stage["min"]) * k // max(1, HOLD - 1)
            span = max(1, stage["max"] - stage["min"])
            frames.append(compose(stage, base, k, level, cap,
                                  (level - stage["min"]) / span, 0))

    # the ceiling, then rebirth into a shiny first stage
    top = stages[-1]
    for k in range(4):
        frames.append(compose(top, base, k, cap_top, cap_top, 1.0, 0,
                              note="CEILING — REBIRTH READY"))

    shiny = sprites.shiny_palette(base, 1)
    for k in range(4):
        frames.append(compose(stages[0], shiny, k, 0, data["cap_tiers"][0], 0.0, 1,
                              note="REBIRTH · PRESTIGE 1"))
    for stage in stages[1:5]:
        cap = dl.current_cap(stage["min"], data["cap_tiers"])
        for k in range(2):
            frames.append(compose(stage, shiny, k, stage["min"], cap, 0.2, 1))
    return frames


def main():
    frames = build()
    out = os.path.join(REPO, "demo.gif")
    frames[0].save(out, save_all=True, append_images=frames[1:],
                   duration=MS, loop=0, optimize=True)
    size = os.path.getsize(out)
    print(f"wrote {out} ({len(frames)} frames, {size:,} bytes)")


if __name__ == "__main__":
    main()
