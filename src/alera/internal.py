"""Centralized private storage for Alera."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Iterator


class AleraStorage:
    """Manage Alera's single hidden runtime directory."""

    ROOT_NAME = ".alera"
    DIRECTORIES = (
        "bin", "hidden", "cache", "index", "database", "recovery", "versions",
        "snapshots", "transactions", "locks", "archives", "backups", "sync",
        "watcher", "security", "temp", "search", "logs", "crash_logs",
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
        for name in self.DIRECTORIES:
            (self.root / name).mkdir(parents=True, exist_ok=True)
        if migrate_legacy:
            self.migrate_legacy()

    def path(self, name: str = "") -> Path:
        target = (self.root / name).resolve()
        try:
            target.relative_to(self.root.resolve())
        except ValueError as exc:
            raise ValueError("Alera internal path escapes .alera") from exc
        return target

    def exists(self, name: str) -> bool:
        return self.path(name).exists()

    def ensure(self, name: str) -> Path:
        target = self.path(name)
        target.mkdir(parents=True, exist_ok=True)
        return target

    def migrate_legacy(self) -> dict[str, int]:
        moved: dict[str, int] = {}
        for legacy_name, subsystem in self.LEGACY_MAP.items():
            source = self.base_path / legacy_name
            target = self.root / subsystem
            count = 0
            if not source.exists():
                moved[subsystem] = 0
                continue
            try:
                for child in list(source.iterdir()):
                    destination = target / child.name
                    if destination.exists():
                        continue
                    shutil.move(str(child), str(destination))
                    count += 1
                try:
                    source.rmdir()
                except OSError:
                    pass
            except OSError:
                pass
            moved[subsystem] = count
        return moved

    def iter_subsystems(self) -> Iterator[Path]:
        for name in self.DIRECTORIES:
            yield self.root / name

    def information(self) -> dict[str, object]:
        total = 0
        counts: dict[str, int] = {}
        for directory in self.iter_subsystems():
            count = 0
            for root, dirs, files in os.walk(directory, followlinks=False):
                count += len(dirs) + len(files)
                for filename in files:
                    try:
                        total += (Path(root) / filename).stat().st_size
                    except OSError:
                        pass
            counts[directory.name] = count
        return {"root": str(self.root), "subsystems": list(self.DIRECTORIES), "objects": counts, "size": total}

    def atomic_json_write(self, name: str, data: object) -> Path:
        target = self.path(name)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
        return target

    def marker(self, name: str, **data: object) -> Path:
        return self.atomic_json_write(f"logs/{name}.json", {"time": time.time(), **data})

    def clear(self, subsystem: str, *, keep: set[str] | None = None) -> int:
        target = self.ensure(subsystem)
        keep = keep or set()
        removed = 0
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
