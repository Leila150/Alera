"""Persistent configuration for Alera's experimental features."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Callable


class HiddenConfig:
    """Control Alera's hidden-storage backend.

    Defaults are ``enabled=True`` and ``storage="internal"``. Android shared
    storage is opt-in with ``storage="android"``.
    """

    VALID_STORAGE = frozenset({"internal", "android"})

    def __init__(self, path: str | os.PathLike[str], *, enabled: bool = True, storage: str = "internal") -> None:
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._callback: Callable[[bool, str], Any] | None = None
        self._enabled = bool(enabled)
        self._storage = "internal"
        self.storage = storage

    def bind(self, callback: Callable[[bool, str], Any]) -> "HiddenConfig":
        self._callback = callback
        return self

    def _changed(self) -> None:
        if self._callback is not None:
            self._callback(self.enabled, self.storage)

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = bool(value)
        self._changed()

    @property
    def storage(self) -> str:
        return self._storage

    @storage.setter
    def storage(self, value: str) -> None:
        value = str(value).strip().lower()
        if value not in self.VALID_STORAGE:
            raise ValueError(f"storage must be one of {sorted(self.VALID_STORAGE)}")
        self._storage = value
        self._changed()

    @property
    def active_backend(self) -> str:
        return self.storage

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
                self._enabled = bool(data.get("enabled", True))
                value = str(data.get("storage", "internal")).strip().lower()
                self._storage = value if value in self.VALID_STORAGE else "internal"
        except (OSError, ValueError, TypeError):
            self._enabled = True
            self._storage = "internal"
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
        self._enabled = True
        self._storage = "internal"
        self._changed()
        if save:
            self.save()
        return self

    def __repr__(self) -> str:
        return f"HiddenConfig(enabled={self.enabled!r}, storage={self.storage!r})"


def install_experimental_config() -> None:
    """Attach ``Experimental.hidden_config`` while preserving Experimental's API."""
    from .experimental import Experimental

    if isinstance(getattr(Experimental, "hidden_config", None), property):
        return

    def get_hidden_config(instance: Experimental) -> HiddenConfig:
        config = getattr(instance, "_hidden_config", None)
        if config is None:
            config = HiddenConfig(instance.base_path / ".alera" / "config" / "experimental.json").load()
            config.bind(lambda enabled, storage: instance.hidden.configure(enabled=enabled, storage=storage))
            instance.hidden.configure(enabled=config.enabled, storage=config.storage)
            instance._hidden_config = config
        return config

    Experimental.hidden_config = property(get_hidden_config)
