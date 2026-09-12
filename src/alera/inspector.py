"""File type, encoding, signature, entropy, and content inspection."""

from __future__ import annotations

import math
import mimetypes
from collections import Counter
from pathlib import Path


class FileInspector:
    """Inspect files without requiring third-party dependencies."""

    def __init__(self, base_path: str | Path = "") -> None:
        self.base = Path(base_path or ".").expanduser().resolve()
        self.base.mkdir(parents=True, exist_ok=True)

    def _path(self, path: str | Path) -> Path:
        candidate = (self.base / path).resolve()
        candidate.relative_to(self.base)
        return candidate

    def inspect(self, path: str | Path, sample_size: int = 65536) -> dict:
        target = self._path(path)
        if not target.is_file():
            raise FileNotFoundError(target)
        sample_size = max(1, int(sample_size))
        with target.open("rb") as handle:
            sample = handle.read(sample_size)
        mime, _ = mimetypes.guess_type(target.name)
        return {
            "path": str(target),
            "name": target.name,
            "suffix": target.suffix.lower(),
            "size": target.stat().st_size,
            "mime": mime or "application/octet-stream",
            "binary": self.is_binary_bytes(sample),
            "encoding": self.detect_encoding(sample),
            "type": self.detect_type(sample),
            "entropy": self.entropy(sample),
            "sha256_sample": __import__("hashlib").sha256(sample).hexdigest(),
        }

    @staticmethod
    def is_binary_bytes(data: bytes) -> bool:
        if not data:
            return False
        if b"\x00" in data:
            return True
        control = sum(1 for byte in data if byte < 32 and byte not in (7, 8, 9, 10, 12, 13))
        return control / len(data) > 0.05

    @staticmethod
    def detect_encoding(data: bytes) -> str:
        if data.startswith(b"\xef\xbb\xbf"):
            return "utf-8-sig"
        if data.startswith(b"\xff\xfe\x00\x00"):
            return "utf-32-le"
        if data.startswith(b"\x00\x00\xfe\xff"):
            return "utf-32-be"
        if data.startswith(b"\xff\xfe"):
            return "utf-16-le"
        if data.startswith(b"\xfe\xff"):
            return "utf-16-be"
        try:
            data.decode("utf-8")
            return "utf-8"
        except UnicodeDecodeError:
            return "binary/unknown"

    @staticmethod
    def detect_type(data: bytes) -> str:
        signatures = {
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
        }
        for signature, name in signatures.items():
            if data.startswith(signature):
                return name
        return "text/data" if not FileInspector.is_binary_bytes(data) else "binary/data"

    @staticmethod
    def entropy(data: bytes) -> float:
        if not data:
            return 0.0
        counts = Counter(data)
        length = len(data)
        return -sum((count / length) * math.log2(count / length) for count in counts.values())

    def text_statistics(self, path: str | Path, encoding: str = "utf-8") -> dict:
        target = self._path(path)
        text = target.read_text(encoding=encoding)
        return {"lines": len(text.splitlines()), "words": len(text.split()), "characters": len(text), "bytes": target.stat().st_size}
