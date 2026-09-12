"""Process inspection and control helpers."""
from __future__ import annotations

import os
import signal
import subprocess
import sys
from typing import Sequence


class ProcessManager:
    """Inspect and control processes using only standard-library facilities."""

    def list(self) -> list[dict]:
        if os.path.isdir("/proc"):
            result = []
            for entry in os.listdir("/proc"):
                if not entry.isdigit():
                    continue
                pid = int(entry)
                try:
                    with open(f"/proc/{pid}/cmdline", "rb") as handle:
                        command = handle.read(65536).replace(b"\x00", b" ").decode(errors="replace").strip()
                    with open(f"/proc/{pid}/status", "r", encoding="utf-8", errors="replace") as handle:
                        status = {line.split(":", 1)[0]: line.split(":", 1)[1].strip() for line in handle if ":" in line}
                    result.append({"pid": pid, "command": command, "name": status.get("Name"), "state": status.get("State")})
                except OSError:
                    continue
            return sorted(result, key=lambda item: item["pid"])
        if sys.platform.startswith("win"):
            try:
                output = subprocess.check_output(["tasklist", "/FO", "CSV", "/NH"], text=True, errors="replace")
                rows = []
                for line in output.splitlines():
                    parts = [part.strip('"') for part in line.split('","')]
                    if len(parts) >= 2 and parts[1].isdigit():
                        rows.append({"pid": int(parts[1]), "name": parts[0], "command": parts[0]})
                return rows
            except (OSError, subprocess.SubprocessError):
                return []
        return []

    def exists(self, pid: int) -> bool:
        try:
            pid = int(pid)
            if pid <= 0:
                return False
            os.kill(pid, 0)
            return True
        except (OSError, ValueError):
            return False

    def start(self, command: Sequence[str], **kwargs):
        if not command:
            raise ValueError("command cannot be empty")
        return subprocess.Popen(list(command), **kwargs)

    def terminate(self, pid: int) -> None:
        os.kill(int(pid), signal.SIGTERM)

    def kill(self, pid: int) -> None:
        os.kill(int(pid), getattr(signal, "SIGKILL", signal.SIGTERM))
