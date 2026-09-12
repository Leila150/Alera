"""Process inspection using the Python standard library."""

from __future__ import annotations

import os
import signal
import subprocess
import sys


class ProcessManager:
    def list(self) -> list[dict]:
        if sys.platform.startswith("win"):
            return []
        result = []
        proc = "/proc"
        if os.path.isdir(proc):
            for entry in os.listdir(proc):
                if not entry.isdigit(): continue
                pid = int(entry)
                try:
                    command = open(f"/proc/{pid}/cmdline", "rb").read().replace(b"\x00", b" ").decode(errors="replace").strip()
                    result.append({"pid": pid, "command": command})
                except OSError:
                    continue
        return sorted(result, key=lambda item: item["pid"])

    def exists(self, pid: int) -> bool:
        try: os.kill(int(pid), 0); return True
        except (OSError, ValueError): return False

    def start(self, command: list[str], **kwargs):
        return subprocess.Popen(command, **kwargs)

    def terminate(self, pid: int) -> None:
        os.kill(int(pid), signal.SIGTERM)

    def kill(self, pid: int) -> None:
        os.kill(int(pid), signal.SIGKILL if hasattr(signal, "SIGKILL") else signal.SIGTERM)
