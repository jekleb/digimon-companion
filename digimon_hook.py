#!/usr/bin/env python3
"""Stop hook: reads only the NEW bytes appended to the turn's transcript since
last run, sums real token usage, updates the companion's persistent state, and
(only on an evolution) emits a systemMessage."""
import json
import sys
import os
import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import digimon_lib as dl
import digimon_elements as el


def sum_usage_tokens(raw_bytes):
    total = 0
    for raw_line in raw_bytes.split(b"\n"):
        line = raw_line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("type") != "assistant":
            continue
        usage = (entry.get("message") or {}).get("usage")
        if not usage:
            continue
        total += (
            usage.get("input_tokens", 0)
            + usage.get("output_tokens", 0)
            + usage.get("cache_creation_input_tokens", 0)
            + usage.get("cache_read_input_tokens", 0)
        )
    return total


def scan_new_tokens(transcript_path, start_offset):
    """Returns (delta_tokens, new_offset). Only reads bytes appended since
    start_offset — cost is proportional to this turn's growth, not the whole
    transcript. A trailing partial line (file mid-write) is left unconsumed so
    it gets picked up whole on the next run."""
    try:
        size = os.path.getsize(transcript_path)
    except OSError:
        return 0, start_offset

    if start_offset > size:
        start_offset = 0  # file was replaced/truncated externally

    if start_offset == size:
        return 0, start_offset

    try:
        with open(transcript_path, "rb") as f:
            f.seek(start_offset)
            chunk = f.read()
    except OSError:
        return 0, start_offset

    if chunk.endswith(b"\n"):
        consumed = len(chunk)
        complete = chunk
    else:
        last_nl = chunk.rfind(b"\n")
        if last_nl == -1:
            return 0, start_offset  # no complete line yet
        consumed = last_nl + 1
        complete = chunk[:consumed]

    return sum_usage_tokens(complete), start_offset + consumed


def prune_missing_sessions(sessions_seen):
    for path in list(sessions_seen.keys()):
        if not os.path.exists(path):
            del sessions_seen[path]


def main():
    try:
        hook_input = json.load(sys.stdin)
    except json.JSONDecodeError:
        hook_input = {}

    transcript_path = hook_input.get("transcript_path")
    if not transcript_path:
        return
    cwd = hook_input.get("cwd", "")

    lock = dl.acquire_lock()
    evolved = rebirthed = False
    elements, inherited, trait, runner_up = {}, None, None, None
    try:
        state = dl.load_state()
        data = dl.load_evolution_data()
        dl.validate_evolution_data(data)

        sessions_seen = state.setdefault("sessions_seen", {})
        prune_missing_sessions(sessions_seen)

        # Backfill a pre-elements pet from session history BEFORE this turn's
        # tokens land in sessions_seen, or they would be counted twice.
        try:
            el.seed_from_history(state, data.get("elements") or {})
        except Exception:
            dl.log_error("digimon_hook.elements.seed")

        prev = sessions_seen.get(transcript_path, {"offset": 0, "tokens": 0})
        prev_offset = prev.get("offset", 0) if isinstance(prev, dict) else 0
        prev_session_tokens = prev.get("tokens", 0) if isinstance(prev, dict) else 0

        delta, new_offset = scan_new_tokens(transcript_path, prev_offset)
        sessions_seen[transcript_path] = {
            "offset": new_offset,
            "tokens": prev_session_tokens + delta,
            "cwd": cwd or prev.get("cwd", ""),
            "last_seen": datetime.datetime.now().isoformat(timespec="seconds"),
        }

        if delta == 0:
            dl.save_state(state)
            return

        prestige = state.get("prestige", 0)
        baseline = state.get("rebirth_baseline", 0)

        # Elemental traits: credit this turn's tokens to the folder's element.
        # Cosmetic only — wrapped so an element bug can never stop XP counting.
        element = None
        try:
            elements = data.get("elements") or {}
            element = el.element_for_cwd(sessions_seen[transcript_path]["cwd"], elements)
            el.credit(state, element, delta)
        except Exception:
            dl.log_error("digimon_hook.elements.credit")

        before = dl.compute_snapshot(state.get("total_tokens", 0), data, prestige, baseline)
        state["total_tokens"] = state.get("total_tokens", 0) + delta
        after = dl.compute_snapshot(state["total_tokens"], data, prestige, baseline)

        ceiling = data["cap_tiers"][-1]
        rebirthed = False
        if after["maxed_out"]:
            # Looped the ceiling: bank a prestige ★ + growth boost and be reborn
            # as the Egg. rebirth_baseline resets the climb; lifetime total_tokens
            # keeps counting up.
            prestige += 1
            baseline = state["total_tokens"]
            state["prestige"] = prestige
            state["rebirth_baseline"] = baseline
            state.setdefault("evolution_history", []).append(
                {
                    "event": "rebirth",
                    "prestige": prestige,
                    "level": ceiling,
                    "total_tokens_at_evolution": state["total_tokens"],
                }
            )
            after = dl.compute_snapshot(state["total_tokens"], data, prestige, baseline)
            rebirthed = True
            inherited = None
            try:
                inherited = el.inherit_on_rebirth(state, prestige)
            except Exception:
                dl.log_error("digimon_hook.elements.rebirth")

        evolved = (not rebirthed) and after["stage"]["name"] != before["stage"]["name"]
        trait, runner_up = None, None
        if evolved:
            try:
                trait, runner_up = el.gain_trait(state, before["stage"]["name"], after["level"])
            except Exception:
                dl.log_error("digimon_hook.elements.trait")
            state.setdefault("evolution_history", []).append(
                {
                    "stage": after["stage"]["stage"],
                    "name": after["stage"]["name"],
                    "level": after["level"],
                    "total_tokens_at_evolution": state["total_tokens"],
                }
            )

        dl.save_state(state)
    except Exception:
        dl.log_error("digimon_hook.main")
        return
    finally:
        lock.close()

    if rebirthed:
        growth_pct = int(round(after["growth_bonus"] * 100))
        stars = dl.prestige_badge(prestige)
        msg = (
            f"✨ REBIRTH! {state['name']} looped the ceiling and was reborn as "
            f"{after['stage']['emoji']} {after['stage']['name']} — "
            f"Prestige {stars} (+{growth_pct}% growth)"
        )
        if inherited and inherited in elements:
            spec = elements[inherited]
            msg += f" · inherits {spec['emoji']} {spec['name']}"
        print(json.dumps({"systemMessage": msg}))
    elif evolved:
        msg = (
            f"🎉 {state['name']} evolved! {before['stage']['emoji']} {before['stage']['name']} "
            f"-> {after['stage']['emoji']} {after['stage']['name']} ({after['stage']['stage']}, "
            f"Lv.{after['level']}/{after['cap']})"
        )
        if trait and trait["element"] in elements:
            spec = elements[trait["element"]]
            how = "chosen" if trait["chosen"] else "fed most"
            msg += f" · gained {spec['emoji']} {spec['name']} trait ({how})"
            if runner_up and runner_up in elements and runner_up != trait["element"]:
                alt = elements[runner_up]
                msg += (f" · {alt['emoji']} {alt['name']} was close — "
                        f"`digimon_cli.py attune {runner_up}` to steer the next one")
        print(json.dumps({"systemMessage": msg}))


if __name__ == "__main__":
    main()
