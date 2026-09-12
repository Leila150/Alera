"""Local directory synchronization."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path


class SyncManager:
    def _files(self, root: Path) -> dict[str, Path]:
        return {str(p.relative_to(root)): p for p in root.rglob("*") if p.is_file()}

    @staticmethod
    def _hash(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def compare(self, source: str | Path, destination: str | Path) -> dict:
        left, right = Path(source).resolve(), Path(destination).resolve()
        a, b = self._files(left), self._files(right)
        added = sorted(set(a) - set(b))
        removed = sorted(set(b) - set(a))
        modified = sorted(k for k in set(a) & set(b) if a[k].stat().st_size != b[k].stat().st_size or self._hash(a[k]) != self._hash(b[k]))
        return {"added": added, "removed": removed, "modified": modified}

    def sync(self, source: str | Path, destination: str | Path, delete_extra: bool = False, dry_run: bool = False) -> dict:
        left, right = Path(source).resolve(), Path(destination).resolve()
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
                (right / relative).unlink(missing_ok=True)
        return changes
