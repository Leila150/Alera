"""Verified directory backup and restore utilities."""
from __future__ import annotations

import hashlib
import json
import shutil
import time
from pathlib import Path
from typing import Any


class BackupManager:
    """Create, verify, and restore self-contained directory backups."""

    MANIFEST = ".alera-manifest.json"

    def __init__(self, base_path: str | Path = "") -> None:
        self.base_path = (Path(base_path).expanduser() if str(base_path) else Path.cwd()).resolve()
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _path(self, value: str | Path) -> Path:
        target = (self.base_path / value).resolve()
        target.relative_to(self.base_path)
        return target

    @staticmethod
    def _checksum(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def manifest(self, source: str | Path = ".") -> dict[str, Any]:
        root = self._path(source)
        if not root.is_dir():
            raise NotADirectoryError(root)
        files: dict[str, dict[str, Any]] = {}
        for path in root.rglob("*"):
            if path.is_file() and path.name != self.MANIFEST:
                stat = path.stat()
                files[str(path.relative_to(root))] = {"size": stat.st_size, "sha256": self._checksum(path)}
        return {"format": 2, "created": time.time(), "root": str(root), "files": files}

    def create(self, source: str | Path, destination: str | Path) -> Path:
        source_path = self._path(source)
        destination_path = self._path(destination)
        if not source_path.is_dir():
            raise NotADirectoryError(source_path)
        try:
            destination_path.relative_to(source_path)
        except ValueError:
            pass
        else:
            raise ValueError("Backup destination cannot be inside the source directory")
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        if destination_path.exists():
            if destination_path.is_dir() and not destination_path.is_symlink():
                shutil.rmtree(destination_path)
            else:
                destination_path.unlink()
        shutil.copytree(source_path, destination_path)
        data = self.manifest(source_path)
        (destination_path / self.MANIFEST).write_text(json.dumps(data, indent=2), encoding="utf-8")
        return destination_path

    def verify(self, backup: str | Path) -> bool:
        root = self._path(backup)
        manifest_path = root / self.MANIFEST
        if not manifest_path.is_file():
            return False
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        expected = data.get("files", {})
        actual = {}
        for path in root.rglob("*"):
            if path.is_file() and path.name != self.MANIFEST:
                actual[str(path.relative_to(root))] = {"size": path.stat().st_size, "sha256": self._checksum(path)}
        return actual == expected

    def restore(self, backup: str | Path, destination: str | Path) -> Path:
        backup_path = self._path(backup)
        destination_path = self._path(destination)
        if not (backup_path / self.MANIFEST).is_file():
            raise ValueError("Not an Alera backup")
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        if destination_path.exists():
            if destination_path.is_dir() and not destination_path.is_symlink():
                shutil.rmtree(destination_path)
            else:
                destination_path.unlink()
        shutil.copytree(backup_path, destination_path, ignore=shutil.ignore_patterns(self.MANIFEST))
        if not self.verify(destination_path):
            raise IOError("Restored backup failed verification")
        return destination_path
