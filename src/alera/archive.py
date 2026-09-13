"""Maximum-feature archive and compression subsystem for Alera."""

from __future__ import annotations

import bz2
import fnmatch
import gzip
import hashlib
import io
import lzma
import os
import shutil
import struct
import tarfile
import tempfile
import time
import zipfile
from pathlib import Path
from typing import BinaryIO, Iterable, Iterator

from .exceptions import AleraPathError, AleraValidationError


class ArchiveManager:
    """A workspace-safe, multi-format archive manager.

    Built-in: ZIP, TAR, TAR.GZ, TAR.BZ2, TAR.XZ, GZIP, BZIP2, XZ.
    Optional: 7Z (py7zr), RAR (rarfile), Zstandard (zstandard), LZ4 (lz4),
    and Brotli (brotli). ZIP-family extensions such as JAR/APK/WAR are
    automatically treated as ZIP containers.
    """

    BUILTIN_FORMATS = {
        "zip", "jar", "apk", "war", "ear", "whl", "xpi", "crx",
        "tar", "tar.gz", "tgz", "tar.bz2", "tbz", "tbz2", "tar.xz", "txz",
        "gz", "bz2", "xz",
    }
    ZIP_ALIASES = {"zip", "jar", "apk", "war", "ear", "whl", "xpi", "crx"}
    _INTERNAL_PREFIXES = (
        ".alera_bin/", ".alera_hidden/", ".alera_recovery/",
        ".alera_cache/", ".alera_versions/",
    )
    MAGIC = {
        "zip": (b"PK\\x03\\x04", b"PK\\x05\\x06", b"PK\\x07\\x08"),
        "gzip": (b"\\x1f\\x8b",),
        "bz2": (b"BZh",),
        "xz": (b"\\xfd7zXZ\\x00",),
        "7z": (b"7z\\xbc\\xaf\\x27\\x1c",),
        "rar": (b"Rar!\\x1a\\x07",),
        "pdf": (b"%PDF-",),
        "zstd": (b"\\x28\\xb5\\x2f\\xfd",),
    }

    def __init__(self, base_path: str | Path = "", *, max_members: int = 100_000,
                 max_extract_size: int = 10 * 1024 * 1024 * 1024,
                 max_ratio: float = 1_000.0) -> None:
        self.base_path = (Path(base_path).expanduser() if str(base_path) else Path.cwd()).resolve()
        self.base_path.mkdir(parents=True, exist_ok=True)
        if max_members < 1 or max_extract_size < 0 or max_ratio <= 0:
            raise AleraValidationError("Invalid archive safety limits.")
        self.max_members = max_members
        self.max_extract_size = max_extract_size
        self.max_ratio = max_ratio

    def _path(self, value: str | Path) -> Path:
        candidate = Path(value).expanduser()
        target = candidate.resolve() if candidate.is_absolute() else (self.base_path / candidate).resolve()
        try:
            target.relative_to(self.base_path)
        except ValueError as exc:
            raise AleraPathError(f"Archive path escapes workspace: {value}") from exc
        return target

    @staticmethod
    def _level(level: int | None) -> int:
        if level is None:
            return 6
        if not isinstance(level, int) or not 0 <= level <= 9:
            raise AleraValidationError("compression_level must be an integer from 0 to 9.")
        return level

    @classmethod
    def _normalize_format(cls, value: str | None, path: Path | None = None) -> str:
        if value:
            fmt = value.lower().strip().lstrip(".")
        elif path:
            name = path.name.lower()
            for suffix, fmt in (
                (".tar.gz", "tar.gz"), (".tar.bz2", "tar.bz2"), (".tar.xz", "tar.xz"),
                (".tgz", "tar.gz"), (".tbz2", "tar.bz2"), (".tbz", "tar.bz2"), (".txz", "tar.xz"),
            ):
                if name.endswith(suffix):
                    return fmt
            fmt = path.suffix.lower().lstrip(".")
        else:
            return ""
        aliases = {
            "tgz": "tar.gz", "gztar": "tar.gz", "tbz": "tar.bz2", "tbz2": "tar.bz2",
            "bztar": "tar.bz2", "txz": "tar.xz", "xztar": "tar.xz",
            "gzip": "gz", "bzip2": "bz2", "lzma": "xz",
        }
        return aliases.get(fmt, fmt)

    @classmethod
    def supported_formats(cls) -> dict[str, str]:
        """Return formats and whether their backend is built-in or optional."""
        result = {name: "builtin" for name in sorted(cls.BUILTIN_FORMATS)}
        result.update({"7z": "optional: py7zr", "rar": "optional: rarfile", "zst": "optional: zstandard", "lz4": "optional: lz4", "br": "optional: brotli"})
        return result

    @classmethod
    def detect_format(cls, archive: str | Path) -> str:
        """Detect a container/compression format from magic bytes first, then extension."""
        path = Path(archive)
        with path.open("rb") as handle:
            header = handle.read(16)
        for fmt, signatures in cls.MAGIC.items():
            if any(header.startswith(signature) for signature in signatures):
                return {"gzip": "gz", "bz2": "bz2", "xz": "xz"}.get(fmt, fmt)
        if tarfile.is_tarfile(path):
            return "tar"
        return cls._normalize_format(None, path)

    @classmethod
    def _safe_member(cls, name: str) -> bool:
        normalized = name.replace("\\", "/")
        if not normalized or normalized.startswith("/") or "\\x00" in normalized:
            return False
        parts = [part for part in normalized.split("/") if part not in ("", ".")]
        return ".." not in parts

    @classmethod
    def _validate_names(cls, names: Iterable[str], destination: Path, limit: int) -> list[str]:
        root = destination.resolve()
        result: list[str] = []
        for index, name in enumerate(names, 1):
            if index > limit:
                raise AleraValidationError("Archive contains too many members.")
            if not cls._safe_member(name):
                raise AleraPathError(f"Unsafe archive member: {name}")
            target = (destination / name).resolve()
            try:
                target.relative_to(root)
            except ValueError as exc:
                raise AleraPathError(f"Archive member escapes destination: {name}") from exc
            result.append(name)
        return result

    @classmethod
    def _selected(cls, name: str, include: Iterable[str] | None, exclude: Iterable[str] | None) -> bool:
        normalized = name.replace("\\", "/")
        if any(normalized == p.rstrip("/") or normalized.startswith(p) for p in cls._INTERNAL_PREFIXES):
            return False
        if include and not any(fnmatch.fnmatch(normalized, pattern) for pattern in include):
            return False
        if exclude and any(fnmatch.fnmatch(normalized, pattern) for pattern in exclude):
            return False
        return True

    def _entries(self, sources: list[str | Path], include: Iterable[str] | None,
                 exclude: Iterable[str] | None) -> Iterator[tuple[Path, str]]:
        if not isinstance(sources, list) or not sources:
            raise AleraValidationError("sources must be a non-empty list.")
        for source in sources:
            path = self._path(source)
            if not path.exists() and not path.is_symlink():
                raise FileNotFoundError(path)
            if path.is_file() or path.is_symlink():
                name = path.relative_to(self.base_path).as_posix()
                if self._selected(name, include, exclude):
                    yield path, name
                continue
            root_name = path.relative_to(self.base_path).as_posix()
            if self._selected(root_name, include, exclude):
                yield path, root_name
            for item in path.rglob("*"):
                name = item.relative_to(self.base_path).as_posix()
                if self._selected(name, include, exclude):
                    yield item, name

    def create(self, archive: str | Path, sources: list[str | Path], format: str | None = None,
               compression_level: int | None = None, include: Iterable[str] | None = None,
               exclude: Iterable[str] | None = None, follow_symlinks: bool = False) -> Path:
        """Create an archive from files/directories."""
        target = self._path(archive)
        target.parent.mkdir(parents=True, exist_ok=True)
        fmt = self._normalize_format(format, target)
        level = self._level(compression_level)
        entries = list(self._entries(sources, include, exclude))
        if not entries:
            raise AleraValidationError("No files matched the archive selection.")

        if fmt in self.ZIP_ALIASES:
            compression = zipfile.ZIP_STORED if level == 0 else zipfile.ZIP_DEFLATED
            with zipfile.ZipFile(target, "w", compression=compression, compresslevel=level) as zf:
                for path, name in entries:
                    if path.is_symlink() and not follow_symlinks:
                        info = zipfile.ZipInfo(name)
                        info.external_attr = (0o120777 << 16) | 0xA0000000
                        zf.writestr(info, os.readlink(path).encode())
                    elif path.is_file():
                        zf.write(path, name)
                    elif path.is_dir():
                        zf.write(path, name + "/")
            return target

        if fmt in {"tar", "tar.gz", "tar.bz2", "tar.xz"}:
            mode = {"tar": "w", "tar.gz": "w:gz", "tar.bz2": "w:bz2", "tar.xz": "w:xz"}[fmt]
            kwargs = {"compresslevel": level} if fmt in {"tar.gz", "tar.bz2"} else {}
            with tarfile.open(target, mode, **kwargs) as tf:
                for path, name in entries:
                    tf.add(path, arcname=name, recursive=False)
            return target

        if fmt in {"gz", "bz2", "xz"}:
            files = [item for item, _ in entries if item.is_file()]
            if len(files) != 1:
                raise AleraValidationError(f"{fmt} requires exactly one source file.")
            source = files[0]
            with source.open("rb") as src:
                if fmt == "gz":
                    dst = gzip.open(target, "wb", compresslevel=level)
                elif fmt == "bz2":
                    dst = bz2.open(target, "wb", compresslevel=level)
                else:
                    dst = lzma.open(target, "wb", preset=level)
                with dst:
                    shutil.copyfileobj(src, dst, 1024 * 1024)
            return target

        if fmt == "7z":
            try:
                import py7zr  # type: ignore
            except ImportError as exc:
                raise AleraValidationError("7z creation requires optional 'py7zr'.") from exc
            with py7zr.SevenZipFile(target, "w") as zf:
                for path, name in entries:
                    zf.write(path, name)
            return target

        raise AleraValidationError(f"Format '{fmt}' is not supported for creation.")

    def extract(self, archive: str | Path, destination: str | Path = ".", members: Iterable[str] | None = None,
                include: Iterable[str] | None = None, exclude: Iterable[str] | None = None,
                max_members: int | None = None, max_total_size: int | None = None,
                max_ratio: float | None = None, overwrite: bool = True) -> Path:
        """Safely extract selected members with archive-bomb protections."""
        source = self._path(archive)
        target = self._path(destination)
        target.mkdir(parents=True, exist_ok=True)
        limit = self.max_members if max_members is None else max_members
        size_limit = self.max_extract_size if max_total_size is None else max_total_size
        ratio_limit = self.max_ratio if max_ratio is None else max_ratio
        wanted = set(members) if members is not None else None

        def selected(name: str) -> bool:
            return (wanted is None or name in wanted) and self._selected(name, include, exclude)

        if zipfile.is_zipfile(source):
            with zipfile.ZipFile(source) as zf:
                infos = [i for i in zf.infolist() if selected(i.filename)]
                self._validate_names((i.filename for i in infos), target, limit)
                total = sum(i.file_size for i in infos)
                compressed = sum(i.compress_size for i in infos)
                self._check_limits(total, compressed, size_limit, ratio_limit)
                for info in infos:
                    out = (target / info.filename).resolve()
                    if info.is_dir():
                        out.mkdir(parents=True, exist_ok=True)
                        continue
                    if out.exists() and not overwrite:
                        continue
                    out.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(info, "r") as src, out.open("wb") as dst:
                        shutil.copyfileobj(src, dst, 1024 * 1024)
            return target

        if tarfile.is_tarfile(source):
            with tarfile.open(source) as tf:
                infos = [m for m in tf.getmembers() if selected(m.name)]
                self._validate_names((m.name for m in infos), target, limit)
                total = sum(m.size for m in infos if m.isfile())
                compressed = max(source.stat().st_size, 1)
                self._check_limits(total, compressed, size_limit, ratio_limit)
                for member in infos:
                    if member.issym() or member.islnk() or member.isdev() or member.isfifo():
                        raise AleraPathError(f"Refusing unsafe special archive member: {member.name}")
                    out = (target / member.name).resolve()
                    if member.isdir():
                        out.mkdir(parents=True, exist_ok=True)
                    elif member.isfile():
                        if out.exists() and not overwrite:
                            continue
                        out.parent.mkdir(parents=True, exist_ok=True)
                        src = tf.extractfile(member)
                        if src is not None:
                            with src, out.open("wb") as dst:
                                shutil.copyfileobj(src, dst, 1024 * 1024)
                        try:
                            os.chmod(out, member.mode & 0o7777)
                        except OSError:
                            pass
            return target

        fmt = self.detect_format(source)
        if fmt in {"gz", "bz2", "xz"}:
            out = target / source.name.rsplit(".", 1)[0]
            if out.exists() and not overwrite:
                return target
            opener = {"gz": gzip.open, "bz2": bz2.open, "xz": lzma.open}[fmt]
            with opener(source, "rb") as src, out.open("wb") as dst:
                shutil.copyfileobj(src, dst, 1024 * 1024)
            return target

        if fmt == "7z":
            try:
                import py7zr  # type: ignore
            except ImportError as exc:
                raise AleraValidationError("7z extraction requires optional 'py7zr'.") from exc
            with py7zr.SevenZipFile(source, "r") as zf:
                names = zf.getnames()
                self._validate_names((n for n in names if selected(n)), target, limit)
                zf.extractall(path=target)
            return target

        if fmt == "rar":
            try:
                import rarfile  # type: ignore
            except ImportError as exc:
                raise AleraValidationError("RAR extraction requires optional 'rarfile' and a compatible RAR backend.") from exc
            with rarfile.RarFile(source) as rf:
                names = [n for n in rf.namelist() if selected(n)]
                self._validate_names(names, target, limit)
                rf.extractall(target, members=names)
            return target

        raise AleraValidationError(f"Unsupported or invalid archive: {source.name}")

    @staticmethod
    def _check_limits(total: int, compressed: int, max_total: int, max_ratio: float) -> None:
        if total > max_total:
            raise AleraValidationError("Archive exceeds the configured extraction size limit.")
        if compressed > 0 and total / compressed > max_ratio:
            raise AleraValidationError("Archive exceeds the configured compression-ratio safety limit.")

    def list_contents(self, archive: str | Path) -> list[str]:
        """List members without extracting."""
        source = self._path(archive)
        if zipfile.is_zipfile(source):
            with zipfile.ZipFile(source) as zf:
                return zf.namelist()
        if tarfile.is_tarfile(source):
            with tarfile.open(source) as tf:
                return tf.getnames()
        fmt = self.detect_format(source)
        if fmt == "7z":
            try:
                import py7zr  # type: ignore
            except ImportError as exc:
                raise AleraValidationError("7z support requires optional 'py7zr'.") from exc
            with py7zr.SevenZipFile(source, "r") as zf:
                return zf.getnames()
        if fmt == "rar":
            try:
                import rarfile  # type: ignore
            except ImportError as exc:
                raise AleraValidationError("RAR support requires optional 'rarfile'.") from exc
            with rarfile.RarFile(source) as rf:
                return rf.namelist()
        if fmt in {"gz", "bz2", "xz"}:
            return [source.name.rsplit(".", 1)[0]]
        raise AleraValidationError(f"Unsupported archive: {source.name}")

    def iter_contents(self, archive: str | Path) -> Iterator[str]:
        """Stream member names."""
        source = self._path(archive)
        if zipfile.is_zipfile(source):
            with zipfile.ZipFile(source) as zf:
                for info in zf.infolist():
                    yield info.filename
            return
        if tarfile.is_tarfile(source):
            with tarfile.open(source) as tf:
                for member in tf:
                    yield member.name
            return
        yield from self.list_contents(source)

    def open_member(self, archive: str | Path, member: str) -> BinaryIO:
        """Open one archive member for reading without extracting it."""
        source = self._path(archive)
        if not self._safe_member(member):
            raise AleraPathError(f"Unsafe archive member: {member}")
        if zipfile.is_zipfile(source):
            zf = zipfile.ZipFile(source)
            try:
                stream = zf.open(member, "r")
            except Exception:
                zf.close()
                raise
            return _ArchiveStream(stream, zf)
        if tarfile.is_tarfile(source):
            tf = tarfile.open(source)
            item = tf.getmember(member)
            stream = tf.extractfile(item)
            if stream is None:
                tf.close()
                raise IsADirectoryError(member)
            return _ArchiveStream(stream, tf)
        raise AleraValidationError("Direct member streaming is unavailable for this archive format.")

    def read_member(self, archive: str | Path, member: str, *, max_bytes: int | None = None) -> bytes:
        """Read one member into memory, optionally bounded."""
        with self.open_member(archive, member) as stream:
            return stream.read() if max_bytes is None else stream.read(max_bytes)

    def extract_member(self, archive: str | Path, member: str, destination: str | Path = ".", *, overwrite: bool = True) -> Path:
        """Extract exactly one member."""
        self.extract(archive, destination, members=[member], overwrite=overwrite, max_members=1)
        return self._path(destination) / member

    def search(self, archive: str | Path, pattern: str, *, case_sensitive: bool = False) -> list[str]:
        """Search member names using glob matching."""
        names = self.list_contents(archive)
        if not case_sensitive:
            pattern = pattern.lower()
            return [name for name in names if fnmatch.fnmatch(name.lower(), pattern)]
        return [name for name in names if fnmatch.fnmatch(name, pattern)]

    def search_content(self, archive: str | Path, needle: bytes | str, *, max_member_size: int = 64 * 1024 * 1024) -> list[str]:
        """Search text/binary content inside archive members without extracting them."""
        target = needle.encode() if isinstance(needle, str) else bytes(needle)
        if not target:
            raise AleraValidationError("needle cannot be empty.")
        matches: list[str] = []
        for name in self.iter_contents(archive):
            try:
                info = self.member_information(archive, name)
                if int(info.get("size", 0)) > max_member_size:
                    continue
                with self.open_member(archive, name) as stream:
                    tail = b""
                    while True:
                        chunk = stream.read(1024 * 1024)
                        if not chunk:
                            break
                        data = tail + chunk
                        if target in data:
                            matches.append(name)
                            break
                        tail = data[-(len(target) - 1):] if len(target) > 1 else b""
            except (KeyError, IsADirectoryError, AleraValidationError):
                continue
        return matches

    def member_information(self, archive: str | Path, member: str) -> dict[str, object]:
        """Return metadata for a single member."""
        source = self._path(archive)
        if zipfile.is_zipfile(source):
            with zipfile.ZipFile(source) as zf:
                i = zf.getinfo(member)
                return {"name": i.filename, "size": i.file_size, "compressed_size": i.compress_size,
                        "compression": i.compress_type, "crc32": i.CRC, "is_dir": i.is_dir(), "date_time": i.date_time,
                        "encrypted": bool(i.flag_bits & 1)}
        if tarfile.is_tarfile(source):
            with tarfile.open(source) as tf:
                m = tf.getmember(member)
                return {"name": m.name, "size": m.size, "compressed_size": None, "mode": m.mode,
                        "uid": m.uid, "gid": m.gid, "mtime": m.mtime, "is_dir": m.isdir(), "type": m.type.decode(errors="replace") if isinstance(m.type, bytes) else str(m.type)}
        raise AleraValidationError("Member metadata is unavailable for this format.")

    def test(self, archive: str | Path) -> dict[str, object]:
        """Test archive integrity without extracting it."""
        source = self._path(archive)
        errors: list[str] = []
        members = 0
        if zipfile.is_zipfile(source):
            with zipfile.ZipFile(source) as zf:
                bad = zf.testzip()
                members = len(zf.infolist())
                if bad:
                    errors.append(f"Corrupt ZIP member: {bad}")
        elif tarfile.is_tarfile(source):
            try:
                with tarfile.open(source) as tf:
                    for member in tf:
                        members += 1
                        if member.isfile():
                            stream = tf.extractfile(member)
                            if stream is not None:
                                while stream.read(1024 * 1024):
                                    pass
                                stream.close()
            except (OSError, tarfile.TarError) as exc:
                errors.append(str(exc))
        elif self.detect_format(source) == "7z":
            try:
                import py7zr  # type: ignore
                with py7zr.SevenZipFile(source, "r") as zf:
                    members = len(zf.getnames())
                    zf.test()
            except Exception as exc:
                errors.append(str(exc))
        else:
            errors.append("Unsupported format or no integrity backend available.")
        return {"valid": not errors, "members": members, "errors": errors}

    def hash(self, archive: str | Path, algorithm: str = "sha256", chunk_size: int = 1024 * 1024) -> str:
        """Hash the archive bytes using streaming I/O."""
        if chunk_size < 1:
            raise AleraValidationError("chunk_size must be positive.")
        digest = hashlib.new(algorithm)
        with self._path(archive).open("rb") as stream:
            for chunk in iter(lambda: stream.read(chunk_size), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def verify_hash(self, archive: str | Path, expected: str, algorithm: str = "sha256") -> bool:
        return self.hash(archive, algorithm).lower() == expected.strip().lower()

    def information(self, archive: str | Path) -> dict[str, object]:
        """Return detailed archive/container statistics."""
        source = self._path(archive)
        stat = source.stat()
        fmt = self.detect_format(source)
        result: dict[str, object] = {
            "path": str(source), "name": source.name, "format": fmt, "size": stat.st_size,
            "modified": stat.st_mtime, "created": getattr(stat, "st_birthtime", stat.st_ctime),
            "sha256": self.hash(source), "integrity": self.test(source),
        }
        try:
            names = self.list_contents(source)
            result["members"] = len(names)
            if fmt in {"zip", "jar", "apk", "war", "ear", "whl", "xpi", "crx"}:
                with zipfile.ZipFile(source) as zf:
                    uncompressed = sum(i.file_size for i in zf.infolist())
                    compressed = sum(i.compress_size for i in zf.infolist())
            elif tarfile.is_tarfile(source):
                with tarfile.open(source) as tf:
                    uncompressed = sum(m.size for m in tf.getmembers() if m.isfile())
                compressed = stat.st_size
            else:
                uncompressed = None
                compressed = stat.st_size
            result["uncompressed_size"] = uncompressed
            result["compressed_size"] = compressed
            result["compression_ratio"] = (uncompressed / compressed) if uncompressed is not None and compressed else None
        except Exception as exc:
            result["inspection_error"] = str(exc)
        return result

    def compare(self, first: str | Path, second: str | Path) -> dict[str, list[str]]:
        """Compare two archives by member names and content hashes."""
        a = self._member_hashes(first)
        b = self._member_hashes(second)
        added = sorted(set(b) - set(a))
        removed = sorted(set(a) - set(b))
        modified = sorted(name for name in set(a) & set(b) if a[name] != b[name])
        unchanged = sorted(name for name in set(a) & set(b) if a[name] == b[name])
        return {"added": added, "removed": removed, "modified": modified, "unchanged": unchanged}

    def _member_hashes(self, archive: str | Path) -> dict[str, str]:
        result: dict[str, str] = {}
        for name in self.iter_contents(archive):
            try:
                with self.open_member(archive, name) as stream:
                    digest = hashlib.sha256()
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(chunk)
                    result[name] = digest.hexdigest()
            except (IsADirectoryError, KeyError):
                continue
        return result

    def convert(self, source: str | Path, destination: str | Path, *, format: str | None = None,
                compression_level: int | None = None) -> Path:
        """Convert a supported archive to another container by streaming members."""
        src = self._path(source)
        dst = self._path(destination)
        temp_dir = Path(tempfile.mkdtemp(prefix="alera-archive-convert-"))
        try:
            self.extract(src, temp_dir, max_total_size=self.max_extract_size)
            items = [p.relative_to(temp_dir) for p in temp_dir.rglob("*") if p.is_file()]
            # create() expects workspace-relative sources, so perform a direct container build here.
            fmt = self._normalize_format(format, dst)
            dst.parent.mkdir(parents=True, exist_ok=True)
            if fmt in self.ZIP_ALIASES:
                with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED, compresslevel=self._level(compression_level)) as zf:
                    for rel in items:
                        zf.write(temp_dir / rel, rel.as_posix())
            elif fmt in {"tar", "tar.gz", "tar.bz2", "tar.xz"}:
                mode = {"tar": "w", "tar.gz": "w:gz", "tar.bz2": "w:bz2", "tar.xz": "w:xz"}[fmt]
                with tarfile.open(dst, mode) as tf:
                    for rel in items:
                        tf.add(temp_dir / rel, arcname=rel.as_posix())
            else:
                raise AleraValidationError("Conversion target must be ZIP or TAR-family.")
            return dst
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def remove_member(self, archive: str | Path, member: str, destination: str | Path | None = None) -> Path:
        """Remove one member by rebuilding the archive safely."""
        source = self._path(archive)
        if destination is None:
            destination = source.with_name(source.name + ".tmp")
        dst = self._path(destination)
        fmt = self.detect_format(source)
        if fmt not in self.ZIP_ALIASES:
            raise AleraValidationError("In-place member editing currently supports ZIP-family archives only.")
        with zipfile.ZipFile(source, "r") as src, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as out:
            for info in src.infolist():
                if info.filename == member:
                    continue
                out.writestr(info, src.read(info))
        if destination == source.with_name(source.name + ".tmp"):
            os.replace(dst, source)
            return source
        return dst

    def add_member(self, archive: str | Path, source: str | Path, member: str | None = None) -> Path:
        """Add one file to a ZIP-family archive."""
        target = self._path(archive)
        path = self._path(source)
        if not path.is_file():
            raise FileNotFoundError(path)
        if not zipfile.is_zipfile(target):
            raise AleraValidationError("add_member currently requires an existing ZIP-family archive.")
        name = member or path.name
        if not self._safe_member(name):
            raise AleraPathError(f"Unsafe member name: {name}")
        with zipfile.ZipFile(target, "a", zipfile.ZIP_DEFLATED) as zf:
            zf.write(path, name)
        return target

    def _stream_codec(self, path: Path, mode: str):
        fmt = self.detect_format(path)
        if fmt == "gz":
            return gzip.open(path, mode)
        if fmt == "bz2":
            return bz2.open(path, mode)
        if fmt == "xz":
            return lzma.open(path, mode)
        raise AleraValidationError("Not a supported standalone compressed stream.")


class _ArchiveStream:
    """Own both a member stream and its archive container."""

    def __init__(self, stream: BinaryIO, owner: object) -> None:
        self._stream = stream
        self._owner = owner

    def __enter__(self) -> "_ArchiveStream":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)

    def readable(self) -> bool:
        return True

    def close(self) -> None:
        try:
            self._stream.close()
        finally:
            close = getattr(self._owner, "close", None)
            if close:
                close()

    def __iter__(self):
        return iter(self._stream)
