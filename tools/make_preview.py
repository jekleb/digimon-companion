#!/usr/bin/env python3
"""Regenerate preview.svg — the README's gallery of the whole evolution line.

Reads evolution_data.json, so the gallery can never drift from the real sprites;
re-run it after any art change. SVG (not a raster) so the pixels stay crisp at
any zoom and the file diffs as text.

    python3 tools/make_preview.py

Lives in the repo on purpose: the previous generator was a throwaway in a temp
directory, so the day the art changed there was nothing left to regenerate with.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)

import digimon_lib as dl  # noqa: E402

PX = 6                    # one sprite pixel, in SVG units
COLS = 4
CARD_W, CARD_H = 156, 186
GAP = 12
MARGIN = 28
HEADER = 78

BG = "#0e1120"
CARD_BG = "#161a2e"
CARD_EDGE = "#2a3150"
FG = "#dfe7f5"
MUTED = "#8b9bb4"
GOLD = "#ffcc33"


def esc(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def level_range(stage):
    lo, hi = stage["min"], stage["max"]
    return f"Lv.{lo}" if lo == hi else f"Lv.{lo}–{hi}"


def sprite_rects(frame, palette, ox, oy):
    """One <rect> per opaque pixel. Runs of the same colour are merged into a
    single wider rect — a 16x16 grid is 256 pixels a stage and the file is
    committed, so this roughly halves the diff without changing the render."""
    out = []
    for y, row in enumerate(frame):
        x = 0
        while x < len(row):
            hexv = palette.get(row[x])
            if not hexv:
                x += 1
                continue
            run = 1
            while x + run < len(row) and palette.get(row[x + run]) == hexv:
                run += 1
            out.append(
                f'<rect x="{ox + x * PX}" y="{oy + y * PX}" '
                f'width="{PX * run}" height="{PX}" fill="{hexv}"/>')
            x += run
    return out


def build():
    data = dl.load_evolution_data()
    dl.validate_sprites(data)
    palette = data["palette"]
    stages = data["stages"]
    rows = (len(stages) + COLS - 1) // COLS

    width = MARGIN * 2 + COLS * CARD_W + (COLS - 1) * GAP
    height = HEADER + rows * CARD_H + (rows - 1) * GAP + MARGIN

    art_px = max(len(f[0]) for s in stages for f in [s["sprite"][0]]) * PX
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" '
        f'font-family="ui-monospace,Menlo,Consolas,monospace">',
        f'<rect width="{width}" height="{height}" fill="{BG}"/>',
        f'<text x="{MARGIN}" y="42" fill="{FG}" font-size="26" font-weight="700" '
        f'letter-spacing="6">TOKIMON</text>',
        f'<text x="{MARGIN}" y="64" fill="{MUTED}" font-size="12" letter-spacing="3">'
        f'{len(stages)}-STAGE 8-BIT COMPANION · EGG → AEON</text>',
    ]

    for i, stage in enumerate(stages):
        cx = MARGIN + (i % COLS) * (CARD_W + GAP)
        cy = HEADER + (i // COLS) * (CARD_H + GAP)
        parts.append(
            f'<rect x="{cx}" y="{cy}" width="{CARD_W}" height="{CARD_H}" rx="10" '
            f'fill="{CARD_BG}" stroke="{CARD_EDGE}"/>')

        frame = stage["sprite"][0] if not isinstance(stage["sprite"][0], str) else stage["sprite"]
        ox = cx + (CARD_W - art_px) // 2
        parts += sprite_rects(frame, palette, ox, cy + 14)

        mid = cx + CARD_W // 2
        ty = cy + 14 + art_px + 22
        parts.append(f'<text x="{mid}" y="{ty}" fill="{FG}" font-size="13" '
                     f'font-weight="700" text-anchor="middle">{esc(stage["name"])}</text>')
        parts.append(f'<text x="{mid}" y="{ty + 16}" fill="{GOLD}" font-size="9.5" '
                     f'letter-spacing="1.5" text-anchor="middle">'
                     f'{esc(stage["stage"].upper())}</text>')
        parts.append(f'<text x="{mid}" y="{ty + 30}" fill="{MUTED}" font-size="10" '
                     f'text-anchor="middle">{level_range(stage)}</text>')

    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def main():
    out = os.path.join(REPO, "preview.svg")
    svg = build()
    with open(out, "w") as f:
        f.write(svg)
    print(f"wrote {out} ({len(svg):,} bytes)")


if __name__ == "__main__":
    main()
