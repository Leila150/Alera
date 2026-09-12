"""Filesystem health and capability checks."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any


class HealthChecker:
    """Run non-destructive filesystem capability and health checks."""

    def __init__(self, base_path: str | Path = "") -> None:
        self.base_path = (Path(base_path).expanduser() if str(base_path) else Path.cwd()).resolve()
        self.base_path.mkdir(parents=True, exist_ok=True)

    def check(self) -> dict[str, Any]:
        result: dict[str, Any] = {"path": str(self.base_path), "exists": self.base_path.exists()}
        result["readable"] = os.access(self.base_path, os.R_OK)
        result["writable"] = os.access(self.base_path, os.W_OK)
        result["executable"] = os.access(self.base_path, os.X_OK)
        try:
            usage = os.statvfs(self.base_path)
            result["free_bytes"] = usage.f_frsize * usage.f_bavail
        except OSError:
            result["free_bytes"] = None
        return result

    def temporary_io(self) -> dict[str, bool]:
        result = {"write": False, "read": False, "delete": False}
        fd, name = tempfile.mkstemp(prefix=".alera-health-", dir=self.base_path)
        path = Path(name)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(b"alera-health")
            result["write"] = True
            result["read"] = path.read_bytes() == b"alera-health"
            path.unlink()
            result["delete"] = True
        finally:
            if path.exists():
                path.unlink()
        return result

    def health(self) -> dict[str, Any]:
        result = self.check()
        result["temporary_io"] = self.temporary_io()
        result["healthy"] = all((result["exists"], result["readable"], result["writable"], result["temporary_io"]["write"], result["temporary_io"]["read"], result["temporary_io"]["delete"]))
        return result
