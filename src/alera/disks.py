"""Cross-platform disk and filesystem information."""

from __future__ import annotations

import os
import shutil
from pathlib import Path


class DiskManager:
    """Inspect mounted filesystems and available storage."""

    def roots(self) -> list[str]:
        if os.name == "nt":
            import string
            return [f"{drive}:\\" for drive in string.ascii_uppercase if Path(f"{drive}:\\").exists()]
        return ["/"]

    def information(self, path: str | Path | None = None) -> dict:
        target = Path(path or ".").resolve()
        usage = shutil.disk_usage(target)
        return {"path": str(target), "total": usage.total, "used": usage.used, "free": usage.free, "percent_used": (usage.used / usage.total * 100) if usage.total else 0.0}

    def enumerate(self) -> list[dict]:
        return [self.information(root) for root in self.roots()]

    def filesystem(self, path: str | Path = ".") -> str | None:
        target = Path(path).resolve()
        if os.name == "nt":
            return "NTFS/Windows filesystem (exact type requires OS-specific APIs)"
        try:
            for line in Path("/proc/mounts").read_text().splitlines():
                fields = line.split()
                if len(fields) >= 3 and target.as_posix().startswith(fields[1].replace("\\040", " ")):
                    return fields[2]
        except (OSError, ValueError):
            pass
        return None

    def removable(self) -> list[str]:
        if os.name == "nt":
            return []
        return [str(path) for path in Path("/media").glob("*") if path.is_dir()] if Path("/media").exists() else []
