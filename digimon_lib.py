#!/usr/bin/env python3
"""Core engine for the Digimon token-companion. No CLI/hook logic lives here."""
import json
import os

DIGIMON_DIR = os.path.expanduser("~/.claude/digimon")
STATE_PATH = os.path.join(DIGIMON_DIR, "state.json")
LOCK_PATH = os.path.join(DIGIMON_DIR, "state.lock")
ERROR_LOG_PATH = os.path.join(DIGIMON_DIR, "error.log")
DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "evolution_data.json")

DEFAULT_NAME = "Tokimon"
REQUIRED_STAGE_FIELDS = ("min", "max", "stage", "name", "emoji", "tagline")
MAX_ERROR_LOG_BYTES = 200_000
# Prestige: each time the companion loops the level ceiling it banks one ★ rank
# and a permanent growth boost. The boost scales the tokens that count toward
# leveling (effective_tokens), so every subsequent climb is faster. 0.06 = +6%
# per rank, i.e. ★★ -> +12%.
PRESTIGE_BOOST = 0.06
# A subagent spawn older than this with no completion line in the transcript
# tail is treated as finished, so the bar can't get stuck "training" forever
# after a crashed/resumed session. Real subagent runs finish well under an hour.
TRAINING_STALE_SECONDS = 3600


def load_evolution_data():
    with open(DATA_PATH) as f:
        return json.load(f)


def validate_evolution_data(data):
    """Catches the failure mode where stages/cap_tiers drift out of sync as
    the tree is extended later — raises loudly instead of silently mislabeling
    levels with the wrong cap."""
    stages = data["stages"]
    cap_tiers = data["cap_tiers"]
    curve = data["curve"]

    for i, s in enumerate(stages):
        missing = [f for f in REQUIRED_STAGE_FIELDS if f not in s]
        if missing:
            raise ValueError(f"stage index {i} missing required field(s): {missing}")

    expected_min = 0
    for s in stages:
        if s["min"] != expected_min:
            raise ValueError(f"stage {s['name']!r} min={s['min']} is not contiguous (expected {expected_min})")
        if s["max"] < s["min"]:
            raise ValueError(f"stage {s['name']!r} has max < min")
        expected_min = s["max"] + 1

    stage_maxes = {s["max"] for s in stages}
    for tier in cap_tiers:
        if tier not in stage_maxes:
            raise ValueError(f"cap tier {tier} does not align with any stage's max level")

    if stages[-1]["max"] != cap_tiers[-1]:
        raise ValueError(
            f"final stage max ({stages[-1]['max']}) does not match final cap tier ({cap_tiers[-1]})"
        )

    curve_boundaries = [seg["up_to_level"] for seg in curve]
    if curve_boundaries != list(cap_tiers):
        raise ValueError(
            f"curve segment boundaries {curve_boundaries} do not match cap_tiers {cap_tiers}"
        )


def validate_sprites(data):
    """Cosmetic validation for the 8-bit `palette` + per-stage `sprite` pixel
    grids. Kept OUT of validate_evolution_data (and the Stop hook) on purpose:
    a malformed sprite is an art bug, and must never stop token tracking. Called
    by `doctor` and the tests."""
    palette = data.get("palette", {})
    for key, val in palette.items():
        if val is not None and not (isinstance(val, str) and len(val) == 7 and val.startswith("#")):
            raise ValueError(f"palette[{key!r}] is not a #rrggbb hex or null: {val!r}")
    palette_keys = set(palette)
    for s in data["stages"]:
        spr = s.get("sprite")
        if spr is None:
            continue
        if not isinstance(spr, list) or not spr:
            raise ValueError(f"stage {s['name']!r} sprite must be a non-empty list of rows")
        # `sprite` is either one frame (list of row strings) or an animation
        # (list of frames). Both are valid so a stage can stay single-frame.
        frames = [spr] if isinstance(spr[0], str) else spr
        size = None
        for f, frame in enumerate(frames):
            where = f"stage {s['name']!r}" + (f" frame {f}" if len(frames) > 1 else "")
            if not isinstance(frame, list) or not frame or not all(isinstance(r, str) for r in frame):
                raise ValueError(f"{where} must be a non-empty list of row strings")
            width = len(frame[0])
            for i, row in enumerate(frame):
                if len(row) != width:
                    raise ValueError(f"{where} row {i} is not rectangular (width {width})")
                unknown = set(row) - palette_keys
                if unknown:
                    raise ValueError(f"{where} row {i} uses non-palette keys {sorted(unknown)}")
            # Frames that differ in size would make the pet jump around mid-loop.
            if size is None:
                size = (len(frame), width)
            elif (len(frame), width) != size:
                raise ValueError(
                    f"stage {s['name']!r} frame {f} is {len(frame)}x{width}, "
                    f"but frame 0 is {size[0]}x{size[1]} — every frame must match")


def tokens_for_level(level, curve):
    """Cumulative tokens required to reach `level`. Extends the last segment's
    rate indefinitely past the highest defined up_to_level, so adding new
    curve segments later just continues the character's existing progress."""
    if level <= 0:
        return 0
    total = 0
    prev_boundary = 0
    for seg in curve:
        up_to = seg["up_to_level"]
        coeff = seg["coefficient"]
        power = seg["power"]
        if level <= up_to:
            return total + coeff * (level - prev_boundary) ** power
        total += coeff * (up_to - prev_boundary) ** power
        prev_boundary = up_to
    last = curve[-1]
    return total + last["coefficient"] * (level - prev_boundary) ** last["power"]


def level_from_tokens(total_tokens, curve, max_level=100000):
    lo, hi = 0, max_level
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if tokens_for_level(mid, curve) <= total_tokens:
            lo = mid
        else:
            hi = mid - 1
    return lo


def current_cap(display_level, cap_tiers):
    for tier in cap_tiers:
        if display_level <= tier:
            return tier
    return cap_tiers[-1]


def get_stage(level, stages):
    for s in stages:
        if s["min"] <= level <= s["max"]:
            return s
    return stages[-1]


def progress_in_level(total_tokens, level, curve):
    lower = tokens_for_level(level, curve)
    upper = tokens_for_level(level + 1, curve)
    span = upper - lower
    if span <= 0:
        return 1.0, 0, 0
    frac = max(0.0, min(1.0, (total_tokens - lower) / span))
    return frac, total_tokens - lower, span


def compute_snapshot(total_tokens, data, prestige=0, rebirth_baseline=0):
    """Snapshot of the companion's current stage/level.

    Level is derived from the tokens earned SINCE the last rebirth
    (total_tokens - rebirth_baseline), scaled up by the prestige growth boost.
    total_tokens itself (the big lifetime number) is passed through untouched
    for display. prestige=0/baseline=0 reproduces the original behaviour exactly."""
    curve = data["curve"]
    cap_tiers = data["cap_tiers"]
    stages = data["stages"]
    max_defined_level = cap_tiers[-1]

    progress_tokens = max(0, total_tokens - rebirth_baseline)
    growth_bonus = PRESTIGE_BOOST * prestige
    effective_tokens = int(progress_tokens * (1 + growth_bonus))

    raw_level = level_from_tokens(effective_tokens, curve)
    display_level = min(raw_level, max_defined_level)
    cap = current_cap(display_level, cap_tiers)
    stage = get_stage(display_level, stages)
    maxed_out = display_level >= max_defined_level

    if maxed_out:
        frac, into, span = 1.0, 0, 0
        next_level_tokens = None
    else:
        frac, into, span = progress_in_level(effective_tokens, display_level, curve)
        next_level_tokens = tokens_for_level(display_level + 1, curve)

    return {
        "level": display_level,
        "cap": cap,
        "stage": stage,
        "maxed_out": maxed_out,
        "level_progress_frac": frac,
        "tokens_into_level": int(into),
        "tokens_span_level": int(span),
        "next_level_tokens": next_level_tokens,
        "total_tokens": total_tokens,
        "prestige": prestige,
        "growth_bonus": growth_bonus,
        "progress_tokens": progress_tokens,
        "effective_tokens": effective_tokens,
    }


def snapshot_from_state(state, data):
    """Convenience wrapper: compute_snapshot with the prestige/rebirth fields
    pulled from a loaded state dict. Used by every read-only viewer."""
    return compute_snapshot(
        state.get("total_tokens", 0),
        data,
        state.get("prestige", 0),
        state.get("rebirth_baseline", 0),
    )


def load_state():
    os.makedirs(DIGIMON_DIR, exist_ok=True)
    if not os.path.exists(STATE_PATH):
        return {
            "name": DEFAULT_NAME,
            "total_tokens": 0,
            "prestige": 0,
            "rebirth_baseline": 0,
            "sessions_seen": {},
            "evolution_history": [],
        }
    with open(STATE_PATH) as f:
        return json.load(f)


def save_state(state):
    os.makedirs(DIGIMON_DIR, exist_ok=True)
    tmp_path = STATE_PATH + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp_path, STATE_PATH)


def acquire_lock():
    """Returns an open file handle holding an exclusive lock. Caller must close() it."""
    import fcntl
    os.makedirs(DIGIMON_DIR, exist_ok=True)
    lf = open(LOCK_PATH, "w")
    fcntl.flock(lf, fcntl.LOCK_EX)
    return lf


def log_error(context):
    """Appends a timestamped traceback to the error log, rotating (keep-the-tail)
    once it exceeds MAX_ERROR_LOG_BYTES so it can't grow unbounded over years."""
    import traceback
    import datetime
    try:
        os.makedirs(DIGIMON_DIR, exist_ok=True)
        ts = datetime.datetime.now().isoformat(timespec="seconds")
        entry = f"--- {ts} | {context} ---\n{traceback.format_exc()}\n"
        if os.path.exists(ERROR_LOG_PATH) and os.path.getsize(ERROR_LOG_PATH) > MAX_ERROR_LOG_BYTES:
            with open(ERROR_LOG_PATH, "rb") as f:
                f.seek(-MAX_ERROR_LOG_BYTES // 2, os.SEEK_END)
                tail = f.read()
            with open(ERROR_LOG_PATH, "wb") as f:
                f.write(b"...[log rotated]...\n")
                f.write(tail)
        with open(ERROR_LOG_PATH, "a") as f:
            f.write(entry)
    except OSError:
        pass


def read_recent_errors(max_entries=5):
    if not os.path.exists(ERROR_LOG_PATH):
        return []
    try:
        with open(ERROR_LOG_PATH) as f:
            content = f.read()
    except OSError:
        return []
    entries = [e for e in content.split("--- ") if e.strip()]
    return entries[-max_entries:]


def recent_error_count(within_hours=24):
    """Only counts errors with a parseable, genuinely recent timestamp — an
    old error sitting in the log (e.g. from a one-off manual test) shouldn't
    keep flagging `status` as broken forever."""
    import datetime
    cutoff = datetime.datetime.now() - datetime.timedelta(hours=within_hours)
    count = 0
    for entry in read_recent_errors(max_entries=50):
        first_line = entry.strip().splitlines()[0] if entry.strip() else ""
        ts_str = first_line.split(" | ")[0].strip() if " | " in first_line else ""
        try:
            ts = datetime.datetime.fromisoformat(ts_str)
        except ValueError:
            continue  # old pre-timestamp entry format; not counted as "recent"
        if ts >= cutoff:
            count += 1
    return count


def format_int(n):
    return f"{n:,}"


def human_tokens(n):
    """Compact token count for the one-line status bar: 1,439,054,442 -> '1.4B'.
    Full comma-grouped form (format_int) is still used in the roomier CLI views."""
    n = int(n)
    if n < 1000:
        return str(n)
    # Divide up through the units, promoting to the next unit whenever rounding
    # to one decimal would spill to 1000 (so 999_950 -> "1M", not "1000K").
    val = float(n)
    suffix = ""
    for suffix in ("K", "M", "B", "T"):
        val /= 1000
        if round(val, 1) < 1000:
            break
    return f"{val:.1f}".rstrip("0").rstrip(".") + suffix


def prestige_symbol(prestige):
    """The emblem for a prestige rank — it levels up its symbol every tier so a
    high prestige reads as more prestigious at a glance."""
    if prestige >= 20:
        return "❖"
    if prestige >= 10:
        return "✧"
    if prestige >= 5:
        return "✦"
    return "★"


def prestige_badge(prestige):
    """Compact tiered badge for the status bar: 0 -> '', 1-3 -> literal emblems
    (★, ★★, ★★★), 4+ -> 'symbolN' (e.g. ✦7) so it never blows out the line and
    the symbol itself signals the tier."""
    if not prestige:
        return ""
    sym = prestige_symbol(prestige)
    return sym * prestige if prestige <= 3 else f"{sym}{prestige}"


def bar(frac, width=20, fill="█", empty="░"):
    frac = max(0.0, min(1.0, frac))
    filled = int(round(frac * width))
    return fill * filled + empty * (width - filled)
