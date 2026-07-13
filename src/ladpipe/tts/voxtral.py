"""VoxtralTTSBackend — Voxtral-4B-TTS via mlx-audio (Apple Silicon, offline).

Loads the MLX community build in-process (no vLLM server). ``estimate_duration``
is a fast char-rate heuristic used only for the provisional rung gate (so obvious
rung-5 drops aren't synthesised); the mixer/rungs reconcile against the REAL clip
length (§6). ``mlx_audio`` is lazy-imported inside ``synthesize``, never at top
level. The model is loaded once, on first use.

License: Voxtral and its reference voices are CC-BY-NC-4.0 (non-commercial,
attribution required) — see README/§9 before redistributing.
"""

from __future__ import annotations

from array import array

from ..types import AudioClip

# Calibrate once against the chosen voice. ~14 chars/sec is a reasonable start; the
# estimate only gates synthesis — real duration always wins.
_CHARS_PER_SEC = 14.0


def estimate_duration_chars(text: str, chars_per_sec: float = _CHARS_PER_SEC) -> float:
    return max(0.3, len(text.strip()) / chars_per_sec)


class VoxtralTTSBackend:
    def __init__(self, model_path: str, voice: str, sample_rate: int) -> None:
        self._model_path = model_path
        self._voice = voice
        self._sample_rate = sample_rate
        self._model: object | None = None

    def estimate_duration(self, text: str) -> float:
        return estimate_duration_chars(text)

    def synthesize(self, text: str) -> AudioClip:
        model = self._ensure_loaded()
        # mlx-audio's generate() is a generator yielding per-segment results, each
        # carrying float samples at the model's native rate (24 kHz). Concatenate.
        samples = array("f")
        for segment in model.generate(text=text, voice=self._voice):  # type: ignore[attr-defined]
            samples.extend(_to_float_array(segment.audio))
        return AudioClip(samples, self._sample_rate)

    def _ensure_loaded(self) -> object:
        if self._model is None:
            from mlx_audio.tts.utils import load

            self._model = load(self._model_path)
        assert self._model is not None
        return self._model


def _to_float_array(audio: object) -> array[float]:
    """Coerce an mlx/numpy waveform to a mono float32 array in [-1, 1]."""
    reshape = getattr(audio, "reshape", None)
    flat = reshape(-1) if reshape is not None else audio
    tolist = getattr(flat, "tolist", None)
    values = tolist() if tolist is not None else list(flat)  # type: ignore[arg-type]
    return array("f", (float(x) for x in values))
