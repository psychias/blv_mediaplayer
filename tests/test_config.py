from __future__ import annotations

from pathlib import Path

import pytest

from ladpipe.config import ConfigError, load_config

REPO = Path(__file__).resolve().parents[1]
DEFAULT = REPO / "config" / "default.yaml"


def test_default_config_loads() -> None:
    cfg = load_config(DEFAULT)
    assert cfg.backends.preprocess == "mock"
    assert cfg.player.captions_default_on is True  # captions on by default
    assert cfg.rules_file is not None and cfg.rules_file.exists()


def test_missing_file_raises() -> None:
    with pytest.raises(ConfigError):
        load_config(Path("/nonexistent/config.yaml"))


def test_unknown_backend_raises(tmp_path: Path) -> None:
    cfg = tmp_path / "c.yaml"
    cfg.write_text(
        "pipeline_version: '1'\n"
        "backends: {preprocess: nope, vl: mock, tts: mock}\n"
        "prefilter: {redundancy_threshold: 0.8}\n"
        "rungs: {max_compress_factor: 1.3, time_shift_cap_s: 5.0, placeholder_marker_s: 0.4}\n"
        "tts: {voice: x, sample_rate: 24000}\n"
        "cache: {dir: /tmp/x}\n"
    )
    with pytest.raises(ConfigError, match="backends.preprocess"):
        load_config(cfg)


def test_bad_threshold_raises(tmp_path: Path) -> None:
    cfg = tmp_path / "c.yaml"
    cfg.write_text(
        "pipeline_version: '1'\n"
        "backends: {preprocess: mock, vl: mock, tts: mock}\n"
        "prefilter: {redundancy_threshold: 1.5}\n"
        "rungs: {max_compress_factor: 1.3, time_shift_cap_s: 5.0, placeholder_marker_s: 0.4}\n"
        "tts: {voice: x, sample_rate: 24000}\n"
        "cache: {dir: /tmp/x}\n"
    )
    with pytest.raises(ConfigError, match="redundancy_threshold"):
        load_config(cfg)


def test_config_hash_is_stable() -> None:
    assert load_config(DEFAULT).config_hash() == load_config(DEFAULT).config_hash()


def test_merge_gap_and_verbosity_defaults() -> None:
    cfg = load_config(DEFAULT)
    assert cfg.rungs.merge_gap_s == 3.0
    assert cfg.vl.verbosity == "balanced"


def test_bad_verbosity_raises(tmp_path: Path) -> None:
    cfg = tmp_path / "c.yaml"
    cfg.write_text(
        "pipeline_version: '1'\n"
        "backends: {preprocess: mock, vl: mock, tts: mock}\n"
        "prefilter: {redundancy_threshold: 0.8}\n"
        "rungs: {max_compress_factor: 1.3, time_shift_cap_s: 5.0, placeholder_marker_s: 0.4}\n"
        "tts: {voice: x, sample_rate: 24000}\n"
        "vl: {verbosity: chatty}\n"
        "cache: {dir: /tmp/x}\n"
    )
    with pytest.raises(ConfigError, match="vl.verbosity"):
        load_config(cfg)
