"""Filesystem safety and best-effort secure deletion utilities."""
from __future__ import annotations

import os
import secrets
from pathlib import Path


class FileSecurity:
    """Provide conservative file-integrity and destructive-operation helpers."""

    def __init__(self, base_path: str | Path = "") -> None:
        self.base_path = (Path(base_path).expanduser() if str(base_path) else Path.cwd()).resolve()
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _path(self, value: str | Path) -> Path:
        p = (self.base_path / value).resolve() if not Path(value).is_absolute() else Path(value).resolve()
        p.relative_to(self.base_path)
        return p

    def random_token(self, length: int = 32) -> str:
        if length < 1:
            raise ValueError("length must be positive")
        return secrets.token_hex((length + 1) // 2)[:length]

    def is_writable(self, value: str | Path) -> bool:
        return os.access(self._path(value), os.W_OK)

    def secure_delete(self, value: str | Path, passes: int = 1) -> Path:
        """Best-effort overwrite then unlink; storage hardware may still retain data."""
        if passes < 1:
            raise ValueError("passes must be positive")
        p = self._path(value)
        if not p.is_file():
            raise IsADirectoryError(p)
        size = p.stat().st_size
        with p.open("r+b", buffering=0) as handle:
            for _ in range(passes):
                handle.seek(0)
                remaining = size
                while remaining:
                    chunk = os.urandom(min(1024 * 1024, remaining))
                    handle.write(chunk)
                    remaining -= len(chunk)
                handle.flush()
                os.fsync(handle.fileno())
        p.unlink()
        return p
