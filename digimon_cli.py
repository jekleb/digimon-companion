#!/usr/bin/env python3
"""Full companion viewer: `python3 digimon_cli.py [status|rename <name>|history]`"""
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import digimon_lib as dl
import digimon_agents as da
import digimon_elements as el
import digimon_sprites as sprites


def print_art(art, indent="   "):
    for line in art:
        print(f"{indent}{line}")
    print()


def _sprite_lines(stage, data, prestige=0):
    """Rendered 8-bit sprite for a stage, colored when the terminal supports it
    and recolored for the current prestige 'shiny' tint."""
    return sprites.stage_art_lines(
        stage, data.get("palette"), color=sprites.supports_color(sys.stdout), prestige=prestige
    )


def _dressed_lines(stage, data, traits, prestige=0, frame=0):
    """The stage sprite wearing the pet's elemental traits, rendered for the terminal."""
    rows, pal = el.dress(stage, data, traits, prestige, frame)
    if not rows:
        return list(stage.get("art") or [])
    return sprites.render_sprite(rows, pal, color=sprites.supports_color(sys.stdout))


def cmd_status():
    state = dl.load_state()
    data = dl.load_evolution_data()
    snap = dl.snapshot_from_state(state, data)
    stage = snap["stage"]
    stages = data["stages"]
    cap_tiers = data["cap_tiers"]

    ceiling = cap_tiers[-1]
    prestige = snap.get("prestige", 0)
    star = dl.prestige_badge(prestige)
    level_str = f"MAX ({ceiling})" if snap["maxed_out"] else f"{snap['level']} / {snap['cap']}"
    print()
    elem = el.summary(state, data)
    title = (f"   {stage['emoji']} {star}  {state.get('name', dl.DEFAULT_NAME)}  —  "
             f"{el.title(stage, elem['_traits'], data.get('elements') or {})} ({stage['stage']})")
    print(title)
    print(f"   \"{stage['tagline']}\"")
    print()
    art = _dressed_lines(stage, data, elem["_traits"], prestige)
    if art:
        print_art(art)
    print(f"   Level:        {level_str}")
    if not snap["maxed_out"]:
        print(f"   Progress:     [{dl.bar(snap['level_progress_frac'], 30)}] "
              f"{dl.format_int(snap['tokens_into_level'])} / {dl.format_int(snap['tokens_span_level'])} tokens to next level")
        print(f"   Next level:   {dl.format_int(snap['next_level_tokens'])} effective tokens")
    else:
        print(f"   Progress:     [{dl.bar(1.0, 30)}] at the Lv.{ceiling} ceiling — rebirth imminent")
    if prestige:
        print(f"   Prestige:     {star}  (rank {prestige}, +{int(round(snap['growth_bonus'] * 100))}% growth)")
    print(f"   Total tokens: {dl.format_int(snap['total_tokens'])} lifetime")
    print(f"   Cap tiers:    {' -> '.join(str(c) for c in cap_tiers)}")
    if elem["line"]:
        print(f"   Elements:     {elem['line']}   (`digimon_cli.py elements`)")
    print()

    recent_errors = dl.recent_error_count(within_hours=24)
    if recent_errors:
        print(f"   ⚠️  {recent_errors} error(s) in the last 24h — run `digimon_cli.py doctor` for details")
        print()

    # next stage preview
    upcoming = [s for s in stages if s["min"] > snap["level"]]
    if upcoming:
        nxt = upcoming[0]
        needed_effective = dl.tokens_for_level(nxt["min"], data["curve"])
        remaining_effective = max(0, needed_effective - snap["effective_tokens"])
        # convert effective tokens back to the lifetime tokens actually required,
        # accounting for the prestige growth boost
        remaining = int(remaining_effective / (1 + snap["growth_bonus"]))
        print(f"   Next evolution: {nxt['emoji']} {nxt['name']} ({nxt['stage']}) at Lv.{nxt['min']}"
              f" — {dl.format_int(remaining)} tokens away")
        print()


def cmd_history():
    state = dl.load_state()
    hist = state.get("evolution_history", [])
    if not hist:
        print("No evolutions yet.")
        return
    print()
    for h in hist:
        toks = dl.format_int(h.get("total_tokens_at_evolution", 0))
        if h.get("event") == "rebirth":
            star = dl.prestige_badge(h.get("prestige", 0))
            print(f"   ✨ REBIRTH → Prestige {star:<6} "
                  f"— looped the Lv.{h.get('level', '?')} ceiling at {toks} total tokens")
        else:
            print(f"   Lv.{h['level']:>3}  {h['name']:<14} ({h['stage']})  "
                  f"— reached at {toks} total tokens")
    print()


def cmd_gallery():
    state = dl.load_state()
    data = dl.load_evolution_data()
    snap = dl.snapshot_from_state(state, data)
    current_name = snap["stage"]["name"]
    prestige = snap.get("prestige", 0)

    print()
    if prestige:
        print(f"   {dl.prestige_badge(prestige)}  shiny palette — Prestige rank {prestige}")
        print()
    for s in data["stages"]:
        marker = "   ◄ you are here" if s["name"] == current_name else ""
        print(f"   {s['emoji']}  {s['name']}  —  {s['stage']}  (Lv.{s['min']}-{s['max']}){marker}")
        print()
        art = _sprite_lines(s, data, prestige)
        if art:
            print_art(art)
        print("   " + "-" * 40)
        print()


def cmd_sessions():
    state = dl.load_state()
    sessions_seen = state.get("sessions_seen", {})
    rows = []
    for path, info in sessions_seen.items():
        if not isinstance(info, dict):
            continue
        cwd = info.get("cwd") or ""
        project = os.path.basename(cwd.rstrip("/")) if cwd else os.path.basename(os.path.dirname(path))
        rows.append((info.get("tokens", 0), project, info.get("last_seen", "?")))
    rows.sort(reverse=True)

    if not rows:
        print("No session history yet.")
        return

    print()
    print(f"   {'tokens':>12}   {'project':<30} last seen")
    for tokens, project, last_seen in rows:
        print(f"   {dl.format_int(tokens):>12}   {project:<30} {last_seen}")
    total = sum(r[0] for r in rows)
    print()
    print(f"   {len(rows)} session(s) tracked, {dl.format_int(total)} tokens total")
    print(f"   (median session: {dl.format_int(sorted(r[0] for r in rows)[len(rows)//2])} tokens)")
    print()
    print("   Use this to sanity-check the level curve in evolution_data.json against")
    print("   how your real sessions actually spend tokens across projects.")
    print()


def cmd_doctor():
    import subprocess
    import json as _json

    print()
    ok = True

    settings_path = os.path.expanduser("~/.claude/settings.json")
    try:
        with open(settings_path) as f:
            settings = _json.load(f)
    except (OSError, ValueError) as e:
        print(f"   ✗ Could not read/parse {settings_path}: {e}")
        ok = False
        settings = {}

    stop_hooks = settings.get("hooks", {}).get("Stop", [])
    hook_wired = any(
        "digimon_hook.py" in h.get("command", "")
        for group in stop_hooks
        for h in group.get("hooks", [])
    )
    print(f"   {'✓' if hook_wired else '✗'} Stop hook wired in settings.json")
    ok = ok and hook_wired

    statusline_wired = "digimon_statusline.py" in settings.get("statusLine", {}).get("command", "")
    print(f"   {'✓' if statusline_wired else '✗'} statusLine wired in settings.json")
    ok = ok and statusline_wired

    data_ok = True
    try:
        data = dl.load_evolution_data()
        dl.validate_evolution_data(data)
    except Exception as e:
        data_ok = False
        print(f"   ✗ evolution_data.json failed validation: {e}")
    else:
        print(f"   ✓ evolution_data.json valid ({len(data['stages'])} stages, caps {data['cap_tiers']})")
    ok = ok and data_ok

    sprite_ok = True
    try:
        data = dl.load_evolution_data()
        dl.validate_sprites(data)
        n_sprites = sum(1 for s in data["stages"] if s.get("sprite"))
    except Exception as e:
        sprite_ok = False
        print(f"   ✗ 8-bit sprites failed validation: {e}")
    else:
        print(f"   ✓ 8-bit sprites valid ({n_sprites}/{len(data['stages'])} stages, "
              f"{len(data.get('palette', {}))}-color palette)")
    ok = ok and sprite_ok

    try:
        el.validate_elements(data)
    except Exception as e:
        print(f"   ✗ elemental traits failed validation: {e}")
        ok = False
    else:
        print(f"   ✓ elemental traits valid ({len(data.get('elements', {}))} elements)")

    here = os.path.dirname(os.path.abspath(__file__))
    hook_path = os.path.join(here, "digimon_hook.py")
    try:
        proc = subprocess.run(
            [sys.executable, hook_path],
            input="{}",
            capture_output=True,
            text=True,
            timeout=10,
        )
        hook_runs = proc.returncode == 0
    except Exception as e:
        hook_runs = False
        proc = None
    print(f"   {'✓' if hook_runs else '✗'} digimon_hook.py runs cleanly on a synthetic no-op payload")
    ok = ok and hook_runs

    statusline_path = os.path.join(here, "digimon_statusline.py")
    try:
        proc = subprocess.run(
            [sys.executable, statusline_path],
            input="{}",
            capture_output=True,
            text=True,
            timeout=10,
        )
        sl_runs = proc.returncode == 0 and proc.stdout.strip() != ""
    except Exception:
        sl_runs = False
    print(f"   {'✓' if sl_runs else '✗'} digimon_statusline.py emits a line on a synthetic payload")
    ok = ok and sl_runs

    try:
        lock = dl.acquire_lock()
        lock.close()
        print(f"   ✓ lock file acquirable at {dl.LOCK_PATH}")
    except Exception as e:
        print(f"   ✗ could not acquire lock: {e}")
        ok = False

    recent_errors = dl.recent_error_count(within_hours=24)
    all_errors = dl.read_recent_errors(max_entries=3)
    if all_errors:
        label = "recent (last 24h)" if recent_errors else "historical, none in last 24h"
        print(f"   {'⚠️ ' if recent_errors else '  '} {len(all_errors)} error(s) logged, {label} (showing last {len(all_errors)}):")
        for e in all_errors:
            first_line = e.strip().splitlines()[0] if e.strip() else ""
            print(f"        - {first_line}")
    else:
        print(f"   ✓ no errors logged")

    print()
    print("   All checks passed." if ok and not recent_errors else "   Some checks need attention (see ✗/⚠️  above).")
    print()


def find_current_transcript():
    """Best-effort locate the newest transcript for the current project, so
    `live`/`agents` can show real training sessions outside the status bar."""
    import glob
    encoded = os.getcwd().replace("/", "-")
    proj = os.path.expanduser(f"~/.claude/projects/{encoded}")
    files = glob.glob(os.path.join(proj, "*.jsonl"))
    if not files:
        return None
    return max(files, key=os.path.getmtime)


def _snapshot():
    state = dl.load_state()
    data = dl.load_evolution_data()
    snap = dl.snapshot_from_state(state, data)
    return state.get("name", dl.DEFAULT_NAME), snap


def cmd_bar():
    """Print one frame of the exact status-bar line (handy for previewing)."""
    name, snap = _snapshot()
    t = time.time()
    transcript = find_current_transcript()
    active = da.detect_active_agents(transcript)
    if active:
        print(sprites.training_line(name, snap, active, t))
    else:
        print(sprites.idle_line(name, snap, t))


def cmd_agents():
    print()
    print("   Agent training styles (subagent_type -> icon · label):")
    print()
    for key, (emoji, label) in sprites.AGENT_STYLES.items():
        print(f"   {emoji}  {label:<16} {key}")
    print(f"   {sprites.DEFAULT_AGENT_ICON}  {'(any other)':<16} <uses the raw agent name>")
    print()
    transcript = find_current_transcript()
    active = da.detect_active_agents(transcript)
    if active:
        names = ", ".join(a["agent"] for a in active)
        print(f"   ▶ Currently training with: {names}")
    else:
        print("   • No subagent running right now (companion is idle).")
    print()


def cmd_live(sim_agent=None):
    """Full-screen 8-bit animation loop. `live <agent>` simulates a training
    scene with that agent; bare `live` reflects the real session. Ctrl+C exits."""
    transcript = find_current_transcript()
    data = dl.load_evolution_data()
    palette = data.get("palette")
    color = sprites.supports_color(sys.stdout)
    started = time.time()
    try:
        while True:
            name, snap = _snapshot()
            t = time.time()
            if sim_agent:
                active = [{"agent": sim_agent, "desc": "simulated training session",
                           "started": started}]
            else:
                active = da.detect_active_agents(transcript)
            scene = (sprites.training_scene(name, snap, active, t, palette, color)
                     if active else sprites.idle_scene(name, snap, t, palette, color))
            sys.stdout.write("\033[H\033[2J")  # home + clear
            sys.stdout.write(scene)
            sys.stdout.write("\n   (Ctrl+C to exit)\n")
            sys.stdout.flush()
            time.sleep(0.4)
    except KeyboardInterrupt:
        sys.stdout.write("\n")


def cmd_elements():
    state = dl.load_state()
    data = dl.load_evolution_data()
    elements = data.get("elements") or {}
    snap = dl.snapshot_from_state(state, data)
    elem = el.summary(state, data)
    print()
    print(f"   {el.title(snap['stage'], elem['_traits'], elements)} — elemental traits")
    print()
    art = _dressed_lines(snap["stage"], data, elem["_traits"], snap.get("prestige", 0))
    if art:
        print_art(art)
    if elem["traits"]:
        print("   This life:")
        for t in elem["_traits"]:
            spec = elements[t["element"]]
            how = "chosen" if t.get("chosen") else ("inherited" if t.get("stage") == "Inherited" else "fed")
            print(f"     {spec['emoji']} {spec['name']:8}  from {t.get('stage', '?'):13} ({how})")
        print()
    if elem["leaning"] or elem["attune"]:
        print(f"   Next trait:   {elem['line'].split(' · ')[-1]}")
        nxt = [s for s in data["stages"] if s["min"] > snap["level"]]
        if nxt:
            print(f"                 banked when it evolves into {nxt[0]['emoji']} {nxt[0]['name']} (Lv.{nxt[0]['min']})")
        print()
    life = elem["lifetime"]
    total = sum(life.values()) or 1
    print("   Element         fed (lifetime)   look")
    for k, spec in elements.items():
        n = life.get(k, 0)
        mark = "  ◄ chosen next" if elem["attune"] == k else ""
        print(f"   {spec['emoji']} {spec['name']:10} {dl.human_tokens(n):>8} {n / total * 100:4.0f}%   {spec['blurb']}{mark}")
    print()
    print("   Steer the next evolution:  digimon_cli.py attune <element>   (or `attune off`)")
    print()


def cmd_attune(choice):
    data = dl.load_evolution_data()
    elements = data.get("elements") or {}
    choice = choice.lower()
    if choice not in elements and choice not in ("off", "none", "auto"):
        print(f"Unknown element {choice!r}. Pick one of: {', '.join(elements)} (or off)")
        return 1
    lock = dl.acquire_lock()
    try:
        state = dl.load_state()
        el.seed_from_history(state, elements)
        if choice in elements:
            state["attune"] = choice
        else:
            state.pop("attune", None)
        dl.save_state(state)
    finally:
        lock.close()
    if choice in elements:
        spec = elements[choice]
        print(f"{spec['emoji']} {state.get('name', dl.DEFAULT_NAME)} will take a {spec['name']} trait at its next evolution.")
    else:
        print("Choice cleared — the next trait goes to whatever it is fed most.")
    return 0


def cmd_rename(new_name):
    lock = dl.acquire_lock()
    try:
        state = dl.load_state()
        old = state.get("name", dl.DEFAULT_NAME)
        state["name"] = new_name
        dl.save_state(state)
    finally:
        lock.close()
    print(f"Renamed {old} -> {new_name}")


def main():
    args = sys.argv[1:]
    if not args or args[0] == "status":
        cmd_status()
    elif args[0] == "history":
        cmd_history()
    elif args[0] == "gallery":
        cmd_gallery()
    elif args[0] == "sessions":
        cmd_sessions()
    elif args[0] == "doctor":
        cmd_doctor()
    elif args[0] == "bar":
        cmd_bar()
    elif args[0] == "agents":
        cmd_agents()
    elif args[0] == "live":
        cmd_live(args[1] if len(args) > 1 else None)
    elif args[0] == "elements":
        cmd_elements()
    elif args[0] == "attune" and len(args) > 1:
        sys.exit(cmd_attune(args[1]))
    elif args[0] == "rename" and len(args) > 1:
        cmd_rename(" ".join(args[1:]))
    else:
        print("Usage: digimon_cli.py "
              "[status|history|gallery|sessions|agents|bar|live [agent]|elements|attune <element|off>|"
              "doctor|rename <name>]")


if __name__ == "__main__":
    main()
