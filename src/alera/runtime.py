"""Alera runtime, diagnostics, service registry, and lifecycle control."""
from __future__ import annotations

import gc
import importlib.util
import os
import platform
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Callable


class AleraRuntime:
    """High-level runtime controller for an Alera instance.

    This layer does not replace the individual services. It provides a single
    place for lifecycle state, capability discovery, diagnostics, service
    introspection, and graceful shutdown.
    """

    def __init__(self, owner: Any) -> None:
        self.owner = owner
        self.started_at = time.time()
        self._shutdown = False

    @property
    def uptime(self) -> float:
        return max(0.0, time.time() - self.started_at)

    @property
    def shutdown_state(self) -> bool:
        return self._shutdown

    def services(self) -> dict[str, str]:
        return {
            name: type(value).__name__
            for name, value in vars(self.owner).items()
            if not name.startswith("_") and name not in {"base_path"}
        }

    def capabilities(self) -> dict[str, Any]:
        optional = {
            name: importlib.util.find_spec(name) is not None
            for name in ("psutil", "py7zr", "rarfile", "zstandard", "lz4", "brotli")
        }
        return {
            "platform": sys.platform,
            "os": os.name,
            "python": platform.python_version(),
            "filesystem": {
                "symlink": hasattr(os, "symlink"),
                "hardlink": hasattr(os, "link"),
                "replace": hasattr(os, "replace"),
                "scandir": hasattr(os, "scandir"),
                "statvfs": hasattr(os, "statvfs"),
            },
            "optional_dependencies": optional,
            "services": self.services(),
        }

    def environment(self) -> dict[str, Any]:
        return {
            "python": sys.version,
            "implementation": platform.python_implementation(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "hostname": platform.node(),
            "pid": os.getpid(),
            "cwd": str(Path.cwd()),
            "base_path": str(self.owner.files.base_path),
        }

    def paths(self) -> dict[str, str]:
        internal = self.owner.internal
        return {name: str(path) for name, path in internal.iter_subsystems()}

    def resources(self) -> dict[str, Any]:
        usage = shutil.disk_usage(self.owner.files.base_path)
        result: dict[str, Any] = {
            "disk": {"total": usage.total, "used": usage.used, "free": usage.free},
            "uptime": self.uptime,
            "pid": os.getpid(),
        }
        try:
            import resource
            self_usage = resource.getrusage(resource.RUSAGE_SELF)
            result["process"] = {
                "max_rss": getattr(self_usage, "ru_maxrss", None),
                "user_time": self_usage.ru_utime,
                "system_time": self_usage.ru_stime,
            }
        except (ImportError, AttributeError, OSError):
            result["process"] = {}
        return result

    def diagnostics(self, *, include_services: bool = True) -> dict[str, Any]:
        result = {
            "ok": True,
            "version": getattr(importlib.import_module("alera"), "__version__", "unknown"),
            "uptime": self.uptime,
            "environment": self.environment(),
            "capabilities": self.capabilities(),
            "resources": self.resources(),
            "internal": self.owner.internal.information(),
            "hidden_config": self.owner.hidden_config.as_dict(),
            "crash_logging": {
                "installed": self.owner.crash.installed,
                "reports": len(self.owner.crash.list()),
            },
        }
        if include_services:
            result["services"] = self.services()
        return result

    def check_services(self) -> dict[str, dict[str, Any]]:
        """Probe service objects without allowing one failure to break diagnostics."""
        result: dict[str, dict[str, Any]] = {}
        for name, service in vars(self.owner).items():
            if name.startswith("_") or name in {"base_path", "operations"}:
                continue
            entry: dict[str, Any] = {"type": type(service).__name__, "ok": True}
            try:
                if hasattr(service, "information"):
                    value = service.information()
                    entry["information"] = value if isinstance(value, dict) else str(value)
            except Exception as exc:
                entry["ok"] = False
                entry["error"] = f"{type(exc).__name__}: {exc}"
            result[name] = entry
        return result

    def gc_collect(self) -> dict[str, int]:
        before = gc.get_count()
        collected = gc.collect()
        after = gc.get_count()
        return {"collected": collected, "before": sum(before), "after": sum(after)}

    def on_event(self, event: str, callback: Callable[[Any], Any]) -> Any:
        return self.owner.operations.on(event, callback)

    def emit(self, event: str, path: str = "", **metadata: Any) -> Any:
        return self.owner.operations.emit(event, path, **metadata)

    def shutdown(self) -> None:
        if self._shutdown:
            return
        try:
            self.owner.crash.uninstall()
        finally:
            self._shutdown = True

    def __enter__(self) -> "AleraRuntime":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.shutdown()
