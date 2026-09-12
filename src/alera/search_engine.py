"""Advanced, composable filesystem search utilities for Alera."""

from __future__ import annotations

import fnmatch
import hashlib
import mimetypes
import re
from datetime import datetime
from pathlib import Path
from typing import Iterable, Iterator


class SearchEngine:
    """Metadata-aware filesystem search engine with streaming support."""

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

    def iter_paths(self, path: str | Path = ".", *, recursive: bool = True,
                   include_files: bool = True, include_directories: bool = False,
                   include_hidden: bool = True, follow_symlinks: bool = False) -> Iterator[Path]:
        """Stream filesystem entries instead of building a giant list."""
        root = self._root(path)
        if root.is_file():
            if include_files:
                yield root
            return
        iterator = root.rglob("*") if recursive else root.glob("*")
        for item in iterator:
            try:
                if not follow_symlinks and item.is_symlink():
                    continue
                if not include_hidden and item.name.startswith("."):
                    continue
                if item.is_file() and include_files:
                    yield item
                elif item.is_dir() and include_directories:
                    yield item
            except OSError:
                continue

    def search(self, pattern: str = "*", *, path: str | Path = ".", recursive: bool = True,
               extension: str | Iterable[str] | None = None, minimum_size: int | None = None,
               maximum_size: int | None = None, modified_after: float | datetime | None = None,
               modified_before: float | datetime | None = None, created_after: float | datetime | None = None,
               created_before: float | datetime | None = None, files_only: bool = True,
               directories_only: bool = False, include_hidden: bool = True,
               follow_symlinks: bool = False, limit: int | None = None) -> list[Path]:
        """Search by name, extension, size, timestamps, and entry type."""
        if files_only and directories_only:
            raise ValueError("files_only and directories_only cannot both be true")
        if minimum_size is not None and minimum_size < 0:
            raise ValueError("minimum_size cannot be negative")
        if maximum_size is not None and maximum_size < 0:
            raise ValueError("maximum_size cannot be negative")
        if limit is not None and limit < 0:
            raise ValueError("limit cannot be negative")
        if extension is None:
            extensions = None
        elif isinstance(extension, str):
            extensions = {extension.lower() if extension.startswith(".") else f".{extension.lower()}"}
        else:
            extensions = {e.lower() if e.startswith(".") else f".{e.lower()}" for e in extension}
        ma, mb = self._time(modified_after), self._time(modified_before)
        ca, cb = self._time(created_after), self._time(created_before)
        result: list[Path] = []
        for item in self.iter_paths(path, recursive=recursive, include_files=not directories_only,
                                    include_directories=not files_only, include_hidden=include_hidden,
                                    follow_symlinks=follow_symlinks):
            try:
                if not fnmatch.fnmatch(item.name, pattern):
                    continue
                if extensions is not None and item.suffix.lower() not in extensions:
                    continue
                info = item.stat()
                if minimum_size is not None and info.st_size < minimum_size:
                    continue
                if maximum_size is not None and info.st_size > maximum_size:
                    continue
                if ma is not None and info.st_mtime < ma:
                    continue
                if mb is not None and info.st_mtime > mb:
                    continue
                if ca is not None and info.st_ctime < ca:
                    continue
                if cb is not None and info.st_ctime > cb:
                    continue
                result.append(item)
                if limit is not None and len(result) >= limit:
                    break
            except OSError:
                continue
        return result

    def name(self, query: str, **kwargs: object) -> list[Path]:
        """Search names using substring matching unless wildcards are supplied."""
        pattern = query if any(c in query for c in "*?[") else f"*{query}*"
        return self.search(pattern, **kwargs)

    def regex(self, pattern: str, *, path: str | Path = ".", recursive: bool = True,
              include_hidden: bool = True, case_sensitive: bool = False,
              limit: int | None = None) -> list[Path]:
        """Search filenames with a regular expression."""
        flags = 0 if case_sensitive else re.IGNORECASE
        compiled = re.compile(pattern, flags)
        result = [p for p in self.iter_paths(path, recursive=recursive, include_hidden=include_hidden)
                  if compiled.search(p.name)]
        return result[:limit] if limit is not None else result

    def content(self, query: str, *, path: str | Path = ".", recursive: bool = True,
                extensions: Iterable[str] | None = None, case_sensitive: bool = False,
                regex: bool = False, max_file_size: int = 8 * 1024 * 1024,
                limit: int | None = None) -> list[Path]:
        """Search UTF-8-compatible text contents with bounded memory use."""
        if max_file_size < 0:
            raise ValueError("max_file_size cannot be negative")
        ext = None if extensions is None else {
            e.lower() if e.startswith(".") else f".{e.lower()}" for e in extensions
        }
        compiled = re.compile(query, 0 if case_sensitive else re.IGNORECASE) if regex else None
        result: list[Path] = []
        for item in self.iter_paths(path, recursive=recursive):
            try:
                if ext is not None and item.suffix.lower() not in ext:
                    continue
                if item.stat().st_size > max_file_size:
                    continue
                text = item.read_text(encoding="utf-8", errors="ignore")
                matched = bool(compiled.search(text)) if compiled else (
                    query in text if case_sensitive else query.casefold() in text.casefold()
                )
                if matched:
                    result.append(item)
                    if limit is not None and len(result) >= limit:
                        break
            except (OSError, UnicodeError, re.error):
                continue
        return result

    def by_mime(self, mime: str, path: str | Path = ".", **kwargs: object) -> list[Path]:
        return [p for p in self.search(path=path, **kwargs) if mimetypes.guess_type(p.name)[0] == mime]

    def by_mime_prefix(self, prefix: str, path: str | Path = ".", **kwargs: object) -> list[Path]:
        prefix = prefix.lower()
        return [p for p in self.search(path=path, **kwargs)
                if (mimetypes.guess_type(p.name)[0] or "").lower().startswith(prefix)]

    def by_hash(self, digest: str, algorithm: str = "sha256", **kwargs: object) -> list[Path]:
        wanted = digest.lower()
        result: list[Path] = []
        for path in self.search(**kwargs):
            try:
                h = hashlib.new(algorithm)
                with path.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        h.update(chunk)
                if h.hexdigest().lower() == wanted:
                    result.append(path)
            except (OSError, ValueError):
                continue
        return result

    def by_size(self, minimum: int | None = None, maximum: int | None = None, **kwargs: object) -> list[Path]:
        return self.search(minimum_size=minimum, maximum_size=maximum, **kwargs)

    def empty_files(self, **kwargs: object) -> list[Path]:
        return self.search(minimum_size=0, maximum_size=0, **kwargs)

    def empty_directories(self, path: str | Path = ".", *, recursive: bool = True) -> list[Path]:
        result: list[Path] = []
        for item in self.iter_paths(path, recursive=recursive, include_files=False, include_directories=True):
            try:
                if not any(item.iterdir()):
                    result.append(item)
            except OSError:
                continue
        return result

    def large_files(self, minimum_size: int, **kwargs: object) -> list[Path]:
        return self.search(minimum_size=minimum_size, **kwargs)

    def old_files(self, days: float, **kwargs: object) -> list[Path]:
        if days < 0:
            raise ValueError("days cannot be negative")
        cutoff = datetime.now().timestamp() - days * 86400
        return [p for p in self.search(**kwargs) if self._safe_mtime(p) < cutoff]

    def recent_files(self, days: float, **kwargs: object) -> list[Path]:
        if days < 0:
            raise ValueError("days cannot be negative")
        cutoff = datetime.now().timestamp() - days * 86400
        return [p for p in self.search(**kwargs) if self._safe_mtime(p) >= cutoff]

    @staticmethod
    def _safe_mtime(path: Path) -> float:
        try:
            return path.stat().st_mtime
        except OSError:
            return 0.0

    def duplicates(self, *, path: str | Path = ".", algorithm: str = "sha256",
                   minimum_size: int = 1) -> dict[str, list[Path]]:
        """Find duplicates by grouping on size first, then streaming hashes."""
        if minimum_size < 0:
            raise ValueError("minimum_size cannot be negative")
        by_size: dict[int, list[Path]] = {}
        for item in self.search(path=path, minimum_size=minimum_size):
            try:
                by_size.setdefault(item.stat().st_size, []).append(item)
            except OSError:
                continue
        duplicates: dict[str, list[Path]] = {}
        for size, candidates in by_size.items():
            if len(candidates) < 2:
                continue
            for item in candidates:
                try:
                    h = hashlib.new(algorithm)
                    with item.open("rb") as handle:
                        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                            h.update(chunk)
                    key = f"{size}:{h.hexdigest()}"
                    duplicates.setdefault(key, []).append(item)
                except (OSError, ValueError):
                    continue
        return {key: paths for key, paths in duplicates.items() if len(paths) > 1}

    def count(self, **kwargs: object) -> int:
        return len(self.search(**kwargs))

    def extensions(self, path: str | Path = ".", *, recursive: bool = True) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in self.iter_paths(path, recursive=recursive):
            suffix = item.suffix.lower() or "[no extension]"
            counts[suffix] = counts.get(suffix, 0) + 1
        return dict(sorted(counts.items(), key=lambda pair: (-pair[1], pair[0])))

    def paths(self, query: str = "*", *, path: str | Path = ".", recursive: bool = True,
              files_only: bool = True, directories_only: bool = False,
              include_hidden: bool = True, follow_symlinks: bool = False) -> Iterator[Path]:
        """Stream matching paths for very large filesystems."""
        for item in self.iter_paths(path, recursive=recursive, include_files=files_only or not directories_only,
                                    include_directories=directories_only or not files_only,
                                    include_hidden=include_hidden, follow_symlinks=follow_symlinks):
            if fnmatch.fnmatch(item.name, query):
                yield item
