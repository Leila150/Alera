"""Recovery journal for Alera operations."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


class RecoveryManager:
    """Record recoverable filesystem operations in a small JSON journal."""

    def __init__(self, base_path: str | Path = "") -> None:
        self.base_path = (Path(base_path).expanduser() if str(base_path) else Path.cwd()).resolve()
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.journal = self.base_path / ".alera_recovery.json"

    def _read(self) -> list[dict[str, Any]]:
        if not self.journal.exists():
            return []
        try:
            return json.loads(self.journal.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []

    def record(self, operation: str, **data: Any) -> dict[str, Any]:
        entry = {"time": time.time(), "operation": operation, **data}
        entries = self._read()
        entries.append(entry)
        self.journal.write_text(json.dumps(entries, indent=2, default=str), encoding="utf-8")
        return entry

    def history(self, operation: str | None = None) -> list[dict[str, Any]]:
        entries = self._read()
        return [e for e in entries if operation is None or e.get("operation") == operation]

    def last(self) -> dict[str, Any] | None:
        entries = self._read()
        return entries[-1] if entries else None

    def clear(self) -> None:
        try:
            self.journal.unlink()
        except FileNotFoundError:
            pass
