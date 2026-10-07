#!/usr/bin/env bash
# Make a tiny synthetic 2-slide lecture video for testing the real (Phase 2) path.
# Two slides with on-screen text (so OCR has something) and a clearly different layout
# (so ffmpeg scene detection fires at the change), plus a tone track. NOT a real lecture —
# just enough to exercise ffmpeg + scene detection + OCR + the description model end to end.
#
# The slides are rendered with Pillow (installed by the [real] extra) rather than ffmpeg's
# drawtext filter, which the current Homebrew ffmpeg is built without.
# Usage: scripts/make_sample_video.sh [out.mp4]
set -euo pipefail
OUT="${1:-sample.mp4}"
PY="${PYTHON:-python}"
command -v ffmpeg >/dev/null || { echo "ffmpeg is required (brew install ffmpeg)" >&2; exit 1; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

"$PY" - "$TMP" <<'PYEOF'
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    sys.exit("Pillow is required: pip install -e '.[real]' (or pip install pillow)")

out = Path(sys.argv[1])
try:
    font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 36)
    small = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 28)
except OSError:
    font = small = ImageFont.load_default()

# Slide 1: white, a title and a two-box diagram.
im = Image.new("RGB", (640, 480), "white")
d = ImageDraw.Draw(im)
d.text((40, 50), "Slide 1: System Architecture", fill="black", font=font)
d.rectangle((60, 160, 300, 400), outline="black", width=4)
d.text((100, 260), "Encoder", fill="black", font=small)
d.rectangle((340, 160, 580, 400), outline="black", width=4)
d.text((380, 260), "Decoder", fill="black", font=small)
d.line((300, 280, 340, 280), fill="black", width=4)
im.save(out / "slide1.png")

# Slide 2: dark background and a 3x4 table, so the scene score at the change is high.
im = Image.new("RGB", (640, 480), (20, 40, 90))
d = ImageDraw.Draw(im)
d.text((40, 50), "Slide 2: Results Table", fill="white", font=font)
for r in range(4):
    for c in range(3):
        x, y = 60 + c * 170, 150 + r * 65
        d.rectangle((x, y, x + 160, y + 55), fill="white")
        d.text((x + 12, y + 10), f"{r * 3 + c}", fill="black", font=small)
im.save(out / "slide2.png")
PYEOF

ffmpeg -y -loglevel error \
  -loop 1 -t 4 -i "$TMP/slide1.png" \
  -loop 1 -t 4 -i "$TMP/slide2.png" \
  -f lavfi -i "sine=frequency=330:duration=8" \
  -filter_complex "[0:v]format=yuv420p[v0];[1:v]format=yuv420p[v1];[v0][v1]concat=n=2:v=1:a=0[v]" \
  -map "[v]" -map 2:a -t 8 -r 10 "$OUT"

echo "wrote $OUT (two slides, scene change at ~4s)"
