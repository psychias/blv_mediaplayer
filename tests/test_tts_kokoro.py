"""Pure-logic tests for KokoroTTSBackend — duration heuristic + voice resolution, no model."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from ladpipe import factory
from ladpipe.config import Backends, Config, ConfigError, TTSConfig
from ladpipe.tts.kokoro import (
    KokoroTTSBackend,
    estimate_duration_chars,
    lang_code,
    resolve_voice,
)


def test_estimate_scales_with_length() -> None:
    short = estimate_duration_chars("hi")
    long = estimate_duration_chars("a considerably longer description of the slide content")
    assert long > short


def test_estimate_has_floor() -> None:
    assert estimate_duration_chars("") >= 0.3


def test_backend_estimate_matches_helper() -> None:
    backend = KokoroTTSBackend(model_path="/m", voice="af_heart", sample_rate=24000)
    text = "a chart with three bars"
    assert backend.estimate_duration(text) == estimate_duration_chars(text)


def test_resolve_voice_prefers_bundled_pack(tmp_path: Path) -> None:
    pack = tmp_path / "voices" / "af_heart.safetensors"
    pack.parent.mkdir()
    pack.write_bytes(b"")
    assert resolve_voice(str(tmp_path), "af_heart") == str(pack)


def test_resolve_voice_passes_unknown_name_through(tmp_path: Path) -> None:
    assert resolve_voice(str(tmp_path), "af_heart") == "af_heart"


def test_lang_code_from_voice_prefix() -> None:
    assert lang_code("af_heart") == "a"
    assert lang_code("bf_emma") == "b"
    assert lang_code("/models/kokoro/voices/af_heart.safetensors") == "a"


def test_factory_requires_model_path(mock_config: Config) -> None:
    cfg = dataclasses.replace(
        mock_config,
        backends=Backends("mock", "mock", "kokoro"),
        tts=TTSConfig(voice="af_heart", sample_rate=24000, kokoro={}),
    )
    with pytest.raises(ConfigError, match="kokoro"):
        factory.build_tts(cfg)
