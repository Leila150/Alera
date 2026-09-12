"""Backup and restore utilities."""
from __future__ import annotations

import hashlib
import json
import shutil
import time
from pathlib import Path
from typing import Any


class BackupManager:
    """Create verified directory backups and restore them."""

    def __init__(self, base_path: str | Path = "") -> None:
        self.base_path = (Path(base_path).expanduser() if str(base_path) else Path.cwd()).resolve()
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _checksum(self, path: Path) -> str:
        h = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()

    def manifest(self, source: str | Path = ".") -> dict[str, Any]:
        root = (self.base_path / source).resolve()
        root.relative_to(self.base_path)
        files = {}
        for p in root.rglob("*"):
            if p.is_file():
                files[str(p.relative_to(root))] = {"size": p.stat().st_size, "sha256": self._checksum(p)}
        return {"created": time.time(), "root": str(root), "files": files}

    def create(self, source: str | Path, destination: str | Path) -> Path:
        source_path = (self.base_path / source).resolve()
        destination_path = (self.base_path / destination).resolve()
        source_path.relative_to(self.base_path)
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        if destination_path.exists():
            shutil.rmtree(destination_path) if destination_path.is_dir() else destination_path.unlink()
        shutil.copytree(source_path, destination_path)
        (destination_path / ".alera-manifest.json").write_text(json.dumps(self.manifest(source), indent=2), encoding="utf-8")
        return destination_path

    def verify(self, backup: str | Path) -> bool:
        root = (self.base_path / backup).resolve()
        manifest_path = root / ".alera-manifest.json"
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        for name, info in data.get("files", {}).items():
            p = root / name
            if not p.is_file() or p.stat().st_size != info["size"] or self._checksum(p) != info["sha256"]:
                return False
        return True

    def restore(self, backup: str | Path, destination: str | Path) -> Path:
        backup_path = (self.base_path / backup).resolve()
        destination_path = (self.base_path / destination).resolve()
        backup_path.relative_to(self.base_path)
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        if destination_path.exists():
            shutil.rmtree(destination_path) if destination_path.is_dir() else destination_path.unlink()
        shutil.copytree(backup_path, destination_path, ignore=shutil.ignore_patterns(".alera-manifest.json"))
        return destination_path
