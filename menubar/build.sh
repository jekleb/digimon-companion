#!/bin/bash
# Builds Tokimon.app — the menu-bar companion. Needs only the Xcode Command Line
# Tools (swiftc + the macOS SDK); no Xcode.app, no project file, no dependencies.
#
#   ./build.sh          build, then relaunch the app
#   ./build.sh --no-run build only
set -euo pipefail

cd "$(dirname "$0")"

APP="build/Tokimon.app"
BIN="$APP/Contents/MacOS/Tokimon"
MIN_MACOS="13.0"

command -v swiftc >/dev/null 2>&1 || {
  echo "swiftc not found. Install the Command Line Tools:  xcode-select --install" >&2
  exit 1
}

echo "==> preparing bundle"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

echo "==> compiling"
# Native arch first, with compiler output shown — a real syntax error must fail
# loudly here rather than get mistaken for "this arch isn't supported".
NATIVE="$(uname -m)"
swiftc -O -target "${NATIVE}-apple-macos${MIN_MACOS}" main.swift -o "build/Tokimon-${NATIVE}"
echo "    built ${NATIVE}"
slices=("build/Tokimon-${NATIVE}")

# Then the other arch, so one build runs on both Intel and Apple Silicon (where
# the notch actually exists). Quiet failure here is fine — it only costs
# portability, not this machine's build.
OTHER="arm64"; [ "$NATIVE" = "arm64" ] && OTHER="x86_64"
if swiftc -O -target "${OTHER}-apple-macos${MIN_MACOS}" \
    main.swift -o "build/Tokimon-${OTHER}" 2>/dev/null; then
  slices+=("build/Tokimon-${OTHER}")
  echo "    built ${OTHER}"
else
  echo "    skipped ${OTHER} (SDK on this machine can't cross-compile it)"
fi

if [ ${#slices[@]} -eq 1 ]; then
  mv "${slices[0]}" "$BIN"
else
  lipo -create "${slices[@]}" -output "$BIN"
  rm -f "${slices[@]}"
fi
chmod +x "$BIN"

echo "==> bundling the Python engine"
# Copied into the bundle rather than read from the checkout on purpose. A repo
# under ~/Documents (or ~/Desktop, or iCloud Drive) is TCC-protected, and a
# GUI-launched menu-bar app reading it hangs forever on a privacy prompt it can
# never display. Nothing inside an app bundle is protected.
ENGINE="$APP/Contents/Resources/engine"
mkdir -p "$ENGINE"
for f in tokimon_feed.py digimon_lib.py digimon_agents.py digimon_sprites.py evolution_data.json; do
  cp "../$f" "$ENGINE/$f"
done

echo "==> writing Info.plist"
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Tokimon</string>
  <key>CFBundleDisplayName</key><string>Tokimon</string>
  <key>CFBundleIdentifier</key><string>com.jekleb.tokimon.menubar</string>
  <key>CFBundleExecutable</key><string>Tokimon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>LSMinimumSystemVersion</key><string>${MIN_MACOS}</string>
  <!-- menu-bar only: no Dock icon, no app switcher entry -->
  <key>LSUIElement</key><true/>
  <key>NSHighResolutionCapable</key><true/>
  <!-- Only needed if TOKIMON_DIR points the engine back at a protected folder;
       the bundled engine avoids the prompt entirely. Without this string macOS
       denies the request outright instead of asking. -->
  <key>NSDocumentsFolderUsageDescription</key>
  <string>Tokimon reads your companion's data from the digimon-companion folder.</string>
</dict>
</plist>
PLIST

# Ad-hoc signature so Gatekeeper lets a locally built app launch without a
# right-click-Open dance. Harmless if codesign is unavailable.
codesign --force --deep --sign - "$APP" >/dev/null 2>&1 && echo "==> ad-hoc signed" || true

echo "==> built $APP"

if [ "${1:-}" != "--no-run" ]; then
  echo "==> launching"
  pkill -x Tokimon >/dev/null 2>&1 || true
  sleep 0.4
  open "$APP"
  echo "    look for the pet in your menu bar (far right of the icons)"
fi
