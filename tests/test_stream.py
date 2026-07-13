"""Streaming orchestration on the mock path (no GPU/network). Proves windows are
produced incrementally with global timestamps and a manifest that grows per window."""

from __future__ import annotations

import json
from pathlib import Path

from ladpipe import audio
from ladpipe.config import Config
from ladpipe.stream import ChunkedStreamingOrchestrator, WindowResult
from ladpipe.types import NullProgress


def _video(tmp_path: Path) -> Path:
    p = tmp_path / "lecture.bin"
    p.write_bytes(b"ladpipe-demo-lecture-v1\n" * 256)
    return p


def _windows(config: Config, tmp_path: Path, window_s: float = 30.0) -> list[WindowResult]:
    orch = ChunkedStreamingOrchestrator(config, window_s=window_s)
    return list(orch.stream(_video(tmp_path), NullProgress()))


def test_stream_produces_multiple_windows(mock_config: Config, tmp_path: Path) -> None:
    windows = _windows(mock_config, tmp_path)
    # The 66 s synthetic timeline splits into 30 s windows -> 3 windows.
    assert len(windows) == 3
    assert [w.index for w in windows] == [0, 1, 2]


def test_each_window_is_length_matched(mock_config: Config, tmp_path: Path) -> None:
    for w in _windows(mock_config, tmp_path):
        assert w.audio_path.exists() and w.captions_path.exists() and w.descriptions_path.exists()
        clip = audio.read_wav(w.audio_path)
        assert abs(clip.duration - (w.t_end - w.t_start)) < 0.05  # window-length-matched


def test_gap_ad_in_first_extended_in_second(mock_config: Config, tmp_path: Path) -> None:
    windows = _windows(mock_config, tmp_path)
    # Window 0 (0-30s) has the rungs 1-3 moments -> spoken AD cues.
    assert "<c.ad>AD:" in windows[0].captions_path.read_text()
    # Window 1 (30-60s) has the high-value non-fitting moment -> extended AD (rung 0).
    assert windows[1].rung_counts[0] >= 1
    assert "<c.ad-extended>" in windows[1].descriptions_path.read_text()
    assert windows[1].extended_audio_path is not None


def test_manifest_grows_incrementally(mock_config: Config, tmp_path: Path) -> None:
    orch = ChunkedStreamingOrchestrator(mock_config, window_s=30.0)
    gen = orch.stream(_video(tmp_path), NullProgress())
    first = next(gen)
    manifest = first.audio_path.parent / "stream.json"
    # After only the first window, the manifest already lists exactly one window —
    # i.e. the player could start now (streaming), not after the whole lecture.
    data = json.loads(manifest.read_text())
    assert len(data["windows"]) == 1 and data["windows"][0]["index"] == 0
    rest = list(gen)
    assert len(json.loads(manifest.read_text())["windows"]) == 1 + len(rest)


def test_pacer_gates_every_window(mock_config: Config, tmp_path: Path) -> None:
    # The pacer is consulted before each window is prepared — this is the bounded-lookahead
    # hook that keeps the engine from racing ahead and pinning the GPU during playback.
    seen: list[int] = []

    class RecordingPacer:
        def wait(self, index: int) -> None:
            seen.append(index)

    orch = ChunkedStreamingOrchestrator(mock_config, window_s=30.0)
    list(orch.stream(_video(tmp_path), NullProgress(), pacer=RecordingPacer()))
    # 3 windows (0,1,2) prepared, plus the gate check before the final StopIteration.
    assert seen == [0, 1, 2, 3]


def test_rungs_spread_across_windows(mock_config: Config, tmp_path: Path) -> None:
    windows = _windows(mock_config, tmp_path)
    total = {r: 0 for r in range(6)}
    for w in windows:
        for r, c in w.rung_counts.items():
            total[r] += c
    # The same six-rung spread the batch path exercises, now split across windows.
    for r in range(6):
        assert total[r] >= 1, f"rung {r} not exercised across windows"


def test_stream_resumes_from_manifest(mock_config: Config, tmp_path: Path) -> None:
    # First run prepares everything; a rerun with the same key must replay the cached
    # windows without reprocessing (this is what makes sidecar restarts near-instant).
    first = _windows(mock_config, tmp_path)
    mtimes = [w.audio_path.stat().st_mtime_ns for w in first]
    second = _windows(mock_config, tmp_path)
    assert [w.index for w in second] == [0, 1, 2]
    assert [w.t_start for w in second] == [w.t_start for w in first]
    assert [w.rung_counts for w in second] == [w.rung_counts for w in first]
    assert [w.audio_path.stat().st_mtime_ns for w in second] == mtimes  # untouched


def test_stream_resumes_partial_cache(mock_config: Config, tmp_path: Path) -> None:
    first = _windows(mock_config, tmp_path)
    # Losing a later window's artifact must regenerate from that window on, keeping
    # the intact prefix cached.
    first[2].audio_path.unlink()
    kept = [w.audio_path.stat().st_mtime_ns for w in first[:2]]
    second = _windows(mock_config, tmp_path)
    assert [w.index for w in second] == [0, 1, 2]
    assert [w.audio_path.stat().st_mtime_ns for w in second[:2]] == kept
    assert second[2].audio_path.exists()


def test_replayed_windows_skip_the_pacer(mock_config: Config, tmp_path: Path) -> None:
    # Replaying cached windows must not consume lookahead credits, or a resume with a
    # bounded pacer would stall before reaching the first live window.
    _windows(mock_config, tmp_path)
    seen: list[int] = []

    class RecordingPacer:
        def wait(self, index: int) -> None:
            seen.append(index)

    orch = ChunkedStreamingOrchestrator(mock_config, window_s=30.0)
    replay = list(orch.stream(_video(tmp_path), NullProgress(), pacer=RecordingPacer()))
    assert len(replay) == 3
    assert seen == [3]  # only the final gate check before StopIteration
