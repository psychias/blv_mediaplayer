from __future__ import annotations

from ladpipe.captions import build_descriptions_webvtt, build_webvtt
from ladpipe.types import Placement, TranscriptSegment


def _seg(start: float, end: float, text: str) -> TranscriptSegment:
    return TranscriptSegment(start=start, end=end, text=text)


def test_webvtt_has_both_cue_kinds() -> None:
    segs = [_seg(1.0, 4.0, "the lecturer speaks here")]
    spoken = Placement("m1", 1, 4.0, 1.8, 1.0, "a labeled diagram", dropped=False)
    vtt = build_webvtt(segs, [spoken])
    assert vtt.startswith("WEBVTT")
    assert "the lecturer speaks here" in vtt  # lecturer cue
    assert "<c.ad>AD: a labeled diagram</c.ad>" in vtt  # AD cue, distinctly marked
    assert "L1" in vtt and "AD1" in vtt  # independently identifiable cue ids


def test_lecturer_cues_are_synced_to_segments() -> None:
    # Two timed segments -> two cues at their own timestamps (synced to the speech).
    segs = [_seg(1.0, 3.0, "first sentence"), _seg(3.0, 6.5, "second sentence")]
    vtt = build_webvtt(segs, [])
    assert "00:00:01.000 --> 00:00:03.000\nfirst sentence" in vtt
    assert "00:00:03.000 --> 00:00:06.500\nsecond sentence" in vtt


def test_ad_cue_uses_placement_time_not_moment_time() -> None:
    segs = [_seg(1.0, 4.0, "speech")]
    shifted = Placement("m1", 3, 7.0, 1.8, 1.0, "shifted line", dropped=False)
    vtt = build_webvtt(segs, [shifted])
    assert "00:00:07.000 --> 00:00:08.800" in vtt


def test_no_ad_cue_for_marker_or_drop() -> None:
    segs = [_seg(1.0, 4.0, "speech")]
    marker = Placement("m1", 4, 4.0, 0.4, 1.0, "not spoken", dropped=False)
    drop = Placement("m2", 5, 4.0, 0.0, 1.0, "dropped", dropped=True)
    vtt = build_webvtt(segs, [marker, drop])
    assert "AD" not in vtt.replace("WEBVTT", "")  # no AD cues
    assert "not spoken" not in vtt and "dropped" not in vtt


def test_extended_ad_goes_to_descriptions_not_main_track() -> None:
    segs = [_seg(1.0, 4.0, "speech")]
    extended = Placement("m1", 0, 4.0, 2.0, 1.0, "a complex pathway diagram", dropped=False)
    # rung-0 lines do NOT appear in the main AD track...
    main = build_webvtt(segs, [extended])
    assert "complex pathway" not in main
    # ...they appear in the descriptions track, distinctly marked.
    desc = build_descriptions_webvtt([extended])
    assert desc.startswith("WEBVTT")
    assert "DESC1" in desc
    assert "<c.ad-extended>AD: a complex pathway diagram</c.ad-extended>" in desc


def test_descriptions_empty_when_no_extended() -> None:
    spoken = Placement("m1", 1, 4.0, 1.8, 1.0, "spoken line", dropped=False)
    assert build_descriptions_webvtt([spoken]).strip() == "WEBVTT"
