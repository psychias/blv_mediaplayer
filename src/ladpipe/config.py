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
TTS_BACKENDS = {"mock", "kokoro", "voxtral"}
OCR_MODES = {"auto", "on", "off"}
VERBOSITY_LEVELS = {"brief", "standard", "detailed"}
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
    # Wait this long after a slide change before a pause-and-describe (rung 0) line starts,
    # so the viewer sees the new slide and hears the lecturer point at it before the video
    # freezes. Clamped to the end of that slide's speech. 0 = pause on the change itself.
    extended_settle_s: float = 1.2


@dataclass(frozen=True)
class TTSConfig:
    voice: str
    sample_rate: int
    kokoro: dict[str, Any] = field(default_factory=dict)
    voxtral: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VLConfig:
    # Path/repo to quantised MLX VL weights (mlx-vlm auto-detects the architecture). The
    # effective model after RAM auto-select is stored here (§6.1). Fine-tuned weights
    # drop in by pointing this at the converted MLX checkpoint — a pure config swap.
    model: str
    image_max_side: int = 768  # downscale the keyframe fed to the VL encoder (§7)
    # Cap AD-line length before TTS (0 = no cap). A safety net against verbose base-model
    # output and a stand-in for the fine-tune's concise AD; shorter lines = faster TTS.
    max_ad_words: int = 0
    # AD detail level (§8): parameterises the VL prompt style and scales the word cap.
    # Part of the cache key (config_hash includes vl), so each level caches separately.
    verbosity: str = "standard"
    model_large: str = ""  # optional richer model used on >= model_large_min_ram_gb
    model_large_min_ram_gb: int = 16

    @property
    def effective_max_ad_words(self) -> int:
        """Word cap after applying the verbosity level (0 = no cap, as before)."""
        base = self.max_ad_words or 14  # sensible cap when the config leaves it uncapped
        if self.verbosity == "brief":
            return min(base, 10)
        if self.verbosity == "detailed":
            return 0 if self.max_ad_words == 0 else self.max_ad_words * 2
        return self.max_ad_words


@dataclass(frozen=True)
class PreprocessConfig:
    whisper_backend: str  # mlx | openai — mlx runs on the GPU (Apple Silicon), much faster
    whisper_model: str  # mlx repo (mlx-community/whisper-large-v3-turbo) or openai name ("turbo")
    scene_threshold: float  # ffmpeg scene-detection sensitivity (0-1)
    keyframe_dedup_max_distance: int  # perceptual-hash hamming distance to dedup slides
    transcript_pad_s: float  # seconds of transcript context around a moment
    ocr: str  # auto | on | off — feed slide OCR into the VL prompt (§6)
    # Cursor-dwell detection (preprocess/pointing.py): a deliberate move then a hold becomes
    # a "pointing" moment. Scene detection cannot see the cursor at all.
    pointing: bool = True
    pointing_min_dwell_s: float = 0.8  # how long the cursor must hold still
    pointing_min_gap_s: float = 10.0  # at most one pointing moment per this many seconds


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
        # "auto" defers to the VL model; the shipped AD4Edu fine-tune was trained with the
        # OCR line alongside the keyframe, so auto resolves to ON. "off" is the explicit override.
        return self.preprocess.ocr != "off"

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


def _resolved_backend(base: Path, raw: Any) -> dict[str, Any]:
    """A TTS backend's settings, with its ``model_path`` resolved beside the config."""
    out = dict(raw or {})
    if "model_path" in out:
        out["model_path"] = _beside_config(base, str(out["model_path"]))
    return out


def _beside_config(base: Path, value: str) -> str:
    """Resolve a relative model/rules path against the config file's own directory.

    The shipped .app carries its models next to its config inside the bundle, so the YAML
    can name them relatively and still resolve wherever the app is installed. A value that
    does not exist on disk when resolved (a Hugging Face repo id, say) is passed through
    untouched, and an absolute path is left alone."""
    if not value:
        return value
    p = Path(value).expanduser()
    if p.is_absolute():
        return str(p)
    candidate = (base / p).resolve()
    return str(candidate) if candidate.exists() else value


def load_config(path: Path) -> Config:
    if not path.exists():
        raise ConfigError(f"config file not found: {path}")
    raw = yaml.safe_load(path.read_text())
    if not isinstance(raw, dict):
        raise ConfigError(f"config must be a YAML mapping: {path}")
    here = path.resolve().parent

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
    rules_file = Path(_beside_config(here, str(rules_raw))) if rules_raw else None
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
        extended_settle_s=float(r_raw.get("extended_settle_s", 1.2)),
    )
    if rungs.max_compress_factor < 1.0:
        raise ConfigError("rungs.max_compress_factor must be >= 1.0")
    if (rungs.time_shift_cap_s < 0.0 or rungs.placeholder_marker_s < 0.0
            or rungs.merge_gap_s < 0.0 or rungs.extended_settle_s < 0.0):
        raise ConfigError("rung timings must be non-negative")

    t_raw = _require(raw, "tts", "config")
    tts = TTSConfig(
        voice=str(_require(t_raw, "voice", "tts")),
        sample_rate=int(_require(t_raw, "sample_rate", "tts")),
        kokoro=_resolved_backend(here, t_raw.get("kokoro", {})),
        voxtral=_resolved_backend(here, t_raw.get("voxtral", {})),
    )
    if tts.sample_rate <= 0:
        raise ConfigError("tts.sample_rate must be positive")

    v_raw = raw.get("vl", {})
    base_model = _beside_config(here, str(v_raw.get("model", "")))
    model_large = _beside_config(here, str(v_raw.get("model_large", "")))
    min_ram = int(v_raw.get("model_large_min_ram_gb", 16))
    # Auto-select the richer model on big-RAM machines, else the smaller one (§6.1).
    effective_model = model_large if (model_large and total_ram_gb() >= min_ram) else base_model
    vl = VLConfig(
        model=effective_model,
        image_max_side=int(v_raw.get("image_max_side", 768)),
        max_ad_words=int(v_raw.get("max_ad_words", 0)),
        verbosity=str(v_raw.get("verbosity", "standard")),
        model_large=model_large,
        model_large_min_ram_gb=min_ram,
    )
    if vl.image_max_side <= 0:
        raise ConfigError("vl.image_max_side must be positive")
    if vl.max_ad_words < 0:
        raise ConfigError("vl.max_ad_words must be >= 0 (0 = no cap)")
    _check_choice(vl.verbosity, VERBOSITY_LEVELS, "vl.verbosity")

    pp_raw = raw.get("preprocess", {})
    preprocess = PreprocessConfig(
        whisper_backend=str(pp_raw.get("whisper_backend", "mlx")),
        whisper_model=_beside_config(
            here, str(pp_raw.get("whisper_model", "mlx-community/whisper-large-v3-turbo"))
        ),
        scene_threshold=float(pp_raw.get("scene_threshold", 0.3)),
        keyframe_dedup_max_distance=int(pp_raw.get("keyframe_dedup_max_distance", 5)),
        transcript_pad_s=float(pp_raw.get("transcript_pad_s", 2.0)),
        ocr=str(pp_raw.get("ocr", "auto")),
        pointing=bool(pp_raw.get("pointing", True)),
        pointing_min_dwell_s=float(pp_raw.get("pointing_min_dwell_s", 0.8)),
        pointing_min_gap_s=float(pp_raw.get("pointing_min_gap_s", 10.0)),
    )
    if preprocess.pointing_min_dwell_s <= 0.0 or preprocess.pointing_min_gap_s <= 0.0:
        raise ConfigError("preprocess.pointing_min_dwell_s and pointing_min_gap_s must be positive")
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
