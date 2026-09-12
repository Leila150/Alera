"""Advanced filesystem search utilities for Alera."""
from __future__ import annotations

import fnmatch
import hashlib
import mimetypes
from datetime import datetime
from pathlib import Path
from typing import Iterable


class SearchEngine:
    """Perform composable, metadata-aware filesystem searches."""

    def __init__(self, base_path: str | Path = "") -> None:
        self.base_path = (Path(base_path).expanduser() if str(base_path) else Path.cwd()).resolve()
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _root(self, path: str | Path = ".") -> Path:
        root = (self.base_path / path).resolve() if not Path(path).is_absolute() else Path(path).resolve()
        root.relative_to(self.base_path)
        return root

    def search(self, pattern: str = "*", *, recursive: bool = True, extension: str | None = None,
               minimum_size: int | None = None, maximum_size: int | None = None,
               modified_after: float | datetime | None = None, files_only: bool = True) -> list[Path]:
        root = self._root()
        items: Iterable[Path] = root.rglob("*") if recursive else root.glob("*")
        ext = extension.lower() if extension else None
        after = modified_after.timestamp() if isinstance(modified_after, datetime) else modified_after
        result: list[Path] = []
        for item in items:
            try:
                if files_only and not item.is_file():
                    continue
                if not files_only and not item.exists():
                    continue
                if not fnmatch.fnmatch(item.name, pattern):
                    continue
                if ext and item.suffix.lower() != (ext if ext.startswith(".") else f".{ext}"):
                    continue
                stat = item.stat()
                if minimum_size is not None and stat.st_size < minimum_size:
                    continue
                if maximum_size is not None and stat.st_size > maximum_size:
                    continue
                if after is not None and stat.st_mtime < after:
                    continue
                result.append(item)
            except OSError:
                continue
        return result

    def by_mime(self, mime: str, path: str | Path = ".") -> list[Path]:
        return [p for p in self.search(path=str(path)) if mimetypes.guess_type(p.name)[0] == mime]

    def by_hash(self, digest: str, algorithm: str = "sha256") -> list[Path]:
        wanted = digest.lower()
        result: list[Path] = []
        for path in self.search():
            h = hashlib.new(algorithm)
            try:
                with path.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        h.update(chunk)
                if h.hexdigest() == wanted:
                    result.append(path)
            except OSError:
                continue
        return result

    def empty_files(self) -> list[Path]:
        return self.search(minimum_size=0, maximum_size=0)

    def large_files(self, minimum_size: int) -> list[Path]:
        return self.search(minimum_size=minimum_size)

    def old_files(self, days: float) -> list[Path]:
        cutoff = datetime.now().timestamp() - days * 86400
        return self.search(modified_after=None, files_only=True, pattern="*") and [p for p in self.search() if p.stat().st_mtime < cutoff]
