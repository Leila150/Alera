"""Advanced directory operations."""
from __future__ import annotations
import os
import shutil
from pathlib import Path
from .exceptions import AleraPathError, AleraValidationError

class DirectoryTools:
    """Copy, synchronize, flatten, clean, and compare directories."""
    def __init__(self, base_path: str | os.PathLike[str] = "") -> None:
        self.base_path = (Path(base_path).expanduser() if str(base_path) else Path.cwd()).resolve()
        self.base_path.mkdir(parents=True, exist_ok=True)

    def path(self, value: str | os.PathLike[str]) -> Path:
        target = (self.base_path / value).resolve() if not Path(value).is_absolute() else Path(value).resolve()
        try: target.relative_to(self.base_path)
        except ValueError as exc: raise AleraPathError(f"Path escapes directory workspace: {value}") from exc
        return target

    def copy(self, source: str | os.PathLike[str], destination: str | os.PathLike[str]) -> Path:
        src, dst = self.path(source), self.path(destination)
        if src.is_dir(): shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(src, dst)
        return dst

    def synchronize(self, source: str | os.PathLike[str], destination: str | os.PathLike[str], *, delete_extra: bool = False) -> dict[str, int]:
        src, dst = self.path(source), self.path(destination)
        if not src.is_dir(): raise NotADirectoryError(src)
        dst.mkdir(parents=True, exist_ok=True)
        copied = deleted = 0
        for item in src.rglob("*"):
            relative = item.relative_to(src); target = dst / relative
            if item.is_dir(): target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.exists() or item.stat().st_mtime_ns > target.stat().st_mtime_ns or item.stat().st_size != target.stat().st_size:
                    shutil.copy2(item, target); copied += 1
        if delete_extra:
            for item in sorted(dst.rglob("*"), reverse=True):
                if not (src / item.relative_to(dst)).exists():
                    if item.is_dir(): item.rmdir()
                    else: item.unlink()
                    deleted += 1
        return {"copied": copied, "deleted": deleted}

    def clean_empty(self, directory: str | os.PathLike[str] = ".") -> list[Path]:
        root = self.path(directory)
        removed = []
        for item in sorted(root.rglob("*"), reverse=True):
            if item.is_dir() and not any(item.iterdir()): item.rmdir(); removed.append(item)
        return removed

    def extensions(self, directory: str | os.PathLike[str] = ".") -> dict[str, int]:
        root = self.path(directory); result: dict[str, int] = {}
        for item in root.rglob("*"):
            if item.is_file(): result[item.suffix.lower() or "[no extension]"] = result.get(item.suffix.lower() or "[no extension]", 0) + 1
        return dict(sorted(result.items()))
