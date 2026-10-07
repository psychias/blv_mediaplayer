#!/usr/bin/env bash
# Fetch + stage all bundled models ONCE, at build time (§9.1). The developer runs
# this (needs internet once); the shipped app and the student never download anything.
#
# Output layout (the app resolves model paths from here, then packaging copies it
# into the .app bundle's Resources/models/ in Phase 4):
#   models/
#     ad4edu-qwen3vl-2b-mm-8bit/  description model: AD4Edu adapter merged into Qwen3-VL-2B,
#                                 8-bit MLX (private repo), ready to run — no merge step
#     kokoro/               mlx-community Kokoro-82M build + the af_heart voice pack
#     whisper/              whisper-large-v3-turbo in MLX format (what mlx-whisper loads)
#
# With --merge-sources it fetches instead the inputs for re-merging after retraining:
#     ad4edu-qwen3vl-2b-mm-lora/  AD4Edu LoRA adapter, multimodal arm (private repo)
#     qwen3vl-2b-base/         Qwen3-VL-2B-Instruct bf16 base the adapter was trained on
# then: python scripts/merge_adapter.py --base models/qwen3vl-2b-base \
#         --adapter models/ad4edu-qwen3vl-2b-mm-lora/seed0 --out models/ad4edu-qwen3vl-2b-mm-8bit
#
# Requires: pip install -e ".[build]"   (huggingface_hub)
#
# The description-model repos are PRIVATE: run `hf auth login` (or export HF_TOKEN) first.
#
# REPRODUCIBILITY: pin exact commit hashes in the *_REV vars below. They default to
# "main" with a warning — a real release build MUST pin them so every build matches
# the cache/manifest. Find a commit hash on the HF repo's "History" page.
set -euo pipefail
cd "$(dirname "$0")/.."

MODELS_DIR="${MODELS_DIR:-models}"
MERGE_SOURCES=0
[ "${1:-}" = "--merge-sources" ] && MERGE_SOURCES=1

# Merged + quantised description model (what config/real.yaml's vl.model points at).
VL_MERGED_REPO="${VL_MERGED_REPO:-Psychias/ad4edu-qwen3vl-2b-mm-8bit}"
VL_MERGED_REV="${VL_MERGED_REV:-main}"
VL_MERGED_DIR="${VL_MERGED_DIR:-ad4edu-qwen3vl-2b-mm-8bit}"

# Re-merge inputs (--merge-sources only).
VL_REPO="${VL_REPO:-Psychias/ad4edu-qwen3vl-2b-sft}"   # multimodal arm: keyframe image + OCR
VL_REV="${VL_REV:-main}"
VL_DIR="${VL_DIR:-ad4edu-qwen3vl-2b-mm-lora}"
# Base the adapter was trained on — pinned to the exact revision in the adapter's run_meta.json.
VL_BASE_REPO="${VL_BASE_REPO:-Qwen/Qwen3-VL-2B-Instruct}"
VL_BASE_REV="${VL_BASE_REV:-89644892e4d85e24eaac8bacfd4f463576704203}"

KOKORO_REPO="${KOKORO_REPO:-mlx-community/Kokoro-82M-bf16}"
KOKORO_REV="${KOKORO_REV:-main}"
KOKORO_VOICE="${KOKORO_VOICE:-af_heart}"   # must match tts.voice in config

# MLX-format weights: config/real.yaml points preprocess.whisper_model at this directory and
# mlx-whisper loads it offline. (The openai/ repo is the PyTorch format and would not load.)
WHISPER_REPO="${WHISPER_REPO:-mlx-community/whisper-large-v3-turbo}"
WHISPER_REV="${WHISPER_REV:-main}"

if [ -z "${HF_TOKEN:-}" ] && [ ! -f "${HF_HOME:-$HOME/.cache/huggingface}/token" ]; then
  echo "WARNING: not signed in to Hugging Face and HF_TOKEN is unset. The description model is private;" >&2
  echo "         run 'hf auth login' (or export HF_TOKEN) first or that fetch will fail." >&2
fi

for v in VL_MERGED_REV VL_REV KOKORO_REV WHISPER_REV; do
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
if [ "$MERGE_SOURCES" = 1 ]; then
  fetch "$VL_REPO"      "$VL_REV"      "$VL_DIR"
  fetch "$VL_BASE_REPO" "$VL_BASE_REV" "qwen3vl-2b-base"
else
  fetch "$VL_MERGED_REPO" "$VL_MERGED_REV" "$VL_MERGED_DIR"
fi
fetch "$KOKORO_REPO"  "$KOKORO_REV"  "kokoro" "config.json" "kokoro-v1_0.safetensors" "voices/$KOKORO_VOICE.safetensors"
fetch "$WHISPER_REPO" "$WHISPER_REV" "whisper"

# Kokoro's English G2P (misaki) tokenises with spaCy's en_core_web_sm, which is not on
# PyPI. Install it into the venv once here so first synthesis never hits the network.
echo ">> spaCy en_core_web_sm (Kokoro/misaki tokenizer)"
python - <<'PY'
import spacy
if not spacy.util.is_package("en_core_web_sm"):
    spacy.cli.download("en_core_web_sm")
print("   done: en_core_web_sm")
PY

echo
echo "All models fetched into '$MODELS_DIR/'. config/real.yaml already points at them:"
if [ "$MERGE_SOURCES" = 1 ]; then
  echo "  vl.model:               $MODELS_DIR/$VL_MERGED_DIR   (after scripts/merge_adapter.py, see header)"
else
  echo "  vl.model:               $MODELS_DIR/$VL_MERGED_DIR"
fi
echo "  tts.kokoro.model_path:  $MODELS_DIR/kokoro    (tts.voice: $KOKORO_VOICE)"
echo "  preprocess.whisper_model: $MODELS_DIR/whisper"
