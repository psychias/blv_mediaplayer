"""Rung ladder (§7): place each AD line against the ACTUAL TTS clip duration.

Prefer the least-disruptive option that doesn't lose the content:

1. Gap-insert    — fits in pause_after as-is.
2. Compress      — fits if sped up within max_compress_factor.
3. Time-shift    — fits at the next sentence boundary, within a 5s cap.
0. Pause-and-describe (extended AD) — if 1-3 don't fit AND the moment is high-value,
   briefly pause the video and play the full description. Preferred over 4/5 for
   high-value moments; ranked after 1-3 because pausing is more disruptive.
4. Placeholder   — brief non-verbal marker, LOW-value moments only.
5. Drop          — skip, LOW-value moments only.

The 5-second cap (rung 3) is hard. Selection uses the real clip duration, never an
estimate. "High-value" = the moment carries a visual signal (figure / pointing /
scene change) — the content speech alone leaves uncovered.
"""

from __future__ import annotations

import dataclasses
import re

from .config import RungConfig
from .types import Moment, Placement

# Words too weak to end a spoken line on — if a hard word-cap lands here, trim back to the
# preceding content word so the AD doesn't trail off ("... with the.").
_STOP_WORDS = (
    "a an the and or but with of to in on for at by that which this these those is are was "
    "were be as it its their his her our your my from into over under about"
)
_TRAILING_STOP = frozenset(_STOP_WORDS.split())


def cap_ad_words(text: str, max_words: int) -> str:
    """Trim an AD line to at most ``max_words`` words (0 = no cap). Prefer to end at a real
    sentence boundary; otherwise end on a whole word with a clean period — never a dangling
    comma or mid-clause fragment (which sounds broken when spoken). Shorter = faster TTS."""
    if max_words <= 0:
        return text.strip()
    words = text.split()
    if len(words) <= max_words:
        return text.strip()
    head = " ".join(words[:max_words])
    # A sentence end is . ! ? followed by space or string-end — so "9.5" is not a boundary.
    ends = [m.end() for m in re.finditer(r"[.!?](?=\s|$)", head)]
    if ends and ends[-1] >= len(head) // 2:
        return head[: ends[-1]].strip()
    kept = words[:max_words]
    while len(kept) > 3 and kept[-1].strip(".,;:'\"").lower() in _TRAILING_STOP:
        kept.pop()
    return " ".join(kept).rstrip(" ,;:.") + "."


def merge_adjacent(
    emits: list[tuple[Moment, str]], gap_s: float
) -> list[tuple[Moment, str]]:
    """Merge emitted AD lines whose moments sit within ``gap_s`` of each other into one
    line (MAVP: merge descriptions <= 3 s apart) — one flowing description reads better
    than two staccato ones and needs only one gap. The merged moment spans both and
    keeps the LATER moment's gap/boundary fields, since that's where the line lands."""
    if gap_s <= 0.0 or len(emits) < 2:
        return emits
    merged: list[tuple[Moment, str]] = [emits[0]]
    for moment, text in emits[1:]:
        prev, prev_text = merged[-1]
        if moment.t_start - prev.t_end <= gap_s:
            combined = dataclasses.replace(
                moment,
                id=f"{prev.id}+{moment.id}",
                t_start=prev.t_start,
                visual_signal=prev.visual_signal or moment.visual_signal,
            )
            merged[-1] = (combined, f"{prev_text} {text}")
        else:
            merged.append((moment, text))
    return merged


def bookend(
    emits: list[tuple[Moment, str]], *, first: bool = True, last: bool = True
) -> list[tuple[Moment, str]]:
    """Bookend the description track (MAVP rule): open the first AD line with a start
    marker and close the last one, so a listener knows where descriptions begin and end.
    Phrased about the AD track (not the lecture) so it's true even when the first/last
    emitted description falls mid-lecture."""
    if not emits:
        return emits
    out = list(emits)
    if first:
        m, text = out[0]
        out[0] = (m, f"Audio description begins. {text}")
    if last:
        m, text = out[-1]
        out[-1] = (m, f"{text} That was the final description.")
    return out


def place(
    moment: Moment,
    clip_duration: float,
    cfg: RungConfig,
    ad_text: str | None,
    extended_ad_enabled: bool = True,
    always_pause: bool = False,
) -> Placement:
    # Always-pause: skip gap-fitting entirely — pause the video and play the full AD.
    if always_pause and extended_ad_enabled:
        return Placement(moment.id, 0, moment.t_start, clip_duration, 1.0, ad_text, False)

    pause = moment.pause_after

    # Rung 1 — gap-insert.
    if clip_duration <= pause:
        return Placement(moment.id, 1, moment.t_end, clip_duration, 1.0, ad_text, False)

    # Rung 2 — compress within the max factor (speed up only as much as needed).
    if pause > 0.0:
        needed = clip_duration / pause
        if needed <= cfg.max_compress_factor:
            return Placement(moment.id, 2, moment.t_end, pause, needed, ad_text, False)

    # Rung 3 — time-shift to the next boundary, within the hard 5s cap.
    within_cap = moment.next_boundary_offset <= cfg.time_shift_cap_s
    if within_cap and clip_duration <= moment.next_boundary_pause:
        start = moment.t_end + moment.next_boundary_offset
        return Placement(moment.id, 3, start, clip_duration, 1.0, ad_text, False)

    # Rung 0 — pause-and-describe (extended AD) for high-value content that won't fit.
    if extended_ad_enabled and moment.visual_signal:
        return Placement(moment.id, 0, moment.t_start, clip_duration, 1.0, ad_text, False)

    # Rung 4 — non-verbal placeholder marker (low-value, words not spoken).
    if pause >= cfg.placeholder_marker_s:
        return Placement(moment.id, 4, moment.t_end, cfg.placeholder_marker_s, 1.0, ad_text, False)

    # Rung 5 — drop (low-value).
    return Placement(moment.id, 5, moment.t_end, 0.0, 1.0, ad_text, True)
