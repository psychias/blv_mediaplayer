#!/usr/bin/env bash
# Assemble a SELF-CONTAINED LectureAD.app that runs on any Apple Silicon Mac with nothing
# installed: no repo, no virtualenv, no model downloads, no network.
#
# What goes inside Contents/Resources:
#   python/      a relocatable standalone CPython (python-build-standalone, via uv) with
#                ladpipe and its real backends installed into it. NOT a virtualenv — a venv
#                records its base interpreter by absolute path and would break once moved.
#   models/      the VL weights, the Kokoro voice and the Whisper weights
#   config.yaml  config/real.yaml with every path rewritten relative to Resources
#   ladpipe      launcher that execs the bundled interpreter as `python -m ladpipe`
#   dev.json     { "cmd": "ladpipe", "config": "config.yaml" } — relative, so AppModel
#                resolves both inside the bundle (see AppModel.bundleRelative)
#
# Usage:  scripts/build_dist.sh [output.app]
set -euo pipefail
cd "$(dirname "$0")/.."
REPO="$(pwd)"

APP="${1:-$REPO/dist/LectureAD.app}"
PYTHON_VERSION="${PYTHON_VERSION:-3.13}"
VL_MODEL="${VL_MODEL:-models/ad4edu-qwen3vl-2b-mm-8bit}"
KOKORO_MODEL="${KOKORO_MODEL:-models/kokoro}"
WHISPER_REPO_DIR="${WHISPER_REPO_DIR:-$HOME/.cache/huggingface/hub/models--mlx-community--whisper-large-v3-turbo}"

command -v uv >/dev/null || { echo "uv is required (https://docs.astral.sh/uv/)" >&2; exit 1; }
[ -d "$VL_MODEL" ]     || { echo "missing $VL_MODEL — run scripts/merge_adapter.py first" >&2; exit 1; }
[ -d "$KOKORO_MODEL" ] || { echo "missing $KOKORO_MODEL — run scripts/fetch_models.sh first" >&2; exit 1; }

echo ">> 1/8 compiling the app"
rm -rf "$APP"
mkdir -p "$(dirname "$APP")"
app/build_app.sh "$APP" >/dev/null
RES="$APP/Contents/Resources"

echo ">> 2/8 staging a relocatable CPython $PYTHON_VERSION"
STAGE="$(mktemp -d)"
UV_PYTHON_INSTALL_BIN=0 UV_PYTHON_INSTALL_DIR="$STAGE" \
  uv python install --managed-python "$PYTHON_VERSION" >/dev/null 2>&1
# uv leaves a versioned directory plus a shorter symlink alias beside it; take the real
# directory, never the alias, or mv sees two sources and refuses.
SRC="$(find "$STAGE" -mindepth 1 -maxdepth 1 -type d -name 'cpython-*' | head -1)"
[ -n "$SRC" ] || { echo "uv did not install a Python into $STAGE" >&2; exit 1; }
mv "$SRC" "$RES/python"
rm -rf "$STAGE"
PY="$RES/python/bin/python3"
[ -x "$PY" ] || { echo "no interpreter at $PY" >&2; exit 1; }
"$PY" -c 'import sys; print("   interpreter:", sys.version.split()[0], "at", sys.prefix)'

echo ">> 3/8 installing ladpipe and its real backends into the bundle"
# python-build-standalone ships an EXTERNALLY-MANAGED marker so package managers refuse to
# touch a system Python. This copy is private to the bundle and is meant to be installed
# into, so the marker goes.
rm -f "$RES"/python/lib/python*/EXTERNALLY-MANAGED
uv pip install --quiet --python "$PY" --system ".[real]"
# Kokoro's English G2P needs spaCy's en_core_web_sm, which is not on PyPI; copy the copy
# the dev venv already has so the build stays offline.
SITE="$("$PY" -c 'import site; print(site.getsitepackages()[0])')"
cp -R .venv/lib/python*/site-packages/en_core_web_sm* "$SITE/" 2>/dev/null || \
  echo "   WARNING: en_core_web_sm not found in .venv — Kokoro may fall back to espeak" >&2

echo ">> 4/8 copying models (this is the bulk of the bundle)"
mkdir -p "$RES/models"
cp -R "$VL_MODEL"     "$RES/models/$(basename "$VL_MODEL")"
cp -R "$KOKORO_MODEL" "$RES/models/kokoro"
if [ -d "$WHISPER_REPO_DIR" ]; then
  SNAP="$(find "$WHISPER_REPO_DIR/snapshots" -mindepth 1 -maxdepth 1 -type d | head -1)"
  cp -RL "$SNAP" "$RES/models/whisper"        # -L: the HF cache stores files as symlinks
else
  echo "   WARNING: no local Whisper weights; the app will need the network once" >&2
fi
cp rules_for_slides.yaml "$RES/rules_for_slides.yaml" 2>/dev/null || true

echo ">> 5/8 bundling ffmpeg and ffprobe"
# macOS ships neither, and the recipient may have no Homebrew. Copy the two tools plus
# their dylib closure and rewrite the load paths to @executable_path, so they run from
# inside the bundle with nothing installed. NOTE: Homebrew's ffmpeg is a GPL build --
# redistributing it carries the GPL's source-offer obligation.
"$PY" - "$RES/media" <<'MEDIA'
import os, pathlib, shutil, subprocess, sys

dest = pathlib.Path(sys.argv[1]); dest.mkdir(parents=True, exist_ok=True)

def deps(path):
    out = subprocess.run(["otool", "-L", path], capture_output=True, text=True).stdout
    return [ln.split()[0] for ln in out.splitlines()[1:]
            if ln.strip().startswith(("/opt/homebrew", "/usr/local/"))]

tools = [shutil.which(n) for n in ("ffmpeg", "ffprobe")]
if not all(tools):
    print("   WARNING: ffmpeg/ffprobe not on PATH; the app will need them installed", file=sys.stderr)
    raise SystemExit(0)

real, queue = set(), list(tools)
while queue:
    p = queue.pop()
    if not p or not os.path.exists(p):
        continue
    rp = os.path.realpath(p)
    if rp in real:
        continue
    real.add(rp)
    queue.extend(deps(rp))

for src in real:
    shutil.copy2(src, dest / os.path.basename(src))
for f in sorted(dest.iterdir()):
    subprocess.run(["install_name_tool", "-id", f"@executable_path/{f.name}", str(f)],
                   capture_output=True)
    for old in deps(str(f)):
        new = f"@executable_path/{os.path.basename(os.path.realpath(old))}"
        subprocess.run(["install_name_tool", "-change", old, new, str(f)], capture_output=True)
    os.chmod(f, 0o755)

left = deps(str(dest / "ffmpeg"))
print(f"   bundled {len(real)} files; unresolved absolute deps: {len(left)}")
if left:
    print("   " + "\n   ".join(left), file=sys.stderr)
MEDIA

echo ">> 6/8 writing the shipped config (paths relative to Resources)"
"$PY" - "$RES" <<'PY'
import sys, pathlib, yaml
res = pathlib.Path(sys.argv[1])
cfg = yaml.safe_load(pathlib.Path("config/real.yaml").read_text())
cfg["vl"]["model"] = "models/" + pathlib.Path(cfg["vl"]["model"]).name
cfg["tts"]["kokoro"]["model_path"] = "models/kokoro"
if (res / "models/whisper").is_dir():
    cfg["preprocess"]["whisper_model"] = "models/whisper"
if (res / "rules_for_slides.yaml").is_file():
    cfg["rules_file"] = "rules_for_slides.yaml"
else:
    cfg.pop("rules_file", None)
# The cache must live where the user can write; never inside the bundle.
cfg["cache"]["dir"] = "~/Library/Application Support/LectureAD/cache"
(res / "config.yaml").write_text(yaml.safe_dump(cfg, sort_keys=False))
print("   wrote", res / "config.yaml")
PY

echo ">> 7/8 writing the launcher and the launch config"
cat > "$RES/ladpipe" <<'SH'
#!/bin/sh
# Runs the bundled interpreter as `python -m ladpipe`, so no console-script shebang
# (which would carry a build-machine path) is involved.
DIR=$(cd "$(dirname "$0")" && pwd)
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
export LADPIPE_MEDIA_DIR="$DIR/media"   # the bundled ffmpeg/ffprobe win over any on PATH
# mlx_whisper (and other libraries) shell out to a bare `ffmpeg`, and a GUI app inherits a
# minimal PATH, so put the bundled copies on it too.
export PATH="$DIR/media:$PATH"
exec "$DIR/python/bin/python3" -m ladpipe "$@"
SH
chmod +x "$RES/ladpipe"
printf '{ "cmd": "ladpipe", "config": "config.yaml", "stream": "0" }\n' > "$RES/dev.json"

echo ">> 8/8 trimming and signing"
find "$RES/python" -name "__pycache__" -type d -prune -exec rm -rf {} + 2>/dev/null || true
find "$RES/python" -name "*.pyc" -delete 2>/dev/null || true
# Rewriting load paths with install_name_tool invalidates Homebrew's signature, and macOS
# SIGKILLs a binary whose signature no longer matches its contents. `codesign --deep` does
# not cover executables that live in Resources, so sign those first, then seal the app.
find "$RES/media" -type f -perm -u+x -exec codesign -s - --force {} \; 2>/dev/null || true
codesign -s - --force --deep "$APP" 2>/dev/null || echo "   (ad-hoc signing reported a warning)"

echo
echo "built: $APP  ($(du -sh "$APP" | cut -f1))"
echo
echo "Send it as a zip:  ditto -c -k --keepParent \"$APP\" LectureAD.zip"
echo "On the other Mac, after unzipping, the first open needs one of:"
echo "  - right-click the app, choose Open, then Open again; or"
echo "  - xattr -dr com.apple.quarantine /Applications/LectureAD.app"
