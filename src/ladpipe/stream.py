"""ChunkedStreamingOrchestrator — prepare a lecture in windows so playback can begin
after the first window instead of after the whole lecture (§12).

It reuses every backend unchanged. A *window source* decides how the video is split:
- ``_SliceSource`` (real): ffmpeg-slices the video and runs preprocess per window, so the
  FIRST window is ready in ~one window's worth of work — the streaming win.
- ``_PartitionSource``: runs preprocess once then splits by time (mock path / fallback).

VL and TTS are built once and kept warm across windows. The hard 5 s rung cap (§7) bounds
how far an AD line can move, which is what makes per-window processing safe. Per-window
artifacts carry GLOBAL timestamps so the player overlays them on the original video.
"""

from __future__ import annotations

import dataclasses
import json
import math
import subprocess
import tempfile
from array import array
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from . import audio, captions, mixer, prefilter, rungs
from .cache import compute_key
from .config import Config, total_ram_gb
from .factory import build_preprocessor, build_tts, build_vl
from .preprocess.local import media_bin
from .tts.base import TTSBackend
from .types import AudioClip, Moment, Placement, ProgressSink, TranscriptSegment
from .vl.base import VLBackend

STREAM_MANIFEST_SCHEMA = "ladpipe-stream-manifest/1"
# Trailing silence appended to each extended-AD (rung 0) clip so the player, which stops
# playback on the clip's duration, doesn't cut the last words to audio-start latency.
_EXT_TAIL_S = 0.4
# Below this much RAM, load VL and TTS per window (sequential, §6.2) instead of keeping
# both warm across windows — three resident MLX models overflow the 8 GB GPU.
_WARM_MODELS_MIN_RAM_GB = 14.0


class Pacer(Protocol):
    """Bounded-lookahead gate. ``wait(index)`` blocks until window ``index`` is allowed to
    be prepared — so the engine stays only a few windows ahead of the playhead instead of
    racing through the whole lecture and pinning the GPU during playback."""

    def wait(self, index: int) -> None: ...


@dataclass
class StreamWindow:
    index: int
    t_start: float
    t_end: float
    base: AudioClip  # the window's lecturer audio (internal time 0 == global t_start)
    moments: list[Moment]  # GLOBAL timestamps
    segments: list[TranscriptSegment]  # GLOBAL timestamps (synced lecturer captions)


@dataclass
class WindowResult:
    index: int
    t_start: float
    t_end: float
    audio_path: Path
    captions_path: Path
    descriptions_path: Path
    extended_audio_path: Path | None
    rung_counts: dict[int, int]


class ChunkedStreamingOrchestrator:
    def __init__(self, config: Config, window_s: float = 90.0) -> None:
        self._config = config
        self._window_s = window_s

    def stream(
        self, video_path: Path, progress: ProgressSink, pacer: Pacer | None = None
    ) -> Iterator[WindowResult]:
        cfg = self._config
        key = compute_key(video_path, cfg)
        out_dir = cfg.cache_dir / f"{key}.stream"
        out_dir.mkdir(parents=True, exist_ok=True)

        # Keep VL+TTS warm only when RAM allows; otherwise load each per window so the
        # two ~2-4B MLX models never sit in the GPU together (8 GB OOMs otherwise).
        warm = total_ram_gb() >= _WARM_MODELS_MIN_RAM_GB
        vl = build_vl(cfg) if warm else None
        tts = build_tts(cfg) if warm else None
        rules = cfg.rules_file.read_text() if cfg.rules_file else ""

        windows_meta: list[dict[str, object]] = []
        # Replay windows a previous run with the same key already finished (sidecar
        # restarts, e.g. the app switching AD verbosity back to a level it used before).
        # Replayed windows don't consume pacer credits — they cost no GPU work, and
        # burning the lookahead on them would stall the resume before any live window.
        replayed = self._replay_cached(out_dir, key)
        for result in replayed:
            windows_meta.append(_window_dict(result))
            progress.progress("window", 0.0, f"Window {result.index} ready (cached)")
            yield result

        start = len(replayed)
        source = self._source().windows(video_path, self._window_s, progress, start_index=start)
        index = start
        while True:
            if pacer is not None:
                pacer.wait(index)  # bounded lookahead: don't run ahead of the playhead
            try:
                window = next(source)  # pulling a window runs its (sliced) preprocess
            except StopIteration:
                break
            result = self._process_window(window, out_dir, key, vl, tts, rules)
            windows_meta.append(_window_dict(result))
            self._write_manifest(out_dir, key, windows_meta)
            progress.progress("window", 0.0, f"Window {window.index} ready")
            yield result
            index += 1

    def _replay_cached(self, out_dir: Path, key: str) -> list[WindowResult]:
        """The longest 0..n consecutive prefix of already-finished windows on disk."""
        manifest_path = out_dir / "stream.json"
        if not manifest_path.exists():
            return []
        try:
            manifest = json.loads(manifest_path.read_text())
        except json.JSONDecodeError:
            return []
        if not isinstance(manifest, dict) or manifest.get("cache_key") != key:
            return []
        results: list[WindowResult] = []
        for i, w in enumerate(manifest.get("windows", [])):
            if not isinstance(w, dict) or w.get("index") != i:
                break  # only a consecutive prefix is safe to replay
            paths = {
                name: out_dir / str(w[name])
                for name in ("audio", "captions", "descriptions")
                if w.get(name)
            }
            ext_name = w.get("extended_audio")
            ext_path = (out_dir / str(ext_name)) if ext_name else None
            required = list(paths.values()) + ([ext_path] if ext_path else [])
            if len(paths) < 3 or not all(p.exists() for p in required):
                break
            results.append(
                WindowResult(
                    index=i,
                    t_start=float(w["t_start"]),
                    t_end=float(w["t_end"]),
                    audio_path=paths["audio"],
                    captions_path=paths["captions"],
                    descriptions_path=paths["descriptions"],
                    extended_audio_path=ext_path,
                    rung_counts={int(k): int(v) for k, v in dict(w["rung_counts"]).items()},
                )
            )
        return results

    def _source(self) -> _WindowSource:
        # Real preprocessing slices the video (first window fast); mock partitions.
        return _SliceSource(self._config) if self._config.backends.preprocess == "local" \
            else _PartitionSource(self._config)

    def _process_window(
        self,
        window: StreamWindow,
        out_dir: Path,
        key: str,
        vl: VLBackend | None,
        tts: TTSBackend | None,
        rules: str,
    ) -> WindowResult:
        cfg = self._config
        ext_on = cfg.extended_ad.enabled
        always = cfg.extended_ad.always_pause

        # --- VL (own it per window when not warm; free before TTS so they never coexist) ---
        active_vl = vl or build_vl(cfg)
        emits: list[tuple[Moment, str]] = []
        for m in window.moments:
            if prefilter.is_redundant(m, cfg.prefilter.redundancy_threshold):
                continue
            decision = active_vl.describe(m, rules)
            if decision.emit and decision.ad_text:
                cap = cfg.vl.effective_max_ad_words
                emits.append((m, rungs.cap_ad_words(decision.ad_text, cap)))
        if vl is None:
            del active_vl
            _free_mlx()

        # MAVP-style post-edit: fuse near-adjacent AD lines. Bookend the opening only —
        # the last window isn't known until the stream ends, after its artifact is written.
        emits = rungs.merge_adjacent(emits, cfg.rungs.merge_gap_s)
        if window.index == 0:
            emits = rungs.bookend(emits, last=False)

        # --- TTS + rungs ---
        active_tts = tts or build_tts(cfg)
        placements: list[Placement] = []
        renders: list[tuple[float, AudioClip]] = []
        extended_clips: list[AudioClip] = []
        for m, ad_text in emits:
            estimate = active_tts.estimate_duration(ad_text)
            provisional = rungs.place(m, estimate, cfg.rungs, ad_text, ext_on, always)
            if provisional.dropped:
                placements.append(provisional)
                continue
            clip = active_tts.synthesize(ad_text)
            placement = rungs.place(m, clip.duration, cfg.rungs, ad_text, ext_on, always)
            if placement.is_extended:
                # Lead with the pause-cue earcon; the placement duration must match the
                # final clip so offsets into the concatenated extended track stay aligned.
                clip = _concat([audio.earcon(clip.sample_rate), clip])
                clip = audio.pad_trailing_silence(clip, _EXT_TAIL_S)
                placement = dataclasses.replace(placement, duration=clip.duration)
                placements.append(placement)
                extended_clips.append(clip)
                continue
            placements.append(placement)
            rendered = self._render(placement, clip)
            if rendered is not None:
                # Mix at window-local time (placements carry global start_time).
                local_start, render_clip = rendered
                renders.append((local_start - window.t_start, render_clip))
        if tts is None:
            del active_tts
            _free_mlx()

        out = mixer.build(window.base, renders)  # window-length, length-matched
        w = out_dir / f"w{window.index:03d}"
        audio.write_wav(out, w.with_suffix(".wav"))
        w.with_suffix(".vtt").write_text(captions.build_webvtt(window.segments, placements))
        w.with_suffix(".desc.vtt").write_text(captions.build_descriptions_webvtt(placements))
        ext_path: Path | None = None
        if extended_clips:
            ext_path = w.with_suffix(".ext.wav")
            audio.write_wav(_concat(extended_clips), ext_path)

        return WindowResult(
            index=window.index,
            t_start=window.t_start,
            t_end=window.t_end,
            audio_path=w.with_suffix(".wav"),
            captions_path=w.with_suffix(".vtt"),
            descriptions_path=w.with_suffix(".desc.vtt"),
            extended_audio_path=ext_path,
            rung_counts=_rung_counts(placements),
        )

    def _render(self, placement: Placement, clip: AudioClip) -> tuple[float, AudioClip] | None:
        cfg = self._config
        if placement.rung in (1, 3):
            return placement.start_time, clip
        if placement.rung == 2:
            n = round(placement.duration * clip.sample_rate)
            return placement.start_time, audio.resample_to_length(clip, n)
        if placement.rung == 4:
            marker = audio.tone(cfg.rungs.placeholder_marker_s, cfg.tts.sample_rate, freq=880.0)
            return placement.start_time, marker
        return None

    def _write_manifest(self, out_dir: Path, key: str, windows: list[dict[str, object]]) -> None:
        manifest = {
            "schema": STREAM_MANIFEST_SCHEMA,
            "pipeline_version": self._config.pipeline_version,
            "cache_key": key,
            "backend_ids": self._config.backend_ids,
            "window_s": self._window_s,
            "windows": windows,  # grows as each window completes
        }
        (out_dir / "stream.json").write_text(json.dumps(manifest, indent=2))


# --------------------------------------------------------------------------- #
# Window sources                                                              #
# --------------------------------------------------------------------------- #
class _WindowSource:
    def windows(
        self, video: Path, window_s: float, progress: ProgressSink, start_index: int = 0
    ) -> Iterator[StreamWindow]:
        raise NotImplementedError


class _PartitionSource(_WindowSource):
    """Run preprocess once, then split base audio + moments by time window."""

    def __init__(self, config: Config) -> None:
        self._config = config

    def windows(
        self, video: Path, window_s: float, progress: ProgressSink, start_index: int = 0
    ) -> Iterator[StreamWindow]:
        base, moments, segments = build_preprocessor(self._config).run(video, progress)
        sr = base.sample_rate
        total = base.duration
        n = max(1, math.ceil(total / window_s))
        for w in range(start_index, n):
            t0 = w * window_s
            t1 = min((w + 1) * window_s, total)
            clip = AudioClip(array("f", base.samples[int(t0 * sr): int(t1 * sr)]), sr)
            wmoments = [m for m in moments if t0 <= m.t_start < t1]
            wsegments = [s for s in segments if t0 <= s.start < t1]
            yield StreamWindow(w, t0, t1, clip, wmoments, wsegments)


class _SliceSource(_WindowSource):
    """ffmpeg-slice the video per window and preprocess each slice (first window fast)."""

    def __init__(self, config: Config) -> None:
        self._config = config

    def windows(
        self, video: Path, window_s: float, progress: ProgressSink, start_index: int = 0
    ) -> Iterator[StreamWindow]:
        duration = _probe_duration(video)
        # A sub-second tail must not spawn a degenerate (empty) trailing window.
        n = max(1, math.ceil((duration - 1.0) / window_s))
        pp = build_preprocessor(self._config)
        work = Path(tempfile.mkdtemp(prefix="ladpipe_stream_"))
        for w in range(start_index, n):
            t0 = w * window_s
            if t0 >= duration:
                break
            seg_file = work / f"w{w:03d}.mp4"
            # Window 0 starts at the first keyframe (t=0), so a fast stream-copy is exact.
            # Later windows MUST be cut accurately: `-c copy` can only start at a keyframe
            # at/before t0, and lecture videos have sparse keyframes (static slides), so a
            # copy begins seconds early — then adding t0 to slice-relative timestamps places
            # every moment/caption at the wrong global time. Re-encoding (fast `-ss` seek +
            # decode-trim to exactly t0) makes the slice start precisely at t0.
            if w == 0:
                cut = ["-ss", "0", "-t", str(window_s), "-i", str(video), "-c", "copy"]
            else:
                cut = ["-ss", str(t0), "-i", str(video), "-t", str(window_s),
                       "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac"]
            subprocess.run(
                [media_bin("ffmpeg"), "-y", "-loglevel", "error", *cut, str(seg_file)],
                check=True, capture_output=True,
            )
            base, moments, segments = pp.run(seg_file, progress)
            if base.duration < 1.0:  # degenerate/empty slice — skip
                continue
            # The first frame of every slice is extracted as a keyframe, but it is never a real
            # slide *change*: in window 0 it's the opening frame (with always-pause the player
            # would pause and describe it the instant playback starts — jarring), and in later
            # windows it's the window boundary (a continuation of the current slide). Drop it so
            # AD only fires on genuine slide transitions.
            moments = [m for m in moments if m.t_start >= 1.0]
            gmoments = [
                dataclasses.replace(m, t_start=m.t_start + t0, t_end=m.t_end + t0) for m in moments
            ]
            gsegments = [
                dataclasses.replace(s, start=s.start + t0, end=s.end + t0) for s in segments
            ]
            yield StreamWindow(w, t0, t0 + base.duration, base, gmoments, gsegments)


def _probe_duration(video: Path) -> float:
    out = subprocess.run(
        [media_bin("ffprobe"), "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nk=1:nw=1", str(video)],
        check=True, capture_output=True, text=True,
    )
    return float(out.stdout.strip())


def _free_mlx() -> None:
    """Release a just-freed MLX model's GPU buffers before loading the next one."""
    import gc

    gc.collect()
    try:
        import mlx.core as mx

        mx.clear_cache()
    except (ImportError, AttributeError):  # pragma: no cover - environment-dependent
        pass


def _concat(clips: list[AudioClip]) -> AudioClip:
    out = array("f")
    for c in clips:
        out.extend(c.samples)
    return AudioClip(out, clips[0].sample_rate)


def _rung_counts(placements: list[Placement]) -> dict[int, int]:
    from collections import Counter

    counts = Counter(p.rung for p in placements)
    return {r: counts.get(r, 0) for r in range(6)}


def _window_dict(r: WindowResult) -> dict[str, object]:
    return {
        "index": r.index,
        "t_start": r.t_start,
        "t_end": r.t_end,
        "audio": r.audio_path.name,
        "captions": r.captions_path.name,
        "descriptions": r.descriptions_path.name,
        "extended_audio": r.extended_audio_path.name if r.extended_audio_path else None,
        "rung_counts": {str(k): v for k, v in r.rung_counts.items()},
    }
