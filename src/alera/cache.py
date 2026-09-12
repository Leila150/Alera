"""Small in-memory file cache with invalidation."""
from __future__ import annotations
from pathlib import Path
from typing import Any

class FileCache:
    """Cache file contents while automatically invalidating changed files."""
    def __init__(self, max_items: int = 128) -> None:
        if max_items <= 0: raise ValueError("max_items must be greater than zero.")
        self.max_items = max_items
        self._items: dict[Path, tuple[int, Any]] = {}
        self._order: list[Path] = []

    def _touch(self, path: Path) -> None:
        if path in self._order: self._order.remove(path)
        self._order.append(path)
        while len(self._order) > self.max_items:
            old = self._order.pop(0); self._items.pop(old, None)

    def get_text(self, file: str | Path, encoding: str = "utf-8") -> str:
        path = Path(file).expanduser().resolve(); stamp = path.stat().st_mtime_ns
        cached = self._items.get(path)
        if cached and cached[0] == stamp: self._touch(path); return cached[1]
        value = path.read_text(encoding=encoding); self._items[path] = (stamp, value); self._touch(path); return value

    def get_bytes(self, file: str | Path) -> bytes:
        path = Path(file).expanduser().resolve(); stamp = path.stat().st_mtime_ns
        cached = self._items.get(path)
        if cached and cached[0] == stamp: self._touch(path); return cached[1]
        value = path.read_bytes(); self._items[path] = (stamp, value); self._touch(path); return value

    def invalidate(self, file: str | Path | None = None) -> None:
        if file is None: self.clear(); return
        path = Path(file).expanduser().resolve(); self._items.pop(path, None)
        if path in self._order: self._order.remove(path)

    def clear(self) -> None:
        self._items.clear(); self._order.clear()

    def __len__(self) -> int: return len(self._items)
