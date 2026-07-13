#!/usr/bin/env bash
# Build LectureAD.app with swiftc (no Xcode required) and assemble the .app bundle.
# Ad-hoc signs it so it launches locally (Phase 4 produces the .dmg).
set -euo pipefail
cd "$(dirname "$0")"

APP="${1:-build/LectureAD.app}"
SRC=(LectureAD/Sources/*.swift)
DEPLOY_TARGET="arm64-apple-macosx14.0"

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp LectureAD/Info.plist "$APP/Contents/Info.plist"

echo ">> compiling ${#SRC[@]} Swift sources"
swiftc -swift-version 5 -O -parse-as-library \
  -target "$DEPLOY_TARGET" \
  -framework SwiftUI -framework AVKit -framework AVFoundation -framework AppKit -framework MediaPlayer \
  "${SRC[@]}" \
  -o "$APP/Contents/MacOS/LectureAD"

# Bake the dev launch config into the bundle so `open` works (it can't pass env vars),
# and so the app is launched via LaunchServices — which is what makes NSAppSleepDisabled
# actually prevent App Nap from suspending the sidecar when the window loses focus.
REPO="$(cd .. && pwd)"   # we already cd'd into app/ above; repo root is its parent
# Default to BATCH ("Smoothest playback"): prepare the whole lecture first, then play from the
# cache with NO inference running — smoothest on low-RAM (8 GB) Macs, where streaming's prepare-
# while-you-watch contends with video decode on the GPU. The start-screen toggle can still pick
# "Start sooner" (streaming) per session. Set "stream":"1" here to default to streaming instead.
cat > "$APP/Contents/Resources/dev.json" <<JSON
{ "cmd": "$REPO/.venv/bin/ladpipe", "config": "$REPO/config/real.yaml", "stream": "0" }
JSON

# Bundle the brand images (logo + loading icon) into Resources.
cp "$REPO/images/logo.png" "$REPO/images/loading_icon.png" "$APP/Contents/Resources/" 2>/dev/null || \
  echo "WARNING: images/ not found — app will fall back to text" >&2

# Generate the macOS app (dock) icon from the logo.
if command -v iconutil >/dev/null && [ -f "$REPO/images/logo.png" ]; then
  ICONSET="$(mktemp -d)/AppIcon.iconset"; mkdir -p "$ICONSET"
  for s in 16 32 128 256 512; do
    sips -z $s $s "$REPO/images/logo.png" --out "$ICONSET/icon_${s}x${s}.png" >/dev/null 2>&1
    sips -z $((s*2)) $((s*2)) "$REPO/images/logo.png" --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null 2>&1
  done
  iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/AppIcon.icns" 2>/dev/null && \
    /usr/libexec/PlistBuddy -c "Add :CFBundleIconFile string AppIcon" "$APP/Contents/Info.plist" 2>/dev/null || true
fi

echo ">> ad-hoc signing"
codesign -s - --force --deep "$APP" 2>/dev/null || true

echo "built: $APP"
echo
echo "Run it (launch via 'open' so macOS App Nap can't suspend preparation when the"
echo "window loses focus — dev config is baked into the bundle):"
echo "  open \"$APP\""
echo
echo "Override per-launch with env vars instead (run the binary directly):"
echo "  LADPIPE_MOCK=1 \"$APP/Contents/MacOS/LectureAD\"   # no-models UI demo"
