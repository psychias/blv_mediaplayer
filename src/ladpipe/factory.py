"""Factory: build backends from config (dependency injection, §4 D/O).

Adding a new backend = implement the Protocol + add one branch here. The
orchestrator and stages never change. Heavy real backends are lazy-imported only
inside their branch, so building the mock path imports zero heavy deps.
"""

from __future__ import annotations

from .config import Config, ConfigError
from .preprocess.base import Preprocessor
from .tts.base import TTSBackend
from .vl.base import VLBackend


def build_preprocessor(config: Config) -> Preprocessor:
    name = config.backends.preprocess
    if name == "mock":
        from .preprocess.mock import MockPreprocessor

        return MockPreprocessor(sample_rate=config.tts.sample_rate)
    if name == "local":
        from .preprocess.local import RealPreprocessor

        return RealPreprocessor(config)
    raise ConfigError(f"unknown preprocess backend: {name}")


def build_vl(config: Config) -> VLBackend:
    name = config.backends.vl
    if name == "mock":
        from .vl.mock import MockVLBackend

        return MockVLBackend()
    if name == "mlxvlm":
        if not config.vl.model:
            raise ConfigError("mlxvlm backend requires vl.model (a 4-bit MLX weights path/repo)")
        from .vl.mlx_vlm import MlxVlmBackend

        return MlxVlmBackend(
            config.vl.model,
            image_max_side=config.vl.image_max_side,
            verbosity=config.vl.verbosity,
        )
    raise ConfigError(f"unknown vl backend: {name}")


def build_tts(config: Config) -> TTSBackend:
    name = config.backends.tts
    if name == "mock":
        from .tts.mock import MockTTSBackend

        return MockTTSBackend(sample_rate=config.tts.sample_rate)
    if name == "voxtral":
        model_path = str(config.tts.voxtral.get("model_path", ""))
        if not model_path:
            raise ConfigError("voxtral backend requires tts.voxtral.model_path")
        from .tts.voxtral import VoxtralTTSBackend

        return VoxtralTTSBackend(model_path, config.tts.voice, config.tts.sample_rate)
    raise ConfigError(f"unknown tts backend: {name}")
