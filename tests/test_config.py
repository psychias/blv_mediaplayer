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


def test_merge_gap_default() -> None:
    assert load_config(DEFAULT).rungs.merge_gap_s == 3.0


def _yaml_with_vl(vl_block: str) -> str:
    return (
        "pipeline_version: '1'\n"
        "backends: {preprocess: mock, vl: mock, tts: mock}\n"
        "prefilter: {redundancy_threshold: 0.8}\n"
        "rungs: {max_compress_factor: 1.3, time_shift_cap_s: 5.0, placeholder_marker_s: 0.4}\n"
        "tts: {voice: x, sample_rate: 24000}\n"
        f"vl: {vl_block}\n"
        "cache: {dir: /tmp/x}\n"
    )


def test_verbosity_defaults_to_standard() -> None:
    assert load_config(DEFAULT).vl.verbosity == "standard"


def test_verbosity_parse_and_override(tmp_path: Path) -> None:
    cfg = tmp_path / "c.yaml"
    cfg.write_text(_yaml_with_vl("{model: m, verbosity: brief}"))
    assert load_config(cfg).vl.verbosity == "brief"


def test_invalid_verbosity_raises(tmp_path: Path) -> None:
    cfg = tmp_path / "c.yaml"
    cfg.write_text(_yaml_with_vl("{model: m, verbosity: chatty}"))
    with pytest.raises(ConfigError, match="vl.verbosity"):
        load_config(cfg)


def test_config_hash_differs_across_verbosity(tmp_path: Path) -> None:
    a = tmp_path / "a.yaml"
    b = tmp_path / "b.yaml"
    a.write_text(_yaml_with_vl("{model: m, verbosity: brief}"))
    b.write_text(_yaml_with_vl("{model: m, verbosity: detailed}"))
    assert load_config(a).config_hash() != load_config(b).config_hash()


def test_effective_max_ad_words_by_verbosity(tmp_path: Path) -> None:
    cases = [  # (max_ad_words, verbosity, expected)
        (14, "standard", 14),
        (14, "brief", 10),
        (14, "detailed", 28),
        (0, "standard", 0),   # uncapped stays uncapped at standard
        (0, "brief", 10),     # brief always caps
        (0, "detailed", 0),   # uncapped stays uncapped at detailed
        (8, "brief", 8),      # brief never raises an existing tighter cap
    ]
    for words, verbosity, expected in cases:
        cfg = tmp_path / "c.yaml"
        vl_block = f"{{model: m, max_ad_words: {words}, verbosity: {verbosity}}}"
        cfg.write_text(_yaml_with_vl(vl_block))
        assert load_config(cfg).vl.effective_max_ad_words == expected, (words, verbosity)


def test_cli_verbosity_flag_overrides_config(tmp_path: Path) -> None:
    from ladpipe.cli import _load, build_parser

    cfg = tmp_path / "c.yaml"
    cfg.write_text(_yaml_with_vl("{model: m, verbosity: brief}"))
    args = build_parser().parse_args(
        ["stream", "--video", "v.mp4", "--config", str(cfg), "--verbosity", "detailed"]
    )
    assert _load(args).vl.verbosity == "detailed"
    # Without the flag, the config value wins.
    args = build_parser().parse_args(["stream", "--video", "v.mp4", "--config", str(cfg)])
    assert _load(args).vl.verbosity == "brief"
