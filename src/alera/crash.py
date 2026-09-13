"""Crash logging for Alera applications and services."""
from __future__ import annotations

import json
import os
import platform
import sys
import threading
import time
import traceback
import uuid
from pathlib import Path
from typing import Any, ClassVar


class CrashLogger:
    """Capture unhandled exceptions without masking the original crash.

    Hook installation is process-wide and reference-counted so creating or
    closing multiple :class:`CrashLogger` instances cannot accidentally
    overwrite another instance's exception hooks.
    """

    _active: ClassVar[list["CrashLogger"]] = []
    _hook_lock: ClassVar[threading.RLock] = threading.RLock()
    _original_sys_hook: ClassVar[Any] = None
    _original_thread_hook: ClassVar[Any] = None
    _hooks_installed: ClassVar[bool] = False

    def __init__(self, base_path: str | os.PathLike[str] = "", *, max_reports: int = 100) -> None:
        raw = Path(base_path).expanduser() if str(base_path) else Path.cwd()
        self.base_path = raw.resolve()
        self.directory = self.base_path / ".alera" / "crash_logs"
        self.max_reports = max(1, int(max_reports))
        self._installed = False
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass

    def report(self, exc_type, exc_value, exc_traceback, *, context: dict[str, Any] | None = None) -> Path | None:
        """Best-effort crash report; logging failure never replaces the crash."""
        report_id = f"{int(time.time() * 1000)}-{uuid.uuid4().hex[:12]}"
        try:
            traceback_text = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
            payload = {
                "schema": 1,
                "id": report_id,
                "timestamp": time.time(),
                "datetime_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "exception": {
                    "type": getattr(exc_type, "__name__", str(exc_type)),
                    "message": str(exc_value),
                    "traceback": traceback_text,
                },
                "runtime": {
                    "python": sys.version,
                    "platform": platform.platform(),
                    "system": platform.system(),
                    "release": platform.release(),
                    "machine": platform.machine(),
                    "pid": os.getpid(),
                    "thread": threading.current_thread().name,
                },
                "context": context or {},
            }
            self.directory.mkdir(parents=True, exist_ok=True)
            target = self.directory / f"crash-{report_id}.json"
            temporary = target.with_suffix(".tmp")
            try:
                with temporary.open("w", encoding="utf-8") as handle:
                    json.dump(payload, handle, indent=2, sort_keys=True, default=str)
                    handle.flush()
                    try:
                        os.fsync(handle.fileno())
                    except OSError:
                        pass
                os.replace(temporary, target)
            finally:
                try:
                    temporary.unlink()
                except FileNotFoundError:
                    pass
            self.prune()
            return target
        except Exception:
            return None

    @classmethod
    def _system_hook(cls, exc_type, exc_value, exc_traceback) -> None:
        with cls._hook_lock:
            loggers = tuple(cls._active)
            previous = cls._original_sys_hook
        for logger in loggers:
            try:
                logger.report(exc_type, exc_value, exc_traceback)
            except Exception:
                pass
        if previous is not None:
            try:
                previous(exc_type, exc_value, exc_traceback)
            except Exception:
                pass

    @classmethod
    def _thread_hook(cls, args) -> None:
        with cls._hook_lock:
            loggers = tuple(cls._active)
            previous = cls._original_thread_hook
        context = {"thread": args.thread.name if args.thread else None}
        for logger in loggers:
            try:
                logger.report(args.exc_type, args.exc_value, args.exc_traceback, context=context)
            except Exception:
                pass
        if previous is not None:
            try:
                previous(args)
            except Exception:
                pass

    def install(self) -> "CrashLogger":
        with self._hook_lock:
            if self._installed:
                return self
            if not self.__class__._hooks_installed:
                self.__class__._original_sys_hook = sys.excepthook
                self.__class__._original_thread_hook = getattr(threading, "excepthook", None)
                sys.excepthook = self.__class__._system_hook
                if hasattr(threading, "excepthook"):
                    threading.excepthook = self.__class__._thread_hook
                self.__class__._hooks_installed = True
            if self not in self.__class__._active:
                self.__class__._active.append(self)
            self._installed = True
        return self

    def uninstall(self) -> None:
        with self._hook_lock:
            if not self._installed:
                return
            try:
                self.__class__._active.remove(self)
            except ValueError:
                pass
            self._installed = False
            if not self.__class__._active and self.__class__._hooks_installed:
                original = self.__class__._original_sys_hook
                original_thread = self.__class__._original_thread_hook
                if original is not None and sys.excepthook is self.__class__._system_hook:
                    sys.excepthook = original
                if hasattr(threading, "excepthook") and original_thread is not None and threading.excepthook is self.__class__._thread_hook:
                    threading.excepthook = original_thread
                self.__class__._original_sys_hook = None
                self.__class__._original_thread_hook = None
                self.__class__._hooks_installed = False

    def list(self, *, newest_first: bool = True) -> list[Path]:
        try:
            reports = list(self.directory.glob("crash-*.json"))
        except OSError:
            return []
        valid: list[Path] = []
        for path in reports:
            try:
                path.stat()
                valid.append(path)
            except OSError:
                pass
        valid.sort(key=lambda path: path.stat().st_mtime, reverse=newest_first)
        return valid

    def read(self, report: str | os.PathLike[str]) -> dict[str, Any]:
        path = Path(report)
        if not path.is_absolute():
            path = self.directory / path
        path = path.resolve()
        try:
            path.relative_to(self.directory.resolve())
        except ValueError as exc:
            raise ValueError("Crash report must be inside .alera/crash_logs") from exc
        return json.loads(path.read_text(encoding="utf-8"))

    def prune(self) -> int:
        reports = self.list(newest_first=True)
        removed = 0
        for report in reports[self.max_reports:]:
            try:
                report.unlink()
                removed += 1
            except OSError:
                pass
        return removed

    def clear(self) -> int:
        removed = 0
        for report in self.list(newest_first=False):
            try:
                report.unlink()
                removed += 1
            except OSError:
                pass
        return removed

    @property
    def installed(self) -> bool:
        return self._installed
