"""Content-addressed local file version history."""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


class VersionManager:
    def __init__(self, base_path: str | Path = "") -> None:
        self.base = Path(base_path or ".").expanduser().resolve()
        self.store = self.base / ".alera_versions"
        self.store.mkdir(parents=True, exist_ok=True)

    def _path(self, path: str | Path) -> Path:
        target = (self.base / path).resolve()
        target.relative_to(self.base)
        if target == self.store or self.store in target.parents:
            raise ValueError("Version storage is internal")
        return target

    def _manifest(self, target: Path) -> Path:
        digest = hashlib.sha256(str(target.relative_to(self.base)).encode()).hexdigest()
        return self.store / f"{digest}.json"

    def create(self, path: str | Path) -> int:
        target = self._path(path)
        if not target.is_file():
            raise FileNotFoundError(target)
        manifest = self._manifest(target)
        records = json.loads(manifest.read_text()) if manifest.exists() else []
        number = len(records) + 1
        snapshot = self.store / f"{manifest.stem}-{number}.bin"
        shutil.copy2(target, snapshot)
        records.append({"version": number, "file": snapshot.name, "size": target.stat().st_size, "sha256": hashlib.sha256(target.read_bytes()).hexdigest(), "created": datetime.now(timezone.utc).isoformat()})
        manifest.write_text(json.dumps(records, indent=2))
        return number

    def list(self, path: str | Path) -> list[dict]:
        manifest = self._manifest(self._path(path))
        return json.loads(manifest.read_text()) if manifest.exists() else []

    def restore(self, path: str | Path, version: int) -> Path:
        target = self._path(path)
        records = self.list(path)
        record = next((item for item in records if item["version"] == version), None)
        if record is None:
            raise ValueError(f"Unknown version: {version}")
        shutil.copy2(self.store / record["file"], target)
        return target

    def delete(self, path: str | Path, version: int) -> None:
        records = self.list(path)
        record = next((item for item in records if item["version"] == version), None)
        if record is None:
            raise ValueError(f"Unknown version: {version}")
        (self.store / record["file"]).unlink(missing_ok=True)
        remaining = [item for item in records if item["version"] != version]
        self._manifest(self._path(path)).write_text(json.dumps(remaining, indent=2))
