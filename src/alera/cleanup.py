"""Configurable, previewable filesystem cleanup."""
from __future__ import annotations

import hashlib
import time
from pathlib import Path


class CleanupManager:
    """Find cleanup candidates while requiring explicit category opt-in."""

    CATEGORIES = ("temporary", "empty_files", "empty_directories", "duplicates", "old_files", "broken_links")
    TEMPORARY_SUFFIXES = {".tmp", ".temp", ".cache", ".bak", ".old", ".swp", ".part"}

    def __init__(self, base_path: str | Path = "", **configuration: bool) -> None:
        self.base = Path(base_path or ".").expanduser().resolve()
        self.base.mkdir(parents=True, exist_ok=True)
        self.configuration = {category: False for category in self.CATEGORIES}
        self.old_days = 30
        self.excluded: set[str] = set()
        self.configure(**configuration)

    def configure(self, **values: bool) -> dict[str, bool]:
        unknown = set(values) - set(self.CATEGORIES)
        if unknown:
            raise ValueError(f"Unknown cleanup categories: {sorted(unknown)}")
        for key, value in values.items():
            self.configuration[key] = bool(value)
        return self.configuration.copy()

    def configuration_copy(self) -> dict[str, bool]:
        return self.configuration.copy()

    def set_old_days(self, days: int) -> int:
        if days < 0:
            raise ValueError("days cannot be negative")
        self.old_days = int(days)
        return self.old_days

    def exclude(self, *paths: str | Path) -> set[str]:
        for value in paths:
            target = (self.base / value).resolve()
            target.relative_to(self.base)
            self.excluded.add(str(target))
        return set(self.excluded)

    def reset_configuration(self) -> dict[str, bool]:
        return self.configure(**{key: False for key in self.CATEGORIES})

    def _internal(self, path: Path) -> bool:
        return any(part.startswith(".alera_") for part in path.relative_to(self.base).parts)

    def _eligible(self, path: Path) -> bool:
        try:
            path.relative_to(self.base)
        except ValueError:
            return False
        return not self._internal(path) and str(path) not in self.excluded

    def _files(self) -> list[Path]:
        return [path for path in self.base.rglob("*") if path.is_file() and self._eligible(path)]

    @staticmethod
    def _hash(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def scan(self) -> dict[str, list[str]]:
        result = {category: [] for category in self.CATEGORIES}
        files = self._files()
        if self.configuration["empty_files"]:
            result["empty_files"] = [str(path) for path in files if path.stat().st_size == 0]
        if self.configuration["empty_directories"]:
            result["empty_directories"] = [str(path) for path in self.base.rglob("*") if path.is_dir() and self._eligible(path) and not any(path.iterdir())]
        if self.configuration["temporary"]:
            result["temporary"] = [str(path) for path in files if path.suffix.lower() in self.TEMPORARY_SUFFIXES]
        if self.configuration["old_files"]:
            cutoff = time.time() - self.old_days * 86400
            result["old_files"] = [str(path) for path in files if path.stat().st_mtime < cutoff]
        if self.configuration["broken_links"]:
            result["broken_links"] = [str(path) for path in self.base.rglob("*") if path.is_symlink() and not path.exists() and self._eligible(path)]
        if self.configuration["duplicates"]:
            groups: dict[tuple[int, str], list[Path]] = {}
            for path in files:
                groups.setdefault((path.stat().st_size, self._hash(path)), []).append(path)
            result["duplicates"] = [str(path) for group in groups.values() if len(group) > 1 for path in group[1:]]
        return result

    def preview(self) -> dict[str, list[str]]:
        return self.scan()

    def clean(self, dry_run: bool = False) -> dict[str, list[str]]:
        found = self.scan()
        if dry_run:
            return found
        for category, paths in found.items():
            if not self.configuration[category]:
                continue
            for raw in paths:
                path = Path(raw)
                try:
                    if category == "empty_directories":
                        path.rmdir()
                    elif path.is_symlink() or path.is_file():
                        path.unlink()
                except OSError:
                    continue
        return found
