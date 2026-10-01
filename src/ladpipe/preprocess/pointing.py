"""Pointing detection: the moments the lecturer's cursor comes to rest on a slide.

Scene detection cannot see these. On a static slide the cursor changes about ten pixels
per frame, a scene score of ~0.01 against a threshold of 0.15, and no moment is ever made
for it. Yet ``pointing`` is the largest class in the corpus the AD model was trained on
(3,559 of 6,868 moments), so without this module the model's best-trained behaviour is
never exercised.

The approach tracks the only thing that moves on a static slide: consecutive frames are
decoded small and grey, differenced, and the changed pixels' centroid is followed. A
*dwell* is a deliberate move followed by the cursor holding still. It is fail-closed by
construction: a recording with no cursor produces no motion and no events, and a slide
with an embedded video changes far more pixels than a cursor can, which resets tracking.

``dwells`` is pure and unit-tested on synthetic motion; ``track_motion`` produces the
motion statistics from video via ffmpeg and is the only part that touches numpy.
"""

from __future__ import annotations

import math
import subprocess
from dataclasses import dataclass

# Calibrated on a 1280x720 lecture recording: the cursor changed 1-11 pixels per frame on a
# 480x270 canvas at threshold 40, with exact zeros between moves (no compression noise).
FPS = 5
CANVAS = (480, 270)
DIFF_THRESHOLD = 40
MAX_CURSOR_PIXELS = 600  # more than this is an animation or video, not a cursor
MIN_MOVE_FRAMES = 2  # a one-frame blip is noise, not a gesture
EDGE_MARGIN = 0.03  # a cursor parked against the frame edge is not pointing at anything
MAX_PER_INTERVAL = 4  # longest holds win when a slide has more dwells than this


@dataclass(frozen=True)
class Motion:
    """What changed between one decoded frame and the previous one."""

    t: float  # time of this frame (s)
    pixels: int  # changed pixels; 0 means the frame is identical to the last
    x: float  # centroid of the change as a fraction of frame width (unused when pixels == 0)
    y: float


@dataclass(frozen=True)
class Dwell:
    """The cursor came to rest at (x, y) at time t and held still for hold_s."""

    t: float
    x: float
    y: float
    hold_s: float


def dwells(
    motion: list[Motion], *, min_dwell_s: float, min_gap_s: float, min_move: float = 0.06
) -> list[Dwell]:
    """Deliberate points in one static interval: a move of at least ``min_move`` (fraction of
    frame width) followed by at least ``min_dwell_s`` of stillness. At most one per
    ``min_gap_s`` and at most MAX_PER_INTERVAL, preferring the longest holds."""
    if len(motion) < 2:
        return []
    dt = motion[1].t - motion[0].t if motion[1].t > motion[0].t else 1.0 / FPS
    candidates: list[Dwell] = []
    move_start: tuple[float, float] | None = None
    last_move: Motion | None = None
    move_frames = 0
    still_frames = 0

    def close() -> None:
        if last_move is None or move_start is None:
            return
        hold = still_frames * dt
        moved = math.hypot(last_move.x - move_start[0], last_move.y - move_start[1])
        near_edge = not (
            EDGE_MARGIN <= last_move.x <= 1 - EDGE_MARGIN
            and EDGE_MARGIN <= last_move.y <= 1 - EDGE_MARGIN
        )
        if move_frames >= MIN_MOVE_FRAMES and hold >= min_dwell_s and moved >= min_move \
                and not near_edge:
            candidates.append(Dwell(last_move.t, last_move.x, last_move.y, hold))

    for m in motion:
        if m.pixels > MAX_CURSOR_PIXELS:  # slide animation / embedded video: reset
            close()
            move_start = last_move = None
            move_frames = still_frames = 0
        elif m.pixels > 0:
            if still_frames:  # a still run just ended: what preceded it was a candidate
                close()
                move_start = None
                move_frames = still_frames = 0
            if move_start is None:
                move_start = (m.x, m.y)
            last_move = m
            move_frames += 1
        elif last_move is not None:
            still_frames += 1
    close()

    picked: list[Dwell] = []
    for c in sorted(candidates, key=lambda d: -d.hold_s):
        if all(abs(c.t - p.t) >= min_gap_s for p in picked):
            picked.append(c)
        if len(picked) >= MAX_PER_INTERVAL:
            break
    return sorted(picked, key=lambda d: d.t)


def track_motion(ffmpeg: str, video: str, t0: float, t1: float) -> list[Motion]:
    """Per-frame change statistics for [t0, t1], decoded small and grey at FPS."""
    import numpy as np

    w, h = CANVAS
    proc = subprocess.Popen(
        [ffmpeg, "-v", "error", "-ss", f"{t0:.3f}", "-t", f"{max(0.0, t1 - t0):.3f}",
         "-i", video, "-vf", f"fps={FPS},scale={w}:{h}", "-f", "rawvideo", "-pix_fmt", "gray",
         "-"],
        stdout=subprocess.PIPE,
    )
    assert proc.stdout is not None
    out: list[Motion] = []
    prev = None
    i = 0
    frame_bytes = w * h
    while True:
        buf = proc.stdout.read(frame_bytes)
        if len(buf) < frame_bytes:
            break
        cur = np.frombuffer(buf, np.uint8).reshape(h, w).astype(np.int16)
        if prev is not None:
            changed = np.abs(cur - prev) > DIFF_THRESHOLD
            n = int(changed.sum())
            if n:
                ys, xs = np.nonzero(changed)
                out.append(Motion(t0 + i / FPS, n, float(xs.mean()) / w, float(ys.mean()) / h))
            else:
                out.append(Motion(t0 + i / FPS, 0, -1.0, -1.0))
        prev = cur
        i += 1
    proc.wait()
    return out


def detect(
    ffmpeg: str,
    video: str,
    intervals: list[tuple[float, float]],
    *,
    min_dwell_s: float,
    min_gap_s: float,
) -> list[tuple[int, Dwell]]:
    """Dwells for each static interval, tagged with the interval's index. The whole span is
    decoded in one pass and split at the interval boundaries; a slide change is itself a
    large change and resets tracking there."""
    usable = [(j, a, b) for j, (a, b) in enumerate(intervals) if b - a >= 3.0]
    if not usable:
        return []
    motion = track_motion(ffmpeg, video, usable[0][1], usable[-1][2])
    found: list[tuple[int, Dwell]] = []
    for j, a, b in usable:
        part = [m for m in motion if a <= m.t < b]
        found.extend((j, d) for d in dwells(part, min_dwell_s=min_dwell_s, min_gap_s=min_gap_s))
    return found


def draw_pointer(frame_path: str, x: float, y: float, height_px: int = 40) -> None:
    """Stamp a classic arrow pointer with its tip at (x, y) onto the frame, in place.

    The real cursor is a few pixels wide once the keyframe is downscaled for the model, too
    small to locate; a drawn pointer is what the model's training frames contained, and it
    made the model name the element under it ("The cursor points to the peak of the
    curve") where a ring got described as "a red circle"."""
    from PIL import Image, ImageDraw

    im = Image.open(frame_path).convert("RGB")
    w, h = im.size
    px, py = x * w, y * h
    shape = [(0, 0), (0, 0.72), (0.2, 0.55), (0.33, 0.85), (0.42, 0.8), (0.3, 0.52), (0.52, 0.52)]
    poly = [(px + a * height_px, py + b * height_px) for a, b in shape]
    draw = ImageDraw.Draw(im)
    draw.polygon(poly, fill=(255, 255, 255), outline=(0, 0, 0))
    draw.line([*poly, poly[0]], fill=(0, 0, 0), width=3)
    im.save(frame_path)

