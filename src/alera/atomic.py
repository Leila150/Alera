"""Atomic and streaming file operations for Alera."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import BinaryIO, Iterable, Iterator, TextIO

from .exceptions import AleraPathError, AleraValidationError


class AtomicFiles:
    """Perform safer replacement and streaming operations inside a workspace."""

    def __init__(self, base_path: str | os.PathLike[str] = "") -> None:
        raw = Path(base_path).expanduser() if str(base_path) else Path.cwd()
        self.base_path = raw.resolve()
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _path(self, value: str | os.PathLike[str]) -> Path:
        candidate = Path(value)
        target = (self.base_path / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
        try:
            target.relative_to(self.base_path)
        except ValueError as exc:
            raise AleraPathError(f"Path escapes atomic workspace: {value}") from exc
        return target

    def write_text(self, file: str | os.PathLike[str], contents: str, *, encoding: str = "utf-8") -> Path:
        """Atomically replace a text file."""
        if not isinstance(contents, str):
            raise AleraValidationError("contents must be a string.")
        target = self._path(file)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
        try:
            with os.fdopen(fd, "w", encoding=encoding, newline="") as handle:
                handle.write(contents)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        except Exception:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            raise
        return target

    def write_bytes(self, file: str | os.PathLike[str], contents: bytes | bytearray | memoryview) -> Path:
        """Atomically replace a binary file."""
        if not isinstance(contents, (bytes, bytearray, memoryview)):
            raise AleraValidationError("contents must be bytes-like.")
        target = self._path(file)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(bytes(contents))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        except Exception:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            raise
        return target

    def read_chunks(self, file: str | os.PathLike[str], *, chunk_size: int = 1024 * 1024) -> Iterator[bytes]:
        """Stream a binary file in bounded chunks."""
        if chunk_size <= 0:
            raise AleraValidationError("chunk_size must be greater than zero.")
        target = self._path(file)
        if not target.is_file():
            raise FileNotFoundError(target)
        with target.open("rb") as handle:
            while chunk := handle.read(chunk_size):
                yield chunk

    def copy_stream(self, source: str | os.PathLike[str], destination: str | os.PathLike[str], *, chunk_size: int = 1024 * 1024) -> Path:
        """Stream-copy one file to another without loading it all into RAM."""
        target = self._path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        with self._path(source).open("rb") as source_handle, target.open("wb") as destination_handle:
            for chunk in iter(lambda: source_handle.read(chunk_size), b""):
                destination_handle.write(chunk)
        return target
