"""End-to-end mock-path orchestration (the Phase 1 gate, in test form).

Runs with no GPU and no network. The mock backends are interchangeable with the
real ones (§4 L), so passing here exercises the same orchestration the real path
will use.
"""

from __future__ import annotations

from pathlib import Path

from ladpipe import audio
from ladpipe.config import Config
from ladpipe.orchestrator import PrepareThenCacheOrchestrator
from ladpipe.types import NullProgress


def _video(tmp_path: Path) -> Path:
    p = tmp_path / "lecture.bin"
    p.write_bytes(b"ladpipe-demo-lecture-v1\n" * 256)
    return p


def test_end_to_end_produces_length_matched_artifacts(mock_config: Config, tmp_path: Path) -> None:
    result = PrepareThenCacheOrchestrator(mock_config).prepare(_video(tmp_path), NullProgress())

    assert result.audio_path.exists() and result.captions_path.exists()
    assert result.descriptions_path.exists() and result.manifest_path.exists()
    assert not result.cache_hit

    # The audio track is length-matched to the synthetic base track by construction
    # (rung-0 pauses live in the descriptions track, not the audio track).
    clip = audio.read_wav(result.audio_path)
    assert abs(clip.duration - result.duration) < 0.05


def test_rung_spread_covers_all_six_plus_suppression(mock_config: Config, tmp_path: Path) -> None:
    result = PrepareThenCacheOrchestrator(mock_config).prepare(_video(tmp_path), NullProgress())
    # The synthetic moments are tuned to exercise every rung 0-5 and both suppress paths.
    for rung in range(6):
        assert result.rung_counts[rung] >= 1, f"rung {rung} not exercised"
    assert len(result.suppressed_moment_ids) == 2  # one pre-filter, one VL-level


def test_captions_contain_lecturer_and_ad_cues(mock_config: Config, tmp_path: Path) -> None:
    result = PrepareThenCacheOrchestrator(mock_config).prepare(_video(tmp_path), NullProgress())
    vtt = result.captions_path.read_text()
    assert vtt.startswith("WEBVTT")
    assert "L1" in vtt  # lecturer cue
    assert "<c.ad>AD:" in vtt  # AD cue, distinctly marked


def test_descriptions_track_holds_extended_ad(mock_config: Config, tmp_path: Path) -> None:
    result = PrepareThenCacheOrchestrator(mock_config).prepare(_video(tmp_path), NullProgress())
    desc = result.descriptions_path.read_text()
    assert desc.startswith("WEBVTT")
    assert "DESC1" in desc and "<c.ad-extended>" in desc  # a rung-0 extended-AD cue
    # the extended-AD audio clips are bundled for the player
    assert mock_config.cache_dir.glob("*.ext.wav")


def test_extended_ad_off_produces_no_descriptions(mock_config: Config, tmp_path: Path) -> None:
    import dataclasses

    from ladpipe.config import ExtendedADConfig

    cfg = dataclasses.replace(mock_config, extended_ad=ExtendedADConfig(enabled=False))
    result = PrepareThenCacheOrchestrator(cfg).prepare(_video(tmp_path), NullProgress())
    assert result.rung_counts[0] == 0  # no extended AD when disabled
    assert "DESC1" not in result.descriptions_path.read_text()


def test_extended_clip_leads_with_earcon(mock_config: Config, tmp_path: Path) -> None:
    PrepareThenCacheOrchestrator(mock_config).prepare(_video(tmp_path), NullProgress())
    ext = next(iter(mock_config.cache_dir.glob("*.ext.wav")))
    clip = audio.read_wav(ext)
    # one rung-0 moment: earcon (~0.26s) + 1.8s mock TTS + 0.4s tail
    assert 2.3 < clip.duration < 2.7
    # the earcon is audible at the very start (not silence)
    head = clip.samples[: clip.sample_rate // 20]  # first 50ms
    assert max(abs(s) for s in head) > 0.1


def test_first_and_last_descriptions_are_bookended(mock_config: Config, tmp_path: Path) -> None:
    result = PrepareThenCacheOrchestrator(mock_config).prepare(_video(tmp_path), NullProgress())
    texts = [p.ad_text for p in result.placements if p.ad_text]
    assert texts[0].startswith("Audio description begins.")
    assert texts[-1].endswith("That was the final description.")


def test_second_run_is_a_cache_hit(mock_config: Config, tmp_path: Path) -> None:
    video = _video(tmp_path)
    orch = PrepareThenCacheOrchestrator(mock_config)
    first = orch.prepare(video, NullProgress())
    second = orch.prepare(video, NullProgress())
    assert not first.cache_hit and second.cache_hit
    assert second.rung_counts == first.rung_counts
    assert second.audio_path == first.audio_path


def test_progress_is_reported(mock_config: Config, tmp_path: Path) -> None:
    sink = NullProgress()
    PrepareThenCacheOrchestrator(mock_config).prepare(_video(tmp_path), sink)
    stages = {s for s, _, _ in sink.events}
    assert {"preprocess", "vl", "tts", "done"} <= stages
