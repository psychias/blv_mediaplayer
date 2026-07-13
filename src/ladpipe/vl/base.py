"""VLBackend Protocol (interface segregation: §4 I)."""

from __future__ import annotations

from typing import Protocol

from ..types import ADDecision, Moment


class VLBackend(Protocol):
    def describe(self, moment: Moment, rules: str) -> ADDecision:
        """Decide whether to emit an AD line for this moment, and what to say."""
        ...
