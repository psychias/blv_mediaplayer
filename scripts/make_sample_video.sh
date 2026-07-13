#!/usr/bin/env bash
# Make a tiny synthetic 2-slide lecture video for testing the real (Phase 2) path.
# Two slides with on-screen text (so OCR has something) + a tone track. NOT a real
# lecture — just enough to exercise ffmpeg + scene detection + OCR end to end.
# Usage: scripts/make_sample_video.sh [out.mp4]
set -euo pipefail
OUT="${1:-sample.mp4}"

ffmpeg -y -loglevel error \
  -f lavfi -i "color=c=white:s=640x480:d=4,format=yuv420p" \
  -f lavfi -i "color=c=white:s=640x480:d=4,format=yuv420p" \
  -f lavfi -i "sine=frequency=330:duration=8" \
  -filter_complex "\
    [0:v]drawtext=text='Slide 1\: System Architecture':x=40:y=200:fontsize=36:fontcolor=black[v0]; \
    [1:v]drawtext=text='Slide 2\: Results Table':x=40:y=200:fontsize=36:fontcolor=black[v1]; \
    [v0][v1]concat=n=2:v=1:a=0[v]" \
  -map "[v]" -map 2:a -t 8 -r 10 "$OUT"

echo "wrote $OUT (two slides, scene change at ~4s)"
