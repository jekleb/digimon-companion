#!/usr/bin/env python3
"""Plain-assert test suite. Run: python3 test_digimon.py"""
import os
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import json
import digimon_lib as dl
import digimon_hook as dh
import digimon_agents as da
import digimon_sprites as sprites
import digimon_elements as el
import tokimon_feed as feed
import tokimon_serve as serve

passed = 0


def check(label, condition):
    global passed
    if not condition:
        raise AssertionError(f"FAILED: {label}")
    passed += 1
    print(f"  ok  {label}")


def test_curve_round_trip():
    data = dl.load_evolution_data()
    curve = data["curve"]
    for lvl in [0, 1, 30, 55, 56, 100, 101, 150, 250, 251, 375, 500, 501, 700, 750]:
        tokens = dl.tokens_for_level(lvl, curve)
        back = dl.level_from_tokens(tokens, curve)
        check(f"level_from_tokens(tokens_for_level({lvl})) == {lvl}", back == lvl)
    check("tokens_for_level is monotonic non-decreasing",
          all(dl.tokens_for_level(l, curve) <= dl.tokens_for_level(l + 1, curve) for l in range(0, 750)))


def test_validate_evolution_data_accepts_real_file():
    data = dl.load_evolution_data()
    dl.validate_evolution_data(data)  # must not raise
    check("real evolution_data.json passes validation", True)


def test_validate_catches_broken_cap_tier():
    data = dl.load_evolution_data()
    data = {**data, "cap_tiers": [100, 250, 999]}
    try:
        dl.validate_evolution_data(data)
        ok = False
    except ValueError:
        ok = True
    check("validation rejects a cap tier with no matching stage max", ok)


def test_validate_catches_curve_cap_mismatch():
    data = dl.load_evolution_data()
    broken_curve = [dict(seg) for seg in data["curve"]]
    broken_curve[-1]["up_to_level"] = 501
    data = {**data, "curve": broken_curve}
    try:
        dl.validate_evolution_data(data)
        ok = False
    except ValueError:
        ok = True
    check("validation rejects curve boundaries that don't match cap_tiers", ok)


def test_validate_catches_missing_field():
    data = dl.load_evolution_data()
    stages = [dict(s) for s in data["stages"]]
    del stages[0]["tagline"]
    data = {**data, "stages": stages}
    try:
        dl.validate_evolution_data(data)
        ok = False
    except ValueError:
        ok = True
    check("validation rejects a stage missing a required field", ok)


def _write(path, content_bytes):
    with open(path, "wb") as f:
        f.write(content_bytes)


def test_scan_new_tokens_basic():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "t.jsonl")
        line = b'{"type":"assistant","message":{"usage":{"input_tokens":10,"output_tokens":5,"cache_creation_input_tokens":0,"cache_read_input_tokens":0}}}\n'
        _write(p, line)
        delta, offset = dh.scan_new_tokens(p, 0)
        check("scan_new_tokens sums a single complete line", delta == 15)
        check("scan_new_tokens offset advances to EOF on complete lines", offset == len(line))

        delta2, offset2 = dh.scan_new_tokens(p, offset)
        check("scan_new_tokens returns 0 delta when nothing new appended", delta2 == 0 and offset2 == offset)

        with open(p, "ab") as f:
            f.write(line)
        delta3, offset3 = dh.scan_new_tokens(p, offset2)
        check("scan_new_tokens picks up only the newly appended line", delta3 == 15)


def test_scan_new_tokens_partial_trailing_line_held_back():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "t.jsonl")
        complete = b'{"type":"assistant","message":{"usage":{"input_tokens":1,"output_tokens":1,"cache_creation_input_tokens":0,"cache_read_input_tokens":0}}}\n'
        partial = b'{"type":"assistant","message":{"usage":{"input_tokens":5'  # no trailing newline, mid-write
        _write(p, complete + partial)
        delta, offset = dh.scan_new_tokens(p, 0)
        check("partial trailing line is not parsed", delta == 2)
        check("offset stops right after the last complete newline", offset == len(complete))

        with open(p, "ab") as f:
            f.write(b'0,"output_tokens":50,"cache_creation_input_tokens":0,"cache_read_input_tokens":0}}}\n')  # completes input_tokens to 50
        delta2, offset2 = dh.scan_new_tokens(p, offset)
        check("previously-partial line is counted once completed", delta2 == 100)


def test_scan_new_tokens_truncated_file_resets():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "t.jsonl")
        _write(p, b"x" * 1000)
        delta, offset = dh.scan_new_tokens(p, 5000)  # stored offset beyond current size
        check("offset beyond file size is treated as a reset, not a crash", offset <= 1000)


def test_scan_new_tokens_missing_file():
    delta, offset = dh.scan_new_tokens("/nonexistent/path/does-not-exist.jsonl", 42)
    check("missing transcript file returns delta 0 without crashing", delta == 0 and offset == 42)


def test_prune_missing_sessions():
    with tempfile.TemporaryDirectory() as d:
        real = os.path.join(d, "real.jsonl")
        _write(real, b"")
        sessions = {real: {"offset": 0}, "/nonexistent/gone.jsonl": {"offset": 0}}
        dh.prune_missing_sessions(sessions)
        check("prune_missing_sessions drops entries for deleted transcripts", list(sessions.keys()) == [real])


def test_human_tokens():
    check("human_tokens < 1000 is plain", dl.human_tokens(942) == "942")
    check("human_tokens thousands -> K", dl.human_tokens(1500) == "1.5K")
    check("human_tokens millions -> M", dl.human_tokens(2_000_000) == "2M")
    check("human_tokens billions -> B", dl.human_tokens(1_439_054_442) == "1.4B")
    check("human_tokens trillions -> T", dl.human_tokens(2_500_000_000_000) == "2.5T")
    check("human_tokens trims trailing .0", dl.human_tokens(3_000) == "3K")
    # rounding-boundary promotion: must not render '1000K' / '1000M' / '1000B'
    check("human_tokens promotes K->M at the boundary", dl.human_tokens(999_950) == "1M")
    check("human_tokens promotes M->B at the boundary", dl.human_tokens(999_950_000) == "1B")
    check("human_tokens promotes B->T at the boundary", dl.human_tokens(999_950_000_000) == "1T")
    check("human_tokens just under a boundary stays put", dl.human_tokens(994_000) == "994K")


def test_supports_color_on_a_tty():
    # Regression guard: supports_color used os.environ without importing os, so it
    # threw NameError on a real TTY and silently disabled all color rendering.
    class FakeTTY:
        def isatty(self):
            return True

    class NotTTY:
        def isatty(self):
            return False

    prev = os.environ.pop("NO_COLOR", None)
    try:
        check("supports_color True on a TTY (no NO_COLOR)", sprites.supports_color(FakeTTY()) is True)
        check("supports_color False on a non-TTY", sprites.supports_color(NotTTY()) is False)
        os.environ["NO_COLOR"] = "1"
        check("supports_color respects NO_COLOR", sprites.supports_color(FakeTTY()) is False)
    finally:
        os.environ.pop("NO_COLOR", None)
        if prev is not None:
            os.environ["NO_COLOR"] = prev


def test_agent_style_known_and_unknown():
    emoji, label = sprites.agent_style("ekleberry")
    check("known agent maps to its label", label == "Ekleberry" and emoji == "✍️")
    emoji, label = sprites.agent_style("some-custom-agent")
    check("unknown agent falls back to generic icon", emoji == sprites.DEFAULT_AGENT_ICON)
    check("unknown agent keeps its raw name", label == "some-custom-agent")
    check("empty agent name is handled", sprites.agent_style("")[1] == "agent")


def test_frame_index_determinism_and_shimmer():
    check("frame_index cycles within range", all(0 <= sprites.frame_index(x / 3.0, 4) < 4 for x in range(30)))
    check("frame_index is deterministic for a fixed t", sprites.frame_index(10.0, 4) == sprites.frame_index(10.0, 4))
    check("frame_index handles n=0 safely", sprites.frame_index(5.0, 0) == 0)
    check("shimmer_bar has exact width when partial", len(sprites.shimmer_bar(0.5, 10, 1.0)) == 10)
    check("shimmer_bar full is all fill", sprites.shimmer_bar(1.0, 6, 3.0) == "█" * 6)
    check("shimmer_bar empty starts with an edge cell, right width", len(sprites.shimmer_bar(0.0, 8, 2.0)) == 8)


def _fake_snap():
    data = dl.load_evolution_data()
    return dl.compute_snapshot(1_439_054_442, data)


def test_status_lines_are_single_line():
    snap = _fake_snap()
    idle = sprites.idle_line("Tokimon", snap, 1.0)
    check("idle_line is a single line", "\n" not in idle and "Tokimon" in idle)
    active = [{"agent": "ekleberry", "desc": "write blog", "started": 0.0}]
    train = sprites.training_line("Tokimon", snap, active, 60.0)
    check("training_line is a single line", "\n" not in train)
    check("training_line names the agent", "Ekleberry" in train and "training" in train)
    check("training_line shows elapsed", "⏱" in train)
    two = active + [{"agent": "cosmic-code", "desc": "x", "started": 5.0}]
    check("training_line summarises extra agents", "+1" in sprites.training_line("Tokimon", snap, two, 1.0))


def _line(obj):
    return (json.dumps(obj) + "\n").encode()


def test_detect_active_agents_running_and_completed():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "t.jsonl")
        now = da.datetime.datetime.now(da.datetime.timezone.utc)
        ts = now.isoformat().replace("+00:00", "Z")
        spawn = {"type": "assistant", "timestamp": ts, "message": {"content": [
            {"type": "tool_use", "id": "toolu_A", "name": "Agent",
             "input": {"subagent_type": "ekleberry", "description": "write"}}]}}
        with open(p, "wb") as f:
            f.write(_line(spawn))
        active = da.detect_active_agents(p, now=now)
        check("a lone Agent spawn is detected as active", len(active) == 1 and active[0]["agent"] == "ekleberry")

        # async launch result must NOT close it
        async_launch = {"type": "user", "toolUseResult": {"status": "async_launched"},
                        "message": {"content": [{"type": "tool_result", "tool_use_id": "toolu_A"}]}}
        with open(p, "ab") as f:
            f.write(_line(async_launch))
        active = da.detect_active_agents(p, now=now)
        check("async_launched result keeps agent active", len(active) == 1)

        # task-notification closes it
        notif = {"type": "user", "message": {"content":
                 "<task-notification><tool-use-id>toolu_A</tool-use-id><status>completed</status></task-notification>"}}
        with open(p, "ab") as f:
            f.write(_line(notif))
        active = da.detect_active_agents(p, now=now)
        check("task-notification completes the async agent", active == [])


def test_detect_active_agents_sync_completion_and_staleness():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "t.jsonl")
        now = da.datetime.datetime.now(da.datetime.timezone.utc)
        ts = now.isoformat().replace("+00:00", "Z")
        spawn = {"type": "assistant", "timestamp": ts, "message": {"content": [
            {"type": "tool_use", "id": "toolu_S", "name": "Task",
             "input": {"subagent_type": "general-purpose", "description": "x"}}]}}
        done = {"type": "user", "toolUseResult": {"status": "completed"},
                "message": {"content": [{"type": "tool_result", "tool_use_id": "toolu_S"}]}}
        with open(p, "wb") as f:
            f.write(_line(spawn))
            f.write(_line(done))
        check("sync completed tool_result closes the agent", da.detect_active_agents(p, now=now) == [])

        # an old spawn with no completion is pruned as stale
        old = (now - da.datetime.timedelta(seconds=dl.TRAINING_STALE_SECONDS + 60))
        old_ts = old.isoformat().replace("+00:00", "Z")
        stale_spawn = {"type": "assistant", "timestamp": old_ts, "message": {"content": [
            {"type": "tool_use", "id": "toolu_OLD", "name": "Agent",
             "input": {"subagent_type": "lumalith", "description": "x"}}]}}
        with open(p, "wb") as f:
            f.write(_line(stale_spawn))
        check("a stale un-closed spawn is not shown as active", da.detect_active_agents(p, now=now) == [])


def test_hook_triggers_rebirth_end_to_end():
    """Drive the REAL Stop hook (with state paths redirected to a temp dir) with
    a transcript big enough to cross the Lv.750 ceiling, and confirm it banks a
    prestige rank, resets the baseline, is reborn as the Egg, and announces it."""
    import io
    import contextlib
    with tempfile.TemporaryDirectory() as d:
        saved = (dl.DIGIMON_DIR, dl.STATE_PATH, dl.LOCK_PATH, dl.ERROR_LOG_PATH)
        dl.DIGIMON_DIR = d
        dl.STATE_PATH = os.path.join(d, "state.json")
        dl.LOCK_PATH = os.path.join(d, "state.lock")
        dl.ERROR_LOG_PATH = os.path.join(d, "error.log")
        try:
            data = dl.load_evolution_data()
            ceiling_tokens = dl.tokens_for_level(data["cap_tiers"][-1], data["curve"])
            big = int(ceiling_tokens) + 10_000_000
            tp = os.path.join(d, "t.jsonl")
            line = ('{"type":"assistant","message":{"usage":{"input_tokens":0,'
                    '"output_tokens":%d,"cache_creation_input_tokens":0,'
                    '"cache_read_input_tokens":0}}}\n' % big).encode()
            with open(tp, "wb") as f:
                f.write(line)

            saved_stdin = sys.stdin
            sys.stdin = io.StringIO(json.dumps({"transcript_path": tp, "cwd": d}))
            buf = io.StringIO()
            try:
                with contextlib.redirect_stdout(buf):
                    dh.main()
            finally:
                sys.stdin = saved_stdin
            out = buf.getvalue()

            state = dl.load_state()
            check("hook banked a prestige rank on crossing the ceiling", state.get("prestige") == 1)
            check("hook reset baseline to the lifetime total",
                  state.get("rebirth_baseline") == state.get("total_tokens"))
            snap = dl.snapshot_from_state(state, data)
            check("reborn as the Egg", snap["stage"]["name"] == "Digitama")
            check("hook emitted a REBIRTH systemMessage", "REBIRTH" in out)
        finally:
            dl.DIGIMON_DIR, dl.STATE_PATH, dl.LOCK_PATH, dl.ERROR_LOG_PATH = saved


def test_extended_tree_shape():
    data = dl.load_evolution_data()
    check("tree extended to 16 stages", len(data["stages"]) == 16)
    check("new Lv.750 cap tier present", data["cap_tiers"][-1] == 750)
    check("final stage is Aeon at Lv.750", data["stages"][-1]["name"] == "Aeonmon"
          and data["stages"][-1]["max"] == 750)
    dl.validate_evolution_data(data)  # contiguity + cap/curve alignment must hold
    check("extended data passes structural validation", True)


def test_prestige_boost_accelerates_level():
    data = dl.load_evolution_data()
    tok = dl.tokens_for_level(100, data["curve"])  # exactly Lv.100 at prestige 0
    base = dl.compute_snapshot(tok, data, prestige=0)
    boosted = dl.compute_snapshot(tok, data, prestige=2)
    check("prestige 0 growth_bonus is 0", base["growth_bonus"] == 0)
    check("prestige 2 growth_bonus is 0.12", abs(boosted["growth_bonus"] - 0.12) < 1e-9)
    check("prestige boosts effective tokens", boosted["effective_tokens"] > base["effective_tokens"])
    check("prestige reaches a higher level for the same tokens", boosted["level"] > base["level"])


def test_rebirth_baseline_resets_to_egg():
    data = dl.load_evolution_data()
    tok = dl.tokens_for_level(300, data["curve"])
    # after a rebirth the baseline equals total, so progress is 0 -> Egg
    reborn = dl.compute_snapshot(tok, data, prestige=1, rebirth_baseline=tok)
    check("rebirth baseline drops the pet back to Lv.0", reborn["level"] == 0)
    check("rebirth keeps the lifetime total for display", reborn["total_tokens"] == tok)
    check("Egg stage after rebirth", reborn["stage"]["name"] == "Digitama")


def test_ceiling_triggers_maxed():
    data = dl.load_evolution_data()
    ceiling = data["cap_tiers"][-1]
    at_cap = dl.tokens_for_level(ceiling, data["curve"])
    snap = dl.compute_snapshot(at_cap, data)
    check("reaching the ceiling flags maxed_out", snap["maxed_out"])
    check("maxed snapshot caps level at the ceiling", snap["level"] == ceiling)


def test_snapshot_from_state_reads_prestige():
    data = dl.load_evolution_data()
    tok = dl.tokens_for_level(100, data["curve"])
    state = {"total_tokens": tok, "prestige": 3, "rebirth_baseline": 0}
    snap = dl.snapshot_from_state(state, data)
    check("snapshot_from_state passes prestige through", snap["prestige"] == 3)
    check("snapshot_from_state applies the boost", abs(snap["growth_bonus"] - 0.18) < 1e-9)


def test_prestige_badge():
    check("prestige 0 -> empty badge", dl.prestige_badge(0) == "")
    check("prestige 2 -> two stars", dl.prestige_badge(2) == "★★")
    check("prestige 3 -> three stars", dl.prestige_badge(3) == "★★★")
    check("prestige 7 -> silver tier compact", dl.prestige_badge(7) == "✦7")
    check("prestige 4 -> star tier compact", dl.prestige_badge(4) == "★4")


def test_prestige_symbol_tiers():
    check("rank 1 -> ★", dl.prestige_symbol(1) == "★")
    check("rank 5 -> ✦", dl.prestige_symbol(5) == "✦")
    check("rank 10 -> ✧", dl.prestige_symbol(10) == "✧")
    check("rank 20 -> ❖", dl.prestige_symbol(20) == "❖")


def test_shiny_palette_recolors_by_prestige():
    palette = {".": None, "c": "#5fd3ff", "K": "#0b0e17"}
    check("prestige 0 returns the palette unchanged", sprites.shiny_palette(palette, 0) is palette)
    p1 = sprites.shiny_palette(palette, 1)
    p2 = sprites.shiny_palette(palette, 2)
    check("transparent stays transparent", p1["."] is None)
    check("a saturated color shifts hue at prestige 1", p1["c"] != palette["c"])
    check("consecutive prestiges differ from each other", p1["c"] != p2["c"])
    check("recolored value is a valid hex", len(p1["c"]) == 7 and p1["c"].startswith("#"))
    check("all keys preserved", set(p1) == set(palette))


def test_stage_art_lines_applies_shiny():
    data = dl.load_evolution_data()
    stage = data["stages"][3]  # Cachemon, has a sprite
    base = sprites.stage_art_lines(stage, data["palette"], color=True, prestige=0)
    shiny = sprites.stage_art_lines(stage, data["palette"], color=True, prestige=2)
    check("prestige changes the rendered (colored) sprite", base != shiny)
    check("recolor preserves sprite dimensions", len(base) == len(shiny))


def test_validate_sprites_accepts_real_file():
    data = dl.load_evolution_data()
    dl.validate_sprites(data)  # must not raise
    check("real evolution_data.json sprites pass validation", True)
    check("every stage has a sprite", all(s.get("sprite") for s in data["stages"]))
    check("palette is present", len(data.get("palette", {})) > 0)


def test_validate_sprites_catches_non_rectangular():
    data = dl.load_evolution_data()
    stages = [dict(s) for s in data["stages"]]
    stages[1] = {**stages[1], "sprite": ["....", "..."]}  # ragged
    try:
        dl.validate_sprites({**data, "stages": stages})
        ok = False
    except ValueError:
        ok = True
    check("validation rejects a non-rectangular sprite", ok)


def test_validate_sprites_catches_unknown_key():
    data = dl.load_evolution_data()
    stages = [dict(s) for s in data["stages"]]
    stages[0] = {**stages[0], "sprite": ["ZZ", "ZZ"]}  # Z not in palette
    try:
        dl.validate_sprites({**data, "stages": stages})
        ok = False
    except ValueError:
        ok = True
    check("validation rejects a sprite key not in the palette", ok)


def test_render_sprite_dimensions_and_modes():
    palette = {".": None, "c": "#5fd3ff", "K": "#0b0e17"}
    rows = ["cKcK", "KcKc", "ccKK"]  # 3 rows -> padded to 4 -> 2 text lines
    mono = sprites.render_sprite(rows, palette, color=False)
    check("render_sprite halves the row count", len(mono) == 2)
    check("mono line has one char per pixel column", all(len(line) == 4 for line in mono))
    check("mono uses block glyphs", set("".join(mono)) <= set("█▀▄ "))
    color = sprites.render_sprite(rows, palette, color=True)
    check("color render contains ANSI truecolor codes", "\033[" in "".join(color))
    check("color render resets at line end", all(line.endswith("\033[0m") for line in color))
    check("transparent-only sprite renders blanks in mono",
          sprites.render_sprite(["..", ".."], palette, color=False) == ["  "])


def test_stage_art_lines_prefers_sprite_then_art():
    palette = {".": None, "c": "#5fd3ff"}
    stage_with_sprite = {"sprite": ["cc", "cc"], "art": ["OLD"]}
    check("stage_art_lines uses sprite when present",
          sprites.stage_art_lines(stage_with_sprite, palette, color=False) != ["OLD"])
    stage_art_only = {"art": ["FALLBACK"]}
    check("stage_art_lines falls back to art",
          sprites.stage_art_lines(stage_art_only, palette, color=False) == ["FALLBACK"])


def test_detect_active_agents_missing_path():
    check("no transcript path -> no active agents", da.detect_active_agents(None) == [])
    check("nonexistent transcript -> no active agents", da.detect_active_agents("/nope/x.jsonl") == [])


def test_feed_is_json_serialisable_and_complete():
    """The Swift menu-bar app decodes this into a struct with non-optional
    fields, so a missing key is a crash over there, not a warning."""
    payload = feed.build_feed()
    required = {
        "ok", "name", "stage", "level", "cap", "ceiling", "maxed_out", "progress",
        "tokens_into_level", "tokens_span_level", "prestige", "prestige_badge",
        "total_tokens", "total_tokens_human", "frames", "sprite_fps", "palette",
        "next_evolution", "training", "errors_24h",
    }
    check("feed carries every key the Swift app decodes", required <= set(payload))
    check("feed round-trips through JSON", json.loads(json.dumps(payload)) == payload)
    check("stage block is complete",
          {"name", "stage", "emoji", "tagline"} <= set(payload["stage"]))
    check("training is a list", isinstance(payload["training"], list))


def test_feed_palette_has_no_transparent_entries():
    """Swift treats 'key absent from the palette' as transparent, so the null
    entries must be stripped rather than sent as JSON nulls."""
    payload = feed.build_feed()
    check("no null colors survive into the feed",
          all(isinstance(v, str) and v.startswith("#") for v in payload["palette"].values()))
    used = set("".join("".join(f) for f in payload["frames"]))
    unresolved = used - set(payload["palette"]) - set(". ")
    check("every sprite glyph is either transparent or in the palette", not unresolved)


def test_feed_prestige_recolor_matches_sprites_module():
    payload = feed.build_feed()
    data = dl.load_evolution_data()
    expected = sprites.shiny_palette(data["palette"], payload["prestige"])
    element_colors = {k: v for spec in data["elements"].values() for k, v in spec["colors"].items()}
    check("feed palette is the shiny palette for the current prestige",
          all(payload["palette"][k] == expected[k] for k in payload["palette"] if k in expected))
    check("element colours are NOT hue-rotated by prestige (Forge stays orange)",
          all(payload["palette"][k] == v for k, v in element_colors.items()))


def test_feed_next_evolution_agrees_with_the_stage_table():
    payload = feed.build_feed()
    data = dl.load_evolution_data()
    upcoming = [s for s in data["stages"] if s["min"] > payload["level"]]
    if upcoming:
        check("next evolution is the next stage above the current level",
              payload["next_evolution"]["name"] == upcoming[0]["name"])
        check("next evolution is a non-negative distance",
              payload["next_evolution"]["tokens_away"] >= 0)
    else:
        check("no next evolution at the ceiling", payload["next_evolution"] is None)


def test_feed_transcript_scan_ignores_stale_and_missing():
    with tempfile.TemporaryDirectory() as tmp:
        old = os.path.join(tmp, "old.jsonl")
        with open(old, "w") as f:
            f.write("{}\n")
        os.utime(old, (0, 0))  # far older than the freshness window
        saved = feed.PROJECTS_DIR
        try:
            feed.PROJECTS_DIR = tmp
            check("stale transcripts are not scanned", feed.recent_transcripts() == [])
            feed.PROJECTS_DIR = "/nope/does/not/exist"
            check("a missing projects dir yields no transcripts",
                  feed.recent_transcripts() == [])
            check("and therefore no training agents", feed.active_agents() == [])
        finally:
            feed.PROJECTS_DIR = saved


def test_sprite_frames_normalises_both_shapes():
    """`sprite` may be one frame or a list of frames; every caller sees frames."""
    single = {"sprite": ["ab", "cd"]}
    multi = {"sprite": [["ab", "cd"], ["dc", "ba"]]}
    check("a bare frame normalises to a one-frame list",
          sprites.sprite_frames(single) == [["ab", "cd"]])
    check("a frame list passes through",
          sprites.sprite_frames(multi) == [["ab", "cd"], ["dc", "ba"]])
    check("no sprite -> no frames", sprites.sprite_frames({}) == [])


def test_stage_art_lines_selects_and_wraps_frames():
    palette = {".": None, "c": "#5fd3ff", "y": "#ffd23f"}
    stage = {"sprite": [["cc", "cc"], ["yy", "yy"]]}
    f0 = sprites.stage_art_lines(stage, palette, color=True, frame=0)
    f1 = sprites.stage_art_lines(stage, palette, color=True, frame=1)
    check("frame 0 and frame 1 render differently", f0 != f1)
    check("the frame index wraps", sprites.stage_art_lines(stage, palette, color=True, frame=2) == f0)
    single = {"sprite": ["cc", "cc"]}
    check("a single-frame stage ignores the frame index",
          sprites.stage_art_lines(single, palette, color=True, frame=7)
          == sprites.stage_art_lines(single, palette, color=True, frame=0))


def test_every_stage_is_animated():
    data = dl.load_evolution_data()
    for stage in data["stages"]:
        frames = sprites.sprite_frames(stage)
        check(f"{stage['name']} has >1 frame", len(frames) > 1)
        check(f"{stage['name']} frame 2 differs from frame 1", frames[0] != frames[1])


def test_validate_sprites_catches_mismatched_frame_sizes():
    """Frames of different sizes would make the pet jump around mid-loop."""
    data = dl.load_evolution_data()
    stages = [dict(s) for s in data["stages"]]
    stages[0] = {**stages[0], "sprite": [["..", ".."], ["...", "...", "..."]]}
    try:
        dl.validate_sprites({**data, "stages": stages})
        ok = False
    except ValueError:
        ok = True
    check("validation rejects frames that disagree on size", ok)


def test_validate_sprites_checks_every_frame_not_just_the_first():
    data = dl.load_evolution_data()
    stages = [dict(s) for s in data["stages"]]
    stages[0] = {**stages[0], "sprite": [["..", ".."], ["..", "ZZ"]]}  # bad key in frame 2
    try:
        dl.validate_sprites({**data, "stages": stages})
        ok = False
    except ValueError:
        ok = True
    check("validation inspects frames beyond the first", ok)


def _serve_request(path, token=None, srv_token="secret-token"):
    """Drive one request through the real handler over a real socket, so the
    auth path being tested is the one that actually runs."""
    import http.client
    server = serve.make_server(0, "127.0.0.1", srv_token, quiet=True)
    port = server.server_address[1]
    t = threading.Thread(target=server.handle_request, daemon=True)
    t.start()
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    headers = {serve.HEADER: token} if token is not None else {}
    conn.request("GET", path, headers=headers)
    resp = conn.getresponse()
    body = json.loads(resp.read() or b"{}")
    status = resp.status
    conn.close()
    t.join(timeout=5)
    server.server_close()
    return status, body


def test_serve_requires_a_token_for_pet_data():
    status, body = _serve_request("/feed")
    check("no token -> 401", status == 401)
    check("401 body names the header", serve.HEADER in body.get("error", ""))
    status, _ = _serve_request("/feed", token="wrong")
    check("wrong token -> 401", status == 401)
    status, body = _serve_request("/feed", token="secret-token")
    check("right token -> 200", status == 200)
    check("authorised response carries the pet", body.get("name") and body.get("frames"))


def test_serve_health_is_open_but_carries_no_pet_data():
    """A client needs to tell 'wrong key' apart from 'nothing there', so health
    answers without a token — and therefore must leak nothing."""
    status, body = _serve_request("/health")
    check("health needs no token", status == 200)
    check("health advertises that a token is needed", body.get("needs_token") is True)
    leaky = {"name", "level", "total_tokens", "frames", "training"} & set(body)
    check("health exposes no pet data", not leaky)


def test_serve_unknown_paths_404():
    status, _ = _serve_request("/secrets", token="secret-token")
    check("unknown path -> 404", status == 404)


def test_serve_token_is_persistent_and_private():
    with tempfile.TemporaryDirectory() as tmp:
        saved_dir, saved_path = dl.DIGIMON_DIR, serve.TOKEN_PATH
        try:
            dl.DIGIMON_DIR = tmp
            serve.TOKEN_PATH = os.path.join(tmp, "serve_token")
            first = serve.load_or_create_token()
            check("a token is generated on first run", len(first) > 20)
            check("the same token is reused", serve.load_or_create_token() == first)
            mode = os.stat(serve.TOKEN_PATH).st_mode & 0o777
            check("token file is owner-only (0600)", mode == 0o600)
        finally:
            dl.DIGIMON_DIR, serve.TOKEN_PATH = saved_dir, saved_path


def test_serve_cache_collapses_rapid_polls():
    """Phone and watch poll independently; they should not each rebuild the feed."""
    calls = []
    real = feed.build_feed
    try:
        feed.build_feed = lambda *a, **k: (calls.append(1), {"ok": True})[1]
        cache = serve.FeedCache(ttl=60)
        for _ in range(5):
            cache.get()
        check("five rapid reads rebuild the feed once", len(calls) == 1)
        cache.get(now=time.time() + 120)
        check("the cache does expire", len(calls) == 2)
    finally:
        feed.build_feed = real


# ------------------------------------------------------------------------
# Elemental traits
# ------------------------------------------------------------------------
def _traits(*keys):
    return [{"element": k} for k in keys]


def test_validate_elements_accepts_real_file():
    el.validate_elements(dl.load_evolution_data())
    check("real elements table validates", True)


def test_validate_elements_catches_key_collision():
    data = json.loads(json.dumps(dl.load_evolution_data()))
    data["elements"]["forge"]["colors"] = {"K": "#ff0000"}   # K is the outline
    try:
        el.validate_elements(data)
        check("colliding colour key is rejected", False)
    except ValueError as e:
        check("colliding colour key is rejected", "already used" in str(e))


def test_element_for_cwd_matches_path_components():
    els = dl.load_evolution_data()["elements"]
    root = "/Users/x/Documents/Claude"
    check("cosmic_code -> astral", el.element_for_cwd(root + "/cosmic_code/videos", els) == "astral")
    check("printing_3d -> forge", el.element_for_cwd(root + "/printing_3d", els) == "forge")
    check("workspace root -> neutral aether", el.element_for_cwd(root, els) == "aether")
    check("empty cwd -> aether", el.element_for_cwd("", els) == "aether")
    check("substring is not a match (cosmic_codex)",
          el.element_for_cwd(root + "/cosmic_codex", els) == "aether")


def test_dominant_element_prefers_real_work_over_neutral():
    check("real element beats a bigger aether pile",
          el.dominant_element({"aether": 10_000, "forge": 5}) == "forge")
    check("aether wins only when alone", el.dominant_element({"aether": 3}) == "aether")
    check("empty tally -> None", el.dominant_element({}) is None)


def test_gain_trait_uses_tally_then_attune_choice():
    state = {}
    el.credit(state, "forge", 100)
    el.credit(state, "tide", 60)
    trait, runner = el.gain_trait(state, "Bytemon", 16)
    check("trait goes to the element fed most", trait["element"] == "forge" and not trait["chosen"])
    check("runner-up is surfaced", runner == "tide")
    check("stage tally resets after a trait", state["stage_element_xp"] == {})
    check("lifetime tally keeps counting", state["element_xp"] == {"forge": 100, "tide": 60})
    el.credit(state, "forge", 999)
    state["attune"] = "gale"
    trait, _ = el.gain_trait(state, "Cachemon", 31)
    check("an attune choice overrides the tally", trait["element"] == "gale" and trait["chosen"])
    check("the choice is consumed", "attune" not in state)
    check("traits stack across the life", [t["element"] for t in state["traits"]] == ["forge", "gale"])


def test_rebirth_inherits_strongest_element():
    state = {"traits": _traits("tide", "forge", "forge", "tide", "forge")}
    inherited = el.inherit_on_rebirth(state, 2)
    check("strongest element is inherited", inherited == "forge")
    check("new life starts with exactly the inherited trait",
          [t["element"] for t in state["traits"]] == ["forge"])
    check("old life is archived in the lineage", len(state["lineage"][0]["traits"]) == 5)


def test_ranked_elements_ties_break_to_most_recent():
    check("tie goes to the most recent", el.ranked_elements(_traits("forge", "tide"))[0] == "tide")
    check("count beats recency", el.ranked_elements(_traits("forge", "forge", "tide"))[0] == "forge")


def test_seed_from_history_is_idempotent_and_ignores_aether_for_the_first_trait():
    state = {"sessions_seen": {
        "/a.jsonl": {"cwd": "/w/Claude", "tokens": 900},
        "/b.jsonl": {"cwd": "/w/Claude/cosmic_code", "tokens": 100},
    }}
    els = dl.load_evolution_data()["elements"]
    check("seeds a pre-elements pet", el.seed_from_history(state, els))
    check("lifetime tally rebuilt from session cwds",
          state["element_xp"] == {"aether": 900, "astral": 100})
    check("first trait is the strongest REAL element", state["traits"][0]["element"] == "astral")
    check("second call is a no-op", not el.seed_from_history(state, els))


def test_dress_never_paints_over_the_body():
    data = dl.load_evolution_data()
    pal = data["palette"]
    for s in data["stages"]:
        for f, frame in enumerate(sprites.sprite_frames(s)):
            for key in data["elements"]:
                dressed, _ = el.dress(s, data, _traits(key, key, key), 0, f)
                body_changed = any(
                    pal.get(frame[y][x]) and dressed[y][x] != frame[y][x]
                    for y in range(len(frame)) for x in range(len(frame[0])))
                if body_changed:
                    check(f"{s['name']} f{f} {key}: particles stay off the body", False)
    check("below attunement, particles only ever land on transparent pixels", True)


def test_dress_attuned_only_recolours_outline():
    data = dl.load_evolution_data()
    pal = data["palette"]
    s = data["stages"][2]
    frame = sprites.sprite_frames(s)[0]
    dressed, _ = el.dress(s, data, _traits(*["forge"] * el.ATTUNED_AT), 0, 0)
    changed = [frame[y][x] for y in range(16) for x in range(16)
               if pal.get(frame[y][x]) and dressed[y][x] != frame[y][x]]
    check("attuned pet's outline takes the element colour", len(changed) > 0)
    check("only outline (K) pixels are recoloured", set(changed) == {"K"})


def test_dress_grows_with_traits():
    data = dl.load_evolution_data()
    s = next(x for x in data["stages"] if x["name"] == "Bitmon")
    frame = sprites.sprite_frames(s)[0]

    def painted(traits):
        d, _ = el.dress(s, data, traits, 0, 0)
        return sum(1 for y in range(16) for x in range(16) if d[y][x] != frame[y][x])

    one, three = painted(_traits("forge")), painted(_traits("forge", "forge", "forge"))
    check("no traits = untouched sprite", painted([]) == 0)
    check("more traits = more elemental pixels", 0 < one < three)
    check("a second element adds its own particles",
          painted(_traits("forge", "forge", "tide")) > painted(_traits("forge", "forge")))


def test_dressed_frames_keep_frame_count_and_resolve_every_glyph():
    data = dl.load_evolution_data()
    for s in data["stages"]:
        frames, pal = el.dressed_frames(s, data, _traits("prism", "volt"), 3)
        check(f"{s['name']} keeps its frame count", len(frames) == len(sprites.sprite_frames(s)))
        used = set("".join("".join(f) for f in frames))
        check(f"{s['name']} every dressed glyph resolves", not (used - set(pal) - set(". ")))


def test_title_and_badge():
    data = dl.load_evolution_data()
    s = data["stages"][3]
    els = data["elements"]
    check("no traits = plain name", el.title(s, [], els) == s["name"])
    check("epithet from the primary element",
          el.title(s, _traits("forge"), els) == f"Blazing {s['name']}")
    check("attuned epithet at ATTUNED_AT traits",
          el.title(s, _traits(*["forge"] * el.ATTUNED_AT), els) == f"Forgeborn {s['name']}")
    check("badge lists elements strongest first", el.badge(_traits("tide", "forge", "forge"), els) == "🔥🌊")


def test_summary_does_not_mutate_a_pre_elements_state():
    state = {"sessions_seen": {"/a.jsonl": {"cwd": "/w/cosmic_code", "tokens": 5}}}
    out = el.summary(state, dl.load_evolution_data())
    check("summary shows the seeded trait", out["badge"] == "✴️")
    check("viewer did not write to the state", "element_xp" not in state)


def test_hook_credits_element_and_banks_trait_on_evolution():
    """Real hook, temp state: a cosmic_code session that crosses a stage boundary
    must credit Astral and bank an Astral trait, and say so."""
    import io
    import contextlib
    with tempfile.TemporaryDirectory() as d:
        saved = (dl.DIGIMON_DIR, dl.STATE_PATH, dl.LOCK_PATH, dl.ERROR_LOG_PATH)
        dl.DIGIMON_DIR = d
        dl.STATE_PATH = os.path.join(d, "state.json")
        dl.LOCK_PATH = os.path.join(d, "state.lock")
        dl.ERROR_LOG_PATH = os.path.join(d, "error.log")
        try:
            data = dl.load_evolution_data()
            need = int(dl.tokens_for_level(7, data["curve"]))   # Egg -> past Bitmon into Bytemon
            proj = os.path.join(d, "cosmic_code")
            os.makedirs(proj)
            tp = os.path.join(d, "t.jsonl")
            with open(tp, "wb") as f:
                f.write(('{"type":"assistant","message":{"usage":{"input_tokens":0,'
                         '"output_tokens":%d}}}\n' % need).encode())
            saved_stdin = sys.stdin
            sys.stdin = io.StringIO(json.dumps({"transcript_path": tp, "cwd": proj}))
            buf = io.StringIO()
            try:
                with contextlib.redirect_stdout(buf):
                    dh.main()
            finally:
                sys.stdin = saved_stdin
            state = dl.load_state()
            check("tokens credited to astral", state["element_xp"].get("astral") == need)
            check("an astral trait was banked on evolving",
                  [t["element"] for t in state.get("traits", [])] == ["astral"])
            check("the evolution message announces the trait", "Astral trait" in buf.getvalue())
            check("no errors logged", not os.path.exists(dl.ERROR_LOG_PATH))
        finally:
            dl.DIGIMON_DIR, dl.STATE_PATH, dl.LOCK_PATH, dl.ERROR_LOG_PATH = saved


def test_feed_carries_elements_block():
    payload = feed.build_feed()
    e = payload["elements"]
    check("feed has an elements block", {"traits", "badge", "line", "leaning", "attune"} <= set(e))
    check("raw trait list is not leaked into the feed", "_traits" not in e)
    check("stage carries a display title", isinstance(payload["stage"].get("title"), str))


def main():
    tests = [v for k, v in list(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        print(f"{t.__name__}:")
        t()
    print(f"\n{passed} assertions passed across {len(tests)} tests. ALL TESTS PASSED.")


if __name__ == "__main__":
    main()
