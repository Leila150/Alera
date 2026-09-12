"""High-performance, composable filesystem search engine."""
from __future__ import annotations

import fnmatch
import hashlib
import mimetypes
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Iterable, Iterator, Pattern


class SearchEngine:
    """Streaming, metadata-aware filesystem search with pruning and hashing."""

    INTERNAL = {".alera_bin", ".alera_hidden", ".alera_recovery", ".alera_cache"}

    def __init__(self, base_path: str | Path = "") -> None:
        self.base_path = (Path(base_path).expanduser() if str(base_path) else Path.cwd()).resolve()
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _root(self, path: str | Path = ".") -> Path:
        raw = Path(path).expanduser()
        root = raw.resolve() if raw.is_absolute() else (self.base_path / raw).resolve()
        try:
            root.relative_to(self.base_path)
        except ValueError as exc:
            raise ValueError("Search path must stay inside the Alera workspace") from exc
        return root

    @staticmethod
    def _time(value: float | datetime | None) -> float | None:
        return value.timestamp() if isinstance(value, datetime) else value

    @staticmethod
    def _extensions(value: str | Iterable[str] | None) -> set[str] | None:
        if value is None:
            return None
        values = [value] if isinstance(value, str) else value
        return {e.lower() if str(e).startswith(".") else f".{str(e).lower()}" for e in values}

    def iter_paths(self, path: str | Path = ".", *, recursive: bool = True,
                   include_files: bool = True, include_directories: bool = False,
                   include_hidden: bool = True, follow_symlinks: bool = False,
                   exclude_internal: bool = True) -> Iterator[Path]:
        """Stream entries and prune internal/hidden directories before descending."""
        root = self._root(path)
        if root.is_file():
            if include_files:
                yield root
            return
        if not root.is_dir():
            return
        stack = [root]
        while stack:
            current = stack.pop()
            try:
                entries = list(current.iterdir())
            except OSError:
                continue
            for item in entries:
                try:
                    relative = item.relative_to(self.base_path)
                    hidden = any(part.startswith(".") for part in relative.parts)
                    if exclude_internal and any(part in self.INTERNAL for part in relative.parts):
                        continue
                    if not include_hidden and hidden:
                        continue
                    if item.is_symlink() and not follow_symlinks:
                        continue
                    if item.is_dir():
                        if include_directories:
                            yield item
                        if recursive:
                            stack.append(item)
                    elif item.is_file() and include_files:
                        yield item
                except OSError:
                    continue

    def search(self, pattern: str = "*", *, path: str | Path = ".", recursive: bool = True,
               extension: str | Iterable[str] | None = None, minimum_size: int | None = None,
               maximum_size: int | None = None, modified_after: float | datetime | None = None,
               modified_before: float | datetime | None = None, created_after: float | datetime | None = None,
               created_before: float | datetime | None = None, files_only: bool = True,
               directories_only: bool = False, include_hidden: bool = True,
               follow_symlinks: bool = False, exclude_internal: bool = True,
               limit: int | None = None) -> list[Path]:
        if files_only and directories_only:
            raise ValueError("files_only and directories_only cannot both be true")
        if minimum_size is not None and minimum_size < 0 or maximum_size is not None and maximum_size < 0:
            raise ValueError("file sizes cannot be negative")
        if limit is not None and limit < 0:
            raise ValueError("limit cannot be negative")
        extensions = self._extensions(extension)
        ma, mb = self._time(modified_after), self._time(modified_before)
        ca, cb = self._time(created_after), self._time(created_before)
        result: list[Path] = []
        for item in self.iter_paths(path, recursive=recursive, include_files=not directories_only,
                                    include_directories=not files_only, include_hidden=include_hidden,
                                    follow_symlinks=follow_symlinks, exclude_internal=exclude_internal):
            try:
                if not fnmatch.fnmatchcase(item.name.casefold(), pattern.casefold()):
                    continue
                if extensions is not None and item.suffix.lower() not in extensions:
                    continue
                info = item.stat()
                if minimum_size is not None and info.st_size < minimum_size or maximum_size is not None and info.st_size > maximum_size:
                    continue
                if ma is not None and info.st_mtime < ma or mb is not None and info.st_mtime > mb:
                    continue
                if ca is not None and info.st_ctime < ca or cb is not None and info.st_ctime > cb:
                    continue
                result.append(item)
                if limit is not None and len(result) >= limit:
                    break
            except OSError:
                continue
        return result

    def name(self, query: str, **kwargs: object) -> list[Path]:
        pattern = query if any(c in query for c in "*?[") else f"*{query}*"
        return self.search(pattern, **kwargs)

    def regex(self, pattern: str | Pattern[str], *, path: str | Path = ".", recursive: bool = True,
              include_hidden: bool = True, case_sensitive: bool = False, limit: int | None = None,
              exclude_internal: bool = True) -> list[Path]:
        compiled = pattern if hasattr(pattern, "search") else re.compile(str(pattern), 0 if case_sensitive else re.IGNORECASE)
        result: list[Path] = []
        for p in self.iter_paths(path, recursive=recursive, include_hidden=include_hidden, exclude_internal=exclude_internal):
            if compiled.search(p.name):
                result.append(p)
                if limit is not None and len(result) >= limit:
                    break
        return result

    def content(self, query: str, *, path: str | Path = ".", recursive: bool = True,
                extensions: Iterable[str] | None = None, case_sensitive: bool = False,
                regex: bool = False, max_file_size: int = 8 * 1024 * 1024,
                chunk_size: int = 1024 * 1024, limit: int | None = None,
                exclude_internal: bool = True) -> list[Path]:
        """Search content incrementally so large text files never load completely."""
        if max_file_size < 0 or chunk_size <= 0:
            raise ValueError("invalid size or chunk_size")
        ext = self._extensions(extensions)
        compiled = re.compile(query, 0 if case_sensitive else re.IGNORECASE) if regex else None
        needle = query if case_sensitive else query.casefold()
        result: list[Path] = []
        for item in self.iter_paths(path, recursive=recursive, include_hidden=True, exclude_internal=exclude_internal):
            try:
                if ext is not None and item.suffix.lower() not in ext or item.stat().st_size > max_file_size:
                    continue
                with item.open("r", encoding="utf-8", errors="ignore") as handle:
                    for chunk in iter(lambda: handle.read(chunk_size), ""):
                        if compiled:
                            matched = bool(compiled.search(chunk))
                        else:
                            matched = needle in (chunk if case_sensitive else chunk.casefold())
                        if matched:
                            result.append(item)
                            break
                if limit is not None and len(result) >= limit:
                    break
            except (OSError, UnicodeError):
                continue
        return result

    def by_mime(self, mime: str, path: str | Path = ".", **kwargs: object) -> list[Path]:
        return [p for p in self.search(path=path, **kwargs) if mimetypes.guess_type(p.name)[0] == mime]

    def by_mime_prefix(self, prefix: str, path: str | Path = ".", **kwargs: object) -> list[Path]:
        prefix = prefix.lower()
        return [p for p in self.search(path=path, **kwargs) if (mimetypes.guess_type(p.name)[0] or "").lower().startswith(prefix)]

    def by_hash(self, digest: str, algorithm: str = "sha256", **kwargs: object) -> list[Path]:
        wanted = digest.casefold()
        result = []
        for p in self.search(**kwargs):
            try:
                h = hashlib.new(algorithm)
                with p.open("rb") as f:
                    for chunk in iter(lambda: f.read(1024 * 1024), b""):
                        h.update(chunk)
                if h.hexdigest().casefold() == wanted:
                    result.append(p)
            except (OSError, ValueError):
                continue
        return result

    def by_size(self, minimum: int | None = None, maximum: int | None = None, **kwargs: object) -> list[Path]:
        return self.search(minimum_size=minimum, maximum_size=maximum, **kwargs)

    def empty_files(self, **kwargs: object) -> list[Path]:
        return self.search(minimum_size=0, maximum_size=0, **kwargs)

    def empty_directories(self, path: str | Path = ".", *, recursive: bool = True, include_hidden: bool = True) -> list[Path]:
        result = []
        for item in self.iter_paths(path, recursive=recursive, include_files=False, include_directories=True, include_hidden=include_hidden):
            try:
                if not any(item.iterdir()):
                    result.append(item)
            except OSError:
                continue
        return result

    def large_files(self, minimum_size: int, **kwargs: object) -> list[Path]:
        return self.search(minimum_size=minimum_size, **kwargs)

    def old_files(self, days: float, **kwargs: object) -> list[Path]:
        if days < 0: raise ValueError("days cannot be negative")
        return [p for p in self.search(**kwargs) if self._safe_mtime(p) < datetime.now().timestamp() - days * 86400]

    def recent_files(self, days: float, **kwargs: object) -> list[Path]:
        if days < 0: raise ValueError("days cannot be negative")
        return [p for p in self.search(**kwargs) if self._safe_mtime(p) >= datetime.now().timestamp() - days * 86400]

    @staticmethod
    def _safe_mtime(path: Path) -> float:
        try: return path.stat().st_mtime
        except OSError: return 0.0

    def duplicates(self, *, path: str | Path = ".", algorithm: str = "sha256", minimum_size: int = 1,
                   include_hidden: bool = True, exclude_internal: bool = True) -> dict[str, list[Path]]:
        by_size: dict[int, list[Path]] = {}
        for item in self.search(path=path, minimum_size=minimum_size, include_hidden=include_hidden, exclude_internal=exclude_internal):
            try: by_size.setdefault(item.stat().st_size, []).append(item)
            except OSError: pass
        duplicates: dict[str, list[Path]] = {}
        for size, candidates in by_size.items():
            if len(candidates) < 2: continue
            for item in candidates:
                try:
                    h = hashlib.new(algorithm)
                    with item.open("rb") as f:
                        for chunk in iter(lambda: f.read(1024 * 1024), b""): h.update(chunk)
                    duplicates.setdefault(f"{size}:{h.hexdigest()}", []).append(item)
                except (OSError, ValueError): continue
        return {k: v for k, v in duplicates.items() if len(v) > 1}

    def count(self, **kwargs: object) -> int:
        return len(self.search(**kwargs))

    def extensions(self, path: str | Path = ".", *, recursive: bool = True, include_hidden: bool = True) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in self.iter_paths(path, recursive=recursive, include_hidden=include_hidden):
            suffix = item.suffix.lower() or "[no extension]"
            counts[suffix] = counts.get(suffix, 0) + 1
        return dict(sorted(counts.items(), key=lambda x: (-x[1], x[0])))

    def paths(self, query: str = "*", **kwargs: object) -> Iterator[Path]:
        for item in self.iter_paths(**kwargs):
            if fnmatch.fnmatchcase(item.name.casefold(), query.casefold()): yield item
