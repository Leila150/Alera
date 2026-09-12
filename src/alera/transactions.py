"""Workspace transactions with rollback support."""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path


class FileTransaction:
    """Stage a workspace backup and restore it automatically on failure."""

    def __init__(self, base_path: str | Path = "") -> None:
        self.base_path = (Path(base_path).expanduser() if str(base_path) else Path.cwd()).resolve()
        self.base_path.mkdir(parents=True, exist_ok=True)
        self._backup: Path | None = None

    def _make_backup(self) -> Path:
        temp = Path(tempfile.mkdtemp(prefix=".alera-tx-"))
        backup = temp / "workspace"
        shutil.copytree(self.base_path, backup, ignore=shutil.ignore_patterns(".alera-tx-*"))
        return temp

    def __enter__(self) -> "FileTransaction":
        self._backup = self._make_backup()
        return self

    def rollback(self) -> None:
        if self._backup is None:
            return
        backup = self._backup / "workspace"
        for item in list(self.base_path.iterdir()):
            if item == self._backup:
                continue
            if item.is_dir() and not item.is_symlink():
                shutil.rmtree(item)
            else:
                item.unlink()
        for item in backup.iterdir():
            target = self.base_path / item.name
            shutil.copytree(item, target) if item.is_dir() else shutil.copy2(item, target)

    def commit(self) -> None:
        self._cleanup()

    def _cleanup(self) -> None:
        if self._backup and self._backup.exists():
            shutil.rmtree(self._backup, ignore_errors=True)
        self._backup = None

    def __exit__(self, exc_type, exc, tb) -> bool:
        try:
            if exc_type is not None:
                self.rollback()
        finally:
            self._cleanup()
        return False
