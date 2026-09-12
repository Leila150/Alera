"""Content-addressed local file version history."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path


class VersionManager:
    """Keep numbered, checksummed snapshots of files."""

    def __init__(self, base_path: str | Path = "") -> None:
        self.base = Path(base_path or ".").expanduser().resolve()
        self.base.mkdir(parents=True, exist_ok=True)
        self.store = self.base / ".alera_versions"
        self.store.mkdir(parents=True, exist_ok=True)

    def _path(self, path: str | Path) -> Path:
        target = (self.base / path).resolve()
        target.relative_to(self.base)
        if target == self.store or self.store in target.parents:
            raise ValueError("Version storage is internal")
        return target

    def _manifest(self, target: Path) -> Path:
        digest = hashlib.sha256(str(target.relative_to(self.base)).encode("utf-8")).hexdigest()
        return self.store / f"{digest}.json"

    @staticmethod
    def _hash(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _write_json(path: Path, value: object) -> None:
        fd, name = tempfile.mkstemp(prefix=".alera-version-", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(value, handle, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(name, path)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def create(self, path: str | Path) -> int:
        target = self._path(path)
        if not target.is_file():
            raise FileNotFoundError(target)
        manifest = self._manifest(target)
        records = self.list(path)
        number = max((int(item["version"]) for item in records), default=0) + 1
        snapshot = self.store / f"{manifest.stem}-{number}.bin"
        shutil.copy2(target, snapshot)
        records.append({
            "version": number,
            "file": snapshot.name,
            "size": target.stat().st_size,
            "sha256": self._hash(target),
            "created": datetime.now(timezone.utc).isoformat(),
        })
        self._write_json(manifest, records)
        return number

    def list(self, path: str | Path) -> list[dict]:
        manifest = self._manifest(self._path(path))
        if not manifest.exists():
            return []
        data = json.loads(manifest.read_text(encoding="utf-8"))
        return sorted(data, key=lambda item: int(item["version"]))

    def restore(self, path: str | Path, version: int) -> Path:
        target = self._path(path)
        record = next((item for item in self.list(path) if int(item["version"]) == int(version)), None)
        if record is None:
            raise ValueError(f"Unknown version: {version}")
        snapshot = self.store / record["file"]
        if not snapshot.is_file() or self._hash(snapshot) != record["sha256"]:
            raise ValueError("Version snapshot is missing or corrupted")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(snapshot, target)
        return target

    def delete(self, path: str | Path, version: int) -> None:
        target = self._path(path)
        records = self.list(target)
        record = next((item for item in records if int(item["version"]) == int(version)), None)
        if record is None:
            raise ValueError(f"Unknown version: {version}")
        (self.store / record["file"]).unlink(missing_ok=True)
        self._write_json(self._manifest(target), [item for item in records if int(item["version"]) != int(version)])
