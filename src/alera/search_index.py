"""Persistent high-speed filesystem search index for Alera."""
from __future__ import annotations

import fnmatch
import hashlib
import sqlite3
from pathlib import Path
from typing import Iterator


class SearchIndex:
    """SQLite-backed metadata/content index that can be rebuilt incrementally."""

    INTERNAL = frozenset({
        ".alera", ".alera_bin", ".alera_hidden", ".alera_recovery",
        ".alera_versions", ".alera_index", ".alera_database",
    })

    def __init__(self, base_path: str | Path = "", database: str | Path = ".alera_search.db") -> None:
        self.base_path = (Path(base_path).expanduser() if str(base_path) else Path.cwd()).resolve()
        self.base_path.mkdir(parents=True, exist_ok=True)
        raw_database = Path(database).expanduser()
        self.database = (self.base_path / raw_database).resolve() if not raw_database.is_absolute() else raw_database.resolve()
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.database)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=NORMAL")
        return db

    def _init(self) -> None:
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS files (
                    path TEXT PRIMARY KEY,
                    size INTEGER NOT NULL,
                    mtime_ns INTEGER NOT NULL,
                    ctime_ns INTEGER NOT NULL,
                    mode INTEGER NOT NULL,
                    suffix TEXT NOT NULL,
                    name TEXT NOT NULL,
                    sha256 TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_files_name ON files(name);
                CREATE INDEX IF NOT EXISTS idx_files_suffix ON files(suffix);
                CREATE INDEX IF NOT EXISTS idx_files_size ON files(size);
                CREATE INDEX IF NOT EXISTS idx_files_sha ON files(sha256);
                """
            )

    def _safe(self, path: Path) -> bool:
        try:
            relative = path.relative_to(self.base_path)
        except ValueError:
            return False
        if path == self.database:
            return False
        return not any(part in self.INTERNAL for part in relative.parts)

    def _walk(self) -> Iterator[Path]:
        stack = [self.base_path]
        while stack:
            current = stack.pop()
            try:
                entries = list(current.iterdir())
            except OSError:
                continue
            for item in entries:
                if not self._safe(item):
                    continue
                try:
                    if item.is_dir() and not item.is_symlink():
                        stack.append(item)
                    elif item.is_file() and not item.is_symlink():
                        yield item
                except OSError:
                    continue

    def index(self, *, full_hash: bool = True, limit: int | None = None) -> dict[str, int]:
        """Incrementally index files; unchanged metadata does not require rehashing."""
        if limit is not None and (not isinstance(limit, int) or limit < 0):
            raise ValueError("limit must be a non-negative integer or None")

        scanned = added = updated = hashed = 0
        seen: set[str] = set()
        with self._connect() as db:
            for path in self._walk():
                if limit is not None and scanned >= limit:
                    break
                scanned += 1
                key = str(path)
                seen.add(key)
                try:
                    st = path.stat()
                except OSError:
                    continue

                old = db.execute(
                    "SELECT size,mtime_ns,sha256 FROM files WHERE path=?", (key,)
                ).fetchone()
                digest = (
                    old["sha256"]
                    if old and old["size"] == st.st_size and old["mtime_ns"] == st.st_mtime_ns
                    else None
                )

                if full_hash and digest is None:
                    h = hashlib.sha256()
                    try:
                        with path.open("rb") as f:
                            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                                h.update(chunk)
                        digest = h.hexdigest()
                        hashed += 1
                    except OSError:
                        continue

                if old is None:
                    added += 1
                elif old["size"] != st.st_size or old["mtime_ns"] != st.st_mtime_ns:
                    updated += 1

                db.execute(
                    """
                    INSERT INTO files(
                        path,size,mtime_ns,ctime_ns,mode,suffix,name,sha256
                    ) VALUES(?,?,?,?,?,?,?,?)
                    ON CONFLICT(path) DO UPDATE SET
                        size=excluded.size,
                        mtime_ns=excluded.mtime_ns,
                        ctime_ns=excluded.ctime_ns,
                        mode=excluded.mode,
                        suffix=excluded.suffix,
                        name=excluded.name,
                        sha256=excluded.sha256
                    """,
                    (
                        key,
                        st.st_size,
                        st.st_mtime_ns,
                        getattr(st, "st_ctime_ns", 0),
                        st.st_mode,
                        path.suffix.lower(),
                        path.name,
                        digest,
                    ),
                )

            # Remove entries that no longer exist. With a limited scan we cannot
            # safely prune unseen rows, so pruning is only performed for a full scan.
            if limit is None:
                rows = db.execute("SELECT path FROM files").fetchall()
                stale = [row[0] for row in rows if row[0] not in seen]
                if stale:
                    db.executemany("DELETE FROM files WHERE path=?", ((path,) for path in stale))

            db.commit()

        return {"scanned": scanned, "added": added, "updated": updated, "hashed": hashed}

    def search(
        self,
        query: str = "*",
        *,
        suffix: str | None = None,
        minimum_size: int | None = None,
        maximum_size: int | None = None,
        limit: int | None = None,
    ) -> list[Path]:
        pattern = str(query).casefold()
        if limit is not None and (not isinstance(limit, int) or limit < 0):
            raise ValueError("limit must be a non-negative integer or None")
        if minimum_size is not None and minimum_size < 0:
            raise ValueError("minimum_size must be non-negative")
        if maximum_size is not None and maximum_size < 0:
            raise ValueError("maximum_size must be non-negative")
        if minimum_size is not None and maximum_size is not None and minimum_size > maximum_size:
            raise ValueError("minimum_size cannot exceed maximum_size")

        sql = "SELECT path FROM files WHERE 1=1"
        args: list[object] = []
        if suffix is not None:
            suffix = suffix if suffix.startswith(".") else "." + suffix
            sql += " AND suffix=?"
            args.append(suffix.casefold())
        if minimum_size is not None:
            sql += " AND size>=?"
            args.append(minimum_size)
        if maximum_size is not None:
            sql += " AND size<=?"
            args.append(maximum_size)

        rows: list[Path] = []
        with self._connect() as db:
            for row in db.execute(sql, args):
                path = Path(row[0])
                if fnmatch.fnmatchcase(path.name.casefold(), pattern):
                    rows.append(path)
                    if limit is not None and len(rows) >= limit:
                        break
        return rows

    def duplicates(self) -> dict[str, list[Path]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT sha256 FROM files WHERE sha256 IS NOT NULL GROUP BY sha256 HAVING COUNT(*)>1"
            ).fetchall()
            return {
                row[0]: [
                    Path(item[0])
                    for item in db.execute("SELECT path FROM files WHERE sha256=?", (row[0],)).fetchall()
                ]
                for row in rows
            }

    def information(self) -> dict[str, int]:
        with self._connect() as db:
            return {
                "files": db.execute("SELECT COUNT(*) FROM files").fetchone()[0],
                "bytes": db.execute("SELECT COALESCE(SUM(size),0) FROM files").fetchone()[0],
            }
