"""Centralized, transactional private storage for Alera."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
import time
from pathlib import Path
from typing import Iterator


class AleraStorage:
    """Manage Alera's single private runtime directory and its subsystems."""

    ROOT_NAME = ".alera"
    SCHEMA_VERSION = 1
    DIRECTORIES = (
        "bin", "hidden", "cache", "index", "database", "recovery", "versions",
        "snapshots", "transactions", "locks", "archives", "backups", "sync",
        "watcher", "security", "temp", "search", "logs", "crash_logs", "config",
    )
    LEGACY_MAP = {
        ".alera_bin": "bin", ".alera_hidden": "hidden", ".alera_cache": "cache",
        ".alera_index": "index", ".alera_database": "database",
        ".alera_recovery": "recovery", ".alera_versions": "versions",
    }

    def __init__(self, base_path: str | os.PathLike[str] = "", *, migrate_legacy: bool = True) -> None:
        raw = Path(base_path).expanduser() if str(base_path) else Path.cwd()
        self.base_path = raw.resolve()
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.root = self.base_path / self.ROOT_NAME
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        for name in self.DIRECTORIES:
            (self.root / name).mkdir(parents=True, exist_ok=True)
        self._write_schema_marker()
        if migrate_legacy:
            self.migrate_legacy()

    def _write_schema_marker(self) -> None:
        marker = self.root / ".schema"
        if marker.exists():
            return
        try:
            marker.write_text(str(self.SCHEMA_VERSION), encoding="ascii")
        except OSError:
            pass

    def path(self, name: str = "") -> Path:
        target = (self.root / name).resolve()
        try:
            target.relative_to(self.root.resolve())
        except ValueError as exc:
            raise ValueError("Alera internal path escapes .alera") from exc
        return target

    def relative(self, path: str | os.PathLike[str]) -> str:
        target = Path(path).expanduser().resolve()
        try:
            return target.relative_to(self.root.resolve()).as_posix()
        except ValueError as exc:
            raise ValueError("path is outside Alera internal storage") from exc

    def is_internal(self, path: str | os.PathLike[str]) -> bool:
        try:
            self.relative(path)
            return True
        except ValueError:
            return False

    def subsystem(self, name: str) -> Path:
        if name not in self.DIRECTORIES:
            raise ValueError(f"Unknown Alera subsystem: {name}")
        return self.path(name)

    def exists(self, name: str = "") -> bool:
        return self.path(name).exists()

    def ensure(self, name: str) -> Path:
        target = self.path(name)
        target.mkdir(parents=True, exist_ok=True)
        return target

    @staticmethod
    def _merge_tree(source: Path, target: Path) -> int:
        moved = 0
        target.mkdir(parents=True, exist_ok=True)
        for child in list(source.iterdir()):
            destination = target / child.name
            try:
                if destination.exists() and child.is_dir() and destination.is_dir() and not child.is_symlink():
                    moved += AleraStorage._merge_tree(child, destination)
                    try:
                        child.rmdir()
                    except OSError:
                        pass
                elif destination.exists():
                    continue
                else:
                    shutil.move(str(child), str(destination))
                    moved += 1
            except OSError:
                pass
        return moved

    def migrate_legacy(self) -> dict[str, int]:
        moved: dict[str, int] = {}
        with self._lock:
            for legacy_name, subsystem in self.LEGACY_MAP.items():
                source = self.base_path / legacy_name
                target = self.root / subsystem
                if not source.exists():
                    moved[subsystem] = 0
                    continue
                try:
                    count = self._merge_tree(source, target)
                    try:
                        source.rmdir()
                    except OSError:
                        pass
                except OSError:
                    count = 0
                moved[subsystem] = count
        return moved

    def iter_subsystems(self) -> Iterator[tuple[str, Path]]:
        for name in self.DIRECTORIES:
            yield name, self.root / name

    def information(self) -> dict[str, object]:
        total = 0
        counts: dict[str, int] = {}
        for name, directory in self.iter_subsystems():
            count = 0
            try:
                for root, dirs, files in os.walk(directory, followlinks=False):
                    count += len(dirs) + len(files)
                    for filename in files:
                        try:
                            total += (Path(root) / filename).lstat().st_size
                        except OSError:
                            pass
            except OSError:
                pass
            counts[name] = count
        return {
            "schema": self.SCHEMA_VERSION,
            "root": str(self.root),
            "subsystems": list(self.DIRECTORIES),
            "objects": counts,
            "size": total,
        }

    def atomic_bytes_write(self, name: str, data: bytes) -> Path:
        target = self.path(name)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(bytes(data))
                handle.flush()
                try:
                    os.fsync(handle.fileno())
                except OSError:
                    pass
            os.replace(temporary, target)
            self._fsync_directory(target.parent)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
        return target

    def atomic_json_write(self, name: str, data: object) -> Path:
        return self.atomic_bytes_write(
            name,
            json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True, default=str).encode("utf-8"),
        )

    def read_json(self, name: str, default: object = None) -> object:
        target = self.path(name)
        try:
            return json.loads(target.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return default

    def marker(self, name: str, **data: object) -> Path:
        return self.atomic_json_write(f"logs/{name}.json", {"schema": 1, "time": time.time(), **data})

    def clear(self, subsystem: str, *, keep: set[str] | None = None) -> int:
        target = self.subsystem(subsystem)
        keep = keep or set()
        removed = 0
        with self._lock:
            for child in list(target.iterdir()):
                if child.name in keep:
                    continue
                try:
                    if child.is_dir() and not child.is_symlink():
                        shutil.rmtree(child)
                    else:
                        child.unlink()
                    removed += 1
                except OSError:
                    pass
        return removed

    def prune_empty(self, subsystem: str, *, max_depth: int | None = None) -> int:
        root = self.subsystem(subsystem)
        removed = 0
        candidates: list[Path] = []
        for directory, dirs, _ in os.walk(root, topdown=False):
            path = Path(directory)
            if path == root:
                continue
            if max_depth is not None and len(path.relative_to(root).parts) > max_depth:
                continue
            candidates.append(path)
        for path in candidates:
            try:
                path.rmdir()
                removed += 1
            except OSError:
                pass
        return removed

    @staticmethod
    def _fsync_directory(directory: Path) -> None:
        if os.name == "nt":
            return
        try:
            fd = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        except OSError:
            pass
