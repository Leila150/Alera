"""SQLite-backed filesystem metadata index."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path


class FileDatabase:
    def __init__(self, base_path: str | Path = "", database: str | Path | None = None) -> None:
        self.base = Path(base_path or ".").expanduser().resolve()
        self.database = Path(database or self.base / ".alera_index.db").expanduser().resolve()
        self.database.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.database) as db:
            db.execute("CREATE TABLE IF NOT EXISTS files (path TEXT PRIMARY KEY, size INTEGER, mtime REAL, sha256 TEXT)")
            db.commit()

    @staticmethod
    def _hash(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""): digest.update(chunk)
        return digest.hexdigest()

    def index(self) -> int:
        count = 0
        with sqlite3.connect(self.database) as db:
            for path in self.base.rglob("*"):
                if not path.is_file() or path == self.database: continue
                stat = path.stat(); relative = str(path.relative_to(self.base))
                db.execute("INSERT OR REPLACE INTO files(path,size,mtime,sha256) VALUES(?,?,?,?)", (relative, stat.st_size, stat.st_mtime, self._hash(path)))
                count += 1
            db.commit()
        return count

    def search(self, pattern: str) -> list[dict]:
        with sqlite3.connect(self.database) as db:
            db.row_factory = sqlite3.Row
            rows = db.execute("SELECT * FROM files WHERE path LIKE ? ORDER BY path", (f"%{pattern}%",)).fetchall()
            return [dict(row) for row in rows]

    def information(self) -> dict:
        with sqlite3.connect(self.database) as db:
            count = db.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        return {"database": str(self.database), "indexed_files": count}
