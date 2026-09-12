"""Filesystem analytics and report generation."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path


class FilesystemAnalytics:
    """Generate streaming-friendly filesystem statistics."""

    def __init__(self, base_path: str | Path = "") -> None:
        self.base = Path(base_path or ".").expanduser().resolve()
        self.base.mkdir(parents=True, exist_ok=True)

    def analyze(self, include_hidden: bool = False) -> dict:
        files = 0
        directories = 0
        total_size = 0
        largest = {"path": None, "size": 0}
        extensions: Counter[str] = Counter()
        for path in self.base.rglob("*"):
            try:
                relative = path.relative_to(self.base)
                if not include_hidden and any(part.startswith(".") for part in relative.parts):
                    continue
                if path.is_dir():
                    directories += 1
                elif path.is_file():
                    size = path.stat().st_size
                    files += 1
                    total_size += size
                    extensions[path.suffix.lower() or "[none]"] += 1
                    if size > largest["size"]:
                        largest = {"path": str(path), "size": size}
            except OSError:
                continue
        return {
            "path": str(self.base),
            "files": files,
            "directories": directories,
            "total_size": total_size,
            "largest_file": largest,
            "average_file_size": total_size / files if files else 0,
            "extensions": dict(extensions),
        }

    def report(self, format: str = "dict", include_hidden: bool = False):
        data = self.analyze(include_hidden=include_hidden)
        if format == "dict":
            return data
        if format == "json":
            return json.dumps(data, indent=2)
        if format == "text":
            return "\n".join(f"{key}: {value}" for key, value in data.items())
        raise ValueError("format must be dict, json, or text")
