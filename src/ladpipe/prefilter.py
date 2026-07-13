"""Redundancy pre-filter: cheaply skip clearly-redundant moments before the VL call.

Asymmetric by design (§7): only short-circuit a moment as redundant when its text
is covered (OCR/transcript cosine >= threshold) AND it has no visual signal. Any
moment with a visual signal always falls through to the VL model — a wrong
"redundant" loses a high-value AD line; a wrong "ambiguous" costs one cheap call.
"""

from __future__ import annotations

import math
import re
from collections import Counter

from .types import Moment

_WORD = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> Counter[str]:
    return Counter(_WORD.findall(text.lower()))


def cosine(a: str, b: str) -> float:
    ca, cb = _tokens(a), _tokens(b)
    if not ca or not cb:
        return 0.0
    dot = sum(ca[t] * cb[t] for t in ca.keys() & cb.keys())
    na = math.sqrt(sum(v * v for v in ca.values()))
    nb = math.sqrt(sum(v * v for v in cb.values()))
    return dot / (na * nb)


def is_redundant(moment: Moment, threshold: float) -> bool:
    """True only when text is covered AND there is no visual signal."""
    if moment.visual_signal:
        return False
    return cosine(moment.ocr_text, moment.transcript_window) >= threshold
