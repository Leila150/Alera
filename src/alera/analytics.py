"""Filesystem analytics and report generation."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path


class FilesystemAnalytics:
    def __init__(self, base_path: str | Path = "") -> None:
        self.base = Path(base_path or ".").expanduser().resolve()

    def analyze(self) -> dict:
        files = [p for p in self.base.rglob("*") if p.is_file()]
        sizes = [p.stat().st_size for p in files]
        extensions = Counter((p.suffix.lower() or "[none]") for p in files)
        return {"files": len(files), "directories": sum(1 for p in self.base.rglob("*") if p.is_dir()), "total_size": sum(sizes), "largest_file": max(sizes, default=0), "average_file_size": sum(sizes) / len(sizes) if sizes else 0, "extensions": dict(extensions)}

    def report(self, format: str = "dict"):
        data = self.analyze()
        if format == "dict": return data
        if format == "json": return json.dumps(data, indent=2)
        if format == "text": return "\n".join(f"{key}: {value}" for key, value in data.items())
        raise ValueError("format must be dict, json, or text")
