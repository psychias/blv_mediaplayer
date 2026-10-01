"""KokoroTTSBackend — Kokoro-82M via mlx-audio (Apple Silicon, offline).

Loads the MLX community build in-process from a local directory. The voice is
resolved to ``<model_path>/voices/<voice>.safetensors`` when that file exists, so
nothing is fetched from the Hub at runtime (a bare name that has no local file falls
through to mlx-audio's own Hub-cached lookup). ``estimate_duration`` is a fast
char-rate heuristic used only for the provisional rung gate; the mixer/rungs
reconcile against the REAL clip length (§6). ``mlx_audio`` is lazy-imported inside
``synthesize``, never at top level. The model is loaded once, on first use.

English G2P is misaki's dictionary; out-of-dictionary words (technical lecture
vocabulary) fall back to the pip-bundled espeak-ng (``espeakng-loader``), which is
wired into phonemizer before the pipeline is built — no Homebrew install needed.

License: Kokoro-82M weights and voice packs are Apache-2.0.
"""

from __future__ import annotations

from array import array
from pathlib import Path

from ..types import AudioClip

# Measured on-device with af_heart over five AD-style sentences (~13 chars/sec). The
# estimate only gates synthesis — real duration always wins.
_CHARS_PER_SEC = 13.0


def estimate_duration_chars(text: str, chars_per_sec: float = _CHARS_PER_SEC) -> float:
    return max(0.3, len(text.strip()) / chars_per_sec)


def resolve_voice(model_path: str, voice: str) -> str:
    """Prefer the bundled voice pack next to the weights; else pass the name through."""
    local = Path(model_path) / "voices" / f"{voice}.safetensors"
    return str(local) if local.exists() else voice


def lang_code(voice: str) -> str:
    """Kokoro voice names start with their language code (af_heart -> 'a', bf_emma -> 'b')."""
    name = Path(voice).name
    return name[0] if name and name[0] in "ab" else "a"


class KokoroTTSBackend:
    def __init__(self, model_path: str, voice: str, sample_rate: int) -> None:
        self._model_path = model_path
        self._voice = voice
        self._sample_rate = sample_rate
        self._model: object | None = None

    def estimate_duration(self, text: str) -> float:
        return estimate_duration_chars(text)

    def synthesize(self, text: str) -> AudioClip:
        model = self._ensure_loaded()
        samples = array("f")
        for segment in model.generate(  # type: ignore[attr-defined]
            text=text,
            voice=resolve_voice(self._model_path, self._voice),
            lang_code=lang_code(self._voice),
        ):
            samples.extend(_to_float_array(segment.audio))
        return AudioClip(samples, self._sample_rate)

    def _ensure_loaded(self) -> object:
        if self._model is None:
            _enable_espeak_fallback()
            from mlx_audio.tts.utils import load

            self._model = load(self._model_path)
        assert self._model is not None
        return self._model


def _enable_espeak_fallback() -> None:
    """Point phonemizer at the pip-bundled espeak-ng before misaki builds its G2P."""
    import espeakng_loader
    from phonemizer.backend.espeak.wrapper import EspeakWrapper

    EspeakWrapper.set_library(espeakng_loader.get_library_path())
    EspeakWrapper.set_data_path(espeakng_loader.get_data_path())


def _to_float_array(audio: object) -> array[float]:
    """Coerce an mlx/numpy waveform to a mono float32 array in [-1, 1]."""
    reshape = getattr(audio, "reshape", None)
    flat = reshape(-1) if reshape is not None else audio
    tolist = getattr(flat, "tolist", None)
    values = tolist() if tolist is not None else list(flat)  # type: ignore[arg-type]
    return array("f", (float(x) for x in values))
