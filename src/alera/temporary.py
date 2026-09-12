"""Industrial-grade temporary workspace management for Alera."""
from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, Iterator, TextIO

from .exceptions import AleraPathError, AleraValidationError


class TemporaryFiles:
    """Manage isolated, tracked temporary resources with safe cleanup and lifecycle control."""

    def __init__(self, base_path: str | os.PathLike[str] = "", *, prefix: str = "alera-tmp-",
                 auto_cleanup: bool = True, secure_cleanup: bool = False) -> None:
        raw = Path(base_path).expanduser() if str(base_path) else Path.cwd()
        try:
            self.base_path = raw.resolve()
        except OSError as exc:
            raise AleraPathError(f"Unable to resolve temporary workspace: {raw}") from exc
        self.base_path.mkdir(parents=True, exist_ok=True)
        if not prefix or os.sep in prefix or (os.altsep and os.altsep in prefix):
            raise AleraValidationError("prefix must be a non-empty filename prefix.")
        self.prefix = prefix
        self.auto_cleanup = bool(auto_cleanup)
        self.secure_cleanup = bool(secure_cleanup)
        self._root = Path(tempfile.mkdtemp(prefix=prefix, dir=self.base_path))
        self._closed = False

    @property
    def path(self) -> Path:
        """Return the private temporary workspace."""
        self._ensure_open()
        return self._root

    @property
    def closed(self) -> bool:
        return self._closed

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("TemporaryFiles manager is closed")

    def _check(self, path: str | os.PathLike[str]) -> Path:
        self._ensure_open()
        candidate = Path(path)
        target = (self._root / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
        try:
            target.relative_to(self._root)
        except ValueError as exc:
            raise AleraPathError(f"Temporary path escapes workspace: {path}") from exc
        return target

    @staticmethod
    def _bytes(value: bytes | bytearray | memoryview) -> bytes:
        if not isinstance(value, (bytes, bytearray, memoryview)):
            raise AleraValidationError("Binary contents must be bytes-like.")
        return bytes(value)

    @staticmethod
    def _validate_size(size: int) -> None:
        if size < 0:
            raise AleraValidationError("size must be zero or greater.")

    def create_file(self, name: str = "", contents: str = "", *, suffix: str = "", prefix: str = "alera-", mode: int = 0o600) -> Path:
        """Create a temporary text file with restrictive permissions by default."""
        if not isinstance(contents, str):
            raise AleraValidationError("contents must be a string.")
        if name:
            target = self._check(name)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(contents, encoding="utf-8")
            try: os.chmod(target, mode)
            except OSError: pass
            return target
        fd, raw = tempfile.mkstemp(suffix=suffix, prefix=prefix, dir=self._root)
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(contents)
        return Path(raw)

    def create_binary_file(self, name: str = "", contents: bytes | bytearray | memoryview = b"", *, suffix: str = "", prefix: str = "alera-", mode: int = 0o600) -> Path:
        """Create a temporary binary file without changing bytes."""
        payload = self._bytes(contents)
        if name:
            target = self._check(name)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
            try: os.chmod(target, mode)
            except OSError: pass
            return target
        fd, raw = tempfile.mkstemp(suffix=suffix, prefix=prefix, dir=self._root)
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
        return Path(raw)

    def create_directory(self, name: str = "", *, prefix: str = "alera-") -> Path:
        """Create an isolated temporary directory."""
        if name:
            target = self._check(name)
            target.mkdir(parents=True, exist_ok=False)
            return target
        return Path(tempfile.mkdtemp(prefix=prefix, dir=self._root))

    def create_sparse_file(self, name: str = "", size: int = 0, *, suffix: str = ".sparse", prefix: str = "alera-") -> Path:
        """Create a sparse file without physically writing every byte."""
        self._validate_size(size)
        target = self._check(name) if name else Path(tempfile.mkstemp(suffix=suffix, prefix=prefix, dir=self._root)[1])
        with target.open("wb") as handle:
            handle.truncate(size)
        return target

    def open_text(self, name: str = "", *, mode: str = "w+", encoding: str = "utf-8", suffix: str = "", prefix: str = "alera-", newline: str | None = "") -> TextIO:
        """Open a tracked temporary text file."""
        if name:
            target = self._check(name)
            target.parent.mkdir(parents=True, exist_ok=True)
            return target.open(mode, encoding=encoding, newline=newline)
        return tempfile.NamedTemporaryFile(mode=mode, encoding=encoding, suffix=suffix, prefix=prefix, dir=self._root, delete=False, newline=newline)

    def open_binary(self, name: str = "", *, mode: str = "w+b", suffix: str = "", prefix: str = "alera-") -> BinaryIO:
        """Open a tracked temporary binary file."""
        if name:
            target = self._check(name)
            target.parent.mkdir(parents=True, exist_ok=True)
            return target.open(mode)
        return tempfile.NamedTemporaryFile(mode=mode, suffix=suffix, prefix=prefix, dir=self._root, delete=False)

    @contextmanager
    def text(self, name: str = "", *, contents: str = "", encoding: str = "utf-8") -> Iterator[TextIO]:
        """Create/open a text resource and close it automatically."""
        handle = self.open_text(name, mode="w+", encoding=encoding)
        try:
            if contents:
                handle.write(contents)
                handle.flush()
            yield handle
        finally:
            handle.close()

    @contextmanager
    def binary(self, name: str = "", *, contents: bytes = b"") -> Iterator[BinaryIO]:
        """Create/open a binary resource and close it automatically."""
        handle = self.open_binary(name, mode="w+b")
        try:
            if contents:
                handle.write(contents)
                handle.flush()
            yield handle
        finally:
            handle.close()

    def list(self, *, recursive: bool = False, files_only: bool = False, directories_only: bool = False) -> list[Path]:
        """List temporary resources, optionally recursively and type-filtered."""
        self._ensure_open()
        if files_only and directories_only:
            raise AleraValidationError("files_only and directories_only cannot both be true")
        iterator = self._root.rglob("*") if recursive else self._root.iterdir()
        result = []
        for item in iterator:
            if files_only and not item.is_file(): continue
            if directories_only and not item.is_dir(): continue
            result.append(item)
        return sorted(result, key=lambda item: str(item).casefold())

    def exists(self, name: str | os.PathLike[str]) -> bool:
        return self._check(name).exists()

    def information(self, name: str | os.PathLike[str]) -> dict[str, object]:
        """Return metadata, age and checksum information for a temporary file/directory."""
        target = self._check(name)
        info = target.stat()
        return {
            "name": target.name, "path": str(target),
            "type": "directory" if target.is_dir() else "file",
            "size": self._size(target), "created": info.st_ctime,
            "modified": info.st_mtime, "age": max(0.0, time.time() - info.st_mtime),
            "mode": info.st_mode & 0o7777,
            "readable": os.access(target, os.R_OK), "writable": os.access(target, os.W_OK),
            "sha256": self._hash(target) if target.is_file() else None,
        }

    def _hash(self, target: Path) -> str:
        digest = hashlib.sha256()
        with target.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def remove(self, name: str | os.PathLike[str]) -> Path:
        """Remove one temporary resource."""
        target = self._check(name)
        if not target.exists():
            raise FileNotFoundError(target)
        if target.is_dir(): shutil.rmtree(target)
        else: target.unlink()
        return target

    def cleanup(self, *, older_than: float | None = None, dry_run: bool = False) -> list[Path]:
        """Clean resources; optionally restrict cleanup by age and preview without deletion."""
        if older_than is not None and older_than < 0:
            raise AleraValidationError("older_than must be zero or greater.")
        candidates = self.list()
        if older_than is not None:
            candidates = [p for p in candidates if self.age(p.name) >= older_than]
        if dry_run:
            return candidates
        removed = []
        for item in candidates:
            try: removed.append(self.remove(item.relative_to(self._root)))
            except (FileNotFoundError, OSError): pass
        return removed

    def close(self) -> None:
        """Destroy the private workspace and make this manager unusable."""
        if self._closed:
            return
        if self.auto_cleanup:
            try:
                if self.secure_cleanup:
                    self._secure_tree(self._root)
                else:
                    shutil.rmtree(self._root, ignore_errors=True)
            finally:
                self._closed = True
        else:
            self._closed = True

    def __enter__(self) -> "TemporaryFiles":
        self._ensure_open()
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    def __del__(self) -> None:
        if getattr(self, "auto_cleanup", False) and not getattr(self, "_closed", True):
            try: self.close()
            except Exception: pass

    @staticmethod
    def _secure_file(path: Path) -> None:
        try:
            size = path.stat().st_size
            with path.open("r+b", buffering=0) as handle:
                remaining = size
                while remaining:
                    chunk = min(1024 * 1024, remaining)
                    handle.write(os.urandom(chunk))
                    remaining -= chunk
                handle.flush()
                os.fsync(handle.fileno())
            path.unlink()
        except OSError:
            try: path.unlink(missing_ok=True)
            except OSError: pass

    def _secure_tree(self, root: Path) -> None:
        if not root.exists(): return
        for item in sorted(root.rglob("*"), key=lambda p: len(p.parts), reverse=True):
            if item.is_file(): self._secure_file(item)
            elif item.is_dir():
                try: item.rmdir()
                except OSError: shutil.rmtree(item, ignore_errors=True)
        try: root.rmdir()
        except OSError: shutil.rmtree(root, ignore_errors=True)

    @staticmethod
    def _size(path: Path) -> int:
        if path.is_file(): return path.stat().st_size
        total = 0
        for item in path.rglob("*"):
            try:
                if item.is_file(): total += item.stat().st_size
            except OSError: pass
        return total

    def age(self, name: str | os.PathLike[str]) -> float:
        return max(0.0, time.time() - self._check(name).stat().st_mtime)

    def cleanup_older_than(self, seconds: float) -> list[Path]:
        """Compatibility helper for age-based cleanup."""
        return self.cleanup(older_than=seconds)
