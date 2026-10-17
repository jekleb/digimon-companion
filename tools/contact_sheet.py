#!/usr/bin/env python3
"""Render sprites to a PNG contact sheet so the art can actually be LOOKED at.

Every art failure so far was invisible in the data and only showed up in a
render, so this exists to make "render and read it" a one-liner. Pure stdlib
(zlib + struct) — no Pillow on this Mac.

    python3 tools/contact_sheet.py out.png                   # every stage, both frames
    python3 tools/contact_sheet.py out.png --elements        # every stage x element
    python3 tools/contact_sheet.py out.png --stage Paramon --traits forge,forge,tide

Each sprite pixel is drawn as a SCALE x SCALE block on a dark card.
"""
import argparse
import os
import struct
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import digimon_lib as dl  # noqa: E402
import digimon_elements as el  # noqa: E402
import digimon_sprites as sprites  # noqa: E402

SCALE = 8
PAD = 6
BG = (14, 17, 32)
CARD = (22, 26, 46)


def _rgb(hexv):
    h = hexv.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def write_png(path, pixels):
    """pixels: list of rows, each a list of (r, g, b)."""
    h, w = len(pixels), len(pixels[0])
    raw = b"".join(b"\x00" + bytes(c for px in row for c in px) for row in pixels)

    def chunk(tag, body):
        return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF)

    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        f.write(chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)))
        f.write(chunk(b"IDAT", zlib.compress(raw, 9)))
        f.write(chunk(b"IEND", b""))


def sheet(cells, cols):
    """cells: list of (frame_rows, palette). Lays them out in a grid."""
    gh = max(len(c[0]) for c in cells)
    gw = max(len(c[0][0]) for c in cells)
    cw, ch = gw * SCALE + 2 * PAD, gh * SCALE + 2 * PAD
    rows = (len(cells) + cols - 1) // cols
    W, H = cols * cw + (cols + 1) * PAD, rows * ch + (rows + 1) * PAD
    img = [[BG] * W for _ in range(H)]
    for i, (frame, pal) in enumerate(cells):
        ox = PAD + (i % cols) * (cw + PAD)
        oy = PAD + (i // cols) * (ch + PAD)
        for y in range(ch):
            for x in range(cw):
                img[oy + y][ox + x] = CARD
        for y, row in enumerate(frame):
            for x, key in enumerate(row):
                hexv = pal.get(key)
                if not hexv:
                    continue
                c = _rgb(hexv)
                for dy in range(SCALE):
                    line = img[oy + PAD + y * SCALE + dy]
                    for dx in range(SCALE):
                        line[ox + PAD + x * SCALE + dx] = c
    return img


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--elements", action="store_true", help="one row per element, primary only")
    ap.add_argument("--stage", help="only this stage name")
    ap.add_argument("--traits", default="", help="comma list of element keys for a single render")
    ap.add_argument("--prestige", type=int, default=0)
    args = ap.parse_args(argv)

    data = dl.load_evolution_data()
    stages = [s for s in data["stages"] if not args.stage or s["name"] == args.stage]
    cells = []
    if args.elements:
        keys = list(data["elements"])
        for s in stages:
            for k in keys:
                traits = [{"element": k}] * 4  # fully attuned, so the strongest look is what gets reviewed
                for f in range(2):
                    frame, pal = el.dress(s, data, traits, args.prestige, f)
                    cells.append((frame, pal))
        cols = len(keys) * 2
    else:
        traits = [{"element": t} for t in args.traits.split(",") if t]
        for s in stages:
            for f in range(len(sprites.sprite_frames(s))):
                cells.append(el.dress(s, data, traits, args.prestige, f))
        cols = 8
    write_png(args.out, sheet(cells, cols))
    print(args.out)


if __name__ == "__main__":
    main()
