#!/usr/bin/env python3
"""Detects which subagent(s) the main session is currently working with, by
reading the tail of the session transcript the status line is handed on stdin.

Why parse the transcript instead of using PreToolUse/PostToolUse hooks: in this
build most subagents run ASYNC — their tool_result comes back immediately at
launch (status "async_launched"), and the real completion arrives later as a
`<task-notification>` line that fires no hook at all. So a Pre/Post-hook sidecar
would blink off the instant an async agent launched. The transcript is the one
place that reflects the true running/finished state for both sync and async
agents, and it self-corrects (no persistent state to get stuck)."""
import datetime
import json
import os
import re

import digimon_lib as dl

# In this build the subagent-spawn tool is named "Agent"; older/other builds
# call it "Task". Match both. TaskCreate/TaskUpdate/ScheduleWakeup are a
# different (todo/scheduling) system and must NOT be matched.
AGENT_TOOL_NAMES = {"Agent", "Task"}
_TOOL_USE_ID_RE = re.compile(r"<tool-use-id>\s*(toolu_[A-Za-z0-9]+)\s*</tool-use-id>")

# The status line re-scans the transcript tail on every bar refresh, so the hot
# path is parsing lines. Only spawn lines (carry a "name":"Agent"/"Task" tool_use),
# tool_result lines (carry toolUseResult), and async completions (task-notification)
# can ever affect the result — every other line (assistant prose, user text,
# thinking) is skipped BEFORE json.loads via a cheap substring test. The agent
# markers are quoted ("Agent"/"Task") so the transcript's compact JSONL only
# matches real tool names, not todo-system lines like TaskCreate/TaskUpdate.
_RELEVANT_MARKERS = (b'"Agent"', b'"Task"', b"toolUseResult", b"task-notification")


def _parse_ts(s):
    if not s:
        return None
    try:
        return datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def read_tail_entries(path, max_bytes=262_144):
    """Parse only the last max_bytes of the JSONL transcript. Cost is bounded
    regardless of how large the session grows. A running agent's spawn line is
    at/near the tail (a sync spawn blocks the main loop; an async spawn is
    recent), so the tail is enough to decide who's active. Falls back to 'idle'
    if a spawn has scrolled out of the window — better than a stuck bar.

    Only lines whose raw bytes contain an agent-relevant marker are JSON-parsed;
    everything else is cheaply skipped (see _RELEVANT_MARKERS)."""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            if size > max_bytes:
                f.seek(size - max_bytes)
                f.readline()  # drop the partial first line
            data = f.read()
    except OSError:
        return []
    entries = []
    for raw in data.split(b"\n"):
        if not any(marker in raw for marker in _RELEVANT_MARKERS):
            continue
        try:
            entries.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
    return entries


def detect_active_agents(transcript_path, now=None, stale_seconds=None):
    """Returns active subagents as a list of dicts (newest first):
    {"id", "agent", "desc", "started"} where started is an epoch float or None.

    A spawn is ACTIVE unless it has been closed by either:
      - a sync tool_result whose top-level toolUseResult.status == "completed", or
      - an async `<task-notification>` line referencing its tool-use-id.
    An async launch result (status "async_launched") does NOT close it.
    Spawns older than stale_seconds are dropped as a crash/resume safety net."""
    if not transcript_path:
        return []
    if now is None:
        now = datetime.datetime.now(datetime.timezone.utc)
    if stale_seconds is None:
        stale_seconds = dl.TRAINING_STALE_SECONDS

    entries = read_tail_entries(transcript_path)
    spawns = {}       # tool_use_id -> {"agent", "desc", "ts"}
    completed = set()  # tool_use_ids that have finished

    for entry in entries:
        etype = entry.get("type")
        message = entry.get("message") or {}
        content = message.get("content")

        if etype == "assistant" and isinstance(content, list):
            ts = _parse_ts(entry.get("timestamp", ""))
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_use" and block.get("name") in AGENT_TOOL_NAMES:
                    inp = block.get("input") or {}
                    spawns[block.get("id")] = {
                        "agent": inp.get("subagent_type") or "claude",
                        "desc": inp.get("description") or "",
                        "ts": ts,
                    }

        elif etype == "user":
            if isinstance(content, list):
                tur = entry.get("toolUseResult")
                status = tur.get("status") if isinstance(tur, dict) else None
                if status == "completed":
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "tool_result":
                            completed.add(block.get("tool_use_id"))
            elif isinstance(content, str) and "task-notification" in content:
                # async completion: the agent has stopped regardless of status
                for tuid in _TOOL_USE_ID_RE.findall(content):
                    completed.add(tuid)

    active = []
    for tuid, info in spawns.items():
        if tuid in completed:
            continue
        ts = info["ts"]
        started = None
        if ts is not None:
            age = (now - ts).total_seconds()
            if age > stale_seconds or age < -60:  # too old, or clock-skew future
                continue
            started = ts.timestamp()
        active.append({
            "id": tuid,
            "agent": info["agent"],
            "desc": info["desc"],
            "started": started,
        })

    active.sort(key=lambda e: (e["started"] is not None, e["started"] or 0), reverse=True)
    return active
