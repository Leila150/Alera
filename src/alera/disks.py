"""Cross-platform disk and filesystem information."""
from __future__ import annotations

import os
import shutil
from pathlib import Path


class DiskManager:
    """Inspect mounted filesystems, usage, and common removable media."""

    def roots(self) -> list[str]:
        if os.name == "nt":
            import string
            return [f"{drive}:\\" for drive in string.ascii_uppercase if Path(f"{drive}:\\").exists()]
        roots = {"/"}
        for candidate in (Path("/mnt"), Path("/media"), Path("/storage")):
            if candidate.exists():
                roots.update(str(path) for path in candidate.iterdir() if path.is_dir())
        return sorted(roots)

    def information(self, path: str | Path | None = None) -> dict:
        target = Path(path or ".").expanduser().resolve()
        usage = shutil.disk_usage(target)
        return {"path": str(target), "total": usage.total, "used": usage.used, "free": usage.free, "percent_used": usage.used / usage.total * 100 if usage.total else 0.0}

    def enumerate(self) -> list[dict]:
        return [self.information(root) for root in self.roots()]

    def filesystem(self, path: str | Path = ".") -> str | None:
        target = Path(path).expanduser().resolve()
        if os.name == "nt":
            return "Windows filesystem"
        mounts = Path("/proc/mounts")
        if mounts.exists():
            best = (0, None)
            try:
                for line in mounts.read_text(errors="replace").splitlines():
                    fields = line.split()
                    if len(fields) >= 3:
                        mount = fields[1].replace("\\040", " ")
                        if str(target).startswith(mount.rstrip("/") + "/") or str(target) == mount:
                            if len(mount) > best[0]:
                                best = (len(mount), fields[2])
            except OSError:
                pass
            return best[1]
        return None

    def removable(self) -> list[str]:
        candidates = []
        for root in (Path("/media"), Path("/mnt"), Path("/storage")):
            if root.exists():
                candidates.extend(str(path) for path in root.iterdir() if path.is_dir())
        return sorted(set(candidates))
