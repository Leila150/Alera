"""Advanced polling-based filesystem watcher."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Callable


class FileWatcher:
    """Detect created, deleted, modified, moved, and attribute changes."""

    EVENTS = ("created", "deleted", "modified", "moved", "attribute_changed")

    def __init__(self, directory: str | Path = ".", recursive: bool = True) -> None:
        self.root = Path(directory).expanduser().resolve()
        self.recursive = recursive
        self._state: dict[Path, tuple[int, int, int]] = {}
        self._callbacks: dict[str, list[Callable[[Path], None]]] = {event: [] for event in self.EVENTS}

    def snapshot(self) -> dict[Path, tuple[int, int, int]]:
        paths = self.root.rglob("*") if self.recursive else self.root.iterdir()
        state = {}
        for path in paths:
            try:
                if path.is_file():
                    stat = path.stat(); state[path] = (stat.st_size, stat.st_mtime_ns, stat.st_mode)
            except OSError:
                continue
        return state

    def on(self, event: str, callback: Callable[[Path], None]) -> None:
        if event not in self.EVENTS:
            raise ValueError(f"Unknown event: {event}")
        self._callbacks[event].append(callback)

    def scan(self) -> dict[str, list[Path]]:
        current = self.snapshot(); old = self._state
        created = sorted(set(current) - set(old)); deleted = sorted(set(old) - set(current))
        modified = sorted(p for p in set(current) & set(old) if current[p][0:2] != old[p][0:2])
        attribute_changed = sorted(p for p in set(current) & set(old) if current[p][2] != old[p][2])
        moved: list[Path] = []
        deleted_by_size = {}
        for path in deleted: deleted_by_size.setdefault(old[path][0], []).append(path)
        for path in created:
            candidates = deleted_by_size.get(current[path][0], [])
            if candidates:
                moved.append(path)
        result = {"created": created, "deleted": deleted, "modified": modified, "moved": moved, "attribute_changed": attribute_changed}
        self._state = current
        for event, paths in result.items():
            for path in paths:
                for callback in self._callbacks[event]:
                    callback(path)
        return result

    def watch(self, interval: float = 0.5, timeout: float | None = None):
        if interval <= 0: raise ValueError("interval must be greater than zero")
        start = time.monotonic(); self._state = self.snapshot()
        while timeout is None or time.monotonic() - start < timeout:
            time.sleep(interval); changes = self.scan()
            if any(changes.values()): yield changes
