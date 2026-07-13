"""Preprocessor Protocol (interface segregation: §4 I)."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from ..types import AudioClip, Moment, ProgressSink, TranscriptSegment


class Preprocessor(Protocol):
    def run(
        self, video_path: Path, progress: ProgressSink
    ) -> tuple[AudioClip, list[Moment], list[TranscriptSegment]]:
        """Return the lecturer base audio track, ordered describable moments, and the
        timestamped transcript segments (used for synced lecturer captions, §7)."""
        ...
