"""File type, encoding, signature, entropy, and content inspection."""

from __future__ import annotations

import hashlib
import math
import mimetypes
from collections import Counter
from pathlib import Path


class FileInspector:
    """Inspect files without third-party dependencies."""

    SIGNATURES = {
        b"\x7fELF": "ELF executable",
        b"MZ": "DOS/Windows executable",
        b"PK\x03\x04": "ZIP archive",
        b"\x1f\x8b": "GZIP archive",
        b"%PDF": "PDF document",
        b"\x89PNG\r\n\x1a\n": "PNG image",
        b"\xff\xd8\xff": "JPEG image",
        b"GIF87a": "GIF image",
        b"GIF89a": "GIF image",
        b"RIFF": "RIFF container",
        b"SQLite format 3\x00": "SQLite database",
        b"PK\x05\x06": "Empty ZIP archive",
    }

    def __init__(self, base_path: str | Path = "") -> None:
        self.base = Path(base_path or ".").expanduser().resolve()
        self.base.mkdir(parents=True, exist_ok=True)

    def _path(self, path: str | Path) -> Path:
        candidate = (self.base / path).resolve()
        candidate.relative_to(self.base)
        return candidate

    def inspect(self, path: str | Path, sample_size: int = 65536) -> dict:
        if sample_size <= 0:
            raise ValueError("sample_size must be positive")
        target = self._path(path)
        if not target.is_file():
            raise FileNotFoundError(target)
        with target.open("rb") as handle:
            sample = handle.read(sample_size)
        stat = target.stat()
        mime, encoding_hint = mimetypes.guess_type(target.name)
        return {
            "path": str(target),
            "name": target.name,
            "suffix": target.suffix.lower(),
            "size": stat.st_size,
            "mime": mime or "application/octet-stream",
            "binary": self.is_binary_bytes(sample),
            "encoding": self.detect_encoding(sample),
            "type": self.detect_type(sample),
            "entropy": self.entropy(sample),
            "sha256_sample": hashlib.sha256(sample).hexdigest(),
            "sample_size": len(sample),
            "mime_encoding_hint": encoding_hint,
        }

    @staticmethod
    def is_binary_bytes(data: bytes) -> bool:
        if not data:
            return False
        if b"\x00" in data:
            return True
        controls = sum(1 for byte in data if byte < 32 and byte not in (7, 8, 9, 10, 12, 13))
        return controls / len(data) > 0.05

    @staticmethod
    def detect_encoding(data: bytes) -> str:
        for prefix, encoding in (
            (b"\xef\xbb\xbf", "utf-8-sig"),
            (b"\xff\xfe\x00\x00", "utf-32-le"),
            (b"\x00\x00\xfe\xff", "utf-32-be"),
            (b"\xff\xfe", "utf-16-le"),
            (b"\xfe\xff", "utf-16-be"),
        ):
            if data.startswith(prefix):
                return encoding
        try:
            data.decode("utf-8")
            return "utf-8"
        except UnicodeDecodeError:
            return "binary/unknown"

    @classmethod
    def detect_type(cls, data: bytes) -> str:
        for signature, name in cls.SIGNATURES.items():
            if data.startswith(signature):
                return name
        return "text/data" if not cls.is_binary_bytes(data) else "binary/data"

    @staticmethod
    def entropy(data: bytes) -> float:
        if not data:
            return 0.0
        counts = Counter(data)
        length = len(data)
        return -sum((count / length) * math.log2(count / length) for count in counts.values())

    def text_statistics(self, path: str | Path, encoding: str = "utf-8") -> dict:
        target = self._path(path)
        if not target.is_file():
            raise FileNotFoundError(target)
        lines = words = characters = 0
        with target.open("r", encoding=encoding) as handle:
            for line in handle:
                lines += 1
                words += len(line.split())
                characters += len(line)
        return {"lines": lines, "words": words, "characters": characters, "bytes": target.stat().st_size}
