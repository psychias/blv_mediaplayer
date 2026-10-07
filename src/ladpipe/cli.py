"""`ladpipe` CLI and the sidecar JSON-events protocol (§8).

Events are newline-delimited JSON on stdout: progress / cache_hit / done / error.
The macOS shell (Phase 3) drives its accessible progress UI from these.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import sys
from pathlib import Path

from .config import VERBOSITY_LEVELS, Backends, Config, ConfigError, load_config
from .orchestrator import PrepareThenCacheOrchestrator
from .types import PipelineResult

DEFAULT_CONFIG = Path(__file__).resolve().parents[2] / "config" / "default.yaml"
_DEMO_BYTES = b"ladpipe-demo-lecture-v1\n" * 4096  # deterministic -> stable cache key

log = logging.getLogger("ladpipe")


class JsonProgress:
    """Progress sink that emits newline-delimited JSON progress events."""

    def __init__(self, stream: object) -> None:
        self._stream = stream

    def progress(self, stage: str, pct: float, label: str) -> None:
        _emit(
            self._stream,
            {"event": "progress", "stage": stage, "pct": round(pct, 4), "label": label},
        )


class HumanProgress:
    """Progress sink that prints a readable line per stage."""

    def progress(self, stage: str, pct: float, label: str) -> None:
        print(f"[{stage:>10}] {pct * 100:5.1f}%  {label}", file=sys.stderr)


def _emit(stream: object, payload: dict[str, object]) -> None:
    stream.write(json.dumps(payload) + "\n")  # type: ignore[attr-defined]
    stream.flush()  # type: ignore[attr-defined]


def _demo_video(config: Config) -> Path:
    path = config.cache_dir.parent / "demo" / "demo_lecture.bin"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(_DEMO_BYTES)
    return path


def _load(args: argparse.Namespace) -> Config:
    config = load_config(Path(args.config))
    if args.mock:
        config = dataclasses.replace(config, backends=Backends("mock", "mock", "mock"))
    if getattr(args, "verbosity", None):
        config = dataclasses.replace(
            config, vl=dataclasses.replace(config.vl, verbosity=args.verbosity)
        )
    return config


def _run(args: argparse.Namespace) -> int:
    use_json: bool = args.json
    try:
        config = _load(args)
        video = _demo_video(config) if args.demo else Path(args.video)
        if not video.exists():
            raise ConfigError(f"video not found: {video}")

        progress = JsonProgress(sys.stdout) if use_json else HumanProgress()
        orchestrator = PrepareThenCacheOrchestrator(config)
        result = orchestrator.prepare(video, progress)

        if use_json:
            event = "cache_hit" if result.cache_hit else "done"
            _emit(
                sys.stdout,
                {
                    "event": event,
                    "artifact": str(result.audio_path),
                    "captions": str(result.captions_path),
                    "descriptions": str(result.descriptions_path),
                    "manifest": str(result.manifest_path),
                },
            )
        else:
            _print_summary(result)
        return 0
    except Exception as exc:
        # Any failure must reach the shell as a graceful error event, never a crash (§10).
        log.exception("pipeline failed")
        message = f"{type(exc).__name__}: {exc}"
        if use_json:
            _emit(sys.stdout, {"event": "error", "message": message})
        else:
            print(f"error: {message}", file=sys.stderr)
        return 1


def _print_summary(result: PipelineResult) -> None:
    spread = " ".join(f"r{r}={result.rung_counts[r]}" for r in range(6))
    print(f"{'cache hit' if result.cache_hit else 'prepared'} — {result.duration:.2f}s")
    print(f"  audio:        {result.audio_path}")
    print(f"  captions:     {result.captions_path}")
    print(f"  descriptions: {result.descriptions_path}")
    print(f"  manifest:     {result.manifest_path}")
    print(f"  described:    {sum(result.rung_counts.values())} line(s)")
    print(f"  rungs:        {spread}  (r0 = extended-AD pause)")
    print(f"  suppressed:   {len(result.suppressed_moment_ids)} moment(s)")


class _StdinCreditPacer:
    """Bounded-lookahead pacer driven by credit lines on stdin. Starts with ``initial``
    credits (windows prepared up front); the player grants one more credit each time the
    playhead advances, keeping preparation only ~``initial`` windows ahead — so the GPU
    is free for smooth playback instead of being pinned preparing the whole lecture."""

    def __init__(self, initial: int) -> None:
        import threading

        self._sem = threading.Semaphore(initial)
        self._closed = False
        reader = threading.Thread(target=self._read_credits, daemon=True)
        reader.start()

    def _read_credits(self) -> None:
        for _ in sys.stdin:  # each line from the app = one more window of headroom
            self._sem.release()
        # stdin closed: no player is pacing us (a terminal run, or the app went away), so
        # stop holding windows back instead of blocking forever after ``initial`` of them.
        self._closed = True
        self._sem.release()

    def wait(self, index: int) -> None:
        if self._closed:
            return
        self._sem.acquire()


def _stream(args: argparse.Namespace) -> int:
    """Streaming mode: emit a window_ready event per window so the player can start early."""
    from .stream import ChunkedStreamingOrchestrator

    use_json: bool = args.json
    try:
        config = _load(args)
        video = Path(args.video)
        if not video.exists():
            raise ConfigError(f"video not found: {video}")
        progress = JsonProgress(sys.stdout) if use_json else HumanProgress()
        orchestrator = ChunkedStreamingOrchestrator(config, window_s=args.window)
        pacer = _StdinCreditPacer(initial=args.lookahead) if args.lookahead > 0 else None
        count = 0
        for w in orchestrator.stream(video, progress, pacer=pacer):
            count += 1
            payload = {
                "event": "window_ready",
                "index": w.index,
                "t_start": w.t_start,
                "t_end": w.t_end,
                "artifact": str(w.audio_path),
                "captions": str(w.captions_path),
                "descriptions": str(w.descriptions_path),
            }
            if use_json:
                _emit(sys.stdout, payload)
            else:
                print(f"window {w.index} [{w.t_start:.0f}-{w.t_end:.0f}s] ready: {w.audio_path}")
        if use_json:
            _emit(sys.stdout, {"event": "stream_done", "windows": count})
        else:
            print(f"streaming complete — {count} window(s)")
        return 0
    except Exception as exc:
        log.exception("streaming failed")
        message = f"{type(exc).__name__}: {exc}"
        if use_json:
            _emit(sys.stdout, {"event": "error", "message": message})
        else:
            print(f"error: {message}", file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ladpipe", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="prepare (and cache) the AD artifact for a lecture")
    run.add_argument("--video", help="path to the lecture video")
    run.add_argument("--demo", action="store_true", help="use a synthetic demo lecture")
    run.add_argument("--mock", action="store_true", help="force all backends to mock")
    run.add_argument("--config", default=str(DEFAULT_CONFIG), help="path to config YAML")
    run.add_argument("--json", action="store_true", help="emit newline-delimited JSON events")
    run.add_argument("--verbosity", choices=sorted(VERBOSITY_LEVELS), default=None,
                     help="AD detail level (overrides vl.verbosity)")

    stream = sub.add_parser("stream", help="prepare in windows; emit window_ready events (§12)")
    stream.add_argument("--video", required=True, help="path to the lecture video")
    stream.add_argument("--mock", action="store_true", help="force all backends to mock")
    stream.add_argument("--config", default=str(DEFAULT_CONFIG), help="path to config YAML")
    stream.add_argument("--window", type=float, default=90.0, help="window length in seconds")
    stream.add_argument("--lookahead", type=int, default=0,
                        help="bounded lookahead: prepare this many windows ahead, then wait for "
                             "a credit line on stdin (0 = unbounded, prepare flat-out)")
    stream.add_argument("--json", action="store_true", help="emit newline-delimited JSON events")
    stream.add_argument("--verbosity", choices=sorted(VERBOSITY_LEVELS), default=None,
                        help="AD detail level (overrides vl.verbosity)")
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = build_parser().parse_args(argv)
    if args.command == "stream":
        return _stream(args)
    if not args.demo and not args.video:
        print("error: provide --video PATH or --demo", file=sys.stderr)
        return 2
    return _run(args)


if __name__ == "__main__":
    raise SystemExit(main())
