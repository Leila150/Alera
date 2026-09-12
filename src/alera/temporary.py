"""Temporary-file and temporary-directory utilities for Alera."""

from __future__ import annotations

import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import BinaryIO, TextIO

from .exceptions import AleraPathError, AleraValidationError


class TemporaryFiles:
    """Manage isolated temporary files and directories inside an Alera workspace."""

    def __init__(self, base_path: str | os.PathLike[str] = "") -> None:
        raw = Path(base_path).expanduser() if str(base_path) else Path.cwd()
        try:
            self.base_path = raw.resolve()
        except OSError as exc:
            raise AleraPathError(f"Unable to resolve temporary workspace: {raw}") from exc
        self.base_path.mkdir(parents=True, exist_ok=True)
        self._root = Path(tempfile.mkdtemp(prefix="alera-tmp-", dir=self.base_path))

    @property
    def path(self) -> Path:
        """Return the private temporary workspace."""
        return self._root

    def _check(self, path: str | os.PathLike[str]) -> Path:
        candidate = Path(path)
        target = (self._root / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
        try:
            target.relative_to(self._root)
        except ValueError as exc:
            raise AleraPathError(f"Temporary path escapes workspace: {path}") from exc
        return target

    @staticmethod
    def _bytes(value: bytes | bytearray | memoryview) -> bytes:
        if not isinstance(value, (bytes, bytearray, memoryview)):
            raise AleraValidationError("Binary contents must be bytes-like.")
        return bytes(value)

    def create_file(self, name: str = "", contents: str = "", *, suffix: str = "", prefix: str = "alera-") -> Path:
        """Create a temporary text file and return its path."""
        if not isinstance(contents, str):
            raise AleraValidationError("contents must be a string.")
        if name:
            target = self._check(name)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(contents, encoding="utf-8")
            return target
        fd, raw = tempfile.mkstemp(suffix=suffix, prefix=prefix, dir=self._root)
        os.close(fd)
        target = Path(raw)
        target.write_text(contents, encoding="utf-8")
        return target

    def create_binary_file(self, name: str = "", contents: bytes | bytearray | memoryview = b"", *, suffix: str = "", prefix: str = "alera-") -> Path:
        """Create a temporary binary file without decoding or altering bytes."""
        payload = self._bytes(contents)
        if name:
            target = self._check(name)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
            return target
        fd, raw = tempfile.mkstemp(suffix=suffix, prefix=prefix, dir=self._root)
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
        return Path(raw)

    def create_directory(self, name: str = "", *, prefix: str = "alera-") -> Path:
        """Create a temporary directory."""
        if name:
            target = self._check(name)
            target.mkdir(parents=True, exist_ok=False)
            return target
        return Path(tempfile.mkdtemp(prefix=prefix, dir=self._root))

    def open_text(self, name: str = "", *, mode: str = "w+", encoding: str = "utf-8", suffix: str = "", prefix: str = "alera-") -> TextIO:
        """Open a temporary text file, creating one automatically when name is empty."""
        if name:
            target = self._check(name)
            target.parent.mkdir(parents=True, exist_ok=True)
            return target.open(mode, encoding=encoding, newline="")
        return tempfile.NamedTemporaryFile(mode=mode, encoding=encoding, suffix=suffix, prefix=prefix, dir=self._root, delete=False, newline="")

    def open_binary(self, name: str = "", *, mode: str = "w+b", suffix: str = "", prefix: str = "alera-") -> BinaryIO:
        """Open a temporary binary file, creating one automatically when name is empty."""
        if name:
            target = self._check(name)
            target.parent.mkdir(parents=True, exist_ok=True)
            return target.open(mode)
        return tempfile.NamedTemporaryFile(mode=mode, suffix=suffix, prefix=prefix, dir=self._root, delete=False)

    def list(self) -> list[Path]:
        """List all live temporary entries."""
        return sorted(self._root.iterdir(), key=lambda item: item.name.lower())

    def exists(self, name: str | os.PathLike[str]) -> bool:
        return self._check(name).exists()

    def information(self, name: str | os.PathLike[str]) -> dict[str, object]:
        """Return useful metadata for a temporary entry."""
        target = self._check(name)
        info = target.stat()
        return {
            "name": target.name,
            "path": str(target),
            "type": "directory" if target.is_dir() else "file",
            "size": self._size(target),
            "created": info.st_ctime,
            "modified": info.st_mtime,
        }

    def remove(self, name: str | os.PathLike[str]) -> Path:
        """Remove one temporary file or directory."""
        target = self._check(name)
        if not target.exists():
            raise FileNotFoundError(target)
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
        return target

    def cleanup(self) -> None:
        """Remove every temporary entry while keeping the manager usable."""
        for item in list(self._root.iterdir()):
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()

    def close(self) -> None:
        """Destroy the private temporary workspace."""
        if self._root.exists():
            shutil.rmtree(self._root)

    def __enter__(self) -> "TemporaryFiles":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    @staticmethod
    def _size(path: Path) -> int:
        if path.is_file():
            return path.stat().st_size
        return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())

    def age(self, name: str | os.PathLike[str]) -> float:
        """Return the age of a temporary entry in seconds."""
        return max(0.0, time.time() - self._check(name).stat().st_mtime)

    def cleanup_older_than(self, seconds: float) -> list[Path]:
        """Remove temporary entries older than the supplied number of seconds."""
        if seconds < 0:
            raise AleraValidationError("seconds must be zero or greater.")
        removed: list[Path] = []
        for item in list(self._root.iterdir()):
            if self.age(item.name) >= seconds:
                removed.append(self.remove(item.name))
        return removed
