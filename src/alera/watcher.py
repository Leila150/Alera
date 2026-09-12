"""Simple polling-based filesystem watcher."""
from __future__ import annotations
import time
from pathlib import Path

class FileWatcher:
    """Detect created, deleted, and modified files without third-party packages."""
    def __init__(self, directory: str | Path = ".", recursive: bool = True) -> None:
        self.root = Path(directory).expanduser().resolve()
        self.recursive = recursive
        self._state: dict[Path, tuple[int, int]] = {}

    def snapshot(self) -> dict[Path, tuple[int, int]]:
        paths = self.root.rglob("*") if self.recursive else self.root.iterdir()
        state = {}
        for path in paths:
            if path.is_file():
                stat = path.stat(); state[path] = (stat.st_size, stat.st_mtime_ns)
        return state

    def scan(self) -> dict[str, list[Path]]:
        current = self.snapshot()
        old = self._state
        result = {
            "created": sorted(set(current) - set(old)),
            "deleted": sorted(set(old) - set(current)),
            "modified": sorted(path for path in set(current) & set(old) if current[path] != old[path]),
        }
        self._state = current
        return result

    def watch(self, interval: float = 0.5, timeout: float | None = None):
        """Yield change dictionaries until timeout expires or the generator is closed."""
        if interval <= 0: raise ValueError("interval must be greater than zero.")
        start = time.monotonic()
        self._state = self.snapshot()
        while timeout is None or time.monotonic() - start < timeout:
            time.sleep(interval)
            changes = self.scan()
            if any(changes.values()): yield changes
