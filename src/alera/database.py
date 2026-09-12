"""SQLite-backed filesystem metadata index."""
from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path


class FileDatabase:
    """Index files for fast metadata searches and incremental refreshes."""

    def __init__(self, base_path: str | Path = "", database: str | Path | None = None) -> None:
        self.base = Path(base_path or ".").expanduser().resolve()
        self.base.mkdir(parents=True, exist_ok=True)
        self.database = Path(database or self.base / ".alera_index.db").expanduser().resolve()
        self.database.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.database) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("CREATE TABLE IF NOT EXISTS files (path TEXT PRIMARY KEY, size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL, sha256 TEXT NOT NULL)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_files_size ON files(size)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_files_sha256 ON files(sha256)")
            db.commit()

    @staticmethod
    def _hash(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def index(self, full_hash: bool = True) -> int:
        seen: set[str] = set()
        count = 0
        with sqlite3.connect(self.database) as db:
            for path in self.base.rglob("*"):
                if not path.is_file() or path == self.database or ".alera_" in path.parts:
                    continue
                try:
                    stat = path.stat()
                    relative = str(path.relative_to(self.base))
                    seen.add(relative)
                    row = db.execute("SELECT size, mtime_ns, sha256 FROM files WHERE path=?", (relative,)).fetchone()
                    digest = row[2] if row and row[0] == stat.st_size and row[1] == stat.st_mtime_ns else (self._hash(path) if full_hash else "")
                    if not digest:
                        digest = self._hash(path)
                    db.execute("INSERT OR REPLACE INTO files(path,size,mtime_ns,sha256) VALUES(?,?,?,?)", (relative, stat.st_size, stat.st_mtime_ns, digest))
                    count += 1
                except OSError:
                    continue
            db.execute("DELETE FROM files WHERE path NOT IN ({})".format(",".join("?" for _ in seen)) if seen else "DELETE FROM files", tuple(seen))
            db.commit()
        return count

    def search(self, pattern: str) -> list[dict]:
        with sqlite3.connect(self.database) as db:
            db.row_factory = sqlite3.Row
            rows = db.execute("SELECT path,size,mtime_ns,sha256 FROM files WHERE path LIKE ? ESCAPE '\\' ORDER BY path", (f"%{pattern.replace('%', r'\%').replace('_', r'\_')}%",)).fetchall()
            return [dict(row) for row in rows]

    def duplicates(self) -> list[list[str]]:
        with sqlite3.connect(self.database) as db:
            rows = db.execute("SELECT sha256, GROUP_CONCAT(path, char(10)) FROM files GROUP BY sha256 HAVING COUNT(*) > 1").fetchall()
        return [str(paths).split("\n") for _, paths in rows]

    def information(self) -> dict:
        with sqlite3.connect(self.database) as db:
            count, total = db.execute("SELECT COUNT(*), COALESCE(SUM(size),0) FROM files").fetchone()
        return {"database": str(self.database), "indexed_files": count, "indexed_bytes": total}
