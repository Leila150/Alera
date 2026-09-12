"""Storage analysis utilities."""
from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path


class StorageAnalyzer:
    """Analyze workspace usage, duplicates, and cleanup candidates."""

    def __init__(self, base_path: str | Path = "") -> None:
        self.base_path = (Path(base_path).expanduser() if str(base_path) else Path.cwd()).resolve()
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _visible(self, path: Path, include_hidden: bool) -> bool:
        if include_hidden:
            return True
        return not any(part.startswith(".") for part in path.relative_to(self.base_path).parts)

    def files(self, include_hidden: bool = False) -> list[Path]:
        return [p for p in self.base_path.rglob("*") if p.is_file() and self._visible(p, include_hidden)]

    def total_size(self, include_hidden: bool = False) -> int:
        return sum(self._size(p) for p in self.files(include_hidden))

    @staticmethod
    def _size(path: Path) -> int:
        try:
            return path.stat().st_size
        except OSError:
            return 0

    @staticmethod
    def _hash(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def largest(self, count: int = 20, include_hidden: bool = False) -> list[tuple[Path, int]]:
        if count < 0:
            raise ValueError("count cannot be negative")
        return sorted(((p, self._size(p)) for p in self.files(include_hidden)), key=lambda item: item[1], reverse=True)[:count]

    def extension_statistics(self, include_hidden: bool = False) -> dict[str, dict[str, int]]:
        result: dict[str, dict[str, int]] = {}
        for path in self.files(include_hidden):
            ext = path.suffix.lower() or "<none>"
            bucket = result.setdefault(ext, {"files": 0, "bytes": 0})
            bucket["files"] += 1
            bucket["bytes"] += self._size(path)
        return result

    def empty_files(self, include_hidden: bool = False) -> list[Path]:
        return [p for p in self.files(include_hidden) if self._size(p) == 0]

    def empty_directories(self, include_hidden: bool = False) -> list[Path]:
        return [p for p in self.base_path.rglob("*") if p.is_dir() and self._visible(p, include_hidden) and not any(p.iterdir())]

    def old_files(self, days: float, include_hidden: bool = False) -> list[Path]:
        if days < 0:
            raise ValueError("days cannot be negative")
        cutoff = time.time() - days * 86400
        return [p for p in self.files(include_hidden) if p.stat().st_mtime < cutoff]

    def duplicates(self, include_hidden: bool = False) -> list[list[Path]]:
        groups: dict[tuple[int, str], list[Path]] = {}
        for path in self.files(include_hidden):
            try:
                groups.setdefault((path.stat().st_size, self._hash(path)), []).append(path)
            except OSError:
                continue
        return [items for items in groups.values() if len(items) > 1]

    def cleanup_empty_directories(self, include_hidden: bool = False) -> list[Path]:
        removed: list[Path] = []
        for path in sorted(self.empty_directories(include_hidden), key=lambda p: len(p.parts), reverse=True):
            try:
                path.rmdir()
                removed.append(path)
            except OSError:
                pass
        return removed

    def filesystem_usage(self) -> dict[str, int]:
        usage = os.statvfs(self.base_path)
        total = usage.f_frsize * usage.f_blocks
        free = usage.f_frsize * usage.f_bavail
        return {"total": total, "free": free, "used": max(0, total - free)}
