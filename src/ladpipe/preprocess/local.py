"""RealPreprocessor — ffmpeg + Whisper + Silero VAD + scene keyframes + Apple Vision OCR.

Design: all timing/assembly logic is pure module-level functions (unit-tested with
no heavy deps). The class methods do the heavy I/O and lazy-import their libraries
(whisper, silero_vad, imagehash/PIL, pyobjc Vision) — never at module top level, so
importing this module stays cheap. Whisper runs concurrently with keyframes+OCR so
preprocessing time is max(transcript, vision), not their sum (§7 speed lever).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .. import audio
from ..config import Config
from ..types import AudioClip, Moment, ProgressSink, TranscriptSegment
from . import pointing
from .pointing import Dwell

_NO_BOUNDARY = 1e9  # sentinel offset so the rung ladder never time-shifts to a missing boundary
_PTS_TIME = re.compile(r"pts_time:([0-9.]+)")

# A transcript segment is exactly the shared TranscriptSegment (start/end/text); alias kept
# for the internal pure-logic helpers below.
Segment = TranscriptSegment


# --------------------------------------------------------------------------- #
# Pure logic (no heavy deps) — unit-tested in tests/test_preprocess_logic.py   #
# --------------------------------------------------------------------------- #
def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def dedup_indices(hashes: list[int], max_distance: int) -> list[int]:
    """Keep the first frame and drop any that are perceptually near the last kept."""
    kept: list[int] = []
    last: int | None = None
    for i, h in enumerate(hashes):
        if last is None or hamming(h, last) > max_distance:
            kept.append(i)
            last = h
    return kept


def pause_starting_at(t: float, speech: list[tuple[float, float]], audio_end: float) -> float:
    """Length of silence beginning at ``t`` (0.0 if the lecturer is still speaking)."""
    for s, e in speech:
        if s <= t < e:
            return 0.0
    starts = [s for s, _ in speech if s >= t]
    return (min(starts) if starts else audio_end) - t


def next_segment_end(t: float, segments: list[Segment]) -> float | None:
    """The first sentence boundary strictly after ``t`` (the next segment end)."""
    ends = sorted(s.end for s in segments if s.end > t)
    return ends[0] if ends else None


def last_speech_end_in_span(
    speech: list[tuple[float, float]], a: float, b: float, default: float
) -> float:
    ends = [min(e, b) for s, e in speech if s < b and e > a]
    return max(ends) if ends else default


def transcript_in_span(segments: list[Segment], a: float, b: float) -> str:
    parts = [s.text.strip() for s in segments if s.end >= a and s.start <= b and s.text.strip()]
    return " ".join(parts)


def assemble_moments(
    scene_times: list[float],
    audio_end: float,
    segments: list[Segment],
    speech: list[tuple[float, float]],
    ocr_by_index: dict[int, str],
    keyframe_by_index: dict[int, str | None],
    pad: float,
) -> list[Moment]:
    """Build ordered Moments from extracted primitives. One moment per (deduped) scene."""
    times = sorted(scene_times)
    moments: list[Moment] = []
    for i, start in enumerate(times):
        span_end = times[i + 1] if i + 1 < len(times) else audio_end
        t_end = last_speech_end_in_span(speech, start, span_end, default=start)
        window = transcript_in_span(segments, start - pad, span_end + pad)
        pause_after = pause_starting_at(t_end, speech, audio_end)

        nb = next_segment_end(t_end, segments)
        if nb is None:
            next_off, next_pause = _NO_BOUNDARY, 0.0
        else:
            next_off, next_pause = nb - t_end, pause_starting_at(nb, speech, audio_end)

        moments.append(
            Moment(
                id=f"m{i:03d}",
                t_start=start,
                t_end=t_end,
                keyframe_path=keyframe_by_index.get(i),
                transcript_window=window,
                ocr_text=ocr_by_index.get(i, ""),
                pause_after=pause_after,
                next_boundary_offset=next_off,
                next_boundary_pause=next_pause,
                visual_signal=True,  # every kept keyframe is a scene change
            )
        )
    return moments


def pointing_moments(
    events: list[tuple[int, Dwell]],
    keyframes: list[str],
    slide_times: list[float],
    audio_end: float,
    segments: list[Segment],
    speech: list[tuple[float, float]],
    ocr_by_index: dict[int, str],
) -> list[Moment]:
    """One Moment per cursor dwell. Its span runs from the dwell to the next slide change,
    capped at 8 s, and its transcript is the +/-8 s the model was trained with. It reuses
    the slide's OCR: the slide has not changed, only the cursor has."""
    times = sorted(slide_times)
    out: list[Moment] = []
    for k, ((j, dw), frame) in enumerate(zip(events, keyframes, strict=True)):
        next_slide = next((t for t in times if t > dw.t), audio_end)
        span_end = min(next_slide, dw.t + 8.0)
        t_end = last_speech_end_in_span(speech, dw.t, span_end, default=dw.t)
        nb = next_segment_end(t_end, segments)
        if nb is None:
            next_off, next_pause = _NO_BOUNDARY, 0.0
        else:
            next_off, next_pause = nb - t_end, pause_starting_at(nb, speech, audio_end)
        out.append(
            Moment(
                id=f"p{k:03d}",
                t_start=dw.t,
                t_end=t_end,
                keyframe_path=frame,
                transcript_window=transcript_in_span(segments, dw.t - 8.0, dw.t + 8.0),
                ocr_text=ocr_by_index.get(j, ""),
                pause_after=pause_starting_at(t_end, speech, audio_end),
                next_boundary_offset=next_off,
                next_boundary_pause=next_pause,
                visual_signal=True,
                kind="pointing",
            )
        )
    return out


# --------------------------------------------------------------------------- #
# Heavy I/O — lazy imports inside each method                                  #
# --------------------------------------------------------------------------- #
class RealPreprocessor:
    def __init__(self, config: Config) -> None:
        self._cfg = config

    def run(
        self, video_path: Path, progress: ProgressSink
    ) -> tuple[AudioClip, list[Moment], list[TranscriptSegment]]:
        work = Path(tempfile.mkdtemp(prefix="ladpipe_"))
        sr = self._cfg.tts.sample_rate

        progress.progress("preprocess", 0.05, "Extracting audio")
        wav = work / "audio.wav"
        self._extract_audio(video_path, wav, sr)
        base = audio.read_wav(wav)
        audio_end = base.duration

        # Silero VAD (torch) runs FIRST, single-threaded — torch's first import is not
        # thread-safe, so initialising it here (before the Whisper worker thread starts)
        # avoids the "circular import / torch has no attribute tensor" race.
        progress.progress("preprocess", 0.20, "Detecting pauses")
        speech = self._speech_intervals(base)

        # Whisper (heaviest) then runs while we do keyframes + OCR: time = max, not sum.
        # Whisper is MLX (no torch), so nothing now races torch.
        with ThreadPoolExecutor(max_workers=1) as pool:
            transcript_future = pool.submit(self._transcribe, wav)

            progress.progress("preprocess", 0.45, "Detecting slides")
            scene_times, frames = self._keyframes(video_path, work)
            kept = dedup_indices(
                [self._phash(f) for f in frames], self._cfg.preprocess.keyframe_dedup_max_distance
            )
            kept_times = [scene_times[i] for i in kept]
            # OCR only when the VL backend needs it; Gemma reads slides itself (§6).
            if self._cfg.needs_ocr:
                progress.progress("preprocess", 0.70, "Reading slide text")
                ocr_by_index = {j: self._ocr(frames[i]) for j, i in enumerate(kept)}
            else:
                ocr_by_index = {j: "" for j in range(len(kept))}
            keyframe_by_index: dict[int, str | None] = {
                j: str(frames[i]) for j, i in enumerate(kept)
            }

            # Cursor dwells on each static slide (also overlaps the transcript).
            pointing_events: list[tuple[int, Dwell]] = []
            pointing_frames: list[str] = []
            if self._cfg.preprocess.pointing and kept_times:
                progress.progress("preprocess", 0.80, "Finding pointing gestures")
                intervals = list(zip(kept_times, [*kept_times[1:], audio_end], strict=True))
                pointing_events = pointing.detect(
                    media_bin("ffmpeg"), str(video_path), intervals,
                    min_dwell_s=self._cfg.preprocess.pointing_min_dwell_s,
                    min_gap_s=self._cfg.preprocess.pointing_min_gap_s,
                )
                pdir = work / "pointing"
                pdir.mkdir(exist_ok=True)
                for k, (_, dw) in enumerate(pointing_events):
                    out = pdir / f"p{k:05d}.png"
                    # 0.4 s into the hold: the cursor has settled and is still there.
                    _ffmpeg(["-ss", f"{dw.t + 0.4:.3f}", "-i", str(video_path),
                             "-frames:v", "1", str(out)])
                    pointing.draw_pointer(str(out), dw.x, dw.y)
                    pointing_frames.append(str(out))

            segments = transcript_future.result()

        progress.progress("preprocess", 0.95, "Assembling moments")
        moments = assemble_moments(
            kept_times, audio_end, segments, speech, ocr_by_index, keyframe_by_index,
            pad=self._cfg.preprocess.transcript_pad_s,
        )
        if pointing_events:
            moments = sorted(
                moments + pointing_moments(
                    pointing_events, pointing_frames, kept_times, audio_end,
                    segments, speech, ocr_by_index,
                ),
                key=lambda m: m.t_start,
            )
        progress.progress("preprocess", 1.0, "Preprocessing complete")
        return base, moments, segments

    # -- heavy steps ------------------------------------------------------- #
    def _extract_audio(self, video: Path, out: Path, sample_rate: int) -> None:
        _ffmpeg(["-i", str(video), "-ac", "1", "-ar", str(sample_rate), "-vn", str(out)])

    def _keyframes(self, video: Path, work: Path) -> tuple[list[float], list[Path]]:
        frames_dir = work / "frames"
        frames_dir.mkdir(parents=True, exist_ok=True)
        # The first frame (t=0) is always a keyframe; scene detection finds the rest.
        first = frames_dir / "f00000.png"
        _ffmpeg(["-i", str(video), "-frames:v", "1", str(first)])

        meta = work / "scenes.txt"
        thr = self._cfg.preprocess.scene_threshold
        _ffmpeg([
            "-i", str(video),
            "-vf", f"select='gt(scene,{thr})',metadata=print:file={meta}",
            "-vsync", "vfr", str(frames_dir / "s%05d.png"),
        ])
        scene_times = [0.0]
        if meta.exists():
            scene_times += [float(m) for m in _PTS_TIME.findall(meta.read_text())]
        scene_frames = sorted(frames_dir.glob("s*.png"))
        frames = [first] + scene_frames
        # Guard against an ffmpeg/parse mismatch: align lengths conservatively.
        n = min(len(scene_times), len(frames))
        return scene_times[:n], frames[:n]

    def _phash(self, frame: Path) -> int:
        import imagehash
        from PIL import Image

        return int(str(imagehash.phash(Image.open(frame))), 16)

    def _ocr(self, frame: Path) -> str:
        # Apple Vision: macOS-native, offline, no model download (§7).
        import Quartz
        import Vision
        from Foundation import NSURL

        url = NSURL.fileURLWithPath_(str(frame))
        source = Quartz.CGImageSourceCreateWithURL(url, None)
        image = Quartz.CGImageSourceCreateImageAtIndex(source, 0, None)
        request = Vision.VNRecognizeTextRequest.alloc().init()
        request.setRecognitionLevel_(1)  # accurate
        handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(image, None)
        handler.performRequests_error_([request], None)
        lines = [obs.topCandidates_(1)[0].string() for obs in (request.results() or [])]
        return "\n".join(lines)

    def _transcribe(self, wav: Path) -> list[Segment]:
        model_ref = self._cfg.preprocess.whisper_model
        if self._cfg.preprocess.whisper_backend == "mlx":
            # mlx-whisper runs on the GPU (Apple Silicon) — much faster than CPU openai-whisper.
            # It runs in a CHILD process: once it has run in-process, later mlx-vlm
            # generations degrade to NaN output (see whisper_worker.py). The child also
            # takes whisper's 1.6 GB with it when it exits, before the VL model loads.
            proc = subprocess.run(
                [sys.executable, "-m", "ladpipe.preprocess.whisper_worker", str(wav), model_ref],
                check=True, capture_output=True, text=True,
            )
            result = {"segments": json.loads(proc.stdout)}
        else:
            import whisper

            result = whisper.load_model(model_ref).transcribe(str(wav), word_timestamps=False)
        return [
            Segment(float(s["start"]), float(s["end"]), str(s["text"]).strip())
            for s in result["segments"]
        ]

    def _speech_intervals(self, base: AudioClip) -> list[tuple[float, float]]:
        # Feed Silero our own 16 kHz samples directly, bypassing silero's read_audio
        # (which now needs torchcodec/torchaudio audio I/O we don't depend on).
        import torch
        from silero_vad import get_speech_timestamps, load_silero_vad

        resampled = audio.resample_to_length(base, round(base.duration * 16000))
        tensor = torch.frombuffer(resampled.samples, dtype=torch.float32)
        model = load_silero_vad()
        stamps = get_speech_timestamps(tensor, model, sampling_rate=16000, return_seconds=True)
        return [(float(s["start"]), float(s["end"])) for s in stamps]


_MEDIA_DIRS = ("/opt/homebrew/bin", "/usr/local/bin", "/usr/bin")


def media_bin(name: str) -> str:
    """Resolve ffmpeg/ffprobe to an absolute path. A GUI app launched via LaunchServices
    gets a minimal PATH without Homebrew's /opt/homebrew/bin, so relying on PATH fails.

    ``LADPIPE_MEDIA_DIR`` wins when it is set: the shipped .app points it at its own
    copies, because the machine it lands on may have no ffmpeg installed at all."""
    bundled = os.environ.get("LADPIPE_MEDIA_DIR")
    if bundled:
        candidate = Path(bundled) / name
        if candidate.exists():
            return str(candidate)
    found = shutil.which(name)
    if found:
        return found
    for d in _MEDIA_DIRS:
        candidate = Path(d) / name
        if candidate.exists():
            return str(candidate)
    return name  # let it fail with a clear "not found" if truly absent


def _ffmpeg(args: list[str]) -> None:
    subprocess.run(
        [media_bin("ffmpeg"), "-y", "-loglevel", "error", *args], check=True, capture_output=True
    )
