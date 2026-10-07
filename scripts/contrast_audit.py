#!/usr/bin/env python3
"""WCAG 2.1 contrast analyzer for every text/background pair in the LectureAD app.

The Swiss accessibility standard (eCH-0059) requires WCAG 2.1 level AA:
  - 4.5:1 for normal text (1.4.3)
  - 3.0:1 for large text and non-text UI components (1.4.3 / 1.4.11)

Every colour literal in app/LectureAD/Sources/Theme.swift (and every composited
caption/pill background) must have a row in PAIRS below. Translucent blacks over the
video are composited against PURE WHITE — the worst-case video frame.

Run: python3 scripts/contrast_audit.py   (exit 1 on any AA failure)
Stdlib only; used as a CI-style gate alongside tests/lint/type checks.
"""

from __future__ import annotations

import sys

RGB = tuple[float, float, float]


def hex_rgb(h: str) -> RGB:
    h = h.lstrip("#")
    return tuple(int(h[i : i + 2], 16) / 255.0 for i in (0, 2, 4))  # type: ignore[return-value]


def over_white(alpha: float, color: str = "#000000") -> RGB:
    """Composite color@alpha over a pure-white (worst-case video) background, in sRGB."""
    fg = hex_rgb(color)
    return tuple(alpha * c + (1.0 - alpha) * 1.0 for c in fg)  # type: ignore[return-value]


def _linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def luminance(rgb: RGB) -> float:
    r, g, b = (_linear(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(fg: RGB, bg: RGB) -> float:
    la, lb = luminance(fg), luminance(bg)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


WHITE = hex_rgb("#FFFFFF")
BLACK = hex_rgb("#000000")
BRAND_BLUE = hex_rgb("#0028A5")  # Color.brandBlue
TEXT_SECONDARY = hex_rgb("#595959")  # Color.textSecondary
BAR_BACKGROUND = hex_rgb("#F5F5F5")  # Color.barBackground
CAPTION_YELLOW = hex_rgb("#FFFF00")  # Color.captionYellow
PILL_STANDARD = over_white(0.80)  # caption pill, standard mode (opacity floor)
PILL_HIGH_CONTRAST = over_white(0.95)  # caption pill, high-contrast mode

# (description, foreground, background, required ratio)
PAIRS: list[tuple[str, RGB, RGB, float]] = [
    ("brandBlue titles on white (Choose/Failure/Prepare)", BRAND_BLUE, WHITE, 4.5),
    ("white text on brandBlue (prominent buttons, AD badge)", WHITE, BRAND_BLUE, 4.5),
    ("textSecondary body text on white", TEXT_SECONDARY, WHITE, 4.5),
    ("black time readout on barBackground", BLACK, BAR_BACKGROUND, 4.5),
    ("textSecondary on barBackground", TEXT_SECONDARY, BAR_BACKGROUND, 4.5),
    ("brandBlue control icons on barBackground (non-text, 1.4.11)",
     BRAND_BLUE, BAR_BACKGROUND, 3.0),
    ("captionYellow AD caption on pill @0.80 over white video", CAPTION_YELLOW, PILL_STANDARD, 4.5),
    ("white lecturer caption on pill @0.80 over white video", WHITE, PILL_STANDARD, 4.5),
    ("captionYellow AD caption on pill @0.95 (high contrast)",
     CAPTION_YELLOW, PILL_HIGH_CONTRAST, 4.5),
    ("white lecturer caption on pill @0.95 (high contrast)", WHITE, PILL_HIGH_CONTRAST, 4.5),
    ("white buffering-pill text on black @0.80 over white video", WHITE, PILL_STANDARD, 4.5),
]


def main() -> int:
    failures = 0
    print(f"{'ratio':>7}  {'min':>4}  result  pair")
    for name, fg, bg, minimum in PAIRS:
        ratio = contrast(fg, bg)
        ok = ratio >= minimum
        failures += 0 if ok else 1
        print(f"{ratio:7.2f}  {minimum:4.1f}  {'PASS ' if ok else 'FAIL '}  {name}")
    if failures:
        print(f"\n{failures} pair(s) below WCAG 2.1 AA — fix before shipping.", file=sys.stderr)
        return 1
    print(f"\nAll {len(PAIRS)} pairs meet WCAG 2.1 AA (eCH-0059).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
