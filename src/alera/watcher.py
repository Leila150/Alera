"""High-performance polling filesystem watcher."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Callable, Iterator


class FileWatcher:
    """Detect filesystem changes with callbacks, move correlation, filtering, and debouncing."""

    EVENTS = ("created", "deleted", "modified", "moved", "attribute_changed")

    def __init__(self, directory: str | Path = ".", recursive: bool = True, include_hidden: bool = True,
                 patterns: list[str] | tuple[str, ...] | None = None, debounce: float = 0.0) -> None:
        self.root = Path(directory).expanduser().resolve()
        self.recursive = recursive
        self.include_hidden = include_hidden
        self.patterns = tuple(patterns or ())
        if debounce < 0:
            raise ValueError("debounce cannot be negative")
        self.debounce = debounce
        self._state: dict[Path, tuple[int, int, int, int, int]] = {}
        self._callbacks: dict[str, list[Callable[[Path], None]]] = {event: [] for event in self.EVENTS}
        self._last_emit: dict[tuple[str, Path], float] = {}

    def _visible(self, path: Path) -> bool:
        try: relative = path.relative_to(self.root)
        except ValueError: return False
        if not self.include_hidden and any(part.startswith(".") for part in relative.parts):
            return False
        return not self.patterns or any(path.match(pattern) or path.name == pattern for pattern in self.patterns)

    def snapshot(self) -> dict[Path, tuple[int, int, int, int, int]]:
        if not self.root.is_dir():
            raise NotADirectoryError(self.root)
        iterator = self.root.rglob("*") if self.recursive else self.root.iterdir()
        state = {}
        for path in iterator:
            try:
                if not path.is_file() or not self._visible(path):
                    continue
                stat = path.stat()
                state[path] = (stat.st_size, stat.st_mtime_ns, stat.st_mode, getattr(stat, "st_ino", 0), getattr(stat, "st_dev", 0))
            except OSError:
                continue
        return state

    def initialize(self) -> "FileWatcher":
        self._state = self.snapshot()
        return self

    def on(self, event: str, callback: Callable[[Path], None]) -> "FileWatcher":
        if event not in self.EVENTS: raise ValueError(f"Unknown event: {event}")
        if not callable(callback): raise TypeError("callback must be callable")
        self._callbacks[event].append(callback)
        return self

    def off(self, event: str, callback: Callable[[Path], None]) -> "FileWatcher":
        if event in self._callbacks and callback in self._callbacks[event]: self._callbacks[event].remove(callback)
        return self

    def clear_callbacks(self, event: str | None = None) -> "FileWatcher":
        if event is None:
            for callbacks in self._callbacks.values(): callbacks.clear()
        elif event in self._callbacks:
            self._callbacks[event].clear()
        else:
            raise ValueError(f"Unknown event: {event}")
        return self

    def _emit(self, event: str, path: Path) -> None:
        key = (event, path)
        now = time.monotonic()
        if self.debounce and now - self._last_emit.get(key, 0.0) < self.debounce:
            return
        self._last_emit[key] = now
        for callback in tuple(self._callbacks[event]):
            try: callback(path)
            except Exception: continue

    def scan(self) -> dict[str, list[Path]]:
        current = self.snapshot()
        old = self._state
        created = set(current) - set(old)
        deleted = set(old) - set(current)
        common = set(current) & set(old)
        modified = {p for p in common if current[p][0:2] != old[p][0:2]}
        attribute_changed = {p for p in common if current[p][2] != old[p][2]}
        old_by_identity = {(v[3], v[4]): p for p, v in old.items() if v[3]}
        new_by_identity = {(v[3], v[4]): p for p, v in current.items() if v[3]}
        moved = {new_by_identity[key] for key in new_by_identity.keys() & old_by_identity.keys() if new_by_identity[key] != old_by_identity[key]}
        moved_old = {old_by_identity[(current[p][3], current[p][4])] for p in moved}
        created -= moved
        deleted -= moved_old
        result = {"created": sorted(created), "deleted": sorted(deleted), "modified": sorted(modified),
                  "moved": sorted(moved), "attribute_changed": sorted(attribute_changed)}
        self._state = current
        for event, paths in result.items():
            for path in paths: self._emit(event, path)
        return result

    def watch(self, interval: float = 0.5, timeout: float | None = None) -> Iterator[dict[str, list[Path]]]:
        if interval <= 0: raise ValueError("interval must be greater than zero")
        if timeout is not None and timeout < 0: raise ValueError("timeout cannot be negative")
        self.initialize()
        start = time.monotonic()
        while timeout is None or time.monotonic() - start < timeout:
            time.sleep(interval)
            changes = self.scan()
            if any(changes.values()): yield changes
