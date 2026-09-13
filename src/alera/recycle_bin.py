"""Maximum-feature recycle-bin management for Alera."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import time
import uuid
from pathlib import Path
from typing import Iterable, Iterator

from .exceptions import AleraBinError, AleraPathError, AleraValidationError


class RecycleBin:
    """Durable, metadata-rich, integrity-aware recycle bin.

    Deleted objects are moved into ``.alera_bin`` rather than destroyed.
    Metadata is journaled atomically and includes the original path, type,
    timestamps, size, hashes, labels, pin state and optional expiration.
    """

    MANIFEST = "manifest.json"
    JOURNAL = "journal.jsonl"
    SCHEMA_VERSION = 2
    INTERNAL = frozenset({MANIFEST, ".manifest.tmp", JOURNAL, ".journal.tmp"})

    def __init__(self, base_path: str | os.PathLike[str] = "", *, quota_bytes: int | None = None,
                 hash_algorithm: str = "sha256", hash_on_add: bool = True) -> None:
        raw = Path(base_path).expanduser() if str(base_path) else Path.cwd()
        self.base_path = raw.resolve()
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.bin_path = self.base_path / ".alera_bin"
        self.bin_path.mkdir(parents=True, exist_ok=True)
        self.quota_bytes = self._validate_quota(quota_bytes)
        self.hash_algorithm = self._validate_hash(hash_algorithm)
        self.hash_on_add = bool(hash_on_add)
        self._manifest_path = self.bin_path / self.MANIFEST
        self._journal_path = self.bin_path / self.JOURNAL
        self._manifest = self._load()
        self._repair_manifest()

    @staticmethod
    def _validate_quota(value):
        if value is not None and (not isinstance(value, int) or value < 0):
            raise AleraValidationError("quota_bytes must be a non-negative integer or None")
        return value

    @staticmethod
    def _validate_hash(algorithm: str) -> str:
        try:
            hashlib.new(algorithm)
        except ValueError as exc:
            raise AleraValidationError(f"Unsupported hash algorithm: {algorithm}") from exc
        return algorithm

    def _load(self) -> dict[str, dict[str, object]]:
        try:
            data = json.loads(self._manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return {}
        if isinstance(data, dict) and isinstance(data.get("items"), dict):
            return dict(data["items"])
        if isinstance(data, dict):
            return data
        return {}

    def _save(self) -> None:
        payload = {"schema_version": self.SCHEMA_VERSION, "updated_at": time.time(), "items": self._manifest}
        fd, temporary = tempfile.mkstemp(prefix=".manifest.", dir=self.bin_path)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, sort_keys=True)
                handle.flush(); os.fsync(handle.fileno())
            os.replace(temporary, self._manifest_path)
            self._fsync_dir(self.bin_path)
        finally:
            try: os.unlink(temporary)
            except FileNotFoundError: pass

    @staticmethod
    def _fsync_dir(path: Path) -> None:
        try:
            fd = os.open(path, os.O_RDONLY)
            try: os.fsync(fd)
            finally: os.close(fd)
        except OSError:
            pass

    def _journal(self, operation: str, **data: object) -> None:
        record = {"time": time.time(), "operation": operation, **data}
        try:
            with self._journal_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, sort_keys=True) + "\n")
                handle.flush(); os.fsync(handle.fileno())
        except OSError:
            pass

    def history(self, *, operation: str | None = None, limit: int | None = None) -> list[dict[str, object]]:
        if limit is not None and limit < 0:
            raise AleraValidationError("limit cannot be negative")
        records: list[dict[str, object]] = []
        try:
            lines = self._journal_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        for line in reversed(lines):
            try: record = json.loads(line)
            except ValueError: continue
            if operation is not None and record.get("operation") != operation: continue
            records.append(record)
            if limit is not None and len(records) >= limit: break
        return records

    def _repair_manifest(self) -> None:
        changed = False
        actual = {p.name for p in self.bin_path.iterdir() if p.name not in self.INTERNAL}
        known = {str(meta.get("stored_name")) for meta in self._manifest.values()}
        for item_id in list(self._manifest):
            meta = self._manifest[item_id]
            stored = str(meta.get("stored_name", ""))
            if not stored or stored not in actual:
                del self._manifest[item_id]; changed = True
        for stored in actual - known:
            path = self.bin_path / stored
            item_id = uuid.uuid4().hex
            self._manifest[item_id] = self._metadata_from_path(
                path, item_id=item_id, original_name=stored, original_path=str(self.base_path / stored),
                deleted_at=path.stat().st_mtime)
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

    def _stored(self, item_id: str) -> Path:
        meta = self._manifest.get(str(item_id))
        if not meta: raise FileNotFoundError(item_id)
        stored = str(meta.get("stored_name", ""))
        path = (self.bin_path / stored).resolve()
        try: path.relative_to(self.bin_path.resolve())
        except ValueError as exc: raise AleraBinError("Invalid recycle-bin manifest entry.") from exc
        return path

    @staticmethod
    def _size(path: Path) -> int:
        try:
            if path.is_file(): return path.stat().st_size
            total = 0
            for root, _, files in os.walk(path, followlinks=False):
                for name in files:
                    try: total += (Path(root) / name).stat().st_size
                    except OSError: pass
            return total
        except OSError:
            return 0

    def _hash_path(self, path: Path, algorithm: str | None = None) -> str | None:
        algorithm = algorithm or self.hash_algorithm
        try: digest = hashlib.new(algorithm)
        except ValueError: return None
        try:
            if path.is_file():
                with path.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""): digest.update(chunk)
            elif path.is_dir():
                for root, dirs, files in os.walk(path, followlinks=False):
                    dirs.sort(); files.sort()
                    for name in files:
                        child = Path(root) / name
                        digest.update(str(child.relative_to(path)).replace(os.sep, "/").encode())
                        with child.open("rb") as handle:
                            for chunk in iter(lambda: handle.read(1024 * 1024), b""): digest.update(chunk)
            else:
                return None
            return digest.hexdigest()
        except OSError:
            return None

    def _metadata_from_path(self, path: Path, *, item_id: str, original_name: str,
                            original_path: str, deleted_at: float | None = None) -> dict[str, object]:
        try: stat_info = path.stat(follow_symlinks=False)
        except OSError: stat_info = None
        return {
            "id": item_id,
            "stored_name": path.name,
            "original_name": original_name,
            "original_path": original_path,
            "deleted_at": deleted_at if deleted_at is not None else time.time(),
            "type": "directory" if path.is_dir() else "symlink" if path.is_symlink() else "file",
            "size": self._size(path),
            "modified_at": getattr(stat_info, "st_mtime", None),
            "mode": getattr(stat_info, "st_mode", None),
            "inode": getattr(stat_info, "st_ino", None),
            "device": getattr(stat_info, "st_dev", None),
            "hash_algorithm": self.hash_algorithm if self.hash_on_add else None,
            "hash": self._hash_path(path) if self.hash_on_add else None,
            "labels": [],
            "note": "",
            "pinned": False,
            "expires_at": None,
        }

    def add(self, path: str | os.PathLike[str], *, display_name: str | None = None,
            labels: Iterable[str] | None = None, note: str = "", pinned: bool = False,
            expires_in: float | None = None) -> dict[str, object]:
        """Move an item into the bin and atomically record its recovery metadata."""
        source = self._resolve_user_path(path)
        if not source.exists() and not source.is_symlink(): raise FileNotFoundError(source)
        item_id = uuid.uuid4().hex
        stored_name = f"{item_id}__{source.name}"
        destination = self.bin_path / stored_name
        try: shutil.move(str(source), str(destination))
        except OSError as exc: raise AleraBinError(f"Could not move {source} into the recycle bin.") from exc
        metadata = self._metadata_from_path(destination, item_id=item_id,
                                            original_name=display_name or source.name,
                                            original_path=str(source), deleted_at=time.time())
        metadata["labels"] = sorted({str(x) for x in (labels or []) if str(x).strip()})
        metadata["note"] = str(note)
        metadata["pinned"] = bool(pinned)
        if expires_in is not None:
            if expires_in < 0: raise AleraValidationError("expires_in cannot be negative")
            metadata["expires_at"] = time.time() + expires_in
        self._manifest[item_id] = metadata
        try:
            self._save(); self._journal("add", id=item_id, original_path=str(source), size=metadata["size"])
        except Exception:
            self._manifest.pop(item_id, None)
            try: shutil.move(str(destination), str(source))
            except OSError: pass
            raise
        self.enforce_quota()
        return metadata.copy()

    def _items(self, newest_first: bool = True) -> list[dict[str, object]]:
        result = []
        for item_id, metadata in self._manifest.items():
            item = metadata.copy(); item["id"] = item_id
            try:
                path = self._stored(item_id)
                if path.exists() or path.is_symlink():
                    item["size"] = self._size(path)
                    item["age"] = max(0.0, time.time() - float(item.get("deleted_at", 0)))
                    item["available"] = True
                else: item["available"] = False
            except (OSError, FileNotFoundError): item["available"] = False
            result.append(item)
        result.sort(key=lambda item: float(item.get("deleted_at", 0)), reverse=newest_first)
        return result

    def items(self, *, newest_first: bool = True) -> list[dict[str, object]]:
        return self._items(newest_first)

    def get(self, item_id: str) -> dict[str, object]:
        for item in self.items():
            if item["id"] == item_id: return item
        raise FileNotFoundError(item_id)

    def information(self, item_id: str | None = None):
        if item_id is not None: return self.get(item_id)
        items = self.items()
        total = sum(int(i.get("size", 0)) for i in items)
        pinned = sum(1 for i in items if i.get("pinned"))
        return {
            "path": str(self.bin_path), "items": len(items), "available_items": sum(bool(i.get("available")) for i in items),
            "size": total, "quota": self.quota_bytes,
            "free_quota": None if self.quota_bytes is None else max(0, self.quota_bytes - total),
            "pinned_items": pinned, "schema_version": self.SCHEMA_VERSION,
            "hash_algorithm": self.hash_algorithm,
        }

    def _destination(self, item: dict[str, object], conflict: str) -> Path:
        destination = self._resolve_user_path(str(item["original_path"]))
        if destination.exists() or destination.is_symlink():
            if conflict == "error": raise FileExistsError(destination)
            if conflict == "replace":
                if destination.is_dir() and not destination.is_symlink(): shutil.rmtree(destination)
                else: destination.unlink()
            elif conflict == "rename":
                original = destination; index = 1
                while destination.exists() or destination.is_symlink():
                    destination = original.with_name(f"{original.stem} (restored {index}){original.suffix}"); index += 1
            else: raise AleraValidationError("conflict must be rename, replace, or error")
        destination.parent.mkdir(parents=True, exist_ok=True)
        return destination

    def restore(self, item_id: str, *, conflict: str = "rename", verify: bool = True) -> Path:
        item = self.get(item_id); source = self._stored(item_id); destination = self._destination(item, conflict)
        if verify and item.get("hash"):
            current = self._hash_path(source, str(item.get("hash_algorithm") or self.hash_algorithm))
            if current != item.get("hash"): raise AleraBinError("Recycle-bin integrity check failed before restore.")
        try: shutil.move(str(source), str(destination))
        except OSError as exc: raise AleraBinError(f"Could not restore {item_id}.") from exc
        del self._manifest[item_id]; self._save(); self._journal("restore", id=item_id, destination=str(destination))
        return destination

    def restore_many(self, item_ids: Iterable[str], *, conflict: str = "rename", verify: bool = True) -> list[Path]:
        return [self.restore(item_id, conflict=conflict, verify=verify) for item_id in item_ids]

    def purge(self, item_id: str, *, force: bool = False) -> dict[str, object]:
        item = self.get(item_id)
        if item.get("pinned") and not force: raise AleraBinError("Pinned recycle-bin items require force=True to purge.")
        path = self._stored(item_id)
        try:
            if path.is_dir() and not path.is_symlink(): shutil.rmtree(path)
            else: path.unlink()
        except OSError as exc: raise AleraBinError(f"Could not permanently remove {item_id}.") from exc
        del self._manifest[item_id]; self._save(); self._journal("purge", id=item_id, size=item.get("size", 0))
        return item

    def purge_many(self, item_ids: Iterable[str], *, force: bool = False) -> list[dict[str, object]]:
        return [self.purge(item_id, force=force) for item_id in item_ids]

    def empty(self, *, force: bool = False) -> list[dict[str, object]]:
        return self.purge_many([str(item["id"]) for item in self.items() if force or not item.get("pinned")], force=force)

    def clear(self, *, force: bool = False) -> list[dict[str, object]]: return self.empty(force=force)

    def purge_older_than(self, seconds: float, *, force: bool = False) -> list[dict[str, object]]:
        if seconds < 0: raise AleraValidationError("seconds cannot be negative")
        cutoff = time.time() - seconds
        return self.purge_many([str(i["id"]) for i in self.items() if float(i.get("deleted_at", 0)) < cutoff and (force or not i.get("pinned"))], force=force)

    def expire(self, *, now: float | None = None, force: bool = False) -> list[dict[str, object]]:
        now = time.time() if now is None else now
        ids = [str(i["id"]) for i in self.items() if i.get("expires_at") is not None and float(i["expires_at"]) <= now and (force or not i.get("pinned"))]
        return self.purge_many(ids, force=force)

    def enforce_quota(self) -> list[dict[str, object]]:
        if self.quota_bytes is None: return []
        removed = []; total = sum(int(i.get("size", 0)) for i in self.items())
        for item in reversed(self.items()):
            if total <= self.quota_bytes: break
            if item.get("pinned"): continue
            removed.append(self.purge(str(item["id"]))); total -= int(item.get("size", 0))
        return removed

    def set_quota(self, quota_bytes: int | None, *, enforce: bool = True) -> list[dict[str, object]]:
        self.quota_bytes = self._validate_quota(quota_bytes)
        return self.enforce_quota() if enforce else []

    def pin(self, item_id: str, value: bool = True) -> dict[str, object]:
        item = self.get(item_id); self._manifest[item_id]["pinned"] = bool(value); self._save(); self._journal("pin", id=item_id, value=bool(value)); return self.get(item_id)

    def label(self, item_id: str, labels: Iterable[str]) -> dict[str, object]:
        item = self.get(item_id); self._manifest[item_id]["labels"] = sorted({str(x) for x in labels if str(x).strip()}); self._save(); return self.get(item_id)

    def note(self, item_id: str, text: str) -> dict[str, object]:
        self.get(item_id); self._manifest[item_id]["note"] = str(text); self._save(); return self.get(item_id)

    def set_expiration(self, item_id: str, expires_at: float | None) -> dict[str, object]:
        self.get(item_id); self._manifest[item_id]["expires_at"] = expires_at; self._save(); return self.get(item_id)

    def verify(self, item_id: str | None = None) -> dict[str, object] | list[dict[str, object]]:
        targets = [self.get(item_id)] if item_id is not None else self.items()
        result = []
        for item in targets:
            path = self._stored(str(item["id"])); expected = item.get("hash")
            actual = self._hash_path(path, str(item.get("hash_algorithm") or self.hash_algorithm)) if expected else None
            result.append({"id": item["id"], "exists": path.exists() or path.is_symlink(), "expected": expected, "actual": actual, "valid": bool(expected) and actual == expected})
        return result[0] if item_id is not None else result

    def repair(self) -> dict[str, object]:
        before = len(self._manifest); self._manifest = self._load(); self._repair_manifest()
        return {"before": before, "after": len(self._manifest), "removed_orphans": max(0, before - len(self._manifest))}

    def search(self, query: str = "", *, label: str | None = None, pinned: bool | None = None,
               type: str | None = None, minimum_size: int | None = None, maximum_size: int | None = None,
               limit: int | None = None) -> list[dict[str, object]]:
        if limit is not None and limit < 0: raise AleraValidationError("limit cannot be negative")
        needle = query.casefold(); result = []
        for item in self.items():
            if needle and needle not in str(item.get("original_name", "")).casefold() and needle not in str(item.get("original_path", "")).casefold() and needle not in str(item.get("note", "")).casefold(): continue
            if label is not None and label not in item.get("labels", []): continue
            if pinned is not None and bool(item.get("pinned")) != pinned: continue
            if type is not None and item.get("type") != type: continue
            size = int(item.get("size", 0))
            if minimum_size is not None and size < minimum_size: continue
            if maximum_size is not None and size > maximum_size: continue
            result.append(item)
            if limit is not None and len(result) >= limit: break
        return result

    def find_by_original_path(self, path: str | os.PathLike[str]) -> list[dict[str, object]]:
        target = str(self._resolve_user_path(path)); return [i for i in self.items() if str(i.get("original_path")) == target]

    def stats(self) -> dict[str, object]:
        items = self.items(); sizes = [int(i.get("size", 0)) for i in items]
        return {"items": len(items), "files": sum(i.get("type") == "file" for i in items), "directories": sum(i.get("type") == "directory" for i in items), "bytes": sum(sizes), "largest": max(sizes, default=0), "average": (sum(sizes) / len(sizes)) if sizes else 0, "pinned": sum(bool(i.get("pinned")) for i in items), "expired": sum(i.get("expires_at") is not None and float(i["expires_at"]) <= time.time() for i in items)}

    def export_manifest(self, destination: str | os.PathLike[str]) -> Path:
        target = Path(destination).expanduser(); target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({"schema_version": self.SCHEMA_VERSION, "items": self._manifest}, indent=2, sort_keys=True), encoding="utf-8")
        return target

    def refresh(self) -> dict[str, object]:
        self._manifest = self._load(); self._repair_manifest(); return self.information()
