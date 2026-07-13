from __future__ import annotations

from pathlib import Path

import pytest

from ladpipe.config import (
    Backends,
    Config,
    ExtendedADConfig,
    PlayerConfig,
    PrefilterConfig,
    PreprocessConfig,
    RungConfig,
    TTSConfig,
    VLConfig,
)


@pytest.fixture
def rung_cfg() -> RungConfig:
    return RungConfig(max_compress_factor=1.3, time_shift_cap_s=5.0, placeholder_marker_s=0.4)


@pytest.fixture
def mock_config(tmp_path: Path) -> Config:
    return Config(
        pipeline_version="0.1.0",
        backends=Backends("mock", "mock", "mock"),
        rules_file=None,
        prefilter=PrefilterConfig(redundancy_threshold=0.8),
        rungs=RungConfig(max_compress_factor=1.3, time_shift_cap_s=5.0, placeholder_marker_s=0.4),
        tts=TTSConfig(voice="neutral_female", sample_rate=24000, voxtral={}),
        vl=VLConfig(model="mlx-community/gemma-4-e2b-it-4bit", image_max_side=768),
        preprocess=PreprocessConfig(
            whisper_backend="mlx",
            whisper_model="mlx-community/whisper-large-v3-turbo",
            scene_threshold=0.3,
            keyframe_dedup_max_distance=5,
            transcript_pad_s=2.0,
            ocr="auto",
        ),
        extended_ad=ExtendedADConfig(enabled=True),
        cache_dir=tmp_path / "cache",
        player=PlayerConfig(captions_default_on=True),
    )
