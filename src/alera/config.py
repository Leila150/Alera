"""Persistent configuration for Alera's experimental features."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


class HiddenConfig:
    """Control Alera's hidden-storage backend.

    ``enabled`` controls whether hidden storage is active.
    ``storage`` is ``"internal"`` by default and may be ``"android"``.
    On non-Android systems, ``"android"`` gracefully falls back to internal
    storage because Android shared storage does not exist there.
    """

    VALID_STORAGE = frozenset({"internal", "android"})

    def __init__(self, path: str | os.PathLike[str], *, enabled: bool = True, storage: str = "internal") -> None:
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._enabled = bool(enabled)
        self._storage = "internal"
        self.storage = storage

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = bool(value)

    @property
    def storage(self) -> str:
        return self._storage

    @storage.setter
    def storage(self, value: str) -> None:
        value = str(value).strip().lower()
        if value not in self.VALID_STORAGE:
            raise ValueError(f"storage must be one of {sorted(self.VALID_STORAGE)}")
        self._storage = value

    @property
    def active_backend(self) -> str:
        return self._storage

    def update(self, *, enabled: bool | None = None, storage: str | None = None, save: bool = True) -> "HiddenConfig":
        if enabled is not None:
            self.enabled = enabled
        if storage is not None:
            self.storage = storage
        if save:
            self.save()
        return self

    def as_dict(self) -> dict[str, Any]:
        return {"enabled": self.enabled, "storage": self.storage}

    def load(self) -> "HiddenConfig":
        if not self.path.exists():
            return self
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self.enabled = bool(data.get("enabled", True))
                self.storage = str(data.get("storage", "internal"))
        except (OSError, ValueError, TypeError):
            # Invalid experimental configuration must never prevent Alera from starting.
            self.enabled = True
            self.storage = "internal"
        return self

    def save(self) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(self.as_dict(), handle, indent=2, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
        return self.path

    def reset(self, *, save: bool = True) -> "HiddenConfig":
        self.enabled = True
        self.storage = "internal"
        if save:
            self.save()
        return self

    def __repr__(self) -> str:
        return f"HiddenConfig(enabled={self.enabled!r}, storage={self.storage!r})"
