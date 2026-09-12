"""File analysis, comparison, checksum, and duplicate-detection tools."""

from __future__ import annotations

import hashlib
import mimetypes
import os
from collections import defaultdict
from pathlib import Path
from typing import Iterable

from .exceptions import AleraPathError, AleraValidationError


class FileAnalysis:
    """Analyze files without modifying them."""

    def __init__(self, base_path: str | os.PathLike[str] = "") -> None:
        raw = Path(base_path).expanduser() if str(base_path) else Path.cwd()
        self.base_path = raw.resolve()
        self.base_path.mkdir(parents=True, exist_ok=True)

    def path(self, value: str | os.PathLike[str]) -> Path:
        candidate = Path(value)
        target = (self.base_path / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
        try:
            target.relative_to(self.base_path)
        except ValueError as exc:
            raise AleraPathError(f"Path escapes analysis workspace: {value}") from exc
        return target

    def checksum(self, file: str | os.PathLike[str], algorithm: str = "sha256", chunk_size: int = 1024 * 1024) -> str:
        """Return a hexadecimal checksum using a streaming read."""
        if chunk_size <= 0:
            raise AleraValidationError("chunk_size must be greater than zero.")
        target = self.path(file)
        if not target.is_file():
            raise FileNotFoundError(target)
        try:
            digest = hashlib.new(algorithm)
        except ValueError as exc:
            raise AleraValidationError(f"Unsupported hash algorithm: {algorithm}") from exc
        with target.open("rb") as handle:
            for chunk in iter(lambda: handle.read(chunk_size), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def hashes(self, file: str | os.PathLike[str]) -> dict[str, str]:
        """Return several common cryptographic hashes in one pass."""
        target = self.path(file)
        if not target.is_file():
            raise FileNotFoundError(target)
        digests = {name: hashlib.new(name) for name in ("md5", "sha1", "sha256", "sha512")}
        with target.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                for digest in digests.values():
                    digest.update(chunk)
        return {name: digest.hexdigest() for name, digest in digests.items()}

    def file_type(self, file: str | os.PathLike[str]) -> dict[str, str | None]:
        """Return filename, suffix, guessed MIME type, and encoding."""
        target = self.path(file)
        if not target.exists():
            raise FileNotFoundError(target)
        mime, encoding = mimetypes.guess_type(target.name)
        return {"name": target.name, "suffix": target.suffix.lower(), "mime": mime, "encoding": encoding}

    def compare(self, first: str | os.PathLike[str], second: str | os.PathLike[str], chunk_size: int = 1024 * 1024) -> bool:
        """Compare two files byte-for-byte without loading them into memory."""
        left, right = self.path(first), self.path(second)
        if not left.is_file() or not right.is_file():
            raise FileNotFoundError("Both paths must be files.")
        if left.stat().st_size != right.stat().st_size:
            return False
        with left.open("rb") as a, right.open("rb") as b:
            while True:
                chunk_a, chunk_b = a.read(chunk_size), b.read(chunk_size)
                if chunk_a != chunk_b:
                    return False
                if not chunk_a:
                    return True

    def duplicates(self, directory: str | os.PathLike[str] = ".", *, algorithm: str = "sha256") -> list[list[Path]]:
        """Find groups of duplicate files by size and checksum."""
        root = self.path(directory)
        if not root.is_dir():
            raise NotADirectoryError(root)
        groups: dict[tuple[int, str], list[Path]] = defaultdict(list)
        for file in root.rglob("*"):
            if file.is_file():
                size = file.stat().st_size
                groups[(size, self.checksum(file, algorithm))].append(file)
        return [items for items in groups.values() if len(items) > 1]

    def directory_size(self, directory: str | os.PathLike[str] = ".") -> int:
        """Return total file size below a directory."""
        root = self.path(directory)
        if not root.is_dir():
            raise NotADirectoryError(root)
        return sum(item.stat().st_size for item in root.rglob("*") if item.is_file())

    def largest(self, directory: str | os.PathLike[str] = ".", limit: int = 10) -> list[tuple[Path, int]]:
        """Return the largest files below a directory."""
        if limit <= 0:
            raise AleraValidationError("limit must be greater than zero.")
        root = self.path(directory)
        if not root.is_dir():
            raise NotADirectoryError(root)
        files = [(item, item.stat().st_size) for item in root.rglob("*") if item.is_file()]
        return sorted(files, key=lambda item: item[1], reverse=True)[:limit]
