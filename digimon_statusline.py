#!/usr/bin/env python3
"""statusLine command: a compact, animated one-line companion readout.

Reads the status-line JSON payload on stdin (Claude Code passes session info
incl. `transcript_path`). If a subagent is currently running, the pet is shown
mid-training with that agent; otherwise it idles. Animation advances on each
status-bar refresh via a wall-clock frame index, so the companion looks alive."""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import digimon_lib as dl
import digimon_agents as da
import digimon_sprites as sprites
import digimon_elements as el


def render(payload):
    state = dl.load_state()
    data = dl.load_evolution_data()
    snap = dl.snapshot_from_state(state, data)
    name = state.get("name", dl.DEFAULT_NAME)
    t = time.time()

    transcript_path = payload.get("transcript_path") if isinstance(payload, dict) else None
    active = da.detect_active_agents(transcript_path)
    try:
        badge = el.summary(state, data)["badge"]
    except Exception:
        dl.log_error("digimon_statusline.elements")  # cosmetic — never blank the bar
        badge = ""
    if active:
        return sprites.training_line(name, snap, active, t, badge)
    return sprites.idle_line(name, snap, t, badge)


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = {}

    try:
        print(render(payload))
    except Exception:
        # The status bar must always emit *something* — never crash the prompt.
        dl.log_error("digimon_statusline.render")
        try:
            state = dl.load_state()
            print(f"🥚 {state.get('name', dl.DEFAULT_NAME)}")
        except Exception:
            print("🥚 Tokimon")


if __name__ == "__main__":
    main()
