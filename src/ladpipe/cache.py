"""Content-hash + pipeline-version keyed artifact cache (§7).

Key = sha256(video content) + pipeline_version + backend_ids + config_hash.
Swapping base→fine-tuned, or any tunable, changes the key and invalidates stale
artifacts automatically. The cached set per lecture is wav + vtt + manifest.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from .config import Config

_CHUNK = 1 << 20


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def compute_key(video_path: Path, config: Config) -> str:
    h = hashlib.sha256()
    h.update(_hash_file(video_path).encode())
    h.update(config.pipeline_version.encode())
    h.update(json.dumps(config.backend_ids, sort_keys=True).encode())
    h.update(config.config_hash().encode())
    return h.hexdigest()[:32]


@dataclass(frozen=True)
class CachePaths:
    audio: Path
    captions: Path
    descriptions: Path  # extended-AD (rung 0) WebVTT track
    extended_audio: Path  # concatenated rung-0 AD clips (only written when present)
    manifest: Path

    def all_exist(self) -> bool:
        # extended_audio is optional (only present when a lecture has rung-0 moments).
        return (
            self.audio.exists()
            and self.captions.exists()
            and self.descriptions.exists()
            and self.manifest.exists()
        )


class ArtifactCache:
    def __init__(self, cache_dir: Path) -> None:
        self._dir = cache_dir

    def paths(self, key: str) -> CachePaths:
        return CachePaths(
            audio=self._dir / f"{key}.wav",
            captions=self._dir / f"{key}.vtt",
            descriptions=self._dir / f"{key}.desc.vtt",
            extended_audio=self._dir / f"{key}.ext.wav",
            manifest=self._dir / f"{key}.json",
        )

    def is_cached(self, key: str) -> bool:
        return self.paths(key).all_exist()

    def ensure_dir(self) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
