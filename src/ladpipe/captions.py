"""WebVTT caption generation — a near-free byproduct, no new model calls (§7).

Two independently identifiable cue kinds:
- Lecturer cues: from each moment's transcript window (timestamped speech).
- AD cues: each *spoken* ad_text (rungs 1-3), timestamped to its post-rung
  placement time so the caption appears when the voice speaks it, and marked
  distinct via an ``AD`` cue id, a ``<c.ad>`` class, and an ``AD:`` prefix.
"""

from __future__ import annotations

from .types import Placement, TranscriptSegment


def _ts(seconds: float) -> str:
    seconds = max(0.0, seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{s:06.3f}"


def build_webvtt(segments: list[TranscriptSegment], placements: list[Placement]) -> str:
    """Render a WebVTT document with lecturer cues (synced to the transcript segments) and
    AD cues (timestamped to their post-rung placement time)."""
    lines: list[str] = ["WEBVTT", ""]

    for i, seg in enumerate(segments, start=1):
        text = seg.text.strip()
        if not text:
            continue
        lines += [f"L{i}", f"{_ts(seg.start)} --> {_ts(seg.end)}", text, ""]

    ad_i = 0
    for p in placements:
        if not p.spoken or not p.ad_text:
            continue
        ad_i += 1
        end = p.start_time + p.duration
        lines += [
            f"AD{ad_i}",
            f"{_ts(p.start_time)} --> {_ts(end)}",
            f"<c.ad>AD: {p.ad_text.strip()}</c.ad>",
            "",
        ]

    return "\n".join(lines).rstrip("\n") + "\n"


def build_descriptions_webvtt(placements: list[Placement]) -> str:
    """Render the extended-AD (rung 0) descriptions track: pause-and-play cues.

    Each cue marks a point where the player pauses the video and plays the full
    description (§7/§8). The cue window is the pause length (== the AD clip duration).
    """
    lines: list[str] = ["WEBVTT", ""]
    desc_i = 0
    for p in placements:
        if not p.is_extended or not p.ad_text:
            continue
        desc_i += 1
        end = p.start_time + p.duration
        lines += [
            f"DESC{desc_i}",
            f"{_ts(p.start_time)} --> {_ts(end)}",
            f"<c.ad-extended>AD: {p.ad_text.strip()}</c.ad-extended>",
            "",
        ]
    return "\n".join(lines).rstrip("\n") + "\n"
