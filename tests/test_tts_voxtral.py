"""Pure-logic tests for VoxtralTTSBackend — duration heuristic, no model."""

from __future__ import annotations

from ladpipe.tts.voxtral import VoxtralTTSBackend, estimate_duration_chars


def test_estimate_scales_with_length() -> None:
    short = estimate_duration_chars("hi")
    long = estimate_duration_chars("a considerably longer description of the slide content")
    assert long > short


def test_estimate_has_floor() -> None:
    assert estimate_duration_chars("") >= 0.3


def test_backend_estimate_matches_helper() -> None:
    backend = VoxtralTTSBackend(model_path="/m", voice="neutral_female", sample_rate=24000)
    text = "a chart with three bars"
    assert backend.estimate_duration(text) == estimate_duration_chars(text)
