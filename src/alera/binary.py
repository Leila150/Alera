"""Advanced binary-file operations for Alera.

The module is intentionally dependency-free and streaming-first.  It handles
large files without loading them into memory unless the caller explicitly asks
for an in-memory result.
"""
from __future__ import annotations

import base64
import bz2
import gzip
import hashlib
import lzma
import mmap
import os
import struct
import zlib
from pathlib import Path
from typing import BinaryIO, Iterable, Iterator

from .exceptions import AleraPathError, AleraValidationError


class BinaryFileManager:
    """High-performance binary file toolkit rooted at an Alera workspace."""

    INTERNAL = frozenset({
        ".alera_bin", ".alera_hidden", ".alera_recovery", ".alera_cache",
        ".alera_versions", ".alera_index", ".alera_database",
    })

    def __init__(self, base_path: str | os.PathLike[str] = "") -> None:
        raw = Path(base_path).expanduser() if str(base_path) else Path.cwd()
        self.base_path = raw.resolve()
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _path(self, path: str | os.PathLike[str]) -> Path:
        candidate = Path(path).expanduser()
        target = (candidate if candidate.is_absolute() else self.base_path / candidate).resolve()
        try:
            relative = target.relative_to(self.base_path)
        except ValueError as exc:
            raise AleraPathError(f"Path escapes binary workspace: {path}") from exc
        if any(part in self.INTERNAL for part in relative.parts):
            raise AleraPathError("Alera internal paths cannot be manipulated as normal binary files.")
        return target

    @staticmethod
    def _chunk_size(size: int) -> int:
        if not isinstance(size, int) or size <= 0:
            raise AleraValidationError("chunk_size must be a positive integer.")
        return size

    def exists(self, path) -> bool: return self._path(path).is_file()
    def size(self, path) -> int: return self._path(path).stat().st_size

    def open(self, path, mode: str = "rb", **kwargs) -> BinaryIO:
        if "b" not in mode: raise AleraValidationError("BinaryFileManager.open requires binary mode.")
        return self._path(path).open(mode, **kwargs)

    def read(self, path, *, offset: int = 0, length: int | None = None) -> bytes:
        if offset < 0 or (length is not None and length < 0): raise AleraValidationError("offset and length must be non-negative.")
        with self.open(path, "rb") as handle:
            handle.seek(offset)
            return handle.read() if length is None else handle.read(length)

    def read_chunks(self, path, chunk_size: int = 1024 * 1024, *, offset: int = 0, length: int | None = None) -> Iterator[bytes]:
        chunk_size = self._chunk_size(chunk_size)
        if offset < 0 or (length is not None and length < 0): raise AleraValidationError("offset and length must be non-negative.")
        remaining = length
        with self.open(path, "rb") as handle:
            handle.seek(offset)
            while True:
                amount = chunk_size if remaining is None else min(chunk_size, remaining)
                if amount == 0: return
                chunk = handle.read(amount)
                if not chunk: return
                yield chunk
                if remaining is not None:
                    remaining -= len(chunk)
                    if remaining <= 0: return

    def write(self, path, data: bytes | bytearray | memoryview, *, offset: int | None = None, atomic: bool = False) -> Path:
        if not isinstance(data, (bytes, bytearray, memoryview)): raise AleraValidationError("data must be bytes-like.")
        target = self._path(path); target.parent.mkdir(parents=True, exist_ok=True); payload = bytes(data)
        if atomic and offset is not None: raise AleraValidationError("atomic offset writes are not supported.")
        if atomic:
            temporary = target.with_name(f".{target.name}.alera-binary-tmp")
            with temporary.open("wb") as handle:
                handle.write(payload); handle.flush(); os.fsync(handle.fileno())
            os.replace(temporary, target)
            return target
        with target.open("wb" if offset is None else "r+b") as handle:
            if offset is not None: handle.seek(offset)
            handle.write(payload); handle.flush()
        return target

    def append(self, path, data) -> Path:
        if not isinstance(data, (bytes, bytearray, memoryview)): raise AleraValidationError("data must be bytes-like.")
        target = self._path(path); target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("ab") as handle: handle.write(bytes(data))
        return target

    def write_chunks(self, path, chunks: Iterable[bytes], *, atomic: bool = False) -> Path:
        target = self._path(path); target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.alera-binary-tmp") if atomic else target
        try:
            with temporary.open("wb") as handle:
                for chunk in chunks:
                    if not isinstance(chunk, (bytes, bytearray, memoryview)): raise AleraValidationError("Every chunk must be bytes-like.")
                    handle.write(bytes(chunk))
                handle.flush(); os.fsync(handle.fileno())
            if atomic: os.replace(temporary, target)
            return target
        finally:
            if atomic:
                try: temporary.unlink()
                except FileNotFoundError: pass

    def copy(self, source, destination, *, chunk_size: int = 1024 * 1024, preserve_metadata: bool = True) -> Path:
        chunk_size = self._chunk_size(chunk_size); src = self._path(source); dst = self._path(destination)
        if not src.is_file(): raise FileNotFoundError(src)
        if src == dst: raise AleraValidationError("Source and destination are identical.")
        dst.parent.mkdir(parents=True, exist_ok=True)
        with src.open("rb") as inp, dst.open("wb") as out:
            while chunk := inp.read(chunk_size): out.write(chunk)
            out.flush(); os.fsync(out.fileno())
        if preserve_metadata:
            import shutil
            shutil.copystat(src, dst, follow_symlinks=False)
        return dst

    def compare(self, left, right, *, chunk_size: int = 1024 * 1024) -> bool:
        if self.size(left) != self.size(right): return False
        left_chunks = self.read_chunks(left, chunk_size); right_chunks = self.read_chunks(right, chunk_size)
        return all(a == b for a, b in zip(left_chunks, right_chunks))

    def compare_range(self, left, right, *, offset: int = 0, length: int | None = None, chunk_size: int = 1024 * 1024) -> bool:
        a = self.read_chunks(left, chunk_size, offset=offset, length=length); b = self.read_chunks(right, chunk_size, offset=offset, length=length)
        sentinel = object()
        while True:
            x, y = next(a, sentinel), next(b, sentinel)
            if x is sentinel or y is sentinel: return x is y
            if x != y: return False

    def hash(self, path, algorithm: str = "sha256", chunk_size: int = 1024 * 1024) -> str:
        self._chunk_size(chunk_size)
        try: digest = hashlib.new(algorithm)
        except ValueError as exc: raise AleraValidationError(f"Unsupported hash algorithm: {algorithm}") from exc
        for chunk in self.read_chunks(path, chunk_size): digest.update(chunk)
        return digest.hexdigest()

    def hashes(self, path, algorithms: Iterable[str] = ("md5", "sha1", "sha256", "sha512"), chunk_size: int = 1024 * 1024) -> dict[str, str]:
        self._chunk_size(chunk_size)
        names = list(dict.fromkeys(algorithms))
        try: digests = {name: hashlib.new(name) for name in names}
        except ValueError as exc: raise AleraValidationError("One or more hash algorithms are unsupported.") from exc
        for chunk in self.read_chunks(path, chunk_size):
            for digest in digests.values(): digest.update(chunk)
        return {name: digest.hexdigest() for name, digest in digests.items()}

    def crc32(self, path, chunk_size: int = 1024 * 1024) -> int:
        value = 0
        for chunk in self.read_chunks(path, chunk_size): value = zlib.crc32(chunk, value)
        return value & 0xffffffff

    def adler32(self, path, chunk_size: int = 1024 * 1024) -> int:
        value = 1
        for chunk in self.read_chunks(path, chunk_size): value = zlib.adler32(chunk, value)
        return value & 0xffffffff

    def byte_frequency(self, path, chunk_size: int = 1024 * 1024) -> list[int]:
        counts = [0] * 256
        for chunk in self.read_chunks(path, chunk_size):
            for value in chunk: counts[value] += 1
        return counts

    def entropy(self, path, chunk_size: int = 1024 * 1024) -> float:
        import math
        counts = self.byte_frequency(path, chunk_size); total = sum(counts)
        if total == 0: return 0.0
        return -sum((count / total) * math.log2(count / total) for count in counts if count)

    def statistics(self, path, chunk_size: int = 1024 * 1024) -> dict[str, object]:
        counts = self.byte_frequency(path, chunk_size); total = sum(counts)
        printable = sum(counts[i] for i in range(32, 127)); nulls = counts[0]
        return {"size": total, "entropy": self.entropy(path, chunk_size), "unique_bytes": sum(bool(x) for x in counts), "zero_bytes": nulls, "zero_ratio": nulls / total if total else 0.0, "printable_bytes": printable, "printable_ratio": printable / total if total else 0.0, "byte_frequency": counts}

    def find(self, path, needle: bytes, *, chunk_size: int = 1024 * 1024, start: int = 0, max_results: int | None = None) -> list[int]:
        if not isinstance(needle, bytes) or not needle: raise AleraValidationError("needle must be non-empty bytes.")
        self._chunk_size(chunk_size)
        overlap = max(0, len(needle) - 1); results: list[int] = []; carry = b""; position = start
        for chunk in self.read_chunks(path, chunk_size, offset=start):
            data = carry + chunk; base = position - len(carry); cursor = 0
            while True:
                found = data.find(needle, cursor)
                if found < 0: break
                results.append(base + found)
                if max_results is not None and len(results) >= max_results: return results
                cursor = found + 1
            carry = data[-overlap:] if overlap else b""; position += len(chunk)
        return results

    def replace(self, path, old: bytes, new: bytes, *, count: int = -1, atomic: bool = True, chunk_size: int = 1024 * 1024) -> int:
        if not isinstance(old, bytes) or not old: raise AleraValidationError("old must be non-empty bytes.")
        if not isinstance(new, bytes): raise AleraValidationError("new must be bytes.")
        data = self.read(path)
        changed = data.count(old) if count < 0 else min(data.count(old), count)
        result = data.replace(old, new, count)
        self.write(path, result, atomic=atomic)
        return changed

    def slice(self, path, destination, start: int, end: int | None = None, *, chunk_size: int = 1024 * 1024) -> Path:
        if start < 0 or (end is not None and end < start): raise AleraValidationError("Invalid slice range.")
        return self.write_chunks(destination, self.read_chunks(path, chunk_size, offset=start, length=None if end is None else end - start), atomic=True)

    def split(self, path, output_directory, *, chunk_size: int = 1024 * 1024, prefix: str | None = None) -> list[Path]:
        self._chunk_size(chunk_size); source = self._path(path); directory = self._path(output_directory); directory.mkdir(parents=True, exist_ok=True)
        prefix = prefix or source.name; result: list[Path] = []
        with source.open("rb") as handle:
            index = 0
            while chunk := handle.read(chunk_size):
                target = directory / f"{prefix}.part{index:06d}"; target.write_bytes(chunk); result.append(target); index += 1
        return result

    def join(self, parts: Iterable[str | os.PathLike[str]], destination, *, chunk_size: int = 1024 * 1024, atomic: bool = True) -> Path:
        return self.write_chunks(destination, (chunk for part in parts for chunk in self.read_chunks(part, chunk_size)), atomic=atomic)

    def hexdump(self, path, *, offset: int = 0, length: int = 256, width: int = 16) -> str:
        if length < 0 or width <= 0: raise AleraValidationError("length must be non-negative and width positive.")
        data = self.read(path, offset=offset, length=length); lines = []
        for index in range(0, len(data), width):
            chunk = data[index:index + width]; hexpart = " ".join(f"{b:02x}" for b in chunk); ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
            lines.append(f"{offset + index:08x}  {hexpart:<{width * 3 - 1}}  |{ascii_part}|" )
        return "\n".join(lines)

    def mmap(self, path, *, access: int = mmap.ACCESS_READ):
        handle = self.open(path, "rb")
        try: return mmap.mmap(handle.fileno(), 0, access=access)
        except Exception:
            handle.close(); raise

    def read_struct(self, path, offset: int, fmt: str, *, endian: str = ""):
        prefix = self._endian(endian); size = struct.calcsize(prefix + fmt); data = self.read(path, offset=offset, length=size)
        if len(data) != size: raise EOFError("Not enough bytes for requested structure.")
        return struct.unpack(prefix + fmt, data)

    def write_struct(self, path, offset: int, fmt: str, values, *, endian: str = "") -> Path:
        prefix = self._endian(endian); data = struct.pack(prefix + fmt, *values) if isinstance(values, tuple) else struct.pack(prefix + fmt, values)
        return self.write(path, data, offset=offset)

    @staticmethod
    def _endian(value: str) -> str:
        if value not in ("", "little", "big", "native"):
            raise AleraValidationError("endian must be '', 'little', 'big', or 'native'.")
        return {"little": "<", "big": ">", "native": "="}[value] if value else "="

    def to_base64(self, path) -> str: return base64.b64encode(self.read(path)).decode("ascii")
    def from_base64(self, value: str, destination) -> Path:
        try: data = base64.b64decode(value, validate=True)
        except Exception as exc: raise AleraValidationError("Invalid Base64 data.") from exc
        return self.write(destination, data, atomic=True)
    def to_hex(self, path) -> str: return self.read(path).hex()
    def from_hex(self, value: str, destination) -> Path:
        try: data = bytes.fromhex(value)
        except ValueError as exc: raise AleraValidationError("Invalid hexadecimal data.") from exc
        return self.write(destination, data, atomic=True)

    def compress(self, path, destination, *, algorithm: str = "gzip", level: int = 6, chunk_size: int = 1024 * 1024) -> Path:
        source, target = self._path(path), self._path(destination); target.parent.mkdir(parents=True, exist_ok=True)
        opener = {"gzip": gzip.open, "bz2": bz2.open, "lzma": lzma.open}.get(algorithm.lower())
        if opener is None: raise AleraValidationError("algorithm must be gzip, bz2, or lzma.")
        kwargs = {"compresslevel": level} if algorithm.lower() in ("gzip", "bz2") else {"preset": level}
        with source.open("rb") as inp, opener(target, "wb", **kwargs) as out:
            while chunk := inp.read(chunk_size): out.write(chunk)
        return target

    def decompress(self, path, destination, *, algorithm: str = "gzip", chunk_size: int = 1024 * 1024) -> Path:
        source, target = self._path(path), self._path(destination); target.parent.mkdir(parents=True, exist_ok=True)
        opener = {"gzip": gzip.open, "bz2": bz2.open, "lzma": lzma.open}.get(algorithm.lower())
        if opener is None: raise AleraValidationError("algorithm must be gzip, bz2, or lzma.")
        with opener(source, "rb") as inp, target.open("wb") as out:
            while chunk := inp.read(chunk_size): out.write(chunk)
        return target

    def information(self, path) -> dict[str, object]:
        target = self._path(path); stat_result = target.stat(); size = stat_result.st_size
        return {"path": str(target), "name": target.name, "size": size, "size_bits": size * 8, "suffix": target.suffix, "modified": stat_result.st_mtime, "created": stat_result.st_ctime, "sha256": self.hash(target), "crc32": self.crc32(target), "entropy": self.entropy(target), "is_empty": size == 0}
