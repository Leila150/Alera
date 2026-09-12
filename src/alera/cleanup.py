"""Industrial-grade, safe and highly configurable filesystem cleanup."""
from __future__ import annotations

import hashlib
import os
import time
from collections import defaultdict
from pathlib import Path
from typing import Iterable, Iterator


class CleanupManager:
    """Discover, classify, preview and safely remove filesystem cleanup candidates."""

    CATEGORIES = ("temporary", "empty_files", "empty_directories", "duplicates", "old_files", "broken_links", "large_files", "zero_byte_files", "stale_locks", "backup_files", "cache_files", "orphaned_sidecars")
    TEMPORARY_SUFFIXES = {".tmp", ".temp", ".swp", ".part", ".crdownload", ".download", ".partial"}
    BACKUP_SUFFIXES = {".bak", ".old", ".orig", ".backup", ".save", ".sav", ".bkp"}
    CACHE_SUFFIXES = {".cache", ".pyc", ".pyo", ".log.tmp"}
    SIDE_CAR_SUFFIXES = {".meta", ".metadata", ".json.bak", ".tmp"}
    INTERNAL_PREFIX = ".alera_"

    def __init__(self, base_path: str | Path = "", **configuration: bool) -> None:
        self.base = Path(base_path or ".").expanduser().resolve()
        self.base.mkdir(parents=True, exist_ok=True)
        self.configuration = {category: False for category in self.CATEGORIES}
        self.old_days = 30
        self.large_file_bytes = 1_000_000_000
        self.stale_lock_seconds = 86_400
        self.minimum_duplicate_size = 1
        self.max_scan_files: int | None = None
        self.follow_symlinks = False
        self.excluded: set[str] = set()
        self.excluded_suffixes: set[str] = set()
        self.excluded_names: set[str] = set()
        self.configure(**configuration)

    def configure(self, **values: bool) -> dict[str, bool]:
        unknown = set(values) - set(self.CATEGORIES)
        if unknown: raise ValueError(f"Unknown cleanup categories: {sorted(unknown)}")
        for key, value in values.items(): self.configuration[key] = bool(value)
        return self.configuration.copy()

    def configuration_copy(self) -> dict[str, bool]: return self.configuration.copy()

    def set_old_days(self, days: int) -> int:
        if days < 0: raise ValueError("days cannot be negative")
        self.old_days = int(days); return self.old_days

    def set_large_file_size(self, size: int) -> int:
        if size < 0: raise ValueError("size cannot be negative")
        self.large_file_bytes = int(size); return self.large_file_bytes

    def set_stale_lock_age(self, seconds: float) -> float:
        if seconds < 0: raise ValueError("seconds cannot be negative")
        self.stale_lock_seconds = float(seconds); return self.stale_lock_seconds

    def set_duplicate_minimum_size(self, size: int) -> int:
        if size < 0: raise ValueError("size cannot be negative")
        self.minimum_duplicate_size = int(size); return self.minimum_duplicate_size

    def set_scan_limit(self, limit: int | None) -> int | None:
        if limit is not None and limit <= 0: raise ValueError("limit must be positive or None")
        self.max_scan_files = limit; return limit

    def exclude(self, *paths: str | Path) -> set[str]:
        for value in paths:
            target = (self.base / value).resolve(); target.relative_to(self.base); self.excluded.add(str(target))
        return set(self.excluded)

    def exclude_names(self, *names: str) -> set[str]: self.excluded_names.update(names); return set(self.excluded_names)

    def exclude_suffixes(self, *suffixes: str) -> set[str]:
        self.excluded_suffixes.update(s.lower() if s.startswith(".") else f".{s.lower()}" for s in suffixes); return set(self.excluded_suffixes)

    def clear_exclusions(self) -> None: self.excluded.clear(); self.excluded_names.clear(); self.excluded_suffixes.clear()

    def reset_configuration(self) -> dict[str, bool]: return self.configure(**{key: False for key in self.CATEGORIES})

    def _internal(self, path: Path) -> bool:
        try: parts = path.relative_to(self.base).parts
        except ValueError: return True
        return any(part.startswith(self.INTERNAL_PREFIX) for part in parts)

    def _eligible(self, path: Path) -> bool:
        try: path.relative_to(self.base)
        except ValueError: return False
        return path != self.base and not self._internal(path) and str(path) not in self.excluded and path.name not in self.excluded_names and path.suffix.lower() not in self.excluded_suffixes

    def _walk(self) -> Iterator[Path]:
        stack = [self.base]; count = 0
        while stack:
            current = stack.pop()
            try: entries = os.scandir(current)
            except OSError: continue
            with entries:
                for entry in entries:
                    path = Path(entry.path)
                    if not self._eligible(path): continue
                    count += 1
                    if self.max_scan_files is not None and count > self.max_scan_files: return
                    try: is_dir = entry.is_dir(follow_symlinks=self.follow_symlinks)
                    except OSError: continue
                    yield path
                    if is_dir: stack.append(path)

    def _files(self) -> Iterator[Path]:
        for path in self._walk():
            try:
                if path.is_file() and not path.is_symlink(): yield path
            except OSError: pass

    @staticmethod
    def _stat(path: Path):
        try: return path.stat(follow_symlinks=False)
        except OSError: return None

    @staticmethod
    def _hash(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""): digest.update(chunk)
        return digest.hexdigest()

    def _duplicate_candidates(self, files: Iterable[Path]) -> list[str]:
        by_size: dict[int, list[Path]] = defaultdict(list)
        for path in files:
            info = self._stat(path)
            if info and info.st_size >= self.minimum_duplicate_size: by_size[info.st_size].append(path)
        result: list[str] = []
        for group in by_size.values():
            if len(group) < 2: continue
            by_hash: dict[str, list[Path]] = defaultdict(list)
            for path in group:
                try: by_hash[self._hash(path)].append(path)
                except OSError: pass
            for matches in by_hash.values():
                if len(matches) > 1: result.extend(str(path) for path in sorted(matches)[1:])
        return result

    @staticmethod
    def _is_empty_dir(path: Path) -> bool:
        try: return not any(path.iterdir())
        except OSError: return False

    def scan(self) -> dict[str, list[str]]:
        result = {category: [] for category in self.CATEGORIES}
        files = list(self._files()); now = time.time(); cutoff = now - self.old_days * 86_400; stale_cutoff = now - self.stale_lock_seconds
        directories: list[Path] = []; links: list[Path] = []
        for path in self._walk():
            try:
                if path.is_symlink(): links.append(path)
                elif path.is_dir(): directories.append(path)
            except OSError: pass
        empty = [str(p) for p in files if (self._stat(p) and self._stat(p).st_size == 0)]
        if self.configuration["empty_files"]: result["empty_files"] = empty
        if self.configuration["zero_byte_files"]: result["zero_byte_files"] = empty
        if self.configuration["empty_directories"]: result["empty_directories"] = [str(p) for p in directories if self._is_empty_dir(p)]
        if self.configuration["temporary"]: result["temporary"] = [str(p) for p in files if p.suffix.lower() in self.TEMPORARY_SUFFIXES]
        if self.configuration["backup_files"]: result["backup_files"] = [str(p) for p in files if p.suffix.lower() in self.BACKUP_SUFFIXES]
        if self.configuration["cache_files"]: result["cache_files"] = [str(p) for p in files if p.suffix.lower() in self.CACHE_SUFFIXES]
        if self.configuration["old_files"]: result["old_files"] = [str(p) for p in files if (self._stat(p) and self._stat(p).st_mtime < cutoff)]
        if self.configuration["large_files"]: result["large_files"] = [str(p) for p in files if (self._stat(p) and self._stat(p).st_size >= self.large_file_bytes)]
        if self.configuration["broken_links"]: result["broken_links"] = [str(p) for p in links if not p.exists()]
        if self.configuration["stale_locks"]: result["stale_locks"] = [str(p) for p in files if p.name.endswith(".alera.lock") and (self._stat(p) and self._stat(p).st_mtime < stale_cutoff)]
        if self.configuration["duplicates"]: result["duplicates"] = self._duplicate_candidates(files)
        if self.configuration["orphaned_sidecars"]: result["orphaned_sidecars"] = [str(p) for p in files if p.suffix.lower() in self.SIDE_CAR_SUFFIXES and not p.with_suffix("").exists()]
        return result

    def preview(self) -> dict[str, list[str]]: return self.scan()

    def summary(self, found: dict[str, list[str]] | None = None) -> dict[str, object]:
        found = found or self.scan(); unique = {p for paths in found.values() for p in paths}; reclaimable = 0
        for raw in unique:
            info = self._stat(Path(raw))
            if info: reclaimable += info.st_size
        return {"categories": {k: len(v) for k, v in found.items()}, "unique_candidates": len(unique), "reclaimable_bytes": reclaimable}

    def clean(self, dry_run: bool = False, *, stop_on_error: bool = False) -> dict[str, list[str]]:
        found = self.scan()
        if dry_run: return found
        errors: list[str] = []
        for category, paths in found.items():
            if category not in self.configuration or not self.configuration[category]: continue
            for raw in paths:
                path = Path(raw)
                try:
                    if category == "empty_directories": path.rmdir()
                    elif path.is_symlink() or path.is_file(): path.unlink()
                except OSError as exc:
                    errors.append(f"{path}: {exc}")
                    if stop_on_error: raise
        if errors: found["errors"] = errors
        return found

    def delete_candidates(self, paths: Iterable[str | Path], *, dry_run: bool = False) -> list[str]:
        deleted: list[str] = []
        for raw in paths:
            candidate = Path(raw); path = (self.base / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
            if not self._eligible(path): continue
            if dry_run: deleted.append(str(path)); continue
            try:
                if path.is_symlink() or path.is_file(): path.unlink(); deleted.append(str(path))
                elif path.is_dir() and not any(path.iterdir()): path.rmdir(); deleted.append(str(path))
            except OSError: continue
        return deleted

    def statistics(self) -> dict[str, object]: return self.summary(self.scan())
