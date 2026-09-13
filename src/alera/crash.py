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
from typing import Any


class CrashLogger:
    """Capture unhandled exceptions without masking the original crash."""

    def __init__(self, base_path: str | os.PathLike[str] = "", *, max_reports: int = 100) -> None:
        raw = Path(base_path).expanduser() if str(base_path) else Path.cwd()
        self.base_path = raw.resolve()
        self.directory = self.base_path / ".alera" / "crash_logs"
        self.max_reports = max(1, int(max_reports))
        self._installed = False
        self._previous_sys_hook = None
        self._previous_thread_hook = None
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

    def install(self) -> "CrashLogger":
        if self._installed:
            return self
        self._previous_sys_hook = sys.excepthook
        self._previous_thread_hook = getattr(threading, "excepthook", None)

        def system_hook(exc_type, exc_value, exc_traceback):
            try:
                self.report(exc_type, exc_value, exc_traceback)
            finally:
                previous = self._previous_sys_hook
                if previous and previous is not system_hook:
                    previous(exc_type, exc_value, exc_traceback)

        def thread_hook(args):
            try:
                self.report(
                    args.exc_type,
                    args.exc_value,
                    args.exc_traceback,
                    context={"thread": args.thread.name if args.thread else None},
                )
            finally:
                previous = self._previous_thread_hook
                if previous and previous is not thread_hook:
                    previous(args)

        sys.excepthook = system_hook
        if hasattr(threading, "excepthook"):
            threading.excepthook = thread_hook
        self._installed = True
        return self

    def uninstall(self) -> None:
        if not self._installed:
            return
        if self._previous_sys_hook is not None:
            sys.excepthook = self._previous_sys_hook
        if self._previous_thread_hook is not None and hasattr(threading, "excepthook"):
            threading.excepthook = self._previous_thread_hook
        self._previous_sys_hook = None
        self._previous_thread_hook = None
        self._installed = False

    def list(self, *, newest_first: bool = True) -> list[Path]:
        try:
            reports = list(self.directory.glob("crash-*.json"))
        except OSError:
            return []
        reports.sort(key=lambda path: path.stat().st_mtime if path.exists() else 0, reverse=newest_first)
        return reports

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
