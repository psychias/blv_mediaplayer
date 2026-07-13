"""Core data types and the progress-reporting protocol.

These are pure dataclasses and Protocols with zero heavy dependencies, so the
orchestration core and the mock path import them with no GPU/network/model deps.
"""

from __future__ import annotations

from array import array
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass
class Moment:
    """One describable moment: a keyframe + its transcript window + slide OCR.

    The VL model only ever sees one of these at a time (never "the video").
    """

    id: str
    t_start: float
    t_end: float
    keyframe_path: str | None
    transcript_window: str
    ocr_text: str
    pause_after: float  # silence right after this moment (s)
    next_boundary_offset: float = 0.0  # s from t_end to next sentence boundary
    next_boundary_pause: float = 0.0  # silence available at that boundary (s)
    visual_signal: bool = False  # cursor / scene-change / figure present (for the pre-filter)


@dataclass(frozen=True)
class TranscriptSegment:
    """One timestamped speech segment from the transcriber (Whisper). These become the
    lecturer caption cues, so they're synced to what the lecturer is actually saying."""

    start: float
    end: float
    text: str


@dataclass
class ADDecision:
    """The VL model's per-moment decision: emit a description or suppress."""

    emit: bool
    ad_text: str | None
    teacher_rung: int | None  # model's suggestion; deployment re-checks feasibility
    rationale: str


@dataclass
class AudioClip:
    """Mono PCM audio as float samples in [-1.0, 1.0]."""

    samples: array[float]  # array('f') — float32 mono
    sample_rate: int

    @property
    def duration(self) -> float:
        return len(self.samples) / self.sample_rate if self.sample_rate else 0.0


@dataclass
class Placement:
    """Where and how one AD line landed after the rung ladder ran.

    Audio-free and JSON-serialisable (goes into the manifest). The orchestrator
    renders the actual clip; the mixer overlays it. Rungs: 0 = pause-and-describe
    (extended AD, played during a brief video pause); 1-3 are voiced into a gap;
    4 is a non-verbal marker; 5 is a drop.
    """

    moment_id: str
    rung: int  # 0-5
    start_time: float  # output-timeline start (s); for rung 0, the pause point
    duration: float  # effective placed duration (s); 0.0 when dropped
    speed_factor: float  # 1.0 except rung 2 (compression)
    ad_text: str | None
    dropped: bool

    @property
    def spoken(self) -> bool:
        """True when the AD words are voiced into a gap (rungs 1-3, length-matched)."""
        return self.rung in (1, 2, 3) and not self.dropped

    @property
    def is_extended(self) -> bool:
        """True for rung 0: the description plays during a brief video pause."""
        return self.rung == 0 and not self.dropped


@dataclass
class PipelineResult:
    """The cached artifact set for one lecture, plus diagnostics."""

    audio_path: Path
    captions_path: Path
    descriptions_path: Path  # WebVTT extended-AD (rung 0) cues
    manifest_path: Path
    duration: float  # length-matched audio duration; pauses (rung 0) add time on playback
    placements: list[Placement]
    rung_counts: dict[int, int]
    suppressed_moment_ids: list[str]
    cache_hit: bool


class ProgressSink(Protocol):
    """Sink for stage progress. The CLI wires a JSON-event emitter to this."""

    def progress(self, stage: str, pct: float, label: str) -> None: ...


@dataclass
class NullProgress:
    """A progress sink that drops everything — used by tests."""

    events: list[tuple[str, float, str]] = field(default_factory=list)

    def progress(self, stage: str, pct: float, label: str) -> None:
        self.events.append((stage, pct, label))
