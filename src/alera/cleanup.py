"""Configurable cleanup with explicit category controls and dry-run support."""

from __future__ import annotations

import time
from pathlib import Path


class CleanupManager:
    CATEGORIES = ("temporary", "empty_files", "empty_directories", "duplicates", "old_files", "broken_links")

    def __init__(self, base_path: str | Path = "", **configuration: bool) -> None:
        self.base = Path(base_path or ".").expanduser().resolve()
        self.configuration = {category: False for category in self.CATEGORIES}
        self.configure(**configuration)

    def configure(self, **values: bool) -> dict[str, bool]:
        unknown = set(values) - set(self.CATEGORIES)
        if unknown: raise ValueError(f"Unknown cleanup categories: {sorted(unknown)}")
        for key, value in values.items(): self.configuration[key] = bool(value)
        return self.configuration.copy()

    def reset_configuration(self) -> dict[str, bool]:
        return self.configure(**{key: False for key in self.CATEGORIES})

    def scan(self) -> dict[str, list[str]]:
        result = {category: [] for category in self.CATEGORIES}
        files = [p for p in self.base.rglob("*") if p.is_file() and ".alera_" not in p.parts]
        if self.configuration["empty_files"]: result["empty_files"] = [str(p) for p in files if p.stat().st_size == 0]
        if self.configuration["empty_directories"]: result["empty_directories"] = [str(p) for p in self.base.rglob("*") if p.is_dir() and not any(p.iterdir())]
        if self.configuration["temporary"]: result["temporary"] = [str(p) for p in files if p.suffix.lower() in {".tmp", ".temp", ".cache", ".bak"}]
        if self.configuration["old_files"]:
            cutoff = time.time() - 30 * 86400
            result["old_files"] = [str(p) for p in files if p.stat().st_mtime < cutoff]
        if self.configuration["broken_links"]: result["broken_links"] = [str(p) for p in self.base.rglob("*") if p.is_symlink() and not p.exists()]
        return result

    def preview(self) -> dict[str, list[str]]:
        return self.scan()

    def clean(self) -> dict[str, list[str]]:
        found = self.scan()
        for category, paths in found.items():
            if not self.configuration[category]: continue
            for raw in paths:
                path = Path(raw)
                if category == "empty_directories": path.rmdir()
                elif path.is_symlink() or path.is_file(): path.unlink(missing_ok=True)
        return found
