"""Stdlib-only PCM/WAV helpers shared by the mixer and the mock backends.

Not in the original spec layout, but justified: WAV creation/overlay/resample is
a concrete cross-stage requirement (§3, §7) and belongs in one place. Uses only
``wave``/``array``/``math`` so the mock path stays dependency-free.
"""

from __future__ import annotations

import math
import wave
from array import array
from pathlib import Path

from .types import AudioClip

_INT16_MAX = 32767


def silence(duration: float, sample_rate: int) -> AudioClip:
    n = max(0, round(duration * sample_rate))
    return AudioClip(array("f", bytes(4 * n)), sample_rate)


def pad_trailing_silence(clip: AudioClip, seconds: float) -> AudioClip:
    """Append silence to a clip — a tail buffer so a player stopping on the clip's
    duration doesn't clip the last words to audio-start latency (extended AD, §7/§8)."""
    out = AudioClip(array("f", clip.samples), clip.sample_rate)
    out.samples.extend(array("f", bytes(4 * max(0, round(seconds * clip.sample_rate)))))
    return out


def tone(duration: float, sample_rate: int, freq: float = 220.0, amp: float = 0.2) -> AudioClip:
    n = max(0, round(duration * sample_rate))
    samples = array("f", [amp * math.sin(2.0 * math.pi * freq * i / sample_rate) for i in range(n)])
    return AudioClip(samples, sample_rate)


def earcon(sample_rate: int) -> AudioClip:
    """Short rising two-tone cue prepended to each extended-AD (rung 0) clip, so a
    listener knows the video paused *for a description* and not by accident (§8;
    MAVP found non-speech cues essential to explain system-initiated pauses)."""
    out = tone(0.09, sample_rate, freq=660.0, amp=0.25)
    out.samples.extend(tone(0.09, sample_rate, freq=990.0, amp=0.25).samples)
    out.samples.extend(silence(0.08, sample_rate).samples)
    return out


def resample_to_length(clip: AudioClip, n_samples: int) -> AudioClip:
    """Linearly resample to exactly ``n_samples`` (used for rung-2 compression)."""
    src = clip.samples
    n_src = len(src)
    if n_samples <= 0 or n_src == 0:
        return AudioClip(array("f"), clip.sample_rate)
    if n_samples == n_src:
        return AudioClip(array("f", src), clip.sample_rate)
    out = array("f", bytes(4 * n_samples))
    scale = (n_src - 1) / (n_samples - 1) if n_samples > 1 else 0.0
    for i in range(n_samples):
        pos = i * scale
        lo = int(pos)
        hi = min(lo + 1, n_src - 1)
        frac = pos - lo
        out[i] = src[lo] * (1.0 - frac) + src[hi] * frac
    return AudioClip(out, clip.sample_rate)


def overlay(base: AudioClip, clip: AudioClip, start_time: float) -> None:
    """Mix ``clip`` onto ``base`` in place at ``start_time``, clipped to base length."""
    if base.sample_rate != clip.sample_rate:
        raise ValueError("sample-rate mismatch in overlay")
    start = max(0, round(start_time * base.sample_rate))
    b = base.samples
    c = clip.samples
    n = min(len(c), len(b) - start)
    for i in range(n):
        v = b[start + i] + c[i]
        b[start + i] = 1.0 if v > 1.0 else -1.0 if v < -1.0 else v


def write_wav(clip: AudioClip, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = array("h", (int(max(-1.0, min(1.0, s)) * _INT16_MAX) for s in clip.samples))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(clip.sample_rate)
        w.writeframes(pcm.tobytes())


def read_wav(path: Path) -> AudioClip:
    with wave.open(str(path), "rb") as w:
        sr = w.getframerate()
        frames = w.readframes(w.getnframes())
    pcm = array("h")
    pcm.frombytes(frames)
    samples = array("f", (s / _INT16_MAX for s in pcm))
    return AudioClip(samples, sr)
