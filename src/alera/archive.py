"""High-level archive creation, inspection, extraction, and validation for Alera."""

from __future__ import annotations

import bz2
import gzip
import hashlib
import lzma
import os
import shutil
import tarfile
import zipfile
from fnmatch import fnmatch
from pathlib import Path
from typing import Iterable, Iterator

from .exceptions import AleraPathError, AleraValidationError


class ArchiveManager:
    """Feature-rich, workspace-safe archive manager.

    Built-in formats:
    - ZIP
    - TAR
    - TAR.GZ / TGZ
    - TAR.BZ2 / TBZ2 / TBZ
    - TAR.XZ / TXZ
    - standalone GZIP, BZIP2, and XZ streams

    Optional formats are supported when their third-party modules are installed:
    - 7Z via ``py7zr``
    - RAR via ``rarfile``

    The manager also provides archive inspection, checksums, compression
    statistics, streaming extraction, filtering, and archive-bomb safeguards.
    """

    BUILTIN_FORMATS = {
        "zip", "tar", "tar.gz", "tgz", "gztar", "tar.bz2", "tbz2", "tbz",
        "bztar", "tar.xz", "txz", "xztar", "gz", "gzip", "bz2", "bzip2", "xz", "lzma",
    }
    _INTERNAL_PREFIXES = (
        ".alera_bin/", ".alera_hidden/", ".alera_recovery/", ".alera_cache/", ".alera_versions/",
    )

    def __init__(self, base_path: str | Path = "") -> None:
        self.base_path = (Path(base_path).expanduser() if str(base_path) else Path.cwd()).resolve()
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _path(self, value: str | Path) -> Path:
        candidate = Path(value)
        target = (self.base_path / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
        try:
            target.relative_to(self.base_path)
        except ValueError as exc:
            raise AleraPathError(f"Path escapes archive workspace: {value}") from exc
        return target

    @staticmethod
    def _normal_format(value: str | None) -> str:
        return "" if value is None else value.lower().strip().lstrip(".").replace("_", ".")

    @classmethod
    def _format(cls, value: str | None, archive: Path | None = None) -> str:
        fmt = cls._normal_format(value)
        if not fmt and archive is not None:
            name = archive.name.lower()
            composites = {
                ".tar.gz": "tar.gz", ".tgz": "tar.gz", ".tar.bz2": "tar.bz2",
                ".tbz2": "tar.bz2", ".tbz": "tar.bz2", ".tar.xz": "tar.xz", ".txz": "tar.xz",
            }
            for suffix, detected in composites.items():
                if name.endswith(suffix):
                    return detected
            fmt = archive.suffix.lower().lstrip(".")
        aliases = {
            "gztar": "tar.gz", "tgz": "tar.gz", "bztar": "tar.bz2", "tbz": "tar.bz2",
            "tbz2": "tar.bz2", "xztar": "tar.xz", "txz": "tar.xz",
            "gzip": "gz", "bzip2": "bz2", "lzma": "xz",
        }
        fmt = aliases.get(fmt, fmt)
        if fmt not in cls.BUILTIN_FORMATS and fmt not in {"7z", "rar"}:
            raise AleraValidationError(
                "Unsupported archive format. Supported: zip, tar, tar.gz, tar.bz2, tar.xz, "
                "gz, bz2, xz, and optional 7z/rar."
            )
        return fmt

    @staticmethod
    def _compression_level(level: int | None) -> int:
        if level is None:
            return 6
        if not isinstance(level, int) or not 0 <= level <= 9:
            raise AleraValidationError("compression_level must be an integer from 0 to 9.")
        return level

    @staticmethod
    def _safe_member(name: str) -> bool:
        normalized = name.replace("\\", "/")
        if not normalized or normalized.startswith(("/", "\\")):
            return False
        return ".." not in [part for part in normalized.split("/") if part not in ("", ".")]

    @classmethod
    def _validate_members(cls, names: Iterable[str], destination: Path, max_members: int | None = None) -> None:
        root = destination.resolve()
        count = 0
        for name in names:
            count += 1
            if max_members is not None and count > max_members:
                raise AleraValidationError("Archive contains too many members.")
            if not cls._safe_member(name):
                raise AleraPathError(f"Archive member escapes destination: {name}")
            target = (destination / Path(name)).resolve()
            try:
                target.relative_to(root)
            except ValueError as exc:
                raise AleraPathError(f"Archive member escapes destination: {name}") from exc

    @classmethod
    def _filtered(cls, name: str, include: Iterable[str] | None, exclude: Iterable[str] | None) -> bool:
        normalized = name.replace("\\", "/")
        if any(normalized == p.rstrip("/") or normalized.startswith(p) for p in cls._INTERNAL_PREFIXES):
            return False
        if include and not any(fnmatch(normalized, pattern) for pattern in include):
            return False
        if exclude and any(fnmatch(normalized, pattern) for pattern in exclude):
            return False
        return True

    def _iter_sources(self, sources: list[str | Path], include: Iterable[str] | None, exclude: Iterable[str] | None) -> Iterator[tuple[Path, str]]:
        if not isinstance(sources, list) or not sources:
            raise AleraValidationError("sources must be a non-empty list.")
        for source in sources:
            path = self._path(source)
            if not path.exists():
                raise FileNotFoundError(path)
            if path.is_file() or path.is_symlink():
                arcname = path.relative_to(self.base_path).as_posix()
                if self._filtered(arcname, include, exclude):
                    yield path, arcname
                continue
            root_name = path.relative_to(self.base_path).as_posix()
            if self._filtered(root_name, include, exclude):
                yield path, root_name
            for item in path.rglob("*"):
                relative = item.relative_to(self.base_path).as_posix()
                if self._filtered(relative, include, exclude):
                    yield item, relative

    def create(self, archive: str | Path, sources: list[str | Path], format: str | None = None,
               compression_level: int | None = None, include: Iterable[str] | None = None,
               exclude: Iterable[str] | None = None, follow_symlinks: bool = False) -> Path:
        """Create an archive from files/directories with optional filtering."""
        target = self._path(archive)
        archive_format = self._format(format, target)
        target.parent.mkdir(parents=True, exist_ok=True)
        level = self._compression_level(compression_level)
        entries = list(self._iter_sources(sources, include, exclude))

        if archive_format == "zip":
            compression = zipfile.ZIP_STORED if level == 0 else zipfile.ZIP_DEFLATED
            with zipfile.ZipFile(target, "w", compression=compression, compresslevel=level) as handle:
                for path, arcname in entries:
                    if path.is_symlink() and not follow_symlinks:
                        info = zipfile.ZipInfo(arcname)
                        info.external_attr = (0o120777 << 16) | 0xA0000000
                        handle.writestr(info, os.readlink(path).encode())
                    else:
                        handle.write(path, arcname)
        elif archive_format in {"tar", "tar.gz", "tar.bz2", "tar.xz"}:
            mode = {"tar": "w", "tar.gz": "w:gz", "tar.bz2": "w:bz2", "tar.xz": "w:xz"}[archive_format]
            kwargs = {"compresslevel": level} if archive_format in {"tar.gz", "tar.bz2"} else {}
            with tarfile.open(target, mode, **kwargs) as handle:
                for path, arcname in entries:
                    handle.add(path, arcname=arcname, recursive=False)
        elif archive_format in {"gz", "bz2", "xz"}:
            if len(entries) != 1 or not entries[0][0].is_file():
                raise AleraValidationError("Standalone gz/bz2/xz archives require exactly one source file.")
            source, _ = entries[0]
            if archive_format == "gz":
                opener = gzip.open
                kwargs = {"compresslevel": level}
            elif archive_format == "bz2":
                opener = bz2.open
                kwargs = {"compresslevel": level}
            else:
                opener = lzma.open
                kwargs = {"preset": level}
            with source.open("rb") as src, opener(target, "wb", **kwargs) as dst:
                shutil.copyfileobj(src, dst, length=1024 * 1024)
        elif archive_format == "7z":
            try:
                import py7zr  # type: ignore
            except ImportError as exc:
                raise AleraValidationError("7z support requires the optional 'py7zr' package.") from exc
            with py7zr.SevenZipFile(target, "w") as handle:
                for path, arcname in entries:
                    handle.write(path, arcname)
        else:
            raise AleraValidationError("RAR creation is not supported; RAR archives are read/extracted only.")
        return target

    def extract(self, archive: str | Path, destination: str | Path = ".", members: Iterable[str] | None = None,
                include: Iterable[str] | None = None, exclude: Iterable[str] | None = None,
                max_members: int | None = 100_000, max_total_size: int | None = 10 * 1024 * 1024 * 1024,
                overwrite: bool = True) -> Path:
        """Safely extract an archive with traversal and archive-bomb limits."""
        source = self._path(archive)
        target = self._path(destination)
        if not source.is_file():
            raise FileNotFoundError(source)
        target.mkdir(parents=True, exist_ok=True)
        wanted = set(members) if members is not None else None

        def selected(name: str) -> bool:
            return (wanted is None or name in wanted) and self._filtered(name, include, exclude)

        if zipfile.is_zipfile(source):
            with zipfile.ZipFile(source) as handle:
                infos = [i for i in handle.infolist() if selected(i.filename)]
                self._validate_members((i.filename for i in infos), target, max_members)
                total = sum(i.file_size for i in infos)
                if max_total_size is not None and total > max_total_size:
                    raise AleraValidationError("Archive exceeds the configured extraction size limit.")
                for info in infos:
                    destination_path = (target / info.filename).resolve()
                    if info.is_dir():
                        destination_path.mkdir(parents=True, exist_ok=True)
                        continue
                    destination_path.parent.mkdir(parents=True, exist_ok=True)
                    if destination_path.exists() and not overwrite:
                        continue
                    with handle.open(info) as src, destination_path.open("wb") as dst:
                        shutil.copyfileobj(src, dst, length=1024 * 1024)
        elif tarfile.is_tarfile(source):
            with tarfile.open(source) as handle:
                infos = [m for m in handle.getmembers() if selected(m.name)]
                self._validate_members((m.name for m in infos), target, max_members)
                total = sum(m.size for m in infos if m.isfile())
                if max_total_size is not None and total > max_total_size:
                    raise AleraValidationError("Archive exceeds the configured extraction size limit.")
                for member in infos:
                    if member.issym() or member.islnk():
                        raise AleraPathError(f"Refusing unsafe archive link: {member.name}")
                    destination_path = (target / member.name).resolve()
                    if destination_path.exists() and not overwrite and member.isfile():
                        continue
                    if member.isdir():
                        destination_path.mkdir(parents=True, exist_ok=True)
                    elif member.isfile():
                        destination_path.parent.mkdir(parents=True, exist_ok=True)
                        extracted = handle.extractfile(member)
                        if extracted is None:
                            continue
                        with extracted, destination_path.open("wb") as dst:
                            shutil.copyfileobj(extracted, dst, length=1024 * 1024)
                        try:
                            os.chmod(destination_path, member.mode & 0o7777)
                        except OSError:
                            pass
        elif source.suffix.lower() in {".gz", ".bz2", ".xz"}:
            destination_path = target / source.stem
            if destination_path.exists() and not overwrite:
                return target
            opener = {".gz": gzip.open, ".bz2": bz2.open, ".xz": lzma.open}[source.suffix.lower()]
            with opener(source, "rb") as src, destination_path.open("wb") as dst:
                shutil.copyfileobj(src, dst, length=1024 * 1024)
        elif source.suffix.lower() == ".7z":
            try:
                import py7zr  # type: ignore
            except ImportError as exc:
                raise AleraValidationError("7z extraction requires the optional 'py7zr' package.") from exc
            with py7zr.SevenZipFile(source, "r") as handle:
                handle.extractall(path=target)
        elif source.suffix.lower() == ".rar":
            try:
                import rarfile  # type: ignore
            except ImportError as exc:
                raise AleraValidationError("RAR extraction requires the optional 'rarfile' package and a compatible RAR backend.") from exc
            with rarfile.RarFile(source) as handle:
                names = [name for name in handle.namelist() if selected(name)]
                self._validate_members(names, target, max_members)
                handle.extractall(target, members=names)
        else:
            raise AleraValidationError("Unsupported or invalid archive.")
        return target

    def list_contents(self, archive: str | Path) -> list[str]:
        """List archive members without extracting them."""
        source = self._path(archive)
        if zipfile.is_zipfile(source):
            with zipfile.ZipFile(source) as handle:
                return handle.namelist()
        if tarfile.is_tarfile(source):
            with tarfile.open(source) as handle:
                return handle.getnames()
        if source.suffix.lower() == ".7z":
            try:
                import py7zr  # type: ignore
            except ImportError as exc:
                raise AleraValidationError("7z support requires the optional 'py7zr' package.") from exc
            with py7zr.SevenZipFile(source, "r") as handle:
                return handle.getnames()
        if source.suffix.lower() == ".rar":
            try:
                import rarfile  # type: ignore
            except ImportError as exc:
                raise AleraValidationError("RAR support requires the optional 'rarfile' package.") from exc
            with rarfile.RarFile(source) as handle:
                return handle.namelist()
        if source.suffix.lower() in {".gz", ".bz2", ".xz"}:
            return [source.stem]
        raise AleraValidationError("Unsupported or invalid archive.")

    def iter_contents(self, archive: str | Path) -> Iterator[str]:
        """Stream archive member names instead of materializing the whole list."""
        source = self._path(archive)
        if zipfile.is_zipfile(source):
            with zipfile.ZipFile(source) as handle:
                for info in handle.infolist():
                    yield info.filename
            return
        if tarfile.is_tarfile(source):
            with tarfile.open(source) as handle:
                for member in handle:
                    yield member.name
            return
        yield from self.list_contents(source)

    def information(self, archive: str | Path) -> dict[str, object]:
        """Return format, size, members, compression ratio, and SHA-256."""
        source = self._path(archive)
        if not source.is_file():
            raise FileNotFoundError(source)
        names = self.list_contents(source)
        format_name = self._format(None, source)
        compressed_size = source.stat().st_size
        uncompressed_size = 0
        if zipfile.is_zipfile(source):
            with zipfile.ZipFile(source) as handle:
                uncompressed_size = sum(i.file_size for i in handle.infolist())
        elif tarfile.is_tarfile(source):
            with tarfile.open(source) as handle:
                uncompressed_size = sum(m.size for m in handle.getmembers() if m.isfile())
        ratio = None if uncompressed_size == 0 else compressed_size / uncompressed_size
        return {
            "path": str(source), "format": format_name, "size": compressed_size,
            "members": len(names), "uncompressed_size": uncompressed_size,
            "compression_ratio": ratio, "sha256": self.hash(archive),
        }

    def hash(self, archive: str | Path, algorithm: str = "sha256", chunk_size: int = 1024 * 1024) -> str:
        """Stream a cryptographic hash of an archive file."""
        if chunk_size <= 0:
            raise AleraValidationError("chunk_size must be positive.")
        source = self._path(archive)
        digest = hashlib.new(algorithm)
        with source.open("rb") as handle:
            while chunk := handle.read(chunk_size):
                digest.update(chunk)
        return digest.hexdigest()

    def verify(self, archive: str | Path) -> dict[str, object]:
        """Test whether an archive is structurally readable."""
        source = self._path(archive)
        try:
            if zipfile.is_zipfile(source):
                with zipfile.ZipFile(source) as handle:
                    return {"valid": handle.testzip() is None, "format": "zip", "members": len(handle.infolist())}
            if tarfile.is_tarfile(source):
                with tarfile.open(source) as handle:
                    count = sum(1 for _ in handle)
                return {"valid": True, "format": self._format(None, source), "members": count}
            if source.suffix.lower() in {".gz", ".bz2", ".xz"}:
                opener = {".gz": gzip.open, ".bz2": bz2.open, ".xz": lzma.open}[source.suffix.lower()]
                with opener(source, "rb") as handle:
                    while handle.read(1024 * 1024):
                        pass
                return {"valid": True, "format": source.suffix.lower().lstrip("."), "members": 1}
            return {"valid": False, "format": "unknown", "members": 0}
        except (OSError, EOFError, ValueError, tarfile.TarError, zipfile.BadZipFile, lzma.LZMAError, EOFError) as exc:
            return {"valid": False, "format": "unknown", "members": 0, "error": str(exc)}

    def test(self, archive: str | Path) -> bool:
        """Convenience boolean integrity check."""
        return bool(self.verify(archive).get("valid"))

    def add(self, archive: str | Path, sources: list[str | Path], **kwargs: object) -> Path:
        """Compatibility alias for :meth:`create`."""
        return self.create(archive, sources, **kwargs)  # type: ignore[arg-type]

    def extract_member(self, archive: str | Path, member: str, destination: str | Path = ".") -> Path:
        """Extract exactly one member."""
        return self.extract(archive, destination, members=[member])

    def remove(self, archive: str | Path) -> None:
        """Delete an archive inside the workspace."""
        source = self._path(archive)
        if not source.exists():
            raise FileNotFoundError(source)
        if source.is_dir():
            raise AleraValidationError("Archive path is a directory.")
        source.unlink()

    def is_archive(self, path: str | Path) -> bool:
        """Return whether a path is recognized as a supported archive."""
        source = self._path(path)
        if not source.is_file():
            return False
        try:
            if zipfile.is_zipfile(source) or tarfile.is_tarfile(source):
                return True
            return source.suffix.lower() in {".gz", ".bz2", ".xz", ".7z", ".rar"}
        except OSError:
            return False

    def supported_formats(self) -> dict[str, str]:
        """Return built-in and optional format support information."""
        try:
            import py7zr  # type: ignore
            seven = "available"
        except ImportError:
            seven = "optional dependency: py7zr"
        try:
            import rarfile  # type: ignore
            rar = "available for reading/extraction"
        except ImportError:
            rar = "optional dependency: rarfile"
        return {
            "zip": "built-in", "tar": "built-in", "tar.gz": "built-in", "tar.bz2": "built-in",
            "tar.xz": "built-in", "gz": "built-in standalone stream", "bz2": "built-in standalone stream",
            "xz": "built-in standalone stream", "7z": seven, "rar": rar,
        }
