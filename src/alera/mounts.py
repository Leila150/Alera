"""Mounted filesystem and device inspection."""
from __future__ import annotations

import os
import platform
from pathlib import Path


class MountManager:
    """Inspect filesystem mounts and available storage roots."""

    def __init__(self, base_path: str | Path = "") -> None:
        self.base_path = (Path(base_path).expanduser() if str(base_path) else Path.cwd()).resolve()

    def roots(self) -> list[Path]:
        if os.name == "nt":
            import string
            import ctypes
            drives = []
            mask = ctypes.windll.kernel32.GetLogicalDrives()
            for i, letter in enumerate(string.ascii_uppercase):
                if mask & (1 << i):
                    drives.append(Path(f"{letter}:\\"))
            return drives
        return [Path("/")]

    def information(self, path: str | Path | None = None) -> dict[str, object]:
        target = Path(path).resolve() if path else self.base_path
        usage = os.statvfs(target) if hasattr(os, "statvfs") else None
        result: dict[str, object] = {"path": str(target), "platform": platform.system(), "filesystem": None}
        if usage:
            result.update({"total": usage.f_frsize * usage.f_blocks, "free": usage.f_frsize * usage.f_bavail, "used": usage.f_frsize * (usage.f_blocks - usage.f_bfree)})
        return result

    def filesystems(self) -> list[dict[str, object]]:
        return [self.information(root) for root in self.roots() if root.exists()]
