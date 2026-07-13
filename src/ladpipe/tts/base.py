"""TTSBackend Protocol.

``estimate_duration`` is mandatory (§5): the rung ladder compares predicted AD
duration against available pause length, so duration estimation is not optional.
"""

from __future__ import annotations

from typing import Protocol

from ..types import AudioClip


class TTSBackend(Protocol):
    def synthesize(self, text: str) -> AudioClip: ...

    def estimate_duration(self, text: str) -> float:
        """Fast provisional duration estimate, before synthesis."""
        ...
