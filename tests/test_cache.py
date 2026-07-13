from __future__ import annotations

import dataclasses
from pathlib import Path

from ladpipe.cache import compute_key
from ladpipe.config import Config


def _video(tmp_path: Path) -> Path:
    p = tmp_path / "lecture.bin"
    p.write_bytes(b"some lecture bytes" * 100)
    return p


def test_key_is_stable(mock_config: Config, tmp_path: Path) -> None:
    video = _video(tmp_path)
    assert compute_key(video, mock_config) == compute_key(video, mock_config)


def test_key_changes_with_video_content(mock_config: Config, tmp_path: Path) -> None:
    video = _video(tmp_path)
    key1 = compute_key(video, mock_config)
    video.write_bytes(b"different content" * 100)
    assert compute_key(video, mock_config) != key1


def test_swapping_vl_model_invalidates_cache(mock_config: Config, tmp_path: Path) -> None:
    # Pointing vl.model at the fine-tuned MLX weights must change the key (§6.1/§7).
    video = _video(tmp_path)
    key_base = compute_key(video, mock_config)
    finetuned = dataclasses.replace(
        mock_config, vl=dataclasses.replace(mock_config.vl, model="/models/finetuned-mlx")
    )
    assert compute_key(video, finetuned) != key_base


def test_changing_tunable_invalidates_cache(mock_config: Config, tmp_path: Path) -> None:
    video = _video(tmp_path)
    key_base = compute_key(video, mock_config)
    tweaked = dataclasses.replace(
        mock_config,
        rungs=dataclasses.replace(mock_config.rungs, max_compress_factor=1.5),
    )
    assert compute_key(video, tweaked) != key_base


def test_backend_swap_invalidates_cache(mock_config: Config, tmp_path: Path) -> None:
    from ladpipe.config import Backends

    video = _video(tmp_path)
    key_base = compute_key(video, mock_config)
    real = dataclasses.replace(mock_config, backends=Backends("local", "mlxvlm", "voxtral"))
    assert compute_key(video, real) != key_base
