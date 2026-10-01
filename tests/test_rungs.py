from __future__ import annotations

import dataclasses

from ladpipe.config import RungConfig
from ladpipe.rungs import bookend, cap_ad_words, merge_adjacent, place, pointing_cue
from ladpipe.types import Moment


def _moment(**kw: object) -> Moment:
    base = dict(
        id="m",
        t_start=0.0,
        t_end=10.0,
        keyframe_path=None,
        transcript_window="",
        ocr_text="",
        pause_after=0.0,
        next_boundary_offset=0.0,
        next_boundary_pause=0.0,
        visual_signal=False,
    )
    base.update(kw)
    return Moment(**base)  # type: ignore[arg-type]


def test_rung1_gap_insert(rung_cfg: RungConfig) -> None:
    p = place(_moment(pause_after=3.0), clip_duration=1.8, cfg=rung_cfg, ad_text="x")
    assert p.rung == 1 and p.speed_factor == 1.0 and p.start_time == 10.0 and not p.dropped


def test_rung2_compress_within_factor(rung_cfg: RungConfig) -> None:
    p = place(_moment(pause_after=1.5), clip_duration=1.8, cfg=rung_cfg, ad_text="x")
    assert p.rung == 2
    assert 1.0 < p.speed_factor <= rung_cfg.max_compress_factor
    assert p.duration == 1.5  # compressed to fill the pause


def test_rung2_not_used_beyond_max_factor(rung_cfg: RungConfig) -> None:
    # needed factor 1.8/1.2 = 1.5 > 1.3 -> must not pick rung 2
    p = place(_moment(pause_after=1.2), clip_duration=1.8, cfg=rung_cfg, ad_text="x")
    assert p.rung != 2


def test_rung3_time_shift_within_cap(rung_cfg: RungConfig) -> None:
    p = place(
        _moment(pause_after=0.5, next_boundary_offset=3.0, next_boundary_pause=2.5),
        clip_duration=1.8,
        cfg=rung_cfg,
        ad_text="x",
    )
    assert p.rung == 3 and p.start_time == 13.0  # t_end + offset


def test_rung3_blocked_by_5s_cap(rung_cfg: RungConfig) -> None:
    # boundary fits the clip but is beyond the hard 5s cap -> not rung 3
    p = place(
        _moment(pause_after=0.5, next_boundary_offset=6.0, next_boundary_pause=5.0),
        clip_duration=1.8,
        cfg=rung_cfg,
        ad_text="x",
    )
    assert p.rung != 3


def test_rung4_placeholder_low_value(rung_cfg: RungConfig) -> None:
    # No visual signal -> low value -> marker, not extended AD.
    p = place(_moment(pause_after=0.5, visual_signal=False), 1.8, rung_cfg, "x")
    assert p.rung == 4 and p.duration == rung_cfg.placeholder_marker_s and not p.spoken


def test_rung5_drop_low_value(rung_cfg: RungConfig) -> None:
    p = place(_moment(pause_after=0.2, visual_signal=False), 1.8, rung_cfg, "x")
    assert p.rung == 5 and p.dropped and p.duration == 0.0


def test_cap_ad_words() -> None:
    assert cap_ad_words("a short line", 0) == "a short line"  # 0 = no cap
    assert cap_ad_words("a short line", 10) == "a short line"  # under cap, unchanged
    long = "The slide explains the cytoplasm, the material between the membrane and the nucleus"
    out = cap_ad_words(long, 8)
    assert len(out.split()) <= 8
    assert out.endswith((".", ",")) or out[-1].isalpha()  # tidy ending, no dangling clause


def test_merge_adjacent_fuses_lines_within_gap() -> None:
    a = _moment(id="a", t_start=10.0, t_end=12.0, visual_signal=True)
    b = _moment(id="b", t_start=12.0, t_end=15.0, pause_after=2.0)  # slide flips 2s later
    merged = merge_adjacent([(a, "First line."), (b, "Second line.")], gap_s=3.0)
    assert len(merged) == 1
    m, text = merged[0]
    assert text == "First line. Second line."
    assert m.id == "a+b"
    assert m.t_start == 10.0 and m.t_end == 15.0  # spans both moments
    assert m.pause_after == 2.0  # later moment's gap fields (where the line lands)
    assert m.visual_signal  # high value if EITHER was


def test_merge_adjacent_chains_and_respects_gap() -> None:
    a = _moment(id="a", t_start=10.0, t_end=11.5)
    b = _moment(id="b", t_start=11.5, t_end=13.0)   # 1.5s after a -> merges
    c = _moment(id="c", t_start=13.0, t_end=20.0)   # 1.5s after b -> merges into a+b
    d = _moment(id="d", t_start=25.0, t_end=27.0)   # 12s after c -> stays separate
    merged = merge_adjacent([(a, "x."), (b, "y."), (c, "z."), (d, "w.")], gap_s=3.0)
    assert [m.id for m, _ in merged] == ["a+b+c", "d"]
    assert merged[0][0].t_start == 10.0


def test_merge_adjacent_does_not_chain_continuous_speech() -> None:
    # Real lectures: t_end is clamped to the next scene time whenever the lecturer talks
    # across the slide change, so end-to-start gaps are 0 for every pair. Slides 20 s
    # apart must still be separate lines (regression: a whole lecture fused at t=0).
    emits = [
        (_moment(id=f"m{i}", t_start=20.0 * i, t_end=20.0 * (i + 1)), f"line {i}.")
        for i in range(10)
    ]
    merged = merge_adjacent(emits, gap_s=3.0)
    assert len(merged) == 10
    assert [m.t_start for m, _ in merged] == [20.0 * i for i in range(10)]


def test_merge_adjacent_disabled_at_zero() -> None:
    a = _moment(id="a", t_start=0.0, t_end=10.0)
    b = _moment(id="b", t_start=10.5, t_end=12.0)
    assert len(merge_adjacent([(a, "x."), (b, "y.")], gap_s=0.0)) == 2


def test_bookend_marks_first_and_last() -> None:
    emits = [(_moment(id="a"), "Alpha."), (_moment(id="b"), "Beta."), (_moment(id="c"), "Gamma.")]
    out = bookend(emits)
    assert out[0][1] == "Audio description begins. Alpha."
    assert out[1][1] == "Beta."  # middle untouched
    assert out[2][1] == "Gamma. That was the final description."


def test_bookend_single_emit_gets_both_and_empty_is_noop() -> None:
    out = bookend([(_moment(id="a"), "Only.")])
    assert out[0][1] == "Audio description begins. Only. That was the final description."
    assert bookend([]) == []


def test_bookend_first_only_for_streaming() -> None:
    emits = [(_moment(id="a"), "Alpha."), (_moment(id="b"), "Beta.")]
    out = bookend(emits, last=False)
    assert out[0][1].startswith("Audio description begins.")
    assert out[1][1] == "Beta."  # end unknown while streaming -> untouched


def test_rung0_extended_for_high_value_nonfitting(rung_cfg: RungConfig) -> None:
    # High-value (visual) moment that fits no gap -> pause-and-describe (rung 0).
    p = place(_moment(pause_after=0.5, visual_signal=True), 1.8, rung_cfg, "x")
    assert p.rung == 0 and p.is_extended and not p.dropped
    assert p.duration == 1.8  # the FULL description plays during the pause


def test_rung0_never_drops_high_value_even_with_no_pause(rung_cfg: RungConfig) -> None:
    # Even with a sub-marker pause, high-value content is described, not dropped.
    p = place(_moment(pause_after=0.0, visual_signal=True), 1.8, rung_cfg, "x")
    assert p.rung == 0 and not p.dropped


def test_always_pause_forces_rung0_even_when_a_gap_fits(rung_cfg: RungConfig) -> None:
    # A line that WOULD fit the gap (rung 1) still pauses the video when always_pause is on.
    p = place(_moment(pause_after=10.0, visual_signal=True), 1.8, rung_cfg, "x", always_pause=True)
    assert p.rung == 0 and not p.dropped and p.duration == 1.8  # full description, no squeezing


def test_extended_disabled_high_value_falls_to_marker(rung_cfg: RungConfig) -> None:
    # With extended AD off, the ladder degrades to gap-only (high-value -> 4/5).
    p = place(_moment(pause_after=0.5, visual_signal=True), 1.8, rung_cfg, "x",
              extended_ad_enabled=False)
    assert p.rung == 4


def test_extended_start_settles_after_the_slide_change(rung_cfg: RungConfig) -> None:
    # The pause must not land on the frame the slide appears: give the viewer a beat to see
    # it, and the lecturer a beat to say "in this myogram...", before the video freezes.
    m = _moment(t_start=100.0, t_end=160.0, pause_after=10.0, visual_signal=True)
    p = place(m, 1.8, rung_cfg, "x", always_pause=True)
    assert p.rung == 0 and p.start_time == 100.0 + rung_cfg.extended_settle_s


def test_extended_start_settles_on_the_high_value_rung0_branch(rung_cfg: RungConfig) -> None:
    # Same anchor when rung 0 is reached because the line fits no gap, not via always_pause.
    m = _moment(t_start=100.0, t_end=160.0, pause_after=0.0, visual_signal=True)
    p = place(m, 9.0, rung_cfg, "x")
    assert p.rung == 0 and p.start_time == 100.0 + rung_cfg.extended_settle_s


def test_extended_settle_never_outlasts_the_slides_speech(rung_cfg: RungConfig) -> None:
    # Speech stops 0.4 s in (t_end is already clamped to the next slide change), so the
    # settle stops there too rather than running on into the following slide.
    m = _moment(t_start=100.0, t_end=100.4, pause_after=10.0, visual_signal=True)
    p = place(m, 1.8, rung_cfg, "x", always_pause=True)
    assert p.start_time == 100.4


def test_extended_settle_zero_pauses_on_the_slide_change(rung_cfg: RungConfig) -> None:
    cfg = dataclasses.replace(rung_cfg, extended_settle_s=0.0)
    m = _moment(t_start=100.0, t_end=160.0, pause_after=10.0, visual_signal=True)
    assert place(m, 1.8, cfg, "x", always_pause=True).start_time == 100.0


def test_pointing_cue_leads_with_the_gesture_when_the_model_did_not() -> None:
    assert pointing_cue("The plateau on the graph.") == (
        "The lecturer points here. The plateau on the graph."
    )
    # Already says who points at what: leave it alone.
    assert pointing_cue("The cursor points to the peak of the curve.") == (
        "The cursor points to the peak of the curve."
    )
    assert pointing_cue("The lecturer traces the axis.") == "The lecturer traces the axis."

