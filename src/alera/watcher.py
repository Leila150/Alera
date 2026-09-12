"""Advanced polling-based filesystem watcher."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Callable


class FileWatcher:
    """Detect created, deleted, modified, moved, and attribute changes."""

    EVENTS = ("created", "deleted", "modified", "moved", "attribute_changed")

    def __init__(self, directory: str | Path = ".", recursive: bool = True, include_hidden: bool = True) -> None:
        self.root = Path(directory).expanduser().resolve()
        self.recursive = recursive
        self.include_hidden = include_hidden
        self._state: dict[Path, tuple[int, int, int, int]] = {}
        self._callbacks: dict[str, list[Callable[[Path], None]]] = {event: [] for event in self.EVENTS}

    def _visible(self, path: Path) -> bool:
        return self.include_hidden or not any(part.startswith(".") for part in path.relative_to(self.root).parts)

    def snapshot(self) -> dict[Path, tuple[int, int, int, int]]:
        if not self.root.is_dir():
            raise NotADirectoryError(self.root)
        paths = self.root.rglob("*") if self.recursive else self.root.iterdir()
        state = {}
        for path in paths:
            try:
                if path.is_file() and self._visible(path):
                    stat = path.stat()
                    state[path] = (stat.st_size, stat.st_mtime_ns, stat.st_mode, getattr(stat, "st_ino", 0))
            except OSError:
                continue
        return state

    def on(self, event: str, callback: Callable[[Path], None]) -> "FileWatcher":
        if event not in self.EVENTS:
            raise ValueError(f"Unknown event: {event}")
        self._callbacks[event].append(callback)
        return self

    def off(self, event: str, callback: Callable[[Path], None]) -> "FileWatcher":
        if event in self._callbacks and callback in self._callbacks[event]:
            self._callbacks[event].remove(callback)
        return self

    def scan(self) -> dict[str, list[Path]]:
        current = self.snapshot()
        old = self._state
        created = sorted(set(current) - set(old))
        deleted = sorted(set(old) - set(current))
        common = set(current) & set(old)
        modified = sorted(path for path in common if current[path][:2] != old[path][:2])
        attribute_changed = sorted(path for path in common if current[path][2] != old[path][2])
        old_by_inode = {value[3]: path for path, value in old.items() if value[3]}
        moved = [path for path in created if current[path][3] and current[path][3] in old_by_inode]
        result = {"created": created, "deleted": deleted, "modified": modified, "moved": sorted(moved), "attribute_changed": attribute_changed}
        self._state = current
        for event, paths in result.items():
            for path in paths:
                for callback in tuple(self._callbacks[event]):
                    callback(path)
        return result

    def watch(self, interval: float = 0.5, timeout: float | None = None):
        if interval <= 0:
            raise ValueError("interval must be greater than zero")
        if timeout is not None and timeout < 0:
            raise ValueError("timeout cannot be negative")
        start = time.monotonic()
        self._state = self.snapshot()
        while timeout is None or time.monotonic() - start < timeout:
            time.sleep(interval)
            changes = self.scan()
            if any(changes.values()):
                yield changes
