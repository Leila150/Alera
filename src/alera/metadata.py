"""Rich filesystem metadata utilities."""
from __future__ import annotations

import hashlib
import mimetypes
import os
import stat
from pathlib import Path
from typing import Any


class MetadataManager:
    """Inspect files without changing their contents."""

    def __init__(self, base_path: str | Path = "") -> None:
        self.base_path = (Path(base_path).expanduser() if str(base_path) else Path.cwd()).resolve()
        self.base_path.mkdir(parents=True, exist_ok=True)

    def path(self, value: str | Path) -> Path:
        p = (self.base_path / value).resolve() if not Path(value).is_absolute() else Path(value).resolve()
        p.relative_to(self.base_path)
        return p

    def information(self, value: str | Path) -> dict[str, Any]:
        p = self.path(value)
        s = p.stat()
        return {
            "path": p,
            "name": p.name,
            "size": s.st_size,
            "mode": stat.S_IMODE(s.st_mode),
            "permissions": oct(stat.S_IMODE(s.st_mode)),
            "created": s.st_ctime,
            "modified": s.st_mtime,
            "accessed": s.st_atime,
            "is_file": p.is_file(),
            "is_directory": p.is_dir(),
            "is_symlink": p.is_symlink(),
            "mime_type": mimetypes.guess_type(p.name)[0],
            "extension": p.suffix,
            "stem": p.stem,
        }

    def hash(self, value: str | Path, algorithm: str = "sha256") -> str:
        h = hashlib.new(algorithm)
        with self.path(value).open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()

    def owner(self, value: str | Path) -> dict[str, Any]:
        p = self.path(value)
        s = p.stat()
        result: dict[str, Any] = {"uid": getattr(s, "st_uid", None), "gid": getattr(s, "st_gid", None)}
        try:
            import pwd, grp
            result["user"] = pwd.getpwuid(s.st_uid).pw_name
            result["group"] = grp.getgrgid(s.st_gid).gr_name
        except (ImportError, KeyError, AttributeError):
            result["user"] = None
            result["group"] = None
        return result

    def set_read_only(self, value: str | Path) -> Path:
        p = self.path(value)
        p.chmod(p.stat().st_mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
        return p

    def set_writable(self, value: str | Path) -> Path:
        p = self.path(value)
        p.chmod(p.stat().st_mode | stat.S_IWUSR)
        return p
