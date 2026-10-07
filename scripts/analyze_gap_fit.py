#!/usr/bin/env python3
"""Gap-fit analysis: turn a real lecture's pause structure into a fine-tune length
target and an evidence-based pause-vs-drop policy.

Inputs (produced cheaply, no VL/Whisper):
  - scenes file: ffmpeg `select='gt(scene,T)',metadata=print` output (pts_time per slide change)
  - silences file: ffmpeg `silencedetect` output (silence_start / silence_duration)

Model: Voxtral duration calibrated on-device as dur(words) ~= A + B*words (see --a/--b).
Rung rules mirror the pipeline: rung1 gap-insert (dur<=gap), rung2 compress (dur<=gap*cap).

Usage:
  python scripts/analyze_gap_fit.py --scenes /tmp/anat_scenes.txt \
      --silences /tmp/anat_silences.txt --audio-end 2953.0
"""

from __future__ import annotations

import argparse
import re
import statistics
from pathlib import Path

_PTS = re.compile(r"pts_time:([0-9.]+)")
_SIL_START = re.compile(r"silence_start: ([0-9.]+)")
_SIL_DUR = re.compile(r"silence_duration: ([0-9.]+)")


def parse_scenes(path: str) -> list[float]:
    text = Path(path).read_text()
    return [0.0] + [float(x) for x in _PTS.findall(text)]


def parse_silences(path: str) -> list[tuple[float, float]]:
    starts, durs = [], []
    for line in Path(path).read_text().splitlines():
        m = _SIL_START.search(line)
        if m:
            starts.append(float(m.group(1)))
        m = _SIL_DUR.search(line)
        if m:
            durs.append(float(m.group(1)))
    return list(zip(starts, durs, strict=False))


def best_gap_per_slide(
    scenes: list[float], silences: list[tuple[float, float]], audio_end: float
) -> list[float]:
    bounds = sorted(scenes) + [audio_end]
    gaps = []
    for i in range(len(bounds) - 1):
        lo, hi = bounds[i], bounds[i + 1]
        in_span = [d for (s, d) in silences if lo <= s < hi]
        gaps.append(max(in_span) if in_span else 0.0)
    return gaps


def dur(words: int, a: float, b: float) -> float:
    return a + b * words


def pct(values: list[float], p: float) -> float:
    s = sorted(values)
    k = (len(s) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenes", required=True)
    ap.add_argument("--silences", required=True)
    ap.add_argument("--audio-end", type=float, required=True)
    ap.add_argument("--a", type=float, default=1.379, help="Voxtral intercept (s)")
    ap.add_argument("--b", type=float, default=0.573, help="Voxtral s/word")
    ap.add_argument("--compress-cap", type=float, default=1.3)
    args = ap.parse_args()

    scenes = parse_scenes(args.scenes)
    silences = parse_silences(args.silences)
    gaps = best_gap_per_slide(scenes, silences, args.audio_end)
    n = len(gaps)

    print(f"# Gap-fit analysis  ({n} slides, {len(silences)} pauses, "
          f"{args.audio_end/60:.0f}-min lecture)\n")
    print("Per-slide BEST gap (s): "
          f"median={statistics.median(gaps):.2f}  p25={pct(gaps,.25):.2f}  "
          f"p75={pct(gaps,.75):.2f}  p90={pct(gaps,.90):.2f}  max={max(gaps):.2f}")
    print(f"Voxtral dur(words) = {args.a:.2f} + {args.b:.2f}*words   "
          f"compress cap = {args.compress_cap}x\n")

    print("AD_words  dur_s   gap_insert%  +compress%  =spoken%   marker_or_drop%")
    for w in (3, 4, 5, 6, 8, 10, 12, 15):
        d = dur(w, args.a, args.b)
        r1 = sum(1 for g in gaps if d <= g)
        r2 = sum(1 for g in gaps if g < d <= g * args.compress_cap)
        spoken = r1 + r2
        print(f"{w:7d}  {d:5.1f}   {100*r1/n:9.0f}  {100*r2/n:9.0f}  "
              f"{100*spoken/n:8.0f}   {100*(n-spoken)/n:13.0f}")

    # Length target: max words for >=50% spoken placement.
    target = None
    for w in range(20, 2, -1):
        d = dur(w, args.a, args.b)
        spoken = sum(1 for g in gaps if d <= g * args.compress_cap)
        if spoken / n >= 0.50:
            target = (w, d, spoken / n)
            break
    if target:
        print(f"\nLENGTH TARGET (>=50% spoken): <= {target[0]} words "
              f"(~{target[1]:.1f}s), places in {100*target[2]:.0f}% of slides.")


if __name__ == "__main__":
    main()
