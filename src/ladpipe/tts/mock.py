"""MockTTSBackend — a tone whose length is a deterministic function of word count.

Stdlib only. ``estimate_duration`` and ``synthesize`` agree exactly (the estimate
is exact here), which keeps the mock rung selection deterministic.
"""

from __future__ import annotations

from .. import audio
from ..types import AudioClip

_BASE_S = 0.30
_PER_WORD_S = 0.30


def _word_count(text: str) -> int:
    return max(1, len(text.split()))


class MockTTSBackend:
    def __init__(self, sample_rate: int) -> None:
        self._sample_rate = sample_rate

    def estimate_duration(self, text: str) -> float:
        return _BASE_S + _PER_WORD_S * _word_count(text)

    def synthesize(self, text: str) -> AudioClip:
        return audio.tone(self.estimate_duration(text), self._sample_rate, freq=330.0, amp=0.3)
