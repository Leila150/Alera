"""Deep, streaming, integrity-focused file analysis."""
from __future__ import annotations

import hashlib
import mimetypes
import os
import math
from collections import defaultdict
from pathlib import Path
from typing import Iterator

from .exceptions import AleraPathError, AleraValidationError


class FileAnalysis:
    """Analyze files using bounded-memory streaming algorithms."""

    def __init__(self, base_path: str | os.PathLike[str] = "") -> None:
        raw = Path(base_path).expanduser() if str(base_path) else Path.cwd()
        self.base_path = raw.resolve()
        self.base_path.mkdir(parents=True, exist_ok=True)

    def path(self, value: str | os.PathLike[str]) -> Path:
        candidate = Path(value)
        target = (self.base_path / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
        try: target.relative_to(self.base_path)
        except ValueError as exc: raise AleraPathError(f"Path escapes analysis workspace: {value}") from exc
        return target

    @staticmethod
    def _validate_chunk(chunk_size: int) -> None:
        if chunk_size <= 0: raise AleraValidationError("chunk_size must be greater than zero")

    def checksum(self, file: str | os.PathLike[str], algorithm: str = "sha256", chunk_size: int = 1024 * 1024) -> str:
        self._validate_chunk(chunk_size)
        target = self.path(file)
        if not target.is_file(): raise FileNotFoundError(target)
        try: digest = hashlib.new(algorithm)
        except ValueError as exc: raise AleraValidationError(f"Unsupported hash algorithm: {algorithm}") from exc
        with target.open("rb") as handle:
            for chunk in iter(lambda: handle.read(chunk_size), b""): digest.update(chunk)
        return digest.hexdigest()

    def hashes(self, file: str | os.PathLike[str], chunk_size: int = 1024 * 1024) -> dict[str, str]:
        self._validate_chunk(chunk_size)
        target = self.path(file)
        if not target.is_file(): raise FileNotFoundError(target)
        names = ("md5", "sha1", "sha256", "sha512")
        digests = {name: hashlib.new(name) for name in names}
        with target.open("rb") as handle:
            for chunk in iter(lambda: handle.read(chunk_size), b""):
                for digest in digests.values(): digest.update(chunk)
        return {name: digest.hexdigest() for name, digest in digests.items()}

    def file_type(self, file: str | os.PathLike[str]) -> dict[str, str | None]:
        target = self.path(file)
        if not target.exists(): raise FileNotFoundError(target)
        mime, encoding = mimetypes.guess_type(target.name)
        return {"name": target.name, "suffix": target.suffix.lower(), "mime": mime, "encoding": encoding}

    def byte_statistics(self, file: str | os.PathLike[str], chunk_size: int = 1024 * 1024) -> dict[str, int | float]:
        """Return byte count, unique bytes, zero bytes, and Shannon entropy."""
        self._validate_chunk(chunk_size)
        counts = [0] * 256
        total = 0
        target = self.path(file)
        if not target.is_file(): raise FileNotFoundError(target)
        with target.open("rb") as handle:
            for chunk in iter(lambda: handle.read(chunk_size), b""):
                total += len(chunk)
                for value in chunk: counts[value] += 1
        entropy = 0.0
        if total:
            for count in counts:
                if count:
                    p = count / total
                    entropy -= p * math.log2(p)
        return {"bytes": total, "unique_bytes": sum(c > 0 for c in counts), "zero_bytes": counts[0], "entropy_bits": entropy}

    def text_statistics(self, file: str | os.PathLike[str], encoding: str = "utf-8", chunk_size: int = 1024 * 1024) -> dict[str, int]:
        self._validate_chunk(chunk_size)
        target = self.path(file)
        if not target.is_file(): raise FileNotFoundError(target)
        lines = chars = words = 0
        with target.open("r", encoding=encoding, errors="replace") as handle:
            for chunk in iter(lambda: handle.read(chunk_size), ""):
                chars += len(chunk); lines += chunk.count("\n"); words += len(chunk.split())
        return {"lines": lines, "characters": chars, "words": words}

    def compare(self, first: str | os.PathLike[str], second: str | os.PathLike[str], chunk_size: int = 1024 * 1024) -> bool:
        self._validate_chunk(chunk_size)
        left, right = self.path(first), self.path(second)
        if not left.is_file() or not right.is_file(): raise FileNotFoundError("Both paths must be files")
        if left.stat().st_size != right.stat().st_size: return False
        with left.open("rb") as a, right.open("rb") as b:
            for ca in iter(lambda: a.read(chunk_size), b""):
                cb = b.read(len(ca))
                if ca != cb: return False
            return True

    def duplicates(self, directory: str | os.PathLike[str] = ".", *, algorithm: str = "sha256", minimum_size: int = 1) -> list[list[Path]]:
        root = self.path(directory)
        if not root.is_dir(): raise NotADirectoryError(root)
        if minimum_size < 0: raise AleraValidationError("minimum_size cannot be negative")
        groups: dict[int, list[Path]] = defaultdict(list)
        for file in root.rglob("*"):
            try:
                if file.is_file() and file.stat().st_size >= minimum_size: groups[file.stat().st_size].append(file)
            except OSError: continue
        result = []
        for size, files in groups.items():
            if len(files) < 2: continue
            hashes: dict[str, list[Path]] = defaultdict(list)
            for file in files:
                try: hashes[self.checksum(file, algorithm)].append(file)
                except OSError: continue
            result.extend(group for group in hashes.values() if len(group) > 1)
        return result

    def directory_size(self, directory: str | os.PathLike[str] = ".") -> int:
        root = self.path(directory)
        if not root.is_dir(): raise NotADirectoryError(root)
        total = 0
        for item in root.rglob("*"):
            try:
                if item.is_file(): total += item.stat().st_size
            except OSError: continue
        return total

    def largest(self, directory: str | os.PathLike[str] = ".", limit: int = 10) -> list[tuple[Path, int]]:
        if limit <= 0: raise AleraValidationError("limit must be greater than zero")
        root = self.path(directory)
        if not root.is_dir(): raise NotADirectoryError(root)
        top: list[tuple[Path, int]] = []
        for item in root.rglob("*"):
            try:
                if item.is_file():
                    top.append((item, item.stat().st_size)); top.sort(key=lambda x: x[1], reverse=True); del top[limit:]
            except OSError: continue
        return top

    def stream_chunks(self, file: str | os.PathLike[str], chunk_size: int = 1024 * 1024) -> Iterator[bytes]:
        self._validate_chunk(chunk_size)
        target = self.path(file)
        with target.open("rb") as handle:
            yield from iter(lambda: handle.read(chunk_size), b"")
