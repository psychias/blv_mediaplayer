"""Config-only VL selection via the single mlx-vlm backend, and the OCR mode (§6)."""

from __future__ import annotations

import dataclasses

import pytest

from ladpipe import factory
from ladpipe.config import Config, ConfigError, VLConfig


def _mlxvlm(config: Config, model: str = "mlx-community/gemma-4-e2b-it-4bit") -> Config:
    return dataclasses.replace(
        config,
        backends=dataclasses.replace(config.backends, vl="mlxvlm"),
        vl=dataclasses.replace(config.vl, model=model),
    )


def test_mlxvlm_selectable_by_config(mock_config: Config) -> None:
    backend = factory.build_vl(_mlxvlm(mock_config))
    assert type(backend).__name__ == "MlxVlmBackend"


def test_mlxvlm_requires_model_path(mock_config: Config) -> None:
    cfg = dataclasses.replace(
        mock_config,
        backends=dataclasses.replace(mock_config.backends, vl="mlxvlm"),
        vl=VLConfig(model="", image_max_side=768),
    )
    with pytest.raises(ConfigError, match="mlxvlm backend requires"):
        factory.build_vl(cfg)


def test_unknown_vl_backend_rejected(mock_config: Config) -> None:
    cfg = dataclasses.replace(
        mock_config, backends=dataclasses.replace(mock_config.backends, vl="not-a-backend")
    )
    with pytest.raises(ConfigError, match="unknown vl backend"):
        factory.build_vl(cfg)


def test_ocr_mode_controls_needs_ocr(mock_config: Config) -> None:
    # auto defers to the model (default reads slides) -> no OCR; on/off are explicit.
    for mode, expected in (("auto", False), ("on", True), ("off", False)):
        cfg = dataclasses.replace(
            mock_config, preprocess=dataclasses.replace(mock_config.preprocess, ocr=mode)
        )
        assert cfg.needs_ocr is expected
