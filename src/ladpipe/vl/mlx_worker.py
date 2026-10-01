"""Run the VL model in a child process — one moment per stdin line, one reply per stdout line.

Invoked as ``python -m ladpipe.vl.mlx_worker <weights-path> <image-max-side>``.

Why a subprocess: the pinned MLX stack (mlx 0.31.2 + mlx-vlm 0.6.3 — see the ``real``
extra in pyproject, which cannot move) accumulates process-global state. After roughly 70
generations the model returns NaN logits, which decode to token 0, ``"!"``; every later
moment is then lost, because the parser fails closed. Reloading the weights does NOT clear
it — verified on a 26-minute lecture, where the failure recurred at the same moment through
three reloads — and only a fresh process does. So the parent restarts this worker on a
generation budget, and again if a degenerate reply shows up anyway.

Protocol: one JSON object per line in (the fields of a ``Moment``), one JSON object per line
out (``{"answer": <classifier word>, "raw": <the model's description JSON>}``). Both sides
stay raw text: the parent owns parsing, so this module is only plumbing.
"""

from __future__ import annotations

import json
import sys

from ..types import Moment
from .mlx_vlm import generate_for_moment, load_model


def main() -> None:
    weights, image_max_side = sys.argv[1], int(sys.argv[2])
    loaded = load_model(weights)
    for line in sys.stdin:
        if not line.strip():
            continue
        moment = Moment(**json.loads(line))
        answer, raw = generate_for_moment(loaded, moment, image_max_side)
        json.dump({"answer": answer, "raw": raw}, sys.stdout)
        sys.stdout.write("\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
