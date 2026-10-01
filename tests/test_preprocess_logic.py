"""Pure-logic tests for RealPreprocessor — no ffmpeg/Whisper/VAD/OCR needed."""

from __future__ import annotations

from pathlib import Path

import pytest

from ladpipe.preprocess.local import (
    Segment,
    assemble_moments,
    dedup_indices,
    hamming,
    last_speech_end_in_span,
    media_bin,
    next_segment_end,
    pause_starting_at,
    transcript_in_span,
)


def test_hamming_and_dedup() -> None:
    assert hamming(0b1010, 0b1000) == 1
    # second frame is near-identical to the first -> dropped; third is far -> kept
    kept = dedup_indices([0b0000, 0b0001, 0b1111], max_distance=1)
    assert kept == [0, 2]


def test_pause_zero_while_speaking() -> None:
    speech = [(0.0, 5.0), (7.0, 9.0)]
    assert pause_starting_at(3.0, speech, audio_end=10.0) == 0.0  # mid-speech


def test_pause_is_gap_to_next_speech() -> None:
    speech = [(0.0, 5.0), (7.0, 9.0)]
    assert pause_starting_at(5.0, speech, audio_end=10.0) == 2.0  # 5.0 -> 7.0
    assert pause_starting_at(9.0, speech, audio_end=10.0) == 1.0  # tail to audio end


def test_next_segment_end_is_next_boundary() -> None:
    segs = [Segment(0.0, 4.0, "a"), Segment(4.0, 8.0, "b")]
    assert next_segment_end(4.0, segs) == 8.0
    assert next_segment_end(8.0, segs) is None


def test_transcript_in_span_joins_overlapping_segments() -> None:
    segs = [Segment(0.0, 4.0, "hello"), Segment(4.0, 8.0, "world"), Segment(9.0, 10.0, "later")]
    assert transcript_in_span(segs, 0.0, 8.0) == "hello world"


def test_last_speech_end_in_span() -> None:
    speech = [(0.0, 3.0), (3.5, 6.0)]
    assert last_speech_end_in_span(speech, 0.0, 5.0, default=0.0) == 5.0  # clamped to span end
    assert last_speech_end_in_span([], 0.0, 5.0, default=1.0) == 1.0  # default when no speech


def test_assemble_moments_builds_ordered_moments() -> None:
    segments = [Segment(0.0, 4.0, "intro"), Segment(6.0, 9.0, "details")]
    speech = [(0.0, 4.0), (6.0, 9.0)]
    moments = assemble_moments(
        scene_times=[0.0, 5.0],
        audio_end=12.0,
        segments=segments,
        speech=speech,
        ocr_by_index={0: "Title", 1: "Figure"},
        keyframe_by_index={0: "/f0.png", 1: "/f1.png"},
        pad=1.0,
    )
    assert [m.id for m in moments] == ["m000", "m001"]
    assert all(m.visual_signal for m in moments)  # scene-change keyframes
    assert moments[0].ocr_text == "Title" and moments[0].keyframe_path == "/f0.png"
    # moment 0 spans [0,5): speech ends at 4.0, then a 2s pause until speech at 6.0
    assert moments[0].t_end == 4.0
    assert moments[0].pause_after == 2.0


def test_media_bin_prefers_the_bundled_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The shipped .app carries its own ffmpeg; the machine it lands on may have none.
    bundled = tmp_path / "media"
    bundled.mkdir()
    (bundled / "ffmpeg").write_text("#!/bin/sh\n")
    monkeypatch.setenv("LADPIPE_MEDIA_DIR", str(bundled))
    assert media_bin("ffmpeg") == str(bundled / "ffmpeg")
    # A name it does not carry still falls through to the usual search.
    assert media_bin("ffprobe") != str(bundled / "ffprobe")


def test_pointing_moments_sit_on_the_dwell_with_an_8s_transcript() -> None:
    from ladpipe.preprocess.local import pointing_moments
    from ladpipe.preprocess.pointing import Dwell

    segments = [Segment(95.0, 99.0, "before"), Segment(101.0, 104.0, "here"),
                Segment(106.0, 109.0, "after"), Segment(130.0, 133.0, "far")]
    speech = [(95.0, 99.0), (101.0, 104.0), (106.0, 109.0), (130.0, 133.0)]
    ms = pointing_moments(
        events=[(1, Dwell(t=100.0, x=0.4, y=0.5, hold_s=2.0))],
        keyframes=["/kf/p0.png"],
        slide_times=[60.0, 90.0, 120.0],
        audio_end=200.0,
        segments=segments, speech=speech, ocr_by_index={1: "Slide two text"},
    )
    assert len(ms) == 1
    m = ms[0]
    assert m.id == "p000" and m.kind == "pointing" and m.visual_signal
    assert m.t_start == 100.0 and m.keyframe_path == "/kf/p0.png"
    assert m.transcript_window == "before here after"  # +/-8 s; "far" at 130 s excluded
    assert m.ocr_text == "Slide two text"  # the slide the cursor rests on
    # Span is min(next slide 120, dwell + 8 = 108); speech running past it clamps to 108,
    # exactly as a slide's t_end clamps to the next scene.
    assert m.t_end == 108.0

