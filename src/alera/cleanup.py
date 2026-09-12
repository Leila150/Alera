"""Configurable cleanup with explicit category controls and preview mode."""

from __future__ import annotations

import hashlib
import time
from pathlib import Path


class CleanupManager:
    CATEGORIES = ("temporary", "empty_files", "empty_directories", "duplicates", "old_files", "broken_links")

    def __init__(self, base_path: str | Path = "", **configuration: bool) -> None:
        self.base = Path(base_path or ".").expanduser().resolve()
        self.configuration = {category: False for category in self.CATEGORIES}
        self.old_days = 30
        self.configure(**configuration)

    def configure(self, **values: bool) -> dict[str, bool]:
        unknown = set(values) - set(self.CATEGORIES)
        if unknown: raise ValueError(f"Unknown cleanup categories: {sorted(unknown)}")
        for key, value in values.items(): self.configuration[key] = bool(value)
        return self.configuration.copy()

    def set_old_days(self, days: int) -> int:
        if days < 0: raise ValueError("days cannot be negative")
        self.old_days = int(days)
        return self.old_days

    def reset_configuration(self) -> dict[str, bool]:
        return self.configure(**{key: False for key in self.CATEGORIES})

    def _files(self) -> list[Path]:
        return [p for p in self.base.rglob("*") if p.is_file() and ".alera_" not in p.parts]

    @staticmethod
    def _hash(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""): digest.update(chunk)
        return digest.hexdigest()

    def scan(self) -> dict[str, list[str]]:
        result = {category: [] for category in self.CATEGORIES}
        files = self._files()
        if self.configuration["empty_files"]: result["empty_files"] = [str(p) for p in files if p.stat().st_size == 0]
        if self.configuration["empty_directories"]: result["empty_directories"] = [str(p) for p in self.base.rglob("*") if p.is_dir() and not any(p.iterdir()) and ".alera_" not in p.parts]
        if self.configuration["temporary"]: result["temporary"] = [str(p) for p in files if p.suffix.lower() in {".tmp", ".temp", ".cache", ".bak"}]
        if self.configuration["old_files"]:
            cutoff = time.time() - self.old_days * 86400
            result["old_files"] = [str(p) for p in files if p.stat().st_mtime < cutoff]
        if self.configuration["broken_links"]: result["broken_links"] = [str(p) for p in self.base.rglob("*") if p.is_symlink() and not p.exists()]
        if self.configuration["duplicates"]:
            groups: dict[tuple[int, str], list[Path]] = {}
            for path in files: groups.setdefault((path.stat().st_size, self._hash(path)), []).append(path)
            result["duplicates"] = [str(path) for group in groups.values() if len(group) > 1 for path in group[1:]]
        return result

    def preview(self) -> dict[str, list[str]]:
        return self.scan()

    def clean(self) -> dict[str, list[str]]:
        found = self.scan()
        for category, paths in found.items():
            if not self.configuration[category]: continue
            for raw in paths:
                path = Path(raw)
                try:
                    if category == "empty_directories": path.rmdir()
                    elif path.is_symlink() or path.is_file(): path.unlink(missing_ok=True)
                except OSError:
                    continue
        return found
