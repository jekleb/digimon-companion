#!/usr/bin/env python3
"""8-bit presentation layer: animation frames, the 'charging' XP bar, and the
one-line idle / training renderers used by the status bar, plus the multi-line
scenes used by `digimon_cli.py live`. Pure formatting — no state, no I/O — so it
stays testable and the animation is a deterministic function of a clock value.

Every renderer takes an explicit `t` (a float, normally time.time()); the frame
shown is int(t * FPS) % len(frames). Passing the clock in keeps frames pinnable
in tests and makes the whole layer side-effect free."""
import colorsys
import os

import digimon_lib as dl

FPS = 2  # animation frames per second (auras, shimmer, clash glyphs)

# The sprite's own frame cycle, kept separate from FPS: the pet's body should
# read as a deliberate 8-bit two-frame loop, and it speeds up when sparring.
SPRITE_FPS_IDLE = 2
SPRITE_FPS_TRAINING = 4

# Each prestige rank rotates the whole palette's hue by the golden-ratio
# fraction, so consecutive rebirth "lives" land ~137° apart on the color wheel —
# maximally distinct from one another rather than a slow drift.
SHINY_HUE_STEP = 0.381966

# subagent_type -> (emoji, short display label). Unknown agents fall back to a
# generic icon with their raw name, so custom agents still read sensibly.
AGENT_STYLES = {
    "ekleberry":         ("✍️", "Ekleberry"),
    "cosmic-code":       ("🚀", "Cosmic Code"),
    "lumalith":          ("🖨️", "Lumalith"),
    "coloring-books":    ("🖍️", "Coloring Books"),
    "thrivemade":        ("🛒", "ThriveMade"),
    "oak-canna":         ("🌿", "OAK Canna"),
    "trading-analyst":   ("📈", "Trading"),
    "general-purpose":   ("🛠️", "General"),
    "Explore":           ("🔍", "Explore"),
    "Plan":              ("📐", "Plan"),
    "claude-code-guide": ("🧭", "CC Guide"),
    "statusline-setup":  ("⚙️", "Statusline"),
    "claude":            ("✨", "Claude"),
}
DEFAULT_AGENT_ICON = "🤖"

# animation cycles ---------------------------------------------------------
# gentle twinkle while resting — kept clear of ★✦✧❖ so it never reads as a
# prestige badge when the pet has no prestige
IDLE_AURA = ["·", "˖", "∘", "˖"]
TRAIN_CLASH = ["⚔️", "💥", "✨", "🔥"]        # sparring impact between pet & agent
SHIMMER_EDGE = ["▏", "▎", "▍", "▌", "▋", "▊", "▉", "█"]  # the "charging" leading cell
# multi-line dojo action for the CLI live scene
DOJO_ACTION = [
    ("  ᕦ( •̀_•́ )ᕤ  ", "swings"),
    ("  ᕦ(╹◡╹)ᕤ  ", "lands a hit"),
    ("  \\(^o^)/  ", "combo!"),
    ("  ᕦ(・ө・)ᕤ  ", "resets stance"),
]


def frame_index(t, n, fps=FPS):
    if n <= 0:
        return 0
    return int(t * fps) % n


# ------------------------------------------------------------------------
# 8-bit pixel sprites. Each stage stores a `sprite` — either one frame (a list
# of equal-length rows of single-char palette keys) or a list of such frames for
# an animation — and the file stores a shared `palette`
# (key -> "#rrggbb", or null for transparent). We render with the half-block
# trick: one text row = two pixel rows, the upper pixel painted as the glyph's
# foreground and the lower as its background — so pixels come out ~square and
# the vertical resolution doubles. Falls back to a monochrome block silhouette
# when the terminal has no color.
# ------------------------------------------------------------------------
def supports_color(stream):
    try:
        return bool(stream.isatty()) and os.environ.get("NO_COLOR") is None
    except Exception:
        return False


def _hex_to_rgb(h):
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def shiny_palette(palette, prestige):
    """Return a hue-rotated 'shiny' copy of the palette for the given prestige
    rank, so every rebirth life is a visibly different color. Prestige 0 returns
    the palette unchanged. Transparent entries stay transparent; near-neutral
    colors (outline, white) barely move because rotation preserves saturation."""
    if not prestige:
        return palette
    shift = (prestige * SHINY_HUE_STEP) % 1.0
    out = {}
    for key, hexv in palette.items():
        if not hexv:
            out[key] = hexv
            continue
        r, g, b = (c / 255.0 for c in _hex_to_rgb(hexv))
        h, l, s = colorsys.rgb_to_hls(r, g, b)
        h = (h + shift) % 1.0
        s = min(1.0, s * 1.08)  # small saturation pop for the "shiny" read
        r2, g2, b2 = colorsys.hls_to_rgb(h, l, s)
        out[key] = "#{:02x}{:02x}{:02x}".format(round(r2 * 255), round(g2 * 255), round(b2 * 255))
    return out


def render_sprite(rows, palette, color=True):
    """Return the sprite as a list of rendered text lines."""
    if not rows:
        return []
    width = max(len(r) for r in rows)
    rows = [r.ljust(width) for r in rows]
    if len(rows) % 2:
        rows = rows + [" " * width]  # pad to an even number of pixel rows

    def rgb(ch):
        hexv = palette.get(ch)
        return _hex_to_rgb(hexv) if hexv else None

    out = []
    for i in range(0, len(rows), 2):
        top, bot = rows[i], rows[i + 1]
        cells = []
        for x in range(width):
            tc, bc = rgb(top[x]), rgb(bot[x])
            if not color:
                cells.append("█" if (tc and bc) else "▀" if tc else "▄" if bc else " ")
                continue
            if tc is None and bc is None:
                cells.append("\033[0m ")
            elif tc is not None and bc is not None:
                cells.append(f"\033[38;2;{tc[0]};{tc[1]};{tc[2]};48;2;{bc[0]};{bc[1]};{bc[2]}m▀")
            elif tc is not None:
                cells.append(f"\033[0;38;2;{tc[0]};{tc[1]};{tc[2]}m▀")
            else:
                cells.append(f"\033[0;38;2;{bc[0]};{bc[1]};{bc[2]}m▄")
        out.append("".join(cells) + ("\033[0m" if color else ""))
    return out


def sprite_frames(stage):
    """A stage's sprite as a LIST OF FRAMES, whatever shape the data file uses.

    `sprite` may be either a single frame (a list of row strings) or a list of
    frames (a list of lists of row strings). Normalising here means every caller
    animates for free and a stage that hasn't been given a second frame yet keeps
    working untouched — the frame index just always lands on 0."""
    sprite = stage.get("sprite")
    if not sprite:
        return []
    if isinstance(sprite[0], str):   # a bare frame
        return [sprite]
    return [f for f in sprite if f]


def stage_art_lines(stage, palette=None, color=False, prestige=0, frame=0):
    """Rendered pixel sprite for a stage, recolored for the prestige rank, with a
    fallback to the legacy ASCII art when a stage has no sprite. `frame` selects
    the animation frame and wraps, so callers can pass a free-running counter."""
    frames = sprite_frames(stage)
    if frames:
        pal = shiny_palette(palette or {}, prestige)
        return render_sprite(frames[frame % len(frames)], pal, color=color)
    return list(stage.get("art") or [])


def agent_style(name):
    """(emoji, label) for a subagent_type. Unknown -> generic icon + raw name."""
    if not name:
        return (DEFAULT_AGENT_ICON, "agent")
    if name in AGENT_STYLES:
        return AGENT_STYLES[name]
    return (DEFAULT_AGENT_ICON, name)


def shimmer_bar(frac, width, t, fill="█", empty="░"):
    """A progress bar whose leading edge cell animates through partial blocks,
    so the XP bar visibly 'charges' instead of sitting static."""
    frac = max(0.0, min(1.0, frac))
    full = int(frac * width)
    if full >= width:
        return fill * width
    edge = SHIMMER_EDGE[frame_index(t, len(SHIMMER_EDGE))]
    return fill * full + edge + empty * (width - full - 1)


def level_label(snap, short=False):
    if snap["maxed_out"]:
        return "MAX"
    if short:
        return f"Lv.{snap['level']}"
    return f"Lv.{snap['level']}/{snap['cap']}"


def idle_line(name, snap, t, elem_badge=""):
    """Compact resting readout for the status bar (single line, no newline).
    `elem_badge` is the pet's elemental-trait emoji run (digimon_elements.badge)."""
    stage = snap["stage"]
    aura = IDLE_AURA[frame_index(t, len(IDLE_AURA))]
    bar = shimmer_bar(snap["level_progress_frac"], 10, t)
    star = dl.prestige_badge(snap.get("prestige", 0))
    return (
        f"{stage['emoji']}{star}{elem_badge}{aura} {name} · {stage['name']} {level_label(snap)} "
        f"[{bar}] {dl.human_tokens(snap['total_tokens'])} tok"
    )


def _elapsed_str(started, t):
    if started is None:
        return ""
    secs = max(0, int(t - started))
    if secs < 60:
        return f"{secs}s"
    return f"{secs // 60}m"


def training_line(name, snap, active, t, elem_badge=""):
    """Status-bar line shown while ≥1 subagent is running: the pet is sparring
    with the newest agent; extra concurrent agents are summarised as '+N'."""
    lead = active[0]
    emoji, label = agent_style(lead.get("agent"))
    clash = TRAIN_CLASH[frame_index(t, len(TRAIN_CLASH))]
    extra = f" +{len(active) - 1}" if len(active) > 1 else ""
    bar = shimmer_bar(snap["level_progress_frac"], 8, t)
    elapsed = _elapsed_str(lead.get("started"), t)
    tail = f" ⏱{elapsed}" if elapsed else ""
    star = dl.prestige_badge(snap.get("prestige", 0))
    return (
        f"{snap['stage']['emoji']}{star}{elem_badge}{clash}{emoji} {name} training w/ {label}{extra} "
        f"· {level_label(snap, short=True)} [{bar}]{tail}"
    )


# ------------------------------------------------------------------------
# Multi-line 8-bit scenes for `digimon_cli.py live` (roomier than the bar).
# ------------------------------------------------------------------------
def idle_scene(name, snap, t, palette=None, color=False):
    stage = snap["stage"]
    frame = frame_index(t, len(sprite_frames(stage)) or 1, fps=SPRITE_FPS_IDLE)
    art = stage_art_lines(stage, palette, color, snap.get("prestige", 0), frame) or [stage["emoji"]]
    aura = IDLE_AURA[frame_index(t, len(IDLE_AURA))]
    bar = shimmer_bar(snap["level_progress_frac"], 24, t)
    lines = [""]
    lines.append(f"   {stage['emoji']} {name} {aura}  —  {stage['name']} ({level_label(snap)})")
    lines.append(f"   \"{stage['tagline']}\"")
    lines.append("")
    lines += [f"      {row}" for row in art]
    lines.append("")
    lines.append(f"   XP [{bar}]  {dl.human_tokens(snap['total_tokens'])} tok")
    lines.append("")
    return "\n".join(lines)


def training_scene(name, snap, active, t, palette=None, color=False):
    stage = snap["stage"]
    frame = frame_index(t, len(sprite_frames(stage)) or 1, fps=SPRITE_FPS_TRAINING)
    art = stage_art_lines(stage, palette, color, snap.get("prestige", 0), frame) or [stage["emoji"]]
    lead = active[0]
    emoji, label = agent_style(lead.get("agent"))
    action, verb = DOJO_ACTION[frame_index(t, len(DOJO_ACTION))]
    clash = TRAIN_CLASH[frame_index(t, len(TRAIN_CLASH))]
    bar = shimmer_bar(snap["level_progress_frac"], 24, t)
    extra = f"  (+{len(active) - 1} more agent{'s' if len(active) > 2 else ''})" if len(active) > 1 else ""
    elapsed = _elapsed_str(lead.get("started"), t)

    lines = [""]
    lines.append(f"   ⚔️  TRAINING SESSION{extra}")
    lines.append(f"   {name} {clash} {emoji} {label}" + (f"   ⏱ {elapsed}" if elapsed else ""))
    if lead.get("desc"):
        lines.append(f"   ▸ {lead['desc']}")
    lines.append("")
    lines += [f"      {row}" for row in art]
    lines.append(f"   {action} {name} {verb}!")
    lines.append("")
    lines.append(f"   XP [{bar}]  {level_label(snap)}")
    lines.append("")
    return "\n".join(lines)
