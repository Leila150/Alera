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
    """High-level runtime controller for Alera's filesystem/system services."""

    def __init__(self, owner: Any) -> None:
        self.owner = owner
        self.started_at = time.time()
        self.started_monotonic = time.monotonic()
        self._shutdown = False

    @property
    def uptime(self) -> float:
        return max(0.0, time.monotonic() - self.started_monotonic)

    @property
    def shutdown_state(self) -> bool:
        return self._shutdown

    def _ensure_running(self) -> None:
        if self._shutdown:
            raise RuntimeError("Alera runtime has already been shut down")

    def services(self) -> dict[str, str]:
        return {name: type(value).__name__ for name, value in vars(self.owner).items() if not name.startswith("_") and name != "base_path"}

    def service(self, name: str) -> Any:
        self._ensure_running()
        if not name or name.startswith("_"):
            raise ValueError("Invalid service name")
        try:
            return getattr(self.owner, name)
        except AttributeError as exc:
            raise KeyError(name) from exc

    def capabilities(self) -> dict[str, Any]:
        optional = {name: importlib.util.find_spec(name) is not None for name in ("psutil", "py7zr", "rarfile", "zstandard", "lz4", "brotli")}
        return {
            "platform": sys.platform,
            "os": os.name,
            "python": platform.python_version(),
            "filesystem": {"symlink": hasattr(os, "symlink"), "hardlink": hasattr(os, "link"), "replace": hasattr(os, "replace"), "scandir": hasattr(os, "scandir"), "statvfs": hasattr(os, "statvfs")},
            "optional_dependencies": optional,
            "services": self.services(),
        }

    def paths(self) -> dict[str, str]:
        """Return the centralized internal subsystem paths."""
        self._ensure_running()
        return {name: str(path) for name, path in self.owner.internal.iter_subsystems()}

    def environment(self) -> dict[str, Any]:
        self._ensure_running()
        return {"python": sys.version, "implementation": platform.python_implementation(), "platform": platform.platform(), "machine": platform.machine(), "processor": platform.processor(), "hostname": platform.node(), "pid": os.getpid(), "cwd": str(Path.cwd()), "base_path": str(self.owner.files.base_path)}

    def resources(self) -> dict[str, Any]:
        self._ensure_running()
        try:
            usage = shutil.disk_usage(self.owner.files.base_path)
            disk = {"total": usage.total, "used": usage.used, "free": usage.free}
        except OSError as exc:
            disk = {"total": None, "used": None, "free": None, "error": f"{type(exc).__name__}: {exc}"}
        result: dict[str, Any] = {"disk": disk, "uptime": self.uptime, "pid": os.getpid()}
        try:
            import resource
            value = resource.getrusage(resource.RUSAGE_SELF)
            result["process"] = {"max_rss": getattr(value, "ru_maxrss", None), "user_time": value.ru_utime, "system_time": value.ru_stime}
        except (ImportError, AttributeError, OSError):
            result["process"] = {}
        return result

    def diagnostics(self, *, include_services: bool = True, deep: bool = False) -> dict[str, Any]:
        self._ensure_running()
        try:
            import alera
            version = getattr(alera, "__version__", "unknown")
        except Exception:
            version = "unknown"
        result = {"ok": True, "version": version, "uptime": self.uptime, "environment": self.environment(), "capabilities": self.capabilities(), "resources": self.resources(), "internal": self.owner.internal.information(), "hidden_config": self.owner.hidden_config.as_dict(), "crash_logging": {"installed": self.owner.crash.installed, "reports": len(self.owner.crash.list())}}
        if include_services:
            result["services"] = self.services()
        if deep:
            result["service_health"] = self.check_services()
            result["operations"] = self.owner.operations.statistics()
        return result

    def check_services(self) -> dict[str, dict[str, Any]]:
        self._ensure_running()
        result: dict[str, dict[str, Any]] = {}
        for name, service in vars(self.owner).items():
            if name.startswith("_") or name in {"base_path", "operations", "runtime"}:
                continue
            entry: dict[str, Any] = {"type": type(service).__name__, "ok": True}
            try:
                if hasattr(service, "health"):
                    entry["health"] = service.health()
                elif hasattr(service, "information"):
                    value = service.information()
                    entry["information"] = value if isinstance(value, dict) else str(value)
            except Exception as exc:
                entry["ok"] = False
                entry["error"] = f"{type(exc).__name__}: {exc}"
            result[name] = entry
        return result

    def gc_collect(self, generation: int | None = None) -> dict[str, Any]:
        self._ensure_running()
        before = gc.get_count()
        collected = gc.collect() if generation is None else gc.collect(generation)
        return {"collected": collected, "before": before, "after": gc.get_count()}

    def benchmark(self, service: str, method: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self._ensure_running()
        target = self.service(service)
        if not method or method.startswith("_"):
            raise ValueError("Only public service methods may be benchmarked")
        callable_method = getattr(target, method, None)
        if not callable(callable_method):
            raise AttributeError(f"{type(target).__name__} has no public callable {method!r}")
        started = time.perf_counter()
        try:
            result = callable_method(*args, **kwargs)
            return {"ok": True, "service": service, "method": method, "elapsed": time.perf_counter() - started, "result": result}
        except Exception as exc:
            return {"ok": False, "service": service, "method": method, "elapsed": time.perf_counter() - started, "error_type": type(exc).__name__, "error": str(exc)}

    def call(self, service: str, method: str, *args: Any, **kwargs: Any) -> Any:
        self._ensure_running()
        if not method or method.startswith("_"):
            raise ValueError("Only public service methods may be called")
        target = self.service(service)
        callable_method = getattr(target, method, None)
        if not callable(callable_method):
            raise AttributeError(f"{type(target).__name__} has no public callable {method!r}")
        return callable_method(*args, **kwargs)

    def on_event(self, event: str, callback: Callable[[Any], Any]) -> Any:
        self._ensure_running()
        return self.owner.operations.on(event, callback)

    def emit(self, event: str, path: str = "", **metadata: Any) -> Any:
        self._ensure_running()
        return self.owner.operations.emit(event, path, **metadata)

    def shutdown(self) -> None:
        if self._shutdown:
            return
        self._shutdown = True
        crash = getattr(self.owner, "crash", None)
        if crash is not None:
            try:
                crash.uninstall()
            except Exception:
                pass
        for service in reversed(list(vars(self.owner).values())):
            if service is self or service is crash:
                continue
            close = getattr(service, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass

    close = shutdown

    def __enter__(self) -> "AleraRuntime":
        self._ensure_running()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.shutdown()
