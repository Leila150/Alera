"""Reusable file transformations with bounded-memory operations."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path


class FileUtilities:
    def __init__(self, base_path: str | Path = "") -> None:
        self.base = Path(base_path or ".").expanduser().resolve()
        self.base.mkdir(parents=True, exist_ok=True)

    def _path(self, path: str | Path) -> Path:
        target = (self.base / path).resolve()
        target.relative_to(self.base)
        return target

    def touch(self, path: str | Path) -> Path:
        target = self._path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.touch(exist_ok=True)
        return target

    def truncate(self, path: str | Path, size: int = 0) -> Path:
        if size < 0:
            raise ValueError("size cannot be negative")
        target = self._path(path)
        with target.open("r+b") as handle:
            handle.truncate(size)
        return target

    def swap(self, first: str | Path, second: str | Path) -> None:
        a, b = self._path(first), self._path(second)
        if not a.exists() or not b.exists():
            raise FileNotFoundError("both swap targets must exist")
        fd, name = tempfile.mkstemp(prefix=".alera-swap-", dir=a.parent)
        os.close(fd)
        temporary = Path(name)
        temporary.unlink()
        try:
            a.rename(temporary)
            b.rename(a)
            temporary.rename(b)
        except Exception:
            if temporary.exists() and not a.exists():
                temporary.rename(a)
            raise

    def prepend(self, path: str | Path, text: str, encoding: str = "utf-8") -> Path:
        target = self._path(path)
        original = target.read_text(encoding=encoding)
        target.write_text(text + original, encoding=encoding)
        return target

    def replace_bytes(self, path: str | Path, old: bytes, new: bytes) -> int:
        if not old:
            raise ValueError("old bytes cannot be empty")
        target = self._path(path)
        data = target.read_bytes()
        count = data.count(old)
        target.write_bytes(data.replace(old, new))
        return count

    def split(self, path: str | Path, chunk_size: int) -> list[Path]:
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        target = self._path(path)
        result: list[Path] = []
        with target.open("rb") as handle:
            index = 0
            while chunk := handle.read(chunk_size):
                part = target.with_name(f"{target.name}.part{index:04d}")
                part.write_bytes(chunk)
                result.append(part)
                index += 1
        return result

    def join(self, parts: list[str | Path], destination: str | Path) -> Path:
        target = self._path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("wb") as output:
            for part in parts:
                source = self._path(part)
                with source.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        output.write(chunk)
        return target

    def deduplicate_lines(self, path: str | Path, encoding: str = "utf-8") -> int:
        target = self._path(path)
        seen: set[str] = set()
        unique: list[str] = []
        with target.open("r", encoding=encoding) as handle:
            for line in handle:
                if line not in seen:
                    seen.add(line)
                    unique.append(line)
        original_count = sum(1 for _ in target.open("r", encoding=encoding))
        target.write_text("".join(unique), encoding=encoding)
        return original_count - len(unique)

    def convert_encoding(self, path: str | Path, source: str, destination_encoding: str) -> Path:
        target = self._path(path)
        target.write_text(target.read_text(encoding=source), encoding=destination_encoding)
        return target
