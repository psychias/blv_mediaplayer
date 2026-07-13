"""Pure-logic tests for RealPreprocessor — no ffmpeg/Whisper/VAD/OCR needed."""

from __future__ import annotations

from ladpipe.preprocess.local import (
    Segment,
    assemble_moments,
    dedup_indices,
    hamming,
    last_speech_end_in_span,
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
