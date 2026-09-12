"""Advanced recycle-bin management for Alera."""
from __future__ import annotations

import json
import os
import shutil
import time
import uuid
from pathlib import Path
from typing import Iterable

from .exceptions import AleraBinError, AleraPathError, AleraValidationError


class RecycleBin:
    """A metadata-backed, quota-aware, conflict-safe recycle bin.

    Items are stored under ``.alera_bin`` and accompanied by a manifest. The
    manager never treats the bin itself as ordinary user data.
    """

    MANIFEST = "manifest.json"
    INTERNAL = {"manifest.json", ".manifest.tmp"}

    def __init__(self, base_path: str | os.PathLike[str] = "", *, quota_bytes: int | None = None) -> None:
        raw = Path(base_path).expanduser() if str(base_path) else Path.cwd()
        self.base_path = raw.resolve()
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.bin_path = self.base_path / ".alera_bin"
        self.bin_path.mkdir(exist_ok=True)
        self.quota_bytes = quota_bytes
        self._manifest_path = self.bin_path / self.MANIFEST
        self._manifest = self._load()
        self._repair_manifest()

    def _load(self) -> dict[str, dict[str, object]]:
        try:
            data = json.loads(self._manifest_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError, TypeError):
            return {}

    def _save(self) -> None:
        temp = self.bin_path / ".manifest.tmp"
        temp.write_text(json.dumps(self._manifest, indent=2, sort_keys=True), encoding="utf-8")
        with temp.open("r+b") as handle:
            handle.flush(); os.fsync(handle.fileno())
        os.replace(temp, self._manifest_path)

    def _repair_manifest(self) -> None:
        changed = False
        actual = {p.name for p in self.bin_path.iterdir() if p.name not in self.INTERNAL}
        for item_id in list(self._manifest):
            stored = str(self._manifest[item_id].get("stored_name", ""))
            if not stored or stored not in actual:
                del self._manifest[item_id]; changed = True
        for stored in actual:
            if not any(str(meta.get("stored_name")) == stored for meta in self._manifest.values()):
                item_id = uuid.uuid4().hex
                path = self.bin_path / stored
                self._manifest[item_id] = {
                    "id": item_id, "stored_name": stored, "original_name": stored,
                    "original_path": str(self.base_path / stored), "deleted_at": path.stat().st_mtime,
                    "type": "directory" if path.is_dir() else "file", "size": self._size(path),
                }
                changed = True
        if changed: self._save()

    def _resolve_user_path(self, value: str | os.PathLike[str]) -> Path:
        candidate = Path(value).expanduser()
        target = candidate.resolve() if candidate.is_absolute() else (self.base_path / candidate).resolve()
        try: target.relative_to(self.base_path)
        except ValueError as exc: raise AleraPathError(f"Path escapes recycle-bin workspace: {value}") from exc
        if target == self.bin_path or self.bin_path in target.parents:
            raise AleraPathError("The recycle bin cannot contain itself.")
        return target

    @staticmethod
    def _size(path: Path) -> int:
        if path.is_file():
            try: return path.stat().st_size
            except OSError: return 0
        total = 0
        try:
            for child in path.rglob("*"):
                if child.is_file():
                    try: total += child.stat().st_size
                    except OSError: pass
        except OSError: pass
        return total

    def _stored(self, item_id: str) -> Path:
        meta = self._manifest.get(item_id)
        if not meta: raise FileNotFoundError(item_id)
        name = str(meta.get("stored_name", ""))
        path = (self.bin_path / name).resolve()
        try: path.relative_to(self.bin_path.resolve())
        except ValueError as exc: raise AleraBinError("Invalid recycle-bin manifest entry.") from exc
        return path

    def add(self, path: str | os.PathLike[str], *, display_name: str | None = None) -> dict[str, object]:
        """Move an item into the bin and record its original location."""
        source = self._resolve_user_path(path)
        if not source.exists(): raise FileNotFoundError(source)
        item_id = uuid.uuid4().hex
        stored_name = f"{item_id}__{source.name}"
        destination = self.bin_path / stored_name
        try: shutil.move(str(source), str(destination))
        except OSError as exc: raise AleraBinError(f"Could not move {source} into the recycle bin.") from exc
        metadata = {
            "id": item_id, "stored_name": stored_name, "original_name": display_name or source.name,
            "original_path": str(source), "deleted_at": time.time(),
            "type": "directory" if destination.is_dir() else "file", "size": self._size(destination),
        }
        self._manifest[item_id] = metadata
        self._save()
        self.enforce_quota()
        return metadata.copy()

    def items(self, *, newest_first: bool = True) -> list[dict[str, object]]:
        result = []
        for item_id, metadata in self._manifest.items():
            item = metadata.copy(); item["id"] = item_id
            path = self._stored(item_id)
            if path.exists():
                item["size"] = self._size(path); item["age"] = max(0.0, time.time() - float(item.get("deleted_at", path.stat().st_mtime)))
            result.append(item)
        result.sort(key=lambda item: float(item.get("deleted_at", 0)), reverse=newest_first)
        return result

    def information(self, item_id: str | None = None) -> dict[str, object] | list[dict[str, object]]:
        if item_id is None:
            items = self.items()
            return {"path": str(self.bin_path), "items": len(items), "size": sum(int(i.get("size", 0)) for i in items), "quota": self.quota_bytes, "free_quota": None if self.quota_bytes is None else max(0, self.quota_bytes - sum(int(i.get("size", 0)) for i in items))}
        return next(item for item in self.items() if item["id"] == item_id)

    def restore(self, item_id: str, *, conflict: str = "rename") -> Path:
        """Restore an item. Conflict modes: ``rename``, ``replace``, or ``error``."""
        if conflict not in {"rename", "replace", "error"}: raise AleraValidationError("conflict must be rename, replace, or error")
        item = dict(self.information(item_id)); source = self._stored(item_id)
        destination = Path(str(item["original_path"]))
        try: destination.relative_to(self.base_path)
        except ValueError as exc: raise AleraBinError("Manifest restore path escapes the workspace.") from exc
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists() or destination.is_symlink():
            if conflict == "error": raise FileExistsError(destination)
            if conflict == "replace":
                if destination.is_dir() and not destination.is_symlink(): shutil.rmtree(destination)
                else: destination.unlink()
            else:
                original = destination
                index = 1
                while destination.exists() or destination.is_symlink():
                    destination = original.with_name(f"{original.stem} (restored {index}){original.suffix}"); index += 1
        try: shutil.move(str(source), str(destination))
        except OSError as exc: raise AleraBinError(f"Could not restore {item_id}.") from exc
        del self._manifest[item_id]; self._save()
        return destination

    def restore_many(self, item_ids: Iterable[str], *, conflict: str = "rename") -> list[Path]:
        return [self.restore(item_id, conflict=conflict) for item_id in item_ids]

    def purge(self, item_id: str) -> dict[str, object]:
        """Permanently remove one bin item."""
        item = dict(self.information(item_id)); path = self._stored(item_id)
        try:
            if path.is_dir() and not path.is_symlink(): shutil.rmtree(path)
            else: path.unlink()
        except OSError as exc: raise AleraBinError(f"Could not permanently remove {item_id}.") from exc
        del self._manifest[item_id]; self._save(); return item

    def purge_many(self, item_ids: Iterable[str]) -> list[dict[str, object]]: return [self.purge(item_id) for item_id in item_ids]

    def empty(self) -> list[dict[str, object]]:
        return self.purge_many([str(item["id"]) for item in self.items()])

    def purge_older_than(self, seconds: float) -> list[dict[str, object]]:
        if seconds < 0: raise AleraValidationError("seconds cannot be negative")
        cutoff = time.time() - seconds
        return self.purge_many([str(i["id"]) for i in self.items() if float(i.get("deleted_at", 0)) < cutoff])

    def enforce_quota(self) -> list[dict[str, object]]:
        if self.quota_bytes is None: return []
        removed = []
        total = sum(int(i.get("size", 0)) for i in self.items())
        for item in reversed(self.items()):
            if total <= self.quota_bytes: break
            removed.append(self.purge(str(item["id"]))); total -= int(item.get("size", 0))
        return removed

    def search(self, query: str) -> list[dict[str, object]]:
        needle = query.casefold()
        return [item for item in self.items() if needle in str(item.get("original_name", "")).casefold() or needle in str(item.get("original_path", "")).casefold()]

    def refresh(self) -> dict[str, object]:
        self._manifest = self._load(); self._repair_manifest(); return self.information()  # type: ignore[return-value]

    def clear(self) -> list[dict[str, object]]: return self.empty()
