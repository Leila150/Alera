"""Unified filesystem operation/event engine for Alera."""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


@dataclass(slots=True, frozen=True)
class FileEvent:
    """Immutable description of a filesystem operation."""

    id: str
    operation: str
    path: str
    timestamp: float
    success: bool
    details: dict[str, Any] = field(default_factory=dict)


class OperationEngine:
    """Central event bus, operation journal and callback dispatcher.

    Services can use this without depending on each other. Callbacks are
    isolated: one broken listener never stops the filesystem operation that
    produced the event.
    """

    def __init__(self, *, history_limit: int = 10_000) -> None:
        if history_limit < 1:
            raise ValueError("history_limit must be positive")
        self.history_limit = history_limit
        self._history: list[FileEvent] = []
        self._listeners: dict[str, list[Callable[[FileEvent], Any]]] = {}
        self._lock = threading.RLock()

    def on(self, operation: str, callback: Callable[[FileEvent], Any]) -> Callable[[FileEvent], Any]:
        if not callable(callback):
            raise TypeError("callback must be callable")
        key = str(operation).strip().lower() or "*"
        with self._lock:
            self._listeners.setdefault(key, []).append(callback)
        return callback

    def off(self, operation: str, callback: Callable[[FileEvent], Any]) -> bool:
        key = str(operation).strip().lower() or "*"
        with self._lock:
            listeners = self._listeners.get(key, [])
            try:
                listeners.remove(callback)
            except ValueError:
                return False
            if not listeners:
                self._listeners.pop(key, None)
            return True

    def clear_listeners(self, operation: str | None = None) -> None:
        with self._lock:
            if operation is None:
                self._listeners.clear()
            else:
                self._listeners.pop(str(operation).strip().lower() or "*", None)

    def emit(self, operation: str, path: str | Path, *, success: bool = True, **details: Any) -> FileEvent:
        event = FileEvent(uuid.uuid4().hex, str(operation), str(path), time.time(), bool(success), dict(details))
        with self._lock:
            self._history.append(event)
            if len(self._history) > self.history_limit:
                del self._history[: len(self._history) - self.history_limit]
            callbacks = list(self._listeners.get("*", ())) + list(self._listeners.get(event.operation.lower(), ()))
        for callback in callbacks:
            try:
                callback(event)
            except Exception:
                continue
        return event

    def history(self, operation: str | None = None, *, path: str | None = None, limit: int | None = None) -> list[FileEvent]:
        with self._lock:
            events = list(self._history)
        if operation is not None:
            events = [event for event in events if event.operation.lower() == operation.lower()]
        if path is not None:
            needle = str(path)
            events = [event for event in events if event.path == needle]
        if limit is not None:
            if limit < 0:
                raise ValueError("limit cannot be negative")
            events = events[-limit:] if limit else []
        return events

    def statistics(self) -> dict[str, Any]:
        with self._lock:
            events = list(self._history)
        operations: dict[str, int] = {}
        failures = 0
        for event in events:
            operations[event.operation] = operations.get(event.operation, 0) + 1
            failures += not event.success
        return {"events": len(events), "failures": failures, "operations": operations, "listeners": sum(len(v) for v in self._listeners.values())}

    def clear_history(self) -> None:
        with self._lock:
            self._history.clear()
