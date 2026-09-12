"""Storage analysis and cleanup utilities."""
from __future__ import annotations

import os
import time
from pathlib import Path


class StorageAnalyzer:
    """Analyze workspace usage, duplicates, and cleanup candidates."""

    def __init__(self, base_path: str | Path = "") -> None:
        self.base_path = (Path(base_path).expanduser() if str(base_path) else Path.cwd()).resolve()
        self.base_path.mkdir(parents=True, exist_ok=True)

    def files(self) -> list[Path]:
        return [p for p in self.base_path.rglob("*") if p.is_file()]

    def total_size(self) -> int:
        return sum(self._size(p) for p in self.files())

    @staticmethod
    def _size(path: Path) -> int:
        try:
            return path.stat().st_size
        except OSError:
            return 0

    def largest(self, count: int = 20) -> list[tuple[Path, int]]:
        return sorted(((p, self._size(p)) for p in self.files()), key=lambda x: x[1], reverse=True)[:count]

    def extension_statistics(self) -> dict[str, dict[str, int]]:
        result: dict[str, dict[str, int]] = {}
        for path in self.files():
            ext = path.suffix.lower() or "<none>"
            bucket = result.setdefault(ext, {"files": 0, "bytes": 0})
            bucket["files"] += 1
            bucket["bytes"] += self._size(path)
        return result

    def empty_files(self) -> list[Path]:
        return [p for p in self.files() if self._size(p) == 0]

    def empty_directories(self) -> list[Path]:
        return [p for p in self.base_path.rglob("*") if p.is_dir() and not any(p.iterdir())]

    def old_files(self, days: float) -> list[Path]:
        cutoff = time.time() - days * 86400
        return [p for p in self.files() if p.stat().st_mtime < cutoff]

    def duplicates(self) -> list[list[Path]]:
        groups: dict[tuple[int, str], list[Path]] = {}
        for path in self.files():
            try:
                import hashlib
                h = hashlib.sha256()
                with path.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        h.update(chunk)
                key = (path.stat().st_size, h.hexdigest())
                groups.setdefault(key, []).append(path)
            except OSError:
                continue
        return [items for items in groups.values() if len(items) > 1]

    def cleanup_empty_directories(self) -> list[Path]:
        removed: list[Path] = []
        for path in sorted(self.empty_directories(), key=lambda p: len(p.parts), reverse=True):
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
