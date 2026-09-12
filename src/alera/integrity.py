"""Filesystem integrity manifests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


class IntegrityManager:
    def __init__(self, base_path: str | Path = "") -> None:
        self.base = Path(base_path or ".").expanduser().resolve()

    @staticmethod
    def _hash(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""): digest.update(chunk)
        return digest.hexdigest()

    def create(self) -> dict[str, str]:
        return {str(path.relative_to(self.base)): self._hash(path) for path in self.base.rglob("*") if path.is_file() and ".alera_" not in path.parts}

    def save(self, destination: str | Path = ".alera-integrity.json") -> Path:
        target = (self.base / destination).resolve()
        target.relative_to(self.base)
        target.write_text(json.dumps(self.create(), indent=2), encoding="utf-8")
        return target

    def verify(self, manifest: dict[str, str] | str | Path) -> dict[str, list[str]]:
        if isinstance(manifest, (str, Path)):
            raw = (self.base / manifest).read_text(encoding="utf-8")
            manifest = json.loads(raw)
        current = self.create()
        expected, actual = set(manifest), set(current)
        return {"added": sorted(actual - expected), "removed": sorted(expected - actual), "modified": sorted(k for k in expected & actual if manifest[k] != current[k])}
