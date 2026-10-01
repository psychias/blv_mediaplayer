"""Pure-logic tests for the cursor-dwell detector — synthetic motion, no video."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ladpipe.preprocess.pointing import MAX_CURSOR_PIXELS, Dwell, Motion, dwells

DT = 0.2  # FPS 5


def _seq(*parts: tuple[str, Any], t0: float = 100.0) -> list[Motion]:
    """Build a motion track from ("still", n) / ("move", [(x, y), ...]) / ("busy", n) runs."""
    out: list[Motion] = []
    t = t0
    for kind, arg in parts:
        if kind == "move":
            for x, y in arg:
                out.append(Motion(t, 6, x, y))
                t += DT
        else:
            pixels = 0 if kind == "still" else MAX_CURSOR_PIXELS + 1
            for _ in range(int(arg)):
                out.append(Motion(t, pixels, -1.0, -1.0))
                t += DT
    return out


def _dwells(
    motion: list[Motion], min_dwell_s: float = 0.8, min_gap_s: float = 10.0
) -> list[Dwell]:
    return dwells(motion, min_dwell_s=min_dwell_s, min_gap_s=min_gap_s)


def test_move_then_hold_is_one_dwell_at_the_resting_point() -> None:
    m = _seq(("still", 5), ("move", [(0.2, 0.5), (0.3, 0.5), (0.4, 0.5)]), ("still", 6))
    d = _dwells(m)
    assert len(d) == 1
    assert (d[0].x, d[0].y) == (0.4, 0.5)  # where it stopped, not where it started
    assert d[0].t == m[7].t  # the last moving frame
    assert abs(d[0].hold_s - 6 * DT) < 1e-9


def test_short_hold_is_not_a_dwell() -> None:
    m = _seq(("move", [(0.2, 0.5), (0.3, 0.5), (0.4, 0.5)]), ("still", 2))  # 0.4 s < 0.8 s
    assert _dwells(m) == []


def test_continuous_motion_never_dwells() -> None:
    m = _seq(("move", [(i / 20, 0.5) for i in range(2, 18)]))
    assert _dwells(m) == []


def test_a_static_slide_with_no_cursor_produces_nothing() -> None:
    assert _dwells(_seq(("still", 50))) == []


def test_animation_or_video_resets_tracking() -> None:
    # Big changes are not a cursor; what came before them must not turn into a dwell.
    m = _seq(("move", [(0.2, 0.5), (0.3, 0.5), (0.4, 0.5)]), ("busy", 3), ("still", 10))
    assert _dwells(m) == []


def test_a_twitch_is_not_a_point() -> None:
    m = _seq(("move", [(0.40, 0.5), (0.41, 0.5)]), ("still", 10))  # moved 1% of the width
    assert _dwells(m) == []


def test_cursor_parked_at_the_edge_is_ignored() -> None:
    m = _seq(("move", [(0.5, 0.5), (0.7, 0.8), (0.99, 0.99)]), ("still", 10))
    assert _dwells(m) == []


def test_min_gap_keeps_the_longer_hold() -> None:
    m = _seq(
        ("move", [(0.2, 0.5), (0.3, 0.5), (0.4, 0.5)]), ("still", 5),   # hold 1.0 s
        ("move", [(0.5, 0.5), (0.6, 0.5), (0.7, 0.5)]), ("still", 15),  # hold 3.0 s, ~2 s later
    )
    d = _dwells(m, min_gap_s=10.0)
    assert len(d) == 1 and (d[0].x, d[0].y) == (0.7, 0.5)


def test_two_points_far_enough_apart_both_survive() -> None:
    m = _seq(
        ("move", [(0.2, 0.5), (0.3, 0.5), (0.4, 0.5)]), ("still", 60),  # 12 s hold
        ("move", [(0.5, 0.5), (0.6, 0.5), (0.7, 0.5)]), ("still", 10),
    )
    d = _dwells(m, min_gap_s=10.0)
    assert [(x.x, x.y) for x in d] == [(0.4, 0.5), (0.7, 0.5)]
    assert d[0].t < d[1].t  # returned in time order, not by hold length


def test_per_interval_cap_prefers_the_longest_holds() -> None:
    parts: list[tuple[str, object]] = []
    for k in range(6):  # six points 12 s apart with growing holds
        x = 0.2 + 0.1 * k
        parts += [("move", [(x, 0.3), (x + 0.02, 0.5), (x + 0.04, 0.7)]), ("still", 55 + 2 * k)]
    d = _dwells(_seq(*parts), min_gap_s=10.0)
    assert len(d) == 4
    assert min(x.hold_s for x in d) > (55 + 2) * DT  # the two shortest were dropped


def test_draw_pointer_stamps_a_visible_pointer(tmp_path: Path) -> None:
    from PIL import Image

    from ladpipe.preprocess.pointing import draw_pointer

    frame = tmp_path / "f.png"
    Image.new("RGB", (400, 300), (200, 200, 255)).save(frame)
    draw_pointer(str(frame), 0.5, 0.5)
    im = Image.open(frame).convert("RGB")
    assert im.getpixel((202, 160)) == (255, 255, 255)  # inside the arrow: white fill
    assert im.getpixel((50, 50)) == (200, 200, 255)  # away from it: untouched

