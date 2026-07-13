"""MockPreprocessor — deterministic synthetic moments + a silent base track.

Stdlib only. The synthetic moments are hand-tuned (against the mock TTS rate and
default rung config) to exercise every rung 1-5, plus both suppression paths
(pre-filter redundancy and VL-level suppress). See tests/test_orchestrator.py.
"""

from __future__ import annotations

from pathlib import Path

from .. import audio
from ..types import AudioClip, Moment, ProgressSink, TranscriptSegment

_TAIL_S = 5.0

# (id, t_start, t_end, pause_after, next_off, next_pause, visual, ocr, transcript)
# Tuned (against the mock TTS ~1.8s clip and default rung config) to exercise every
# rung 0-5. High-value = visual_signal True; rungs 4/5 require LOW-value moments.
_MOMENTS: list[tuple[str, float, float, float, float, float, bool, str, str]] = [
    ("m01", 2.0, 5.0, 3.0, 0.0, 0.0, True, "figure 1", "now look at the figure"),  # rung 1
    ("m02", 9.0, 12.0, 2.5, 0.0, 0.0, True, "plot", "consider this curve"),  # rung 1
    ("m03", 16.0, 19.0, 1.5, 0.0, 0.0, True, "table", "these results"),  # rung 2 (compress)
    ("m04", 23.0, 26.0, 0.5, 3.0, 2.5, True, "diagram", "the architecture"),  # rung 3 (shift)
    # high-value, fits no gap -> rung 0 pause-and-describe (extended AD)
    ("m05", 30.0, 33.0, 0.5, 8.0, 0.0, True, "schematic", "the circuit"),
    # low-value (no visual signal), no fit, pause >= marker -> rung 4 marker
    ("m06", 37.0, 40.0, 0.5, 8.0, 0.0, False, "appendix note", "and so on briefly"),
    # low-value, no fit, pause < marker -> rung 5 drop
    ("m07", 44.0, 47.0, 0.2, 8.0, 0.0, False, "footnote reference", "moving on quickly"),
    # redundant: identical OCR/transcript and no visual signal -> pre-filter suppresses
    ("m08", 51.0, 54.0, 3.0, 0.0, 0.0, False,
     "the gradient descent update rule", "the gradient descent update rule"),
    # passes the pre-filter (visual) but empty OCR -> the VL backend suppresses
    ("m09", 58.0, 61.0, 3.0, 0.0, 0.0, True, "", "and finally"),
]


class MockPreprocessor:
    def __init__(self, sample_rate: int) -> None:
        self._sample_rate = sample_rate

    def run(
        self, video_path: Path, progress: ProgressSink
    ) -> tuple[AudioClip, list[Moment], list[TranscriptSegment]]:
        progress.progress("preprocess", 0.0, "Extracting audio")
        moments = [
            Moment(
                id=mid,
                t_start=ts,
                t_end=te,
                keyframe_path=None,
                transcript_window=tr,
                ocr_text=ocr,
                pause_after=pause,
                next_boundary_offset=noff,
                next_boundary_pause=npause,
                visual_signal=vis,
            )
            for (mid, ts, te, pause, noff, npause, vis, ocr, tr) in _MOMENTS
        ]
        progress.progress("preprocess", 0.6, "Detecting moments")
        # Synthetic transcript segments aligned to each moment's spoken span (one per
        # moment), so the lecturer captions are timestamped like real Whisper segments.
        segments = [
            TranscriptSegment(start=m.t_start, end=m.t_end, text=m.transcript_window)
            for m in moments
            if m.transcript_window.strip()
        ]
        total = max(m.t_end for m in moments) + _TAIL_S
        base = audio.silence(total, self._sample_rate)
        progress.progress("preprocess", 1.0, "Preprocessing complete")
        return base, moments, segments
