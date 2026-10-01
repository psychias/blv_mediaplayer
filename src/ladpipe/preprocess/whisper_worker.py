"""Run mlx-whisper in a child process: ``python -m ladpipe.preprocess.whisper_worker WAV MODEL``.

Prints the transcript segments as JSON on stdout. Whisper must not share a process with
the VL model: after mlx-whisper has run — on any thread, even with its model released —
later mlx-vlm generations in the same process degrade to NaN output (token 0, "!!!!")
after a few dozen calls. Reproduced on Qwen3-VL 8-bit with mlx 0.31 / mlx-vlm 0.6.3;
VAD (torch) and Apple Vision OCR in-process are harmless. A child process contains it.
"""

from __future__ import annotations

import json
import sys


def main() -> None:
    wav, model_ref = sys.argv[1], sys.argv[2]
    import mlx_whisper

    result = mlx_whisper.transcribe(wav, path_or_hf_repo=model_ref)
    segments = [
        {"start": float(s["start"]), "end": float(s["end"]), "text": str(s["text"]).strip()}
        for s in result["segments"]
    ]
    json.dump(segments, sys.stdout)


if __name__ == "__main__":
    main()
