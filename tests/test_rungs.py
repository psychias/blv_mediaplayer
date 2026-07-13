from __future__ import annotations

from ladpipe.config import RungConfig
from ladpipe.rungs import bookend, cap_ad_words, merge_adjacent, place
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
    a = _moment(id="a", t_start=0.0, t_end=10.0, visual_signal=True)
    b = _moment(id="b", t_start=12.0, t_end=15.0, pause_after=2.0)  # 2s after a -> merge
    merged = merge_adjacent([(a, "First line."), (b, "Second line.")], gap_s=3.0)
    assert len(merged) == 1
    m, text = merged[0]
    assert text == "First line. Second line."
    assert m.id == "a+b"
    assert m.t_start == 0.0 and m.t_end == 15.0  # spans both moments
    assert m.pause_after == 2.0  # later moment's gap fields (where the line lands)
    assert m.visual_signal  # high value if EITHER was


def test_merge_adjacent_chains_and_respects_gap() -> None:
    a = _moment(id="a", t_start=0.0, t_end=10.0)
    b = _moment(id="b", t_start=12.0, t_end=14.0)   # merges with a
    c = _moment(id="c", t_start=15.0, t_end=17.0)   # merges into a+b (1s after b)
    d = _moment(id="d", t_start=25.0, t_end=27.0)   # 8s gap -> stays separate
    merged = merge_adjacent([(a, "x."), (b, "y."), (c, "z."), (d, "w.")], gap_s=3.0)
    assert [m.id for m, _ in merged] == ["a+b+c", "d"]


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
