"""Advanced, streaming, metadata-aware filesystem search for Alera."""
from __future__ import annotations

import fnmatch
import hashlib
import mimetypes
import os
import re
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Iterator, Pattern, Sequence


@dataclass(frozen=True)
class SearchResult:
    """A ranked search result with useful filesystem metadata."""
    path: Path
    score: float = 0.0
    reason: str = ""
    size: int = 0
    is_file: bool = True
    is_directory: bool = False
    extension: str = ""
    mime_type: str | None = None
    modified: float = 0.0

    def __fspath__(self) -> str:
        return os.fspath(self.path)

    def __str__(self) -> str:
        return str(self.path)


class SearchEngine:
    """A batteries-included search engine designed for very large workspaces.

    Features include streaming traversal, glob/regex/name/content search,
    fuzzy scoring, boolean queries, metadata filters, duplicate detection,
    MIME/hash search, cross-chunk content matching, result ranking, search
    suggestions, persistent lightweight filename indexing, and safe pruning
    of Alera internal storage.
    """

    INTERNAL = frozenset({
        ".alera_bin", ".alera_hidden", ".alera_recovery", ".alera_cache",
        ".alera_versions", ".alera_index", ".alera_database",
    })
    DEFAULT_CHUNK_SIZE = 1024 * 1024
    DEFAULT_MAX_FILE_SIZE = 64 * 1024 * 1024
    _WORD_RE = re.compile(r"[\w]+", re.UNICODE)

    def __init__(self, base_path: str | Path = "", *, index_path: str | Path | None = None) -> None:
        raw = Path(base_path).expanduser() if str(base_path) else Path.cwd()
        self.base_path = raw.resolve()
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.index_path = (self.base_path / ".alera_index" / "search.sqlite3") if index_path is None else Path(index_path).expanduser().resolve()
        self._lock = threading.RLock()

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
        return {str(e).lower() if str(e).startswith(".") else "." + str(e).lower() for e in values}

    @staticmethod
    def _validate_limit(limit: int | None) -> None:
        if limit is not None and (not isinstance(limit, int) or limit < 0):
            raise ValueError("limit must be a non-negative integer")

    def _allowed(self, item: Path, *, include_hidden: bool, exclude_internal: bool) -> bool:
        try:
            rel = item.relative_to(self.base_path)
        except ValueError:
            return False
        if exclude_internal and any(part in self.INTERNAL for part in rel.parts):
            return False
        if not include_hidden and any(part.startswith(".") for part in rel.parts):
            return False
        return True

    def iter_paths(self, path: str | Path = ".", *, recursive: bool = True,
                   include_files: bool = True, include_directories: bool = False,
                   include_hidden: bool = True, follow_symlinks: bool = False,
                   exclude_internal: bool = True) -> Iterator[Path]:
        """Stream filesystem entries without building the complete result set."""
        root = self._root(path)
        if root.is_file():
            if include_files and self._allowed(root, include_hidden=include_hidden, exclude_internal=exclude_internal):
                yield root
            return
        if not root.is_dir():
            return
        stack = [root]
        while stack:
            current = stack.pop()
            try:
                entries = os.scandir(current)
            except OSError:
                continue
            children: list[Path] = []
            with entries:
                for entry in entries:
                    item = Path(entry.path)
                    if not self._allowed(item, include_hidden=include_hidden, exclude_internal=exclude_internal):
                        continue
                    try:
                        if entry.is_symlink() and not follow_symlinks:
                            continue
                        is_dir = entry.is_dir(follow_symlinks=follow_symlinks)
                    except OSError:
                        continue
                    if is_dir:
                        if include_directories:
                            yield item
                        if recursive:
                            children.append(item)
                    elif include_files:
                        try:
                            if entry.is_file(follow_symlinks=follow_symlinks):
                                yield item
                        except OSError:
                            continue
            stack.extend(reversed(children))

    def _matches_metadata(self, item: Path, *, extensions: set[str] | None = None,
                          minimum_size: int | None = None, maximum_size: int | None = None,
                          modified_after: float | None = None, modified_before: float | None = None,
                          created_after: float | None = None, created_before: float | None = None) -> os.stat_result | None:
        try:
            info = item.stat(follow_symlinks=False)
        except OSError:
            return None
        if extensions is not None and item.suffix.lower() not in extensions:
            return None
        if minimum_size is not None and info.st_size < minimum_size:
            return None
        if maximum_size is not None and info.st_size > maximum_size:
            return None
        if modified_after is not None and info.st_mtime < modified_after:
            return None
        if modified_before is not None and info.st_mtime > modified_before:
            return None
        if created_after is not None and info.st_ctime < created_after:
            return None
        if created_before is not None and info.st_ctime > created_before:
            return None
        return info

    def search(self, pattern: str = "*", *, path: str | Path = ".", recursive: bool = True,
               extension: str | Iterable[str] | None = None, minimum_size: int | None = None,
               maximum_size: int | None = None, modified_after: float | datetime | None = None,
               modified_before: float | datetime | None = None, created_after: float | datetime | None = None,
               created_before: float | datetime | None = None, files_only: bool = True,
               directories_only: bool = False, include_hidden: bool = True,
               follow_symlinks: bool = False, exclude_internal: bool = True,
               limit: int | None = None, sort: str | None = None) -> list[Path]:
        if files_only and directories_only:
            raise ValueError("files_only and directories_only cannot both be true")
        if minimum_size is not None and minimum_size < 0 or maximum_size is not None and maximum_size < 0:
            raise ValueError("file sizes cannot be negative")
        self._validate_limit(limit)
        ext = self._extensions(extension)
        ma, mb = self._time(modified_after), self._time(modified_before)
        ca, cb = self._time(created_after), self._time(created_before)
        result: list[Path] = []
        for item in self.iter_paths(path, recursive=recursive, include_files=not directories_only,
                                    include_directories=not files_only, include_hidden=include_hidden,
                                    follow_symlinks=follow_symlinks, exclude_internal=exclude_internal):
            if not fnmatch.fnmatchcase(item.name.casefold(), pattern.casefold()):
                continue
            if self._matches_metadata(item, extensions=ext, minimum_size=minimum_size, maximum_size=maximum_size,
                                      modified_after=ma, modified_before=mb, created_after=ca, created_before=cb) is None:
                continue
            result.append(item)
            if limit is not None and len(result) >= limit and sort is None:
                break
        if sort:
            result = self._sort_paths(result, sort)
            if limit is not None:
                result = result[:limit]
        return result

    @staticmethod
    def _sort_paths(paths: Sequence[Path], sort: str) -> list[Path]:
        key = sort.lower().replace("-", "_")
        if key in {"name", "path"}: return sorted(paths, key=lambda p: str(p).casefold())
        if key == "size": return sorted(paths, key=lambda p: SearchEngine._stat_value(p, "st_size"))
        if key in {"size_desc", "largest"}: return sorted(paths, key=lambda p: SearchEngine._stat_value(p, "st_size"), reverse=True)
        if key in {"modified", "mtime"}: return sorted(paths, key=lambda p: SearchEngine._stat_value(p, "st_mtime"))
        if key in {"modified_desc", "newest"}: return sorted(paths, key=lambda p: SearchEngine._stat_value(p, "st_mtime"), reverse=True)
        return paths

    @staticmethod
    def _stat_value(path: Path, field: str) -> float:
        try: return float(getattr(path.stat(follow_symlinks=False), field))
        except OSError: return 0.0

    def name(self, query: str, **kwargs: object) -> list[Path]:
        pattern = query if any(c in query for c in "*?[") else f"*{query}*"
        return self.search(pattern, **kwargs)

    def regex(self, pattern: str | Pattern[str], *, path: str | Path = ".", recursive: bool = True,
              include_hidden: bool = True, case_sensitive: bool = False, limit: int | None = None,
              exclude_internal: bool = True, files_only: bool = True) -> list[Path]:
        self._validate_limit(limit)
        compiled = pattern if hasattr(pattern, "search") else re.compile(str(pattern), 0 if case_sensitive else re.IGNORECASE)
        result: list[Path] = []
        for p in self.iter_paths(path, recursive=recursive, include_files=files_only, include_directories=not files_only,
                                  include_hidden=include_hidden, exclude_internal=exclude_internal):
            if compiled.search(p.name):
                result.append(p)
                if limit is not None and len(result) >= limit: break
        return result

    def fuzzy(self, query: str, *, path: str | Path = ".", recursive: bool = True,
              threshold: float = 0.35, include_hidden: bool = True, limit: int | None = 50,
              files_only: bool = True, directories_only: bool = False) -> list[SearchResult]:
        """Rank filenames using subsequence + edit-distance-like similarity."""
        if not query: raise ValueError("query must not be empty")
        if files_only and directories_only: raise ValueError("files_only and directories_only cannot both be true")
        self._validate_limit(limit)
        q = query.casefold()
        ranked: list[SearchResult] = []
        for p in self.iter_paths(path, recursive=recursive, include_files=not directories_only,
                                  include_directories=not files_only, include_hidden=include_hidden):
            score = self._fuzzy_score(q, p.name.casefold())
            if score < threshold: continue
            info = self._result(p, score, "fuzzy filename match")
            ranked.append(info)
        ranked.sort(key=lambda r: (-r.score, len(r.path.name), str(r.path).casefold()))
        return ranked[:limit] if limit is not None else ranked

    @staticmethod
    def _fuzzy_score(query: str, candidate: str) -> float:
        if query == candidate: return 1.0
        if query in candidate: return 0.95 - min(0.15, (len(candidate) - len(query)) / max(1, len(candidate)) * 0.15)
        pos = -1
        gaps = 0
        matched = 0
        for ch in query:
            nxt = candidate.find(ch, pos + 1)
            if nxt < 0: return 0.0
            if pos >= 0: gaps += nxt - pos - 1
            pos = nxt; matched += 1
        subseq = matched / max(1, len(candidate))
        compact = 1.0 / (1.0 + gaps / max(1, len(query)))
        return min(0.94, 0.55 * subseq + 0.45 * compact)

    def ranked(self, query: str, *, path: str | Path = ".", recursive: bool = True,
               include_hidden: bool = True, limit: int | None = 50, content: bool = True,
               case_sensitive: bool = False) -> list[SearchResult]:
        """Rank matches by exactness, filename relevance, path relevance and content."""
        self._validate_limit(limit)
        q = query if case_sensitive else query.casefold()
        results: list[SearchResult] = []
        for p in self.iter_paths(path, recursive=recursive, include_hidden=include_hidden):
            name = p.name if case_sensitive else p.name.casefold()
            score = 0.0; reasons: list[str] = []
            if name == q: score += 1.0; reasons.append("exact name")
            elif q in name: score += 0.75; reasons.append("name contains query")
            else:
                fuzzy = self._fuzzy_score(q, name)
                if fuzzy >= 0.45: score += fuzzy * 0.55; reasons.append("fuzzy name")
            path_text = str(p.relative_to(self.base_path))
            if q in (path_text if case_sensitive else path_text.casefold()): score += 0.2; reasons.append("path match")
            if content and p.is_file() and self._content_contains(p, query, case_sensitive=case_sensitive, max_file_size=self.DEFAULT_MAX_FILE_SIZE):
                score += 0.45; reasons.append("content match")
            if score:
                results.append(self._result(p, score, ", ".join(reasons)))
        results.sort(key=lambda r: (-r.score, len(str(r.path)), str(r.path).casefold()))
        return results[:limit] if limit is not None else results

    def content(self, query: str, *, path: str | Path = ".", recursive: bool = True,
                extensions: Iterable[str] | None = None, case_sensitive: bool = False,
                regex: bool = False, max_file_size: int = DEFAULT_MAX_FILE_SIZE,
                chunk_size: int = DEFAULT_CHUNK_SIZE, limit: int | None = None,
                exclude_internal: bool = True, include_hidden: bool = True,
                whole_word: bool = False) -> list[Path]:
        """Search file contents with overlap so matches spanning chunks are found."""
        if max_file_size < 0 or chunk_size <= 0: raise ValueError("invalid size or chunk_size")
        self._validate_limit(limit)
        ext = self._extensions(extensions)
        compiled = None
        if regex:
            expression = rf"\b(?:{query})\b" if whole_word else query
            compiled = re.compile(expression, 0 if case_sensitive else re.IGNORECASE)
        needle = query if case_sensitive else query.casefold()
        overlap = max(0, len(query.encode("utf-8")) * 2)
        result: list[Path] = []
        for item in self.iter_paths(path, recursive=recursive, include_hidden=include_hidden, exclude_internal=exclude_internal):
            if ext is not None and item.suffix.lower() not in ext: continue
            try:
                if not item.is_file() or item.stat().st_size > max_file_size: continue
                if self._content_contains(item, query, case_sensitive=case_sensitive, regex=regex,
                                          compiled=compiled, chunk_size=chunk_size, overlap=overlap,
                                          whole_word=whole_word):
                    result.append(item)
                    if limit is not None and len(result) >= limit: break
            except (OSError, UnicodeError):
                continue
        return result

    def _content_contains(self, path: Path, query: str, *, case_sensitive: bool = False,
                          regex: bool = False, compiled: Pattern[str] | None = None,
                          max_file_size: int | None = None, chunk_size: int = DEFAULT_CHUNK_SIZE,
                          overlap: int = 4096, whole_word: bool = False) -> bool:
        try:
            if max_file_size is not None and path.stat().st_size > max_file_size: return False
            expression = rf"\b(?:{query})\b" if whole_word and regex else query
            rx = compiled or (re.compile(expression, 0 if case_sensitive else re.IGNORECASE) if regex else None)
            needle = query if case_sensitive else query.casefold()
            with path.open("r", encoding="utf-8", errors="ignore") as handle:
                previous = ""
                while True:
                    chunk = handle.read(chunk_size)
                    if not chunk: break
                    data = previous + chunk
                    if rx:
                        if rx.search(data): return True
                    elif needle in (data if case_sensitive else data.casefold()):
                        return True
                    previous = data[-overlap:] if overlap else ""
            return False
        except (OSError, UnicodeError, re.error):
            return False

    def boolean(self, expression: str, *, path: str | Path = ".", recursive: bool = True,
                include_hidden: bool = True, limit: int | None = None) -> list[Path]:
        """Evaluate a simple filename query: AND, OR, NOT and parentheses."""
        self._validate_limit(limit)
        tokens = re.findall(r"\(|\)|\bAND\b|\bOR\b|\bNOT\b|[^\s()]+", expression, re.IGNORECASE)
        if not tokens: return []
        universe = list(self.iter_paths(path, recursive=recursive, include_hidden=include_hidden))
        universe_set = set(universe)
        def atom(token: str) -> set[Path]:
            pattern = token.strip('"\'')
            if not pattern: return set()
            return set(self.search(pattern, path=path, recursive=recursive, include_hidden=include_hidden))
        def parse_or(index: int) -> tuple[set[Path], int]:
            left, index = parse_and(index)
            while index < len(tokens) and tokens[index].upper() == "OR":
                right, index = parse_and(index + 1); left |= right
            return left, index
        def parse_and(index: int) -> tuple[set[Path], int]:
            left, index = parse_not(index)
            while index < len(tokens) and tokens[index].upper() == "AND":
                right, index = parse_not(index + 1); left &= right
            return left, index
        def parse_not(index: int) -> tuple[set[Path], int]:
            if index < len(tokens) and tokens[index].upper() == "NOT":
                value, index = parse_not(index + 1); return universe_set - value, index
            return parse_primary(index)
        def parse_primary(index: int) -> tuple[set[Path], int]:
            if index >= len(tokens): return set(), index
            if tokens[index] == "(":
                value, index = parse_or(index + 1)
                if index < len(tokens) and tokens[index] == ")": index += 1
                return value, index
            return atom(tokens[index]), index + 1
        result, _ = parse_or(0)
        ordered = sorted(result, key=lambda p: str(p).casefold())
        return ordered[:limit] if limit is not None else ordered

    def suggest(self, query: str, *, path: str | Path = ".", limit: int = 10) -> list[str]:
        """Return likely filename completions for a partial query."""
        if limit < 0: raise ValueError("limit cannot be negative")
        q = query.casefold()
        names: dict[str, int] = {}
        for p in self.iter_paths(path, recursive=True, include_hidden=True):
            name = p.name
            if q in name.casefold(): names[name] = names.get(name, 0) + 1
        return [n for n, _ in sorted(names.items(), key=lambda x: (-x[1], len(x[0]), x[0].casefold()))[:limit]]

    def by_mime(self, mime: str, path: str | Path = ".", **kwargs: object) -> list[Path]:
        return [p for p in self.search(path=path, **kwargs) if mimetypes.guess_type(p.name)[0] == mime]

    def by_mime_prefix(self, prefix: str, path: str | Path = ".", **kwargs: object) -> list[Path]:
        prefix = prefix.lower()
        return [p for p in self.search(path=path, **kwargs) if (mimetypes.guess_type(p.name)[0] or "").lower().startswith(prefix)]

    def by_hash(self, digest: str, algorithm: str = "sha256", **kwargs: object) -> list[Path]:
        wanted = digest.casefold(); result: list[Path] = []
        for p in self.search(**kwargs):
            try:
                h = hashlib.new(algorithm)
                with p.open("rb") as f:
                    for chunk in iter(lambda: f.read(self.DEFAULT_CHUNK_SIZE), b""): h.update(chunk)
                if h.hexdigest().casefold() == wanted: result.append(p)
            except (OSError, ValueError): continue
        return result

    def by_size(self, minimum: int | None = None, maximum: int | None = None, **kwargs: object) -> list[Path]:
        return self.search(minimum_size=minimum, maximum_size=maximum, **kwargs)

    def empty_files(self, **kwargs: object) -> list[Path]: return self.search(minimum_size=0, maximum_size=0, **kwargs)

    def empty_directories(self, path: str | Path = ".", *, recursive: bool = True, include_hidden: bool = True) -> list[Path]:
        return [p for p in self.iter_paths(path, recursive=recursive, include_files=False, include_directories=True, include_hidden=include_hidden) if self._is_empty_dir(p)]

    @staticmethod
    def _is_empty_dir(path: Path) -> bool:
        try: return next(path.iterdir(), None) is None
        except OSError: return False

    def large_files(self, minimum_size: int, **kwargs: object) -> list[Path]: return self.search(minimum_size=minimum_size, **kwargs)

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
                        for chunk in iter(lambda: f.read(self.DEFAULT_CHUNK_SIZE), b""): h.update(chunk)
                    duplicates.setdefault(f"{size}:{h.hexdigest()}", []).append(item)
                except (OSError, ValueError): continue
        return {k: v for k, v in duplicates.items() if len(v) > 1}

    def count(self, **kwargs: object) -> int: return sum(1 for _ in self.iter_paths(**{k: v for k, v in kwargs.items() if k in {"path", "recursive", "include_hidden"}})) if not kwargs else len(self.search(**kwargs))

    def extensions(self, path: str | Path = ".", *, recursive: bool = True, include_hidden: bool = True) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in self.iter_paths(path, recursive=recursive, include_hidden=include_hidden):
            suffix = item.suffix.lower() or "[no extension]"
            counts[suffix] = counts.get(suffix, 0) + 1
        return dict(sorted(counts.items(), key=lambda x: (-x[1], x[0])))

    def paths(self, query: str = "*", **kwargs: object) -> Iterator[Path]:
        for item in self.iter_paths(**kwargs):
            if fnmatch.fnmatchcase(item.name.casefold(), query.casefold()): yield item

    def _result(self, path: Path, score: float, reason: str) -> SearchResult:
        try: info = path.stat(follow_symlinks=False)
        except OSError: info = None
        return SearchResult(path=path, score=score, reason=reason,
                            size=info.st_size if info else 0,
                            is_file=path.is_file() if info else False,
                            is_directory=path.is_dir() if info else False,
                            extension=path.suffix.lower(),
                            mime_type=mimetypes.guess_type(path.name)[0],
                            modified=info.st_mtime if info else 0.0)

    # Persistent filename index. This deliberately remains lightweight and
    # dependency-free; the dedicated SearchIndex service can provide richer indexing.
    def index(self, *, path: str | Path = ".", full_hash: bool = False, limit: int | None = None) -> dict[str, int]:
        self._validate_limit(limit)
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, sqlite3.connect(self.index_path) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=NORMAL")
            db.execute("CREATE TABLE IF NOT EXISTS files (path TEXT PRIMARY KEY, name TEXT NOT NULL, suffix TEXT, size INTEGER, mtime_ns INTEGER, sha256 TEXT)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_search_name ON files(name)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_search_suffix ON files(suffix)")
            seen: set[str] = set(); added = updated = 0
            for item in self.iter_paths(path, recursive=True, include_hidden=True):
                if limit is not None and added + updated >= limit: break
                try:
                    info = item.stat(follow_symlinks=False); key = str(item)
                    seen.add(key)
                    old = db.execute("SELECT size, mtime_ns, sha256 FROM files WHERE path=?", (key,)).fetchone()
                    digest = old[2] if old and old[0] == info.st_size and old[1] == info.st_mtime_ns else None
                    if full_hash and digest is None and item.is_file(): digest = self._hash_path(item, "sha256")
                    db.execute("INSERT INTO files(path,name,suffix,size,mtime_ns,sha256) VALUES(?,?,?,?,?,?) ON CONFLICT(path) DO UPDATE SET name=excluded.name,suffix=excluded.suffix,size=excluded.size,mtime_ns=excluded.mtime_ns,sha256=excluded.sha256", (key, item.name, item.suffix.lower(), info.st_size, info.st_mtime_ns, digest))
                    if old is None: added += 1
                    elif old[0] != info.st_size or old[1] != info.st_mtime_ns: updated += 1
                except OSError: continue
            rows = db.execute("SELECT path FROM files").fetchall()
            stale = [row[0] for row in rows if row[0] not in seen and self._inside_existing_root(row[0], path)]
            if stale: db.executemany("DELETE FROM files WHERE path=?", ((p,) for p in stale))
            db.commit()
            return {"added": added, "updated": updated, "removed": len(stale), "total": db.execute("SELECT COUNT(*) FROM files").fetchone()[0]}

    def indexed_search(self, query: str = "*", *, extension: str | None = None,
                       minimum_size: int | None = None, maximum_size: int | None = None,
                       limit: int | None = None) -> list[Path]:
        self._validate_limit(limit)
        if not self.index_path.exists(): self.index()
        pattern = query.casefold()
        sql = "SELECT path FROM files WHERE lower(name) LIKE ?"
        args: list[object] = [pattern.replace("*", "%")]
        if extension:
            ext = extension if extension.startswith(".") else "." + extension
            sql += " AND lower(suffix)=?"; args.append(ext.lower())
        if minimum_size is not None: sql += " AND size>=?"; args.append(minimum_size)
        if maximum_size is not None: sql += " AND size<=?"; args.append(maximum_size)
        sql += " ORDER BY name COLLATE NOCASE"
        if limit is not None: sql += " LIMIT ?"; args.append(limit)
        with self._lock, sqlite3.connect(self.index_path) as db:
            return [Path(row[0]) for row in db.execute(sql, args)]

    def index_information(self) -> dict[str, object]:
        if not self.index_path.exists(): return {"path": str(self.index_path), "exists": False, "entries": 0}
        with sqlite3.connect(self.index_path) as db:
            count = db.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        return {"path": str(self.index_path), "exists": True, "entries": count, "size": self.index_path.stat().st_size}

    def clear_index(self) -> None:
        with self._lock:
            try: self.index_path.unlink()
            except FileNotFoundError: return
            for suffix in ("-wal", "-shm"):
                try: Path(str(self.index_path) + suffix).unlink()
                except FileNotFoundError: pass

    def _inside_existing_root(self, stored: str, root: str | Path) -> bool:
        try: Path(stored).resolve().relative_to(self._root(root)); return True
        except (ValueError, OSError): return False

    @staticmethod
    def _hash_path(path: Path, algorithm: str = "sha256", chunk_size: int = DEFAULT_CHUNK_SIZE) -> str:
        digest = hashlib.new(algorithm)
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(chunk_size), b""): digest.update(chunk)
        return digest.hexdigest()

    def hash_of(self, path: str | Path, algorithm: str = "sha256") -> str:
        target = self._root(path)
        if not target.is_file(): raise FileNotFoundError(target)
        return self._hash_path(target, algorithm)
