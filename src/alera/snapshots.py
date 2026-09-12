"""Lightweight directory snapshots and change detection."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from .exceptions import AleraPathError

class SnapshotManager:
    """Capture directory manifests and compare them later."""
    def __init__(self, base_path: str | Path = "") -> None:
        self.base_path = (Path(base_path).expanduser() if str(base_path) else Path.cwd()).resolve()
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _path(self, value: str | Path) -> Path:
        target = (self.base_path / value).resolve() if not Path(value).is_absolute() else Path(value).resolve()
        try: target.relative_to(self.base_path)
        except ValueError as exc: raise AleraPathError(f"Path escapes snapshot workspace: {value}") from exc
        return target

    def create(self, directory: str | Path = ".") -> dict[str, dict[str, object]]:
        root = self._path(directory)
        if not root.is_dir(): raise NotADirectoryError(root)
        result: dict[str, dict[str, object]] = {}
        for item in root.rglob("*"):
            if item.is_file():
                stat = item.stat()
                digest = hashlib.sha256(item.read_bytes()).hexdigest()
                result[str(item.relative_to(root))] = {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns, "sha256": digest}
        return result

    @staticmethod
    def save(snapshot: dict[str, dict[str, object]], file: str | Path) -> Path:
        target = Path(file).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(snapshot, indent=2, sort_keys=True), encoding="utf-8")
        return target

    @staticmethod
    def load(file: str | Path) -> dict[str, dict[str, object]]:
        return json.loads(Path(file).expanduser().read_text(encoding="utf-8"))

    @staticmethod
    def compare(old: dict[str, dict[str, object]], new: dict[str, dict[str, object]]) -> dict[str, list[str]]:
        old_keys, new_keys = set(old), set(new)
        added = sorted(new_keys - old_keys)
        removed = sorted(old_keys - new_keys)
        modified = sorted(key for key in old_keys & new_keys if old[key].get("sha256") != new[key].get("sha256"))
        return {"added": added, "removed": removed, "modified": modified}
