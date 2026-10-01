"""PrepareThenCacheOrchestrator: sequences stages, reports progress, caches.

It only *sequences* — it implements no stage and cannot tell mock from real
backends (§4 S/L). Pressing play never reaches here: the player consumes a cached
artifact only (§1).

Streaming seam (§12): a future ChunkedStreamingOrchestrator can reuse every
backend unchanged by running this same per-moment sequence over ~60-90s windows
and emitting partial artifacts; the hard 5s rung cap keeps lookahead overlap safe.
Do not implement it here.
"""

from __future__ import annotations

import dataclasses
import json
from array import array
from collections import Counter
from pathlib import Path
from typing import Any

from . import audio, captions, mixer, prefilter, rungs
from .cache import ArtifactCache, CachePaths, compute_key
from .config import Config
from .factory import build_preprocessor, build_tts, build_vl, free_mlx
from .types import AudioClip, Moment, PipelineResult, Placement, ProgressSink

MANIFEST_SCHEMA = "ladpipe-manifest/1"
# Trailing silence appended to each extended-AD (rung 0) clip — a tail buffer so the player,
# which stops playback on the clip's duration, doesn't cut the last words to audio-start latency.
_EXT_TAIL_S = 0.4


class PrepareThenCacheOrchestrator:
    def __init__(self, config: Config) -> None:
        self._config = config
        self._cache = ArtifactCache(config.cache_dir)

    def prepare(self, video_path: Path, progress: ProgressSink) -> PipelineResult:
        key = compute_key(video_path, self._config)
        paths = self._cache.paths(key)

        if paths.all_exist():
            progress.progress("cache", 1.0, "Loaded from cache")
            return self._result_from_manifest(paths.manifest, paths, cache_hit=True)

        self._cache.ensure_dir()
        cfg = self._config

        base, moments, segments = build_preprocessor(cfg).run(video_path, progress)
        # The forced t=0 keyframe is the opening frame, not a slide change (stream.py
        # drops it too): with always-pause it would pause the video the instant playback
        # starts, and merge_adjacent would anchor its line at 0.0.
        moments = [m for m in moments if m.t_start >= 1.0]

        # --- VL stage (load vision, run the per-moment loop, then release) ---
        vl = build_vl(cfg)
        rules = cfg.rules_file.read_text() if cfg.rules_file else ""
        emits: list[tuple[Moment, str]] = []
        suppressed: list[str] = []
        for i, m in enumerate(moments):
            progress.progress("vl", (i + 1) / len(moments), "Describing moments")
            if prefilter.is_redundant(m, cfg.prefilter.redundancy_threshold):
                suppressed.append(m.id)
                continue
            decision = vl.describe(m, rules)
            if decision.emit and decision.ad_text:
                cap = cfg.vl.effective_max_ad_words
                text = rungs.cap_ad_words(decision.ad_text, cap)
                if m.kind == "pointing":
                    text = rungs.pointing_cue(text)
                emits.append((m, text))
            else:
                suppressed.append(m.id)
        del vl  # free vision before loading TTS (§6.2)
        free_mlx()

        # MAVP-style post-edit: fuse near-adjacent AD lines, then bookend the track so a
        # listener hears where the descriptions begin and end.
        emits = rungs.merge_adjacent(emits, cfg.rungs.merge_gap_s)
        emits = rungs.bookend(emits)

        # --- TTS + rung stage (estimate -> gate -> synth -> reconcile, §6/§7) ---
        tts = build_tts(cfg)
        ext_on = cfg.extended_ad.enabled
        always = cfg.extended_ad.always_pause
        placements: list[Placement] = []
        renders: list[tuple[float, AudioClip]] = []  # rungs 1-4 mixed into the base track
        extended_clips: list[AudioClip] = []  # rung 0 clips, played during pauses
        for i, (m, ad_text) in enumerate(emits):
            progress.progress("tts", (i + 1) / max(1, len(emits)), "Synthesising audio description")
            est = tts.estimate_duration(ad_text)
            provisional = rungs.place(m, est, cfg.rungs, ad_text, ext_on, always)
            if provisional.dropped:
                placements.append(provisional)  # obvious drop: never synthesised
                continue
            clip = tts.synthesize(ad_text)
            placement = rungs.place(m, clip.duration, cfg.rungs, ad_text, ext_on, always)
            if placement.is_extended:
                # rung 0: play during a pause, not mixed in. Lead with an earcon (the pause
                # cue) and pad a tail of silence so the player (which stops on the cue
                # duration) doesn't clip the last words; the placement duration must match
                # the final clip to keep the player's offsets into the concatenated
                # extended track aligned.
                clip = _concat([audio.earcon(clip.sample_rate), clip])
                clip = audio.pad_trailing_silence(clip, _EXT_TAIL_S)
                placement = dataclasses.replace(placement, duration=clip.duration)
                placements.append(placement)
                extended_clips.append(clip)
                continue
            placements.append(placement)
            render = self._render(placement, clip, cfg)
            if render is not None:
                renders.append(render)
        del tts

        # --- mix + captions + descriptions ---
        progress.progress("mix", 0.5, "Mixing audio track")
        out = mixer.build(base, renders)  # length-matched (rungs 1-4 only)
        audio.write_wav(out, paths.audio)
        paths.captions.write_text(captions.build_webvtt(segments, placements))
        paths.descriptions.write_text(captions.build_descriptions_webvtt(placements))
        if extended_clips:
            audio.write_wav(_concat(extended_clips), paths.extended_audio)

        rung_counts = _rung_counts(placements)
        self._write_manifest(paths, key, out, placements, rung_counts, suppressed, extended_clips)

        progress.progress("done", 1.0, "Preparation complete")
        return PipelineResult(
            audio_path=paths.audio,
            captions_path=paths.captions,
            descriptions_path=paths.descriptions,
            manifest_path=paths.manifest,
            duration=out.duration,
            placements=placements,
            rung_counts=rung_counts,
            suppressed_moment_ids=suppressed,
            cache_hit=False,
        )

    def _render(
        self, placement: Placement, clip: AudioClip, cfg: Config
    ) -> tuple[float, AudioClip] | None:
        """Turn a placement into a (start_time, clip) render, or None if silent."""
        if placement.rung in (1, 3):
            return placement.start_time, clip
        if placement.rung == 2:
            n = round(placement.duration * clip.sample_rate)
            return placement.start_time, audio.resample_to_length(clip, n)
        if placement.rung == 4:
            marker = audio.tone(cfg.rungs.placeholder_marker_s, cfg.tts.sample_rate, freq=880.0)
            return placement.start_time, marker
        return None  # rung 5 drop

    def _write_manifest(
        self,
        paths: CachePaths,
        key: str,
        out: AudioClip,
        placements: list[Placement],
        rung_counts: dict[int, int],
        suppressed: list[str],
        extended_clips: list[AudioClip],
    ) -> None:
        extended_pause_s = sum(c.duration for c in extended_clips)
        manifest = {
            "schema": MANIFEST_SCHEMA,
            "pipeline_version": self._config.pipeline_version,
            "cache_key": key,
            "backend_ids": self._config.backend_ids,
            "config_hash": self._config.config_hash(),
            "audio": paths.audio.name,
            "captions": paths.captions.name,
            "descriptions": paths.descriptions.name,
            "extended_audio": paths.extended_audio.name if extended_clips else None,
            "duration_s": out.duration,
            # With rung-0 pauses the played timeline is longer than the audio track.
            "played_duration_s": out.duration + extended_pause_s,
            "extended_pause_s": extended_pause_s,
            "sample_rate": out.sample_rate,
            "captions_default_on": self._config.player.captions_default_on,
            "rung_counts": {str(k): v for k, v in rung_counts.items()},
            "suppressed_moment_ids": suppressed,
            "placements": [_placement_dict(pl) for pl in placements],
        }
        paths.manifest.write_text(json.dumps(manifest, indent=2))

    def _result_from_manifest(
        self, manifest_path: Path, paths: CachePaths, cache_hit: bool
    ) -> PipelineResult:
        data = json.loads(manifest_path.read_text())
        placements = [_placement_from_dict(d) for d in data["placements"]]
        rung_counts = {int(k): v for k, v in data["rung_counts"].items()}
        return PipelineResult(
            audio_path=paths.audio,
            captions_path=paths.captions,
            descriptions_path=paths.descriptions,
            manifest_path=paths.manifest,
            duration=float(data["duration_s"]),
            placements=placements,
            rung_counts=rung_counts,
            suppressed_moment_ids=list(data["suppressed_moment_ids"]),
            cache_hit=cache_hit,
        )


def _concat(clips: list[AudioClip]) -> AudioClip:
    out = array("f")
    sr = clips[0].sample_rate
    for c in clips:
        out.extend(c.samples)
    return AudioClip(out, sr)


def _rung_counts(placements: list[Placement]) -> dict[int, int]:
    counts = Counter(p.rung for p in placements)
    return {r: counts.get(r, 0) for r in range(6)}  # rungs 0-5


def _placement_dict(p: Placement) -> dict[str, object]:
    return {
        "moment_id": p.moment_id,
        "rung": p.rung,
        "start_time": p.start_time,
        "duration": p.duration,
        "speed_factor": p.speed_factor,
        "ad_text": p.ad_text,
        "dropped": p.dropped,
    }


def _placement_from_dict(d: dict[str, Any]) -> Placement:
    return Placement(
        moment_id=str(d["moment_id"]),
        rung=int(d["rung"]),
        start_time=float(d["start_time"]),
        duration=float(d["duration"]),
        speed_factor=float(d["speed_factor"]),
        ad_text=None if d["ad_text"] is None else str(d["ad_text"]),
        dropped=bool(d["dropped"]),
    )
