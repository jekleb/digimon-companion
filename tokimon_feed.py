#!/usr/bin/env python3
"""JSON feed for the Tokimon macOS menu-bar companion.

The menu-bar app is written in Swift, but every rule about the pet — the XP
curve, the 16-stage tree, prestige recoloring — stays here in Python so there is
exactly one source of truth. This module emits a single flat JSON object the
Swift side can decode without knowing any of that math.

Unlike `digimon_statusline.py`, nothing hands us a `transcript_path`: the menu
bar lives outside any session. So we find the currently-live transcripts
ourselves (most recently written under ~/.claude/projects) and union their
active subagents, which is what makes the pet train while *any* session is
working.

Usage:
    tokimon_feed.py               # one JSON object on stdout
    tokimon_feed.py --watch 2.5   # a JSON line every 2.5s, forever
"""
import argparse
import glob
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import digimon_lib as dl
import digimon_agents as da
import digimon_sprites as sprites

PROJECTS_DIR = os.path.expanduser("~/.claude/projects")

# Only transcripts touched this recently can hold a running agent. Keeps the
# scan cheap and stops long-dead sessions from pinning the pet in "training".
TRANSCRIPT_FRESH_SECONDS = 600
MAX_TRANSCRIPTS = 4


def recent_transcripts(now=None, limit=MAX_TRANSCRIPTS):
    """Newest-first transcript paths written within TRANSCRIPT_FRESH_SECONDS."""
    now = time.time() if now is None else now
    found = []
    try:
        for path in glob.iglob(os.path.join(PROJECTS_DIR, "*", "*.jsonl")):
            try:
                mtime = os.path.getmtime(path)
            except OSError:
                continue
            if now - mtime <= TRANSCRIPT_FRESH_SECONDS:
                found.append((mtime, path))
    except OSError:
        return []
    found.sort(reverse=True)
    return [path for _, path in found[:limit]]


def active_agents(now=None):
    """Active subagents across every live session, newest first, deduped by id."""
    seen, out = set(), []
    for path in recent_transcripts(now=now):
        try:
            agents = da.detect_active_agents(path)
        except Exception:
            dl.log_error("tokimon_feed.detect_active_agents")
            continue
        for agent in agents:
            if agent["id"] in seen:
                continue
            seen.add(agent["id"])
            emoji, label = sprites.agent_style(agent.get("agent"))
            out.append({
                "id": agent["id"],
                "agent": agent.get("agent") or "",
                "label": label,
                "emoji": emoji,
                "desc": agent.get("desc") or "",
                "started": agent.get("started"),
            })
    out.sort(key=lambda e: (e["started"] is not None, e["started"] or 0), reverse=True)
    return out


def next_evolution(snap, data):
    """The upcoming stage and how many *lifetime* tokens away it is, or None at
    the ceiling. Mirrors `digimon_cli.py status` — effective tokens are divided
    back out by the prestige growth boost to get real spend."""
    upcoming = [s for s in data["stages"] if s["min"] > snap["level"]]
    if not upcoming:
        return None
    nxt = upcoming[0]
    needed = dl.tokens_for_level(nxt["min"], data["curve"])
    remaining_effective = max(0, needed - snap["effective_tokens"])
    return {
        "name": nxt["name"],
        "stage": nxt["stage"],
        "emoji": nxt["emoji"],
        "level": nxt["min"],
        "tokens_away": int(remaining_effective / (1 + snap["growth_bonus"])),
    }


def build_feed(now=None):
    state = dl.load_state()
    data = dl.load_evolution_data()
    snap = dl.snapshot_from_state(state, data)
    stage = snap["stage"]
    prestige = snap.get("prestige", 0)

    # Hand Swift the already-recolored palette so the shiny hue rotation lives
    # in one place; Swift just fills rects with the hexes it is given.
    palette = sprites.shiny_palette(data.get("palette") or {}, prestige)

    return {
        "ok": True,
        "generated": time.time() if now is None else now,
        "name": state.get("name", dl.DEFAULT_NAME),
        "stage": {
            "name": stage["name"],
            "stage": stage["stage"],
            "emoji": stage["emoji"],
            "tagline": stage.get("tagline", ""),
        },
        "level": snap["level"],
        "cap": snap["cap"],
        "ceiling": data["cap_tiers"][-1],
        "maxed_out": snap["maxed_out"],
        "progress": snap["level_progress_frac"],
        "tokens_into_level": snap["tokens_into_level"],
        "tokens_span_level": snap["tokens_span_level"],
        "prestige": prestige,
        "prestige_badge": dl.prestige_symbol(prestige) if prestige else "",
        "total_tokens": snap["total_tokens"],
        "total_tokens_human": dl.human_tokens(snap["total_tokens"]),
        "sprite": stage.get("sprite") or [],
        "palette": {k: v for k, v in palette.items() if v},
        "next_evolution": next_evolution(snap, data),
        "training": active_agents(now=now),
        "errors_24h": dl.recent_error_count(within_hours=24),
    }


def emit(now=None):
    """Print one feed line. Never raises — the menu bar must not go dark because
    a transcript was mid-write."""
    try:
        payload = build_feed(now=now)
    except Exception as exc:
        dl.log_error("tokimon_feed.build_feed")
        payload = {"ok": False, "error": str(exc)}
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


def main(argv=None):
    ap = argparse.ArgumentParser(description="JSON feed for the Tokimon menu-bar app")
    ap.add_argument("--watch", type=float, metavar="SECONDS",
                    help="emit a JSON line every SECONDS instead of exiting")
    args = ap.parse_args(argv)

    if not args.watch:
        emit()
        return 0

    interval = max(0.5, args.watch)
    while True:
        emit()
        time.sleep(interval)


if __name__ == "__main__":
    sys.exit(main())
