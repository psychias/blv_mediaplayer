from __future__ import annotations

import pytest

from ladpipe.prefilter import cosine, is_redundant
from ladpipe.types import Moment


def _moment(ocr: str, transcript: str, visual: bool) -> Moment:
    return Moment(
        id="m",
        t_start=0.0,
        t_end=1.0,
        keyframe_path=None,
        transcript_window=transcript,
        ocr_text=ocr,
        pause_after=0.0,
        visual_signal=visual,
    )


def test_cosine_identical_is_one() -> None:
    assert cosine("gradient descent rule", "gradient descent rule") == pytest.approx(1.0)


def test_cosine_disjoint_is_zero() -> None:
    assert cosine("apple banana", "circuit diagram") == 0.0


def test_redundant_when_covered_and_no_visual() -> None:
    m = _moment("gradient descent update rule", "gradient descent update rule", visual=False)
    assert is_redundant(m, threshold=0.8)


def test_visual_signal_always_sent_to_vl() -> None:
    # Identical text would be redundant, but a visual signal forces a VL call (§7).
    m = _moment("gradient descent update rule", "gradient descent update rule", visual=True)
    assert not is_redundant(m, threshold=0.8)


def test_low_overlap_sent_to_vl() -> None:
    m = _moment("circuit schematic", "now consider the next topic", visual=False)
    assert not is_redundant(m, threshold=0.8)
