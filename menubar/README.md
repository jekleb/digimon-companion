# Tokimon in the menu bar

A tiny macOS app that puts the companion in the **menu bar** — the same strip the
notch sits in on a notched Mac — so the pet is visible all the time, not only
inside a Claude Code session.

```
🟠 ▮▮▮▯▯▯▯▯  Lv.428★
```

- the current stage's **8-bit sprite**, animated (a slow breathe when idle, a
  sparring judder while a subagent runs)
- a chunky **XP bar** whose leading segment charges, tinted with the pet's own palette
- **level + prestige badge**, and the lead training agent's icon while training
- click it for a panel with the sprite at 6×, stage, tagline, XP, lifetime
  tokens, the next evolution, and the live training roster

## Requirements

macOS 13+ and the Xcode **Command Line Tools** (`xcode-select --install`).
No Xcode.app, no project file, no dependencies — one `swiftc` invocation.

## Build and run

```bash
cd menubar && ./build.sh
```

That produces `menubar/build/Tokimon.app` (a universal binary where the SDK
allows), ad-hoc signs it, and launches it. Look at the **far right of the menu
bar**, to the left of the system icons. `./build.sh --no-run` builds only.

To start it automatically, open the pet's menu and tick **Start at Login** —
that writes `~/Library/LaunchAgents/com.jekleb.tokimon.menubar.plist`. Untick to
remove it.

Move `Tokimon.app` afterwards and the login item **repoints itself** the next
time you open the app from its new location — otherwise launchd would go on
starting a path that no longer exists, silently, and the pet would just stop
showing up at login with nothing to explain why. (Repointing is skipped for an
app running from Gatekeeper's read-only translocation mount, since that path
vanishes on quit.)

## Menu

| Item | What it does |
|---|---|
| *(panel)* | Sprite at 6×, stage, XP, lifetime tokens, next evolution, training roster |
| Refresh Now | Re-reads the feed immediately |
| Open Live View in Terminal | Runs `digimon_cli.py live` in Terminal |
| Copy Status | Puts a one-line summary on the clipboard |
| Start at Login | Installs / removes the LaunchAgent |
| Quit Tokimon | Quits |

## How it fits together

The app is a **pure presentation layer**. Every rule about the pet — XP curve,
16-stage tree, prestige recolor — stays in the Python engine, so there is one
source of truth and the menu bar can never disagree with the status line.

```
digimon_hook.py  ──writes──▶  ~/.claude/digimon/state.json
                                        │
                            tokimon_feed.py  (JSON snapshot:
                              stage, level, XP, sprite rows,
                              prestige-shifted palette, live agents)
                                        │  polled every 10s idle / 2s training
                                  Tokimon.app  ──draws at 4 fps──▶  menu bar
```

Two clocks on purpose: **data** is polled on a subprocess, while the
**animation** redraws from a wall-clock frame index — so the pet looks alive
without spawning a process per frame.

The poll interval adapts: **10s when idle, 2s while a subagent is training**.
Idle is where the day is spent, and each run costs a Python start plus a stat of
every recent transcript, so a flat cadence spent most of its budget confirming
nothing had changed — while being *less* responsive at the one moment worth
watching.

`tokimon_feed.py` also solves a problem the status line doesn't have: nothing
hands the menu bar a `transcript_path`, because it lives outside any session. So
it finds the recently-written transcripts under `~/.claude/projects/` itself and
unions their active subagents — which is what makes the pet train while *any*
session is working, in any project.

```bash
python3 tokimon_feed.py              # one JSON snapshot
python3 tokimon_feed.py --watch 2.5  # a line every 2.5s
```

## Notes

- **Pixel-crisp by construction.** Sprite and bar cells are snapped to whole
  device pixels before filling, so the art stays hard-edged on Retina and
  non-Retina displays alike instead of going soft at fractional scales.
- **The engine is copied into the bundle**, not read from the checkout. If the
  repo lives under `~/Documents` (or `~/Desktop`, or iCloud Drive) it is
  TCC-protected, and a GUI-launched menu-bar app reading it **hangs forever** on
  a privacy prompt an accessory app never gets to display. Nothing inside an app
  bundle is protected, so the bundled copy just works. Practical consequence:
  after editing `evolution_data.json` or any engine module, re-run `./build.sh`
  to pick the change up. `TOKIMON_DIR` overrides the location if you want the
  app to read a live checkout instead.
- **Live state is still shared.** Only the *code* is bundled — level, tokens and
  prestige are read from `~/.claude/digimon/state.json`, the same file the Stop
  hook writes, so the menu bar and the status line can never disagree.
- **Failures are logged**, never silent, to `~/.claude/digimon/menubar.log`. A
  feed run that can't finish is killed after 10s rather than left behind.
- **The notch itself.** macOS gives apps no API to draw *inside* the notch —
  menu-bar items flow around it. This app takes the adjacent slot, which is the
  closest thing macOS actually supports without a screen-overlay hack.
- `./build/Tokimon.app --panel-png out.png` renders the detail panel straight to
  a file, for checking layout changes without opening the menu.
