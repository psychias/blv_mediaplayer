"""Mixer: overlay rendered AD clips onto the lecturer track, length-matched (§7).

Single responsibility: given the base track and a list of (start_time, clip)
renders, mix them in and return a track of EXACTLY the base length. The player
needs no alignment logic because the output is length-matched by construction.
"""

from __future__ import annotations

from array import array

from . import audio
from .types import AudioClip


def build(base: AudioClip, renders: list[tuple[float, AudioClip]]) -> AudioClip:
    out = AudioClip(array("f", base.samples), base.sample_rate)
    for start_time, clip in renders:
        audio.overlay(out, clip, start_time)
    return out
