"""Android shared-storage utilities for Alera."""
from __future__ import annotations

import os
from pathlib import Path


class AndroidStorage:
    """Discover common Android shared-storage locations without requiring root."""

    def __init__(self, base_path: str | Path = "") -> None:
        self.base_path = (Path(base_path).expanduser() if str(base_path) else Path.cwd()).resolve()

    @property
    def is_android(self) -> bool:
        return os.name == "posix" and ("ANDROID_ROOT" in os.environ or "ANDROID_DATA" in os.environ or Path("/system/bin/app_process").exists())

    @property
    def primary(self) -> Path | None:
        candidates = [os.environ.get("EXTERNAL_STORAGE"), "/storage/emulated/0", "/sdcard"]
        for candidate in candidates:
            if candidate:
                path = Path(candidate)
                if path.exists():
                    return path.resolve()
        return None

    def directories(self) -> dict[str, Path]:
        root = self.primary
        if root is None:
            return {}
        return {name: root / name for name in ("Download", "Documents", "Pictures", "Movies", "Music", "DCIM", "Android") if (root / name).exists()}

    def information(self) -> dict[str, object]:
        root = self.primary
        result: dict[str, object] = {"android": self.is_android, "primary": root, "shared_storage": root is not None}
        if root:
            usage = os.statvfs(root)
            result.update({"total": usage.f_frsize * usage.f_blocks, "free": usage.f_frsize * usage.f_bavail, "used": usage.f_frsize * (usage.f_blocks - usage.f_bfree)})
        return result
