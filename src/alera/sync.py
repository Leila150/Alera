"""Local directory synchronization."""
from __future__ import annotations

import hashlib
import shutil
from pathlib import Path


class SyncManager:
    """Compare and synchronize directories with dry-run support."""

    @staticmethod
    def _files(root: Path) -> dict[str, Path]:
        return {str(path.relative_to(root)): path for path in root.rglob("*") if path.is_file() and ".alera_" not in path.parts}

    @staticmethod
    def _hash(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def compare(self, source: str | Path, destination: str | Path) -> dict:
        left, right = Path(source).expanduser().resolve(), Path(destination).expanduser().resolve()
        if not left.is_dir() or not right.is_dir():
            raise NotADirectoryError("Both source and destination must be directories")
        a, b = self._files(left), self._files(right)
        added = sorted(set(a) - set(b))
        removed = sorted(set(b) - set(a))
        modified = sorted(k for k in set(a) & set(b) if a[k].stat().st_size != b[k].stat().st_size or self._hash(a[k]) != self._hash(b[k]))
        return {"added": added, "removed": removed, "modified": modified}

    def sync(self, source: str | Path, destination: str | Path, delete_extra: bool = False, dry_run: bool = False) -> dict:
        left, right = Path(source).expanduser().resolve(), Path(destination).expanduser().resolve()
        if not left.is_dir():
            raise NotADirectoryError(left)
        if left == right:
            raise ValueError("Source and destination must differ")
        right.mkdir(parents=True, exist_ok=True)
        changes = self.compare(left, right)
        if dry_run:
            return changes
        for relative in changes["added"] + changes["modified"]:
            target = right / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(left / relative, target)
        if delete_extra:
            for relative in changes["removed"]:
                target = right / relative
                if target.is_file() or target.is_symlink():
                    target.unlink()
        return changes
