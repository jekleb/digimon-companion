#!/usr/bin/env python3
"""Elemental traits: the pet picks up the element of whatever it is fed.

Every token the Stop hook counts is also credited to an ELEMENT, chosen from the
session's working directory (cosmic_code -> Astral, printing_3d -> Forge, ...;
the table lives in evolution_data.json under `elements`). At each evolution the
pet keeps ONE trait: the element it was fed most during the stage it is leaving
— or the element the user *chose* with `digimon_cli.py attune <element>`, which
always wins. Traits stack across the life; at rebirth the life's strongest
element is inherited as the new Egg's first trait, so a bloodline carries on.

Purely cosmetic: traits never touch XP, levels or the curve.

The look is generated, not hand-drawn per element: `dress()` takes the stage's
own sprite frame and scatters element particles into the transparent pixels
around the body (flames rise off the top, droplets drip down the sides, sparks
crackle at the edges, ...). Particles only ever land on transparent pixels, so
they can never damage the creature art — the failure mode a palette swap had.
"""
import digimon_sprites as sprites

# Elements with no project folder behind them. Aether still earns a trait when
# it is the ONLY thing the pet was fed during a stage, but it never outvotes
# real project work — otherwise the busy workspace root would win every stage.
NEUTRAL_ELEMENT = "aether"

# Particle count for the primary element by how many traits of it the life has
# banked. Index = trait count (capped at the last entry).
PRIMARY_PARTICLES = [0, 3, 4, 5, 6]
SECONDARY_PARTICLES = [0, 2, 2, 3, 4]
# Trait count at which an element is "attuned": the pet's outline itself takes
# on the element's colour, on top of the particles.
ATTUNED_AT = 4


MOTIFS = ("rise", "sprout", "drip", "spark", "gust", "twinkle", "shard", "prism")
REQUIRED_ELEMENT_FIELDS = ("name", "emoji", "motif", "colors", "match")


def validate_elements(data):
    """Art-side validation for the `elements` table (doctor + tests only, never
    the hook — like sprites, a bad element must not stop token tracking).
    Colour keys must be single characters that collide with neither the base
    palette nor another element, or a particle would silently repaint the body."""
    elements = data.get("elements") or {}
    if NEUTRAL_ELEMENT not in elements:
        raise ValueError(f"elements must define the neutral {NEUTRAL_ELEMENT!r} element")
    taken = set(data.get("palette") or {})
    for key, spec in elements.items():
        missing = [f for f in REQUIRED_ELEMENT_FIELDS if f not in spec]
        if missing:
            raise ValueError(f"element {key!r} missing field(s) {missing}")
        if spec["motif"] not in MOTIFS:
            raise ValueError(f"element {key!r} motif {spec['motif']!r} is not one of {MOTIFS}")
        colors = spec["colors"]
        if not colors:
            raise ValueError(f"element {key!r} needs at least one colour")
        for ch, hexv in colors.items():
            if len(ch) != 1:
                raise ValueError(f"element {key!r} colour key {ch!r} must be one character")
            if ch in taken:
                raise ValueError(f"element {key!r} colour key {ch!r} is already used")
            if not (isinstance(hexv, str) and len(hexv) == 7 and hexv.startswith("#")):
                raise ValueError(f"element {key!r} colour {ch!r} is not #rrggbb: {hexv!r}")
            taken.add(ch)


# --------------------------------------------------------------------------
# Attribution
# --------------------------------------------------------------------------
def element_for_cwd(cwd, elements):
    """Element key for a working directory. Matches any path component against
    each element's `match` list (case-insensitive); first element wins. Anything
    unmatched — the workspace root, a stray folder — is the neutral element."""
    parts = {p.lower() for p in (cwd or "").replace("\\", "/").split("/") if p}
    for key, spec in elements.items():
        if any(m.lower() in parts for m in spec.get("match", [])):
            return key
    return NEUTRAL_ELEMENT


def dominant_element(tally):
    """The element fed most, preferring any real element over the neutral one.
    Ties break on key order, so the result is deterministic. None if empty."""
    fed = {k: v for k, v in (tally or {}).items() if v > 0}
    if not fed:
        return None
    real = {k: v for k, v in fed.items() if k != NEUTRAL_ELEMENT}
    pool = real or fed
    return max(sorted(pool), key=lambda k: pool[k])


def credit(state, element, tokens):
    """Credit `tokens` of work to `element`, lifetime and for the current stage."""
    if tokens <= 0:
        return
    for field in ("element_xp", "stage_element_xp"):
        tally = state.setdefault(field, {})
        tally[element] = tally.get(element, 0) + tokens


def gain_trait(state, stage_name, level):
    """Bank one trait for the stage just completed and reset the stage tally.

    A pending `attune` choice wins; otherwise the stage's dominant element.
    Returns (trait dict or None, runner_up element or None) — the runner-up is
    surfaced in the evolution message as the path not taken."""
    tally = state.get("stage_element_xp") or {}
    chosen = state.pop("attune", None)
    element = chosen or dominant_element(tally)
    runner_up = None
    others = {k: v for k, v in tally.items() if k != element}
    if others:
        runner_up = dominant_element(others)
    state["stage_element_xp"] = {}
    if not element:
        return None, runner_up
    trait = {"element": element, "stage": stage_name, "level": level, "chosen": bool(chosen)}
    state.setdefault("traits", []).append(trait)
    return trait, runner_up


def seed_from_history(state, elements):
    """One-time migration for a pet that predates elements. Rebuilds lifetime
    element_xp from the per-session token counts the hook already keeps (each
    session remembers its cwd), and gives the current life one starting trait —
    its lifetime strongest element — so an old pet is not drawn bare. Returns
    True if it seeded anything. Idempotent: a state that has element_xp is left
    alone."""
    if "element_xp" in state:
        return False
    tally = {}
    for info in (state.get("sessions_seen") or {}).values():
        if not isinstance(info, dict):
            continue
        k = element_for_cwd(info.get("cwd", ""), elements)
        tally[k] = tally.get(k, 0) + int(info.get("tokens", 0) or 0)
    state["element_xp"] = {k: v for k, v in tally.items() if v > 0}
    state.setdefault("stage_element_xp", {})
    if not state.get("traits"):
        first = dominant_element(state["element_xp"])
        state["traits"] = ([{"element": first, "stage": "Awakened", "level": 0, "chosen": False}]
                           if first else [])
    return True


def inherit_on_rebirth(state, prestige):
    """Archive this life's traits into the lineage and seed the new Egg with the
    life's strongest element, so the next life starts already leaning that way."""
    traits = state.get("traits") or []
    ranked = ranked_elements(traits)
    primary = ranked[0] if ranked else None
    state.setdefault("lineage", []).append({"prestige": prestige, "traits": traits})
    state["traits"] = []
    if primary:
        state["traits"].append({"element": primary, "stage": "Inherited", "level": 0, "chosen": False})
    state["stage_element_xp"] = {}
    return primary


def ranked_elements(traits):
    """Elements of a life ordered strongest first: most traits, ties broken by
    whichever was gained most recently (the pet leans toward what it is doing now)."""
    counts, last = {}, {}
    for i, t in enumerate(traits or []):
        k = t.get("element")
        if not k:
            continue
        counts[k] = counts.get(k, 0) + 1
        last[k] = i
    return sorted(counts, key=lambda k: (counts[k], last[k]), reverse=True)


def trait_counts(traits):
    counts = {}
    for t in traits or []:
        k = t.get("element")
        if k:
            counts[k] = counts.get(k, 0) + 1
    return counts


def title(stage, traits, elements):
    """Display title, e.g. 'Blazing Omniloadmon' — the primary element's epithet
    in front of the stage name. Attuned pets get the element's full title."""
    ranked = ranked_elements(traits)
    if not ranked or ranked[0] not in elements:
        return stage["name"]
    spec = elements[ranked[0]]
    n = trait_counts(traits)[ranked[0]]
    word = spec.get("attuned_epithet") if n >= ATTUNED_AT else spec.get("epithet")
    return f"{word} {stage['name']}" if word else stage["name"]


def badge(traits, elements, limit=3):
    """Compact emoji run for the status bar: one emoji per distinct element in
    the life, strongest first."""
    return "".join(elements[k]["emoji"] for k in ranked_elements(traits)[:limit] if k in elements)


# --------------------------------------------------------------------------
# Art: dress a sprite frame in its elements
# --------------------------------------------------------------------------
def _geometry(frame, palette):
    h, w = len(frame), len(frame[0])
    body = {(x, y) for y, row in enumerate(frame) for x, ch in enumerate(row) if palette.get(ch)}
    top, bottom, left, right = {}, {}, {}, {}
    for x, y in body:
        top[x] = min(top.get(x, y), y)
        bottom[x] = max(bottom.get(x, y), y)
        left[y] = min(left.get(y, x), x)
        right[y] = max(right.get(y, x), x)
    return w, h, body, top, bottom, left, right


def _free(p, w, h, body, used):
    x, y = p
    return 0 <= x < w and 0 <= y < h and p not in body and p not in used


def _spread(cands, k, offset=0):
    """k candidates picked evenly across the list (stable, deterministic)."""
    if k <= 0 or not cands:
        return []
    if k >= len(cands):
        return list(cands)
    step = len(cands) / k
    return [cands[int((i * step + offset) % len(cands))] for i in range(k)]


def _halo(w, h, body, used):
    """Transparent pixels touching the body — the fallback ring for crowded sprites."""
    out = []
    for y in range(h):
        for x in range(w):
            p = (x, y)
            if not _free(p, w, h, body, used):
                continue
            if any((x + dx, y + dy) in body for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))):
                out.append(p)
    return out


def _motif_points(motif, geo, k, frame_i, used):
    """[(x, y, tone)] for one element's particles. tone 0 = main colour,
    1 = highlight. Every motif moves between frame 0 and 1 so the particles
    animate with the body's own two-frame loop."""
    w, h, body, top, bottom, left, right = geo
    pts = []

    def crowded(x, y):
        return any(abs(a - x) <= 1 and abs(b - y) <= 1 for a, b, _ in pts)

    def put(x, y, tone, spaced=False):
        # spaced=True keeps lone sparkles from clumping into a line
        if spaced and crowded(x, y):
            return False
        if _free((x, y), w, h, body, used) and (x, y) not in {(a, b) for a, b, _ in pts}:
            pts.append((x, y, tone))
            return True
        return False

    if motif == "rise":           # flames / embers licking up off the top edge
        cols = [x for x in sorted(top) if top[x] >= 1]
        for i, x in enumerate(_spread(cols, k)):
            t = top[x]
            lift = (i + frame_i) % 2          # alternate columns flicker up and down
            put(x, t - 1, 0)
            if lift and t >= 2:
                put(x, t - 2, 1)
    elif motif == "sprout":       # leaves growing off the top, swaying
        cols = [x for x in sorted(top) if top[x] >= 1]
        for i, x in enumerate(_spread(cols, k)):
            t = top[x]
            put(x, t - 1, 0)
            sway = 1 if (i + frame_i) % 2 else -1
            if t >= 2:
                put(x + sway, t - 2, 1)
    elif motif == "drip":         # droplets running down the sides
        rows = [y for y in sorted(left) if y >= h // 3]
        for i, y in enumerate(_spread(rows, k)):
            side = left[y] - 1 if i % 2 == 0 else right[y] + 1
            yy = y + frame_i
            if not put(side, yy, i % 2):
                put(side, y, i % 2)
    elif motif == "spark":        # zig-zag sparks crackling at the edges
        rows = sorted(left)
        for i, y in enumerate(_spread(rows, k, offset=frame_i * 2)):
            side, out = (left[y] - 1, -1) if i % 2 == 0 else (right[y] + 1, 1)
            put(side, y, 0)
            put(side + out, y + (1 if frame_i else -1), 1)
    elif motif == "gust":         # short wind streaks sliding past the sides
        rows = sorted(left)
        for i, y in enumerate(_spread(rows, k, offset=frame_i)):
            if i % 2 == 0:
                put(left[y] - 1, y, 0)
                put(left[y] - 2, y, 1)
            else:
                put(right[y] + 1, y, 0)
                put(right[y] + 2, y, 1)
    else:                          # "twinkle" / "shard" / "prism": open-air sparkles
        far = [(x, y) for y in range(h) for x in range(w)
               if _free((x, y), w, h, body, used)
               and all((x + dx, y + dy) not in body for dx in (-1, 0, 1) for dy in (-1, 0, 1))]
        far.sort(key=lambda p: (p[1], p[0]))
        for i, (x, y) in enumerate(_spread(far, k, offset=frame_i * 3)):
            tone = (i + frame_i) % 2
            if put(x, y, tone, spaced=True) and motif == "shard" and y + 1 < h:
                put(x, y + 1, 1 - tone)
    # Crowded sprites (Omniloadmon, Aeonmon) have almost no open air: top up
    # from the ring hugging the body so every element still shows.
    if len(pts) < k:
        ring = _halo(w, h, body, used | {(a, b) for a, b, _ in pts})
        for i, (x, y) in enumerate(ring[(frame_i * 5) % max(1, len(ring)):] + ring):
            if len(pts) >= k:
                break
            put(x, y, (i + frame_i) % 2, spaced=True)
    return pts


def dress(stage, data, traits, prestige=0, frame_i=0):
    """(frame_rows, palette) for a stage, wearing its elements.

    The palette is the prestige-shiny palette plus every element's colours —
    element colours are added AFTER the hue rotation on purpose, so Forge stays
    fire-orange in every rebirth life instead of rotating to blue."""
    frames = sprites.sprite_frames(stage)
    base_pal = data.get("palette") or {}
    pal = dict(sprites.shiny_palette(base_pal, prestige))
    elements = data.get("elements") or {}
    for spec in elements.values():
        pal.update(spec.get("colors", {}))
    if not frames:
        return [], pal
    frame = frames[frame_i % len(frames)]
    ranked = [k for k in ranked_elements(traits) if k in elements]
    if not ranked:
        return list(frame), pal

    counts = trait_counts(traits)
    grid = [list(r) for r in frame]
    geo = _geometry(frame, base_pal)
    used = set()

    plan = [(ranked[0], PRIMARY_PARTICLES)]
    if len(ranked) > 1:
        plan.append((ranked[1], SECONDARY_PARTICLES))
    for key, table in plan:
        spec = elements[key]
        keys = list(spec["colors"])
        k = table[min(counts[key], len(table) - 1)]
        for x, y, tone in _motif_points(spec["motif"], geo, k, frame_i % 2, used):
            ch = keys[(tone + (x + y) * (spec["motif"] == "prism")) % len(keys)]
            grid[y][x] = ch
            used.add((x, y))

    # Attuned: the outer outline is redrawn in the primary element's colour — a
    # solid line (a checkerboard read as dust in the contact sheet), with a glint
    # of the highlight colour that steps along it between frames.
    if counts[ranked[0]] >= ATTUNED_AT:
        w, h, body, *_ = geo
        main, glint = (list(elements[ranked[0]]["colors"]) * 2)[:2]
        for (x, y) in body:
            if frame[y][x] != "K":
                continue
            if any(not (0 <= x + dx < w and 0 <= y + dy < h) or (x + dx, y + dy) not in body
                   for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))):
                grid[y][x] = glint if (x + y + 2 * frame_i) % 4 == 0 else main
    return ["".join(r) for r in grid], pal


def dressed_frames(stage, data, traits, prestige=0):
    """Every animation frame of a stage, dressed. Same length as the stage's own
    frame list, so callers keep animating exactly as before."""
    n = len(sprites.sprite_frames(stage))
    out, pal = [], None
    for f in range(n):
        frame, pal = dress(stage, data, traits, prestige, f)
        out.append(frame)
    return out, pal or {}


# --------------------------------------------------------------------------
# Read-only summary shared by the CLI, status line and menu-bar feed
# --------------------------------------------------------------------------
def summary(state, data):
    """Everything a viewer needs about the pet's elements, precomputed so the
    Swift app and the status line never re-derive the rules.

    Never mutates `state`: a pet that predates elements is summarised as if
    `seed_from_history` had run, so viewers look right before the next hook."""
    elements = data.get("elements") or {}
    if "element_xp" not in state:
        import copy
        state = copy.deepcopy(state)
        seed_from_history(state, elements)
    traits = [t for t in state.get("traits") or [] if t.get("element") in elements]
    counts = trait_counts(traits)
    ranked = ranked_elements(traits)

    tally = {k: v for k, v in (state.get("stage_element_xp") or {}).items() if v > 0}
    lead = dominant_element(tally)
    total = sum(tally.values())
    leaning = None
    if lead and lead in elements:
        leaning = {"key": lead, "emoji": elements[lead]["emoji"], "name": elements[lead]["name"],
                   "share": tally[lead] / total if total else 0.0}
    attune = state.get("attune")
    if attune not in elements:
        attune = None

    parts = []
    if ranked:
        parts.append("Traits " + " ".join(f"{elements[k]['emoji']}×{counts[k]}" for k in ranked))
    if attune:
        a = elements[attune]
        parts.append(f"next trait: {a['emoji']} {a['name']} (chosen)")
    elif leaning:
        parts.append(f"feeding {leaning['emoji']} {leaning['name']} {round(leaning['share'] * 100)}%")
    return {
        "traits": [{"key": k, "emoji": elements[k]["emoji"], "name": elements[k]["name"],
                    "count": counts[k], "attuned": counts[k] >= ATTUNED_AT} for k in ranked],
        "badge": badge(traits, elements),
        "leaning": leaning,
        "attune": attune,
        "lifetime": {k: v for k, v in (state.get("element_xp") or {}).items() if k in elements},
        "line": " · ".join(parts),
        "_traits": traits,   # raw list, for dress(); dropped by the feed
    }
