"""Typed config load + validation. Fails loudly with clear messages (§10)."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

PREPROCESS_BACKENDS = {"mock", "local"}
VL_BACKENDS = {"mock", "mlxvlm"}  # one mlx-vlm backend loads either trained model (§6)
TTS_BACKENDS = {"mock", "voxtral"}
OCR_MODES = {"auto", "on", "off"}
VL_VERBOSITY = {"minimal", "balanced", "expansive"}  # AD level of detail (MAVP-style)
WHISPER_BACKENDS = {"mlx", "openai"}  # mlx = GPU-resident on Apple Silicon (much faster)


def total_ram_gb() -> float:
    """Physical RAM in GB (stdlib; used to auto-select the VL model by RAM, §6.1)."""
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / (1024**3)
    except (ValueError, OSError, AttributeError):
        return 0.0


class ConfigError(ValueError):
    """Raised when configuration is missing or invalid."""


@dataclass(frozen=True)
class Backends:
    preprocess: str
    vl: str
    tts: str


@dataclass(frozen=True)
class PrefilterConfig:
    redundancy_threshold: float


@dataclass(frozen=True)
class RungConfig:
    max_compress_factor: float
    time_shift_cap_s: float
    placeholder_marker_s: float
    # Merge emitted AD lines whose moments sit within this many seconds of each other
    # into one line (MAVP: merge descriptions <= 3 s apart). 0 = never merge.
    merge_gap_s: float = 3.0


@dataclass(frozen=True)
class TTSConfig:
    voice: str
    sample_rate: int
    voxtral: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VLConfig:
    # Path/repo to 4-bit MLX VL weights (mlx-vlm auto-detects the architecture). The
    # effective model after RAM auto-select is stored here (§6.1). Fine-tuned weights
    # drop in by pointing this at the converted MLX checkpoint — a pure config swap.
    model: str
    image_max_side: int = 768  # downscale the keyframe fed to the VL encoder (§7)
    # Cap AD-line length before TTS (0 = no cap). A safety net against verbose base-model
    # output and a stand-in for the fine-tune's concise AD; shorter lines = faster TTS.
    max_ad_words: int = 0
    # AD level of detail (MAVP-style minimal | balanced | expansive): adjusts the VL
    # prompt's style line. One variant per prepare run; the cache is keyed by it.
    verbosity: str = "balanced"
    model_large: str = ""  # optional richer model used on >= model_large_min_ram_gb
    model_large_min_ram_gb: int = 16


@dataclass(frozen=True)
class PreprocessConfig:
    whisper_backend: str  # mlx | openai — mlx runs on the GPU (Apple Silicon), much faster
    whisper_model: str  # mlx repo (mlx-community/whisper-large-v3-turbo) or openai name ("turbo")
    scene_threshold: float  # ffmpeg scene-detection sensitivity (0-1)
    keyframe_dedup_max_distance: int  # perceptual-hash hamming distance to dedup slides
    transcript_pad_s: float  # seconds of transcript context around a moment
    ocr: str  # auto | on | off — feed slide OCR into the VL prompt (§6)


@dataclass(frozen=True)
class ExtendedADConfig:
    # Rung 0: briefly pause the video to play a high-value description that won't
    # fit any gap (§7). Off = old gap-only behaviour (high-value non-fitting -> 4/5).
    enabled: bool
    # When True, EVERY emitted AD pauses the video and plays the full description
    # (rung 0), instead of trying to squeeze it into the lecturer's pauses
    # (gap-insert/compress/time-shift). Cleaner for the listener; the video pauses more.
    always_pause: bool = False


@dataclass(frozen=True)
class PlayerConfig:
    captions_default_on: bool


@dataclass(frozen=True)
class Config:
    pipeline_version: str
    backends: Backends
    rules_file: Path | None
    prefilter: PrefilterConfig
    rungs: RungConfig
    tts: TTSConfig
    vl: VLConfig
    preprocess: PreprocessConfig
    extended_ad: ExtendedADConfig
    cache_dir: Path
    player: PlayerConfig

    @property
    def backend_ids(self) -> dict[str, str]:
        return {
            "preprocess": self.backends.preprocess,
            "vl": self.backends.vl,
            "tts": self.backends.tts,
        }

    @property
    def needs_ocr(self) -> bool:
        # "auto" defers to the VL model; the shipped default reads slides itself, so
        # auto resolves to off. "on"/"off" are explicit overrides (§6).
        return self.preprocess.ocr == "on"

    def config_hash(self) -> str:
        """Stable hash over tunables that affect the artifact (for the cache key)."""
        payload = {
            "prefilter": asdict(self.prefilter),
            "rungs": asdict(self.rungs),
            "tts": {"voice": self.tts.voice, "sample_rate": self.tts.sample_rate},
            # Only the effective model + image size affect the artifact; the
            # large-model provenance fields do not.
            "vl": {
                k: v
                for k, v in asdict(self.vl).items()
                if k not in ("model_large", "model_large_min_ram_gb")
            },
            "preprocess": asdict(self.preprocess),
            "extended_ad": asdict(self.extended_ad),
        }
        blob = json.dumps(payload, sort_keys=True).encode()
        return hashlib.sha256(blob).hexdigest()


def _require(d: dict[str, Any], key: str, where: str) -> Any:
    if key not in d:
        raise ConfigError(f"missing required config key '{key}' in {where}")
    return d[key]


def load_config(path: Path) -> Config:
    if not path.exists():
        raise ConfigError(f"config file not found: {path}")
    raw = yaml.safe_load(path.read_text())
    if not isinstance(raw, dict):
        raise ConfigError(f"config must be a YAML mapping: {path}")

    backends_raw = _require(raw, "backends", "config")
    backends = Backends(
        preprocess=str(_require(backends_raw, "preprocess", "backends")),
        vl=str(_require(backends_raw, "vl", "backends")),
        tts=str(_require(backends_raw, "tts", "backends")),
    )
    _check_choice(backends.preprocess, PREPROCESS_BACKENDS, "backends.preprocess")
    _check_choice(backends.vl, VL_BACKENDS, "backends.vl")
    _check_choice(backends.tts, TTS_BACKENDS, "backends.tts")

    rules_raw = raw.get("rules_file")
    rules_file = Path(str(rules_raw)).expanduser() if rules_raw else None
    if rules_file is not None and not rules_file.exists():
        raise ConfigError(f"rules_file does not exist: {rules_file}")

    pf_raw = _require(raw, "prefilter", "config")
    prefilter = PrefilterConfig(
        redundancy_threshold=float(_require(pf_raw, "redundancy_threshold", "prefilter"))
    )
    if not 0.0 <= prefilter.redundancy_threshold <= 1.0:
        raise ConfigError("prefilter.redundancy_threshold must be in [0, 1]")

    r_raw = _require(raw, "rungs", "config")
    rungs = RungConfig(
        max_compress_factor=float(_require(r_raw, "max_compress_factor", "rungs")),
        time_shift_cap_s=float(_require(r_raw, "time_shift_cap_s", "rungs")),
        placeholder_marker_s=float(_require(r_raw, "placeholder_marker_s", "rungs")),
        merge_gap_s=float(r_raw.get("merge_gap_s", 3.0)),
    )
    if rungs.max_compress_factor < 1.0:
        raise ConfigError("rungs.max_compress_factor must be >= 1.0")
    if rungs.time_shift_cap_s < 0.0 or rungs.placeholder_marker_s < 0.0 or rungs.merge_gap_s < 0.0:
        raise ConfigError("rung timings must be non-negative")

    t_raw = _require(raw, "tts", "config")
    tts = TTSConfig(
        voice=str(_require(t_raw, "voice", "tts")),
        sample_rate=int(_require(t_raw, "sample_rate", "tts")),
        voxtral=dict(t_raw.get("voxtral", {})),
    )
    if tts.sample_rate <= 0:
        raise ConfigError("tts.sample_rate must be positive")

    v_raw = raw.get("vl", {})
    base_model = str(v_raw.get("model", ""))
    model_large = str(v_raw.get("model_large", ""))
    min_ram = int(v_raw.get("model_large_min_ram_gb", 16))
    # Auto-select the richer model on big-RAM machines, else the smaller one (§6.1).
    effective_model = model_large if (model_large and total_ram_gb() >= min_ram) else base_model
    vl = VLConfig(
        model=effective_model,
        image_max_side=int(v_raw.get("image_max_side", 768)),
        max_ad_words=int(v_raw.get("max_ad_words", 0)),
        verbosity=str(v_raw.get("verbosity", "balanced")),
        model_large=model_large,
        model_large_min_ram_gb=min_ram,
    )
    if vl.image_max_side <= 0:
        raise ConfigError("vl.image_max_side must be positive")
    if vl.max_ad_words < 0:
        raise ConfigError("vl.max_ad_words must be >= 0 (0 = no cap)")
    _check_choice(vl.verbosity, VL_VERBOSITY, "vl.verbosity")

    pp_raw = raw.get("preprocess", {})
    preprocess = PreprocessConfig(
        whisper_backend=str(pp_raw.get("whisper_backend", "mlx")),
        whisper_model=str(pp_raw.get("whisper_model", "mlx-community/whisper-large-v3-turbo")),
        scene_threshold=float(pp_raw.get("scene_threshold", 0.3)),
        keyframe_dedup_max_distance=int(pp_raw.get("keyframe_dedup_max_distance", 5)),
        transcript_pad_s=float(pp_raw.get("transcript_pad_s", 2.0)),
        ocr=str(pp_raw.get("ocr", "auto")),
    )
    if not 0.0 <= preprocess.scene_threshold <= 1.0:
        raise ConfigError("preprocess.scene_threshold must be in [0, 1]")
    _check_choice(preprocess.ocr, OCR_MODES, "preprocess.ocr")
    _check_choice(preprocess.whisper_backend, WHISPER_BACKENDS, "preprocess.whisper_backend")

    ext_raw = raw.get("extended_ad", {})
    extended_ad = ExtendedADConfig(
        enabled=bool(ext_raw.get("enabled", True)),
        always_pause=bool(ext_raw.get("always_pause", False)),
    )

    cache_raw = _require(raw, "cache", "config")
    cache_dir = Path(str(_require(cache_raw, "dir", "cache"))).expanduser()

    player_raw = raw.get("player", {})
    player = PlayerConfig(captions_default_on=bool(player_raw.get("captions_default_on", True)))

    return Config(
        pipeline_version=str(_require(raw, "pipeline_version", "config")),
        backends=backends,
        rules_file=rules_file,
        prefilter=prefilter,
        rungs=rungs,
        tts=tts,
        vl=vl,
        preprocess=preprocess,
        extended_ad=extended_ad,
        cache_dir=cache_dir,
        player=player,
    )


def _check_choice(value: str, allowed: set[str], where: str) -> None:
    if value not in allowed:
        raise ConfigError(f"{where} must be one of {sorted(allowed)}, got '{value}'")
