"""MockVLBackend — deterministic canned decisions, stdlib only.

Emits a short fixed-length description for any moment that carries OCR content,
and suppresses (emit=False) when the slide has no extractable content. This is
intentionally trivial: its job is to prove the orchestration plumbing, not to
describe anything. The decision is a pure function of the moment.
"""

from __future__ import annotations

from ..types import ADDecision, Moment

# 5 words -> ~1.8s under the mock TTS rate; keeps the rung math deterministic.
_AD_TEXT = "Slide shows a labeled diagram"


class MockVLBackend:
    def describe(self, moment: Moment, rules: str) -> ADDecision:
        if not moment.ocr_text.strip():
            return ADDecision(
                emit=False,
                ad_text=None,
                teacher_rung=None,
                rationale="no extractable slide content",
            )
        return ADDecision(
            emit=True,
            ad_text=_AD_TEXT,
            teacher_rung=1,
            rationale="visual content not covered by speech",
        )
