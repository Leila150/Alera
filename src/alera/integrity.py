"""Filesystem integrity manifests."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path


class IntegrityManager:
    """Create and verify SHA-256 manifests for a workspace."""

    def __init__(self, base_path: str | Path = "") -> None:
        self.base = Path(base_path or ".").expanduser().resolve()
        self.base.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _hash(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def create(self, include_hidden: bool = False) -> dict[str, str]:
        result: dict[str, str] = {}
        for path in self.base.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(self.base)
            if not include_hidden and any(part.startswith(".alera_") for part in relative.parts):
                continue
            try:
                result[str(relative)] = self._hash(path)
            except OSError:
                continue
        return dict(sorted(result.items()))

    def save(self, destination: str | Path = ".alera-integrity.json", include_hidden: bool = False) -> Path:
        target = (self.base / destination).resolve()
        target.relative_to(self.base)
        data = json.dumps({"format": 1, "files": self.create(include_hidden)}, indent=2)
        fd, name = tempfile.mkstemp(prefix=".alera-integrity-", dir=target.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(name, target)
        finally:
            if os.path.exists(name):
                os.unlink(name)
        return target

    def verify(self, manifest: dict | str | Path) -> dict[str, list[str]]:
        if isinstance(manifest, (str, Path)):
            path = (self.base / manifest).resolve()
            path.relative_to(self.base)
            data = json.loads(path.read_text(encoding="utf-8"))
        else:
            data = manifest
        expected = data.get("files", data)
        current = self.create(include_hidden=True)
        expected_keys, actual_keys = set(expected), set(current)
        return {
            "added": sorted(actual_keys - expected_keys),
            "removed": sorted(expected_keys - actual_keys),
            "modified": sorted(key for key in expected_keys & actual_keys if expected[key] != current[key]),
        }
