#!/usr/bin/env bash
# Fetch + stage all bundled models ONCE, at build time (§9.1). The developer runs
# this (needs internet once); the shipped app and the student never download anything.
#
# Output layout (the app resolves model paths from here, then packaging copies it
# into the .app bundle's Resources/models/ in Phase 4):
#   models/
#     gemma4-e2b-it-4bit/   4-bit MLX VL weights (mlx-vlm)
#     voxtral/              mlx-community Voxtral-4B-TTS build
#     whisper/              whisper turbo weights
#
# Requires: pip install -e ".[build]"   (huggingface_hub)
#
# REPRODUCIBILITY: pin exact commit hashes in the *_REV vars below. They default to
# "main" with a warning — a real release build MUST pin them so every build matches
# the cache/manifest. Find a commit hash on the HF repo's "History" page.
set -euo pipefail
cd "$(dirname "$0")/.."

MODELS_DIR="${MODELS_DIR:-models}"

# 4-bit MLX VL model (NOT the -gguf / -w4a16-ct variants, which mlx-vlm won't load).
VL_REPO="${VL_REPO:-mlx-community/gemma-4-e2b-it-4bit}"
VL_REV="${VL_REV:-main}"
VL_DIR="${VL_DIR:-gemma4-e2b-it-4bit}"

VOXTRAL_REPO="mlx-community/Voxtral-4B-TTS-2603-mlx-4bit"   # non-gated mirror, no token needed
VOXTRAL_REV="${VOXTRAL_REV:-main}"

WHISPER_REPO="${WHISPER_REPO:-openai/whisper-large-v3-turbo}"
WHISPER_REV="${WHISPER_REV:-main}"

for v in VL_REV VOXTRAL_REV WHISPER_REV; do
  if [ "${!v}" = "main" ]; then
    echo "WARNING: $v is 'main' (not pinned). Pin a commit hash for a reproducible release build." >&2
  fi
done

fetch() {  # repo  revision  dest-subdir  [allow-patterns...]
  local repo="$1" rev="$2" dest="$3"; shift 3
  echo ">> $repo @ $rev -> $MODELS_DIR/$dest"
  python - "$repo" "$rev" "$MODELS_DIR/$dest" "$@" <<'PY'
import sys
from huggingface_hub import snapshot_download
repo, rev, dest, *patterns = sys.argv[1:]
snapshot_download(
    repo_id=repo,
    revision=rev,
    local_dir=dest,
    allow_patterns=patterns or None,
)
print("   done:", dest)
PY
}

mkdir -p "$MODELS_DIR"
fetch "$VL_REPO"      "$VL_REV"      "$VL_DIR"
fetch "$VOXTRAL_REPO" "$VOXTRAL_REV" "voxtral"
fetch "$WHISPER_REPO" "$WHISPER_REV" "whisper"

echo
echo "All models fetched into '$MODELS_DIR/'. Point config at them, e.g.:"
echo "  vl.model:               $MODELS_DIR/$VL_DIR"
echo "  tts.voxtral.model_path: $MODELS_DIR/voxtral"
echo "  preprocess.whisper_model: turbo   (or a path under $MODELS_DIR/whisper)"
