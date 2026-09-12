"""Core filesystem explorer for Alera."""
from __future__ import annotations

import fnmatch
import hashlib
import mimetypes
import os
import shutil
import stat
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, Iterable, Iterator, TextIO

from .exceptions import AleraBinError, AleraPathError, AleraValidationError


class FileExplorer:
    """A safe, high-performance, batteries-included filesystem core."""

    INTERNAL = frozenset({
        ".alera_bin", ".alera_hidden", ".alera_recovery", ".alera_cache",
        ".alera_versions", ".alera_index", ".alera_database",
    })

    def __init__(self, base_path: str | os.PathLike[str] = "", *, create_base: bool = True,
                 follow_symlinks: bool = False) -> None:
        raw = Path(base_path).expanduser() if str(base_path) else Path.cwd()
        try:
            self.base_path = raw.resolve()
        except OSError as exc:
            raise AleraPathError(f"Unable to resolve base path: {raw}") from exc
        if create_base:
            self.base_path.mkdir(parents=True, exist_ok=True)
        elif not self.base_path.exists():
            raise FileNotFoundError(self.base_path)
        self.follow_symlinks = bool(follow_symlinks)
        self._bin_path = self.base_path / ".alera_bin"
        self._bin_path.mkdir(parents=True, exist_ok=True)

    @property
    def bin_path(self) -> Path:
        return self._bin_path

    def _path(self, path: str | os.PathLike[str] | None, *, allow_root: bool = True,
              allow_internal: bool = False) -> Path:
        candidate = Path(path).expanduser() if path not in (None, "") else Path(".")
        result = candidate.resolve() if candidate.is_absolute() else (self.base_path / candidate).resolve()
        try:
            relative = result.relative_to(self.base_path)
        except ValueError as exc:
            raise AleraPathError(f"Path escapes explorer base: {path}") from exc
        if not allow_root and result == self.base_path:
            raise AleraPathError("The explorer root cannot be targeted by this operation.")
        if not allow_internal and any(part in self.INTERNAL for part in relative.parts):
            raise AleraPathError("Alera internal paths cannot be manipulated as normal files.")
        return result

    def _raw_path(self, path: str | os.PathLike[str]) -> Path:
        """Resolve a path without following its final symlink."""
        candidate = Path(path).expanduser()
        result = candidate if candidate.is_absolute() else self.base_path / candidate
        result = result.absolute()
        try:
            result.relative_to(self.base_path)
        except ValueError as exc:
            raise AleraPathError(f"Path escapes explorer base: {path}") from exc
        return result

    @staticmethod
    def _require_single(value: object, name: str = "name") -> str | os.PathLike[str]:
        if isinstance(value, (list, tuple, set, frozenset)):
            raise AleraValidationError(f"{name} accepts one item, not a collection. Use the plural method.")
        if not isinstance(value, (str, os.PathLike)):
            raise AleraValidationError(f"{name} must be a path-like string.")
        return value

    @staticmethod
    def _require_list(values: object, name: str = "names") -> list[object]:
        if not isinstance(values, list):
            raise AleraValidationError(f"{name} must be a list.")
        return values

    @staticmethod
    def _validate_chunk_size(chunk_size: int) -> None:
        if not isinstance(chunk_size, int) or chunk_size <= 0:
            raise AleraValidationError("chunk_size must be a positive integer.")

    def exists(self, path) -> bool: return self._path(path).exists()
    def lexists(self, path) -> bool: return os.path.lexists(self._raw_path(path))
    def is_file(self, path) -> bool: return self._path(path).is_file()
    def is_folder(self, path) -> bool: return self._path(path).is_dir()
    def is_symlink(self, path) -> bool: return self._raw_path(path).is_symlink()

    def create_folder(self, name, path=None, *, exist_ok: bool = False, parents: bool = True) -> Path:
        target = self._path(Path(path or "") / self._require_single(name), allow_root=False)
        target.mkdir(parents=parents, exist_ok=exist_ok)
        return target

    def create_folders(self, names: list, path=None, *, exist_ok: bool = False) -> list[Path]:
        self._require_list(names)
        return [self.create_folder(name, path, exist_ok=exist_ok) for name in names]

    def create_file(self, name, contents: str = "", *, encoding: str = "utf-8", exist_ok: bool = False) -> Path:
        if not isinstance(contents, str):
            raise AleraValidationError("contents must be a string.")
        target = self._path(self._require_single(name), allow_root=False)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w" if exist_ok else "x", encoding=encoding, newline="") as handle:
            handle.write(contents)
        return target

    def create_binary_file(self, name, contents, *, exist_ok: bool = False) -> Path:
        if not isinstance(contents, (bytes, bytearray, memoryview)):
            raise AleraValidationError("Binary contents must be bytes-like.")
        target = self._path(self._require_single(name), allow_root=False)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("wb" if exist_ok else "xb") as handle:
            handle.write(bytes(contents))
        return target

    def touch(self, name, *, exist_ok: bool = True, times=None) -> Path:
        target = self._path(name, allow_root=False)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.touch(exist_ok=exist_ok)
        if times is not None:
            os.utime(target, times=times)
        return target

    def read_file(self, name, encoding: str = "utf-8") -> str:
        with self._path(name).open("r", encoding=encoding) as handle:
            return handle.read()

    def read_binary_file(self, name) -> bytes:
        with self._path(name).open("rb") as handle:
            return handle.read()

    def write_file(self, name, contents: str, encoding: str = "utf-8", *, atomic: bool = False) -> Path:
        if not isinstance(contents, str):
            raise AleraValidationError("contents must be a string.")
        if not atomic:
            target = self._path(name, allow_root=False)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(contents, encoding=encoding)
            return target
        return self._atomic_write(name, contents.encode(encoding))

    def append_file(self, name, contents: str, encoding: str = "utf-8") -> Path:
        if not isinstance(contents, str):
            raise AleraValidationError("contents must be a string.")
        target = self._path(name, allow_root=False)
        with target.open("a", encoding=encoding, newline="") as handle:
            handle.write(contents)
        return target

    def write_binary_file(self, name, contents, *, atomic: bool = False) -> Path:
        if not isinstance(contents, (bytes, bytearray, memoryview)):
            raise AleraValidationError("Binary contents must be bytes-like.")
        data = bytes(contents)
        return self._atomic_write(name, data) if atomic else self._write_binary(name, data)

    def _write_binary(self, name, data: bytes) -> Path:
        target = self._path(name, allow_root=False)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return target

    def _atomic_write(self, name, data: bytes) -> Path:
        target = self._path(name, allow_root=False)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
            return target
        finally:
            try: os.unlink(temporary)
            except FileNotFoundError: pass

    def read_bytes_chunks(self, name, chunk_size: int = 1024 * 1024) -> Iterator[bytes]:
        self._validate_chunk_size(chunk_size)
        with self._path(name).open("rb") as handle:
            while True:
                chunk = handle.read(chunk_size)
                if not chunk: break
                yield chunk

    def write_bytes_chunks(self, name, chunks: Iterable[bytes], *, atomic: bool = False) -> Path:
        target = self._path(name, allow_root=False)
        target.parent.mkdir(parents=True, exist_ok=True)
        if atomic:
            fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
            try:
                with os.fdopen(fd, "wb") as handle:
                    for chunk in chunks:
                        if not isinstance(chunk, (bytes, bytearray, memoryview)):
                            raise AleraValidationError("All chunks must be bytes-like.")
                        handle.write(bytes(chunk))
                    handle.flush(); os.fsync(handle.fileno())
                os.replace(temporary, target)
                return target
            finally:
                try: os.unlink(temporary)
                except FileNotFoundError: pass
        with target.open("wb") as handle:
            for chunk in chunks:
                if not isinstance(chunk, (bytes, bytearray, memoryview)):
                    raise AleraValidationError("All chunks must be bytes-like.")
                handle.write(bytes(chunk))
        return target

    @contextmanager
    def open_text(self, name, mode: str = "r", encoding: str = "utf-8", **kwargs) -> Iterator[TextIO]:
        with self._path(name).open(mode, encoding=encoding, **kwargs) as handle:
            yield handle

    @contextmanager
    def open_binary(self, name, mode: str = "rb", **kwargs) -> Iterator[BinaryIO]:
        with self._path(name).open(mode, **kwargs) as handle:
            yield handle

    def truncate(self, name, size: int = 0) -> Path:
        if size < 0: raise AleraValidationError("size must be non-negative")
        target = self._path(name, allow_root=False)
        with target.open("r+b") as handle: handle.truncate(size)
        return target

    def rename(self, old, new, *, overwrite: bool = False) -> Path:
        source = self._path(old, allow_root=False); destination = self._path(new, allow_root=False)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists() and not overwrite: raise FileExistsError(destination)
        if overwrite: os.replace(source, destination)
        else: source.rename(destination)
        return destination

    def copy(self, source, destination, *, overwrite: bool = False, preserve_metadata: bool = True) -> Path:
        src = self._path(source, allow_root=False); dst = self._path(destination, allow_root=False)
        if src.is_dir() and (dst == src or src in dst.parents): raise AleraPathError("A directory cannot be copied into itself or a child.")
        if dst.exists() and not overwrite: raise FileExistsError(dst)
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            return Path(shutil.copytree(src, dst, dirs_exist_ok=overwrite, copy_function=shutil.copy2 if preserve_metadata else shutil.copy))
        return Path(shutil.copy2(src, dst) if preserve_metadata else shutil.copy(src, dst))

    def move(self, source, destination, *, overwrite: bool = False) -> Path:
        src = self._path(source, allow_root=False); dst = self._path(destination, allow_root=False)
        if src.is_dir() and (dst == src or src in dst.parents): raise AleraPathError("A directory cannot be moved into itself or a child.")
        if dst.exists() and not overwrite: raise FileExistsError(dst)
        dst.parent.mkdir(parents=True, exist_ok=True)
        if overwrite and dst.exists():
            shutil.rmtree(dst) if dst.is_dir() else dst.unlink()
        return Path(shutil.move(str(src), str(dst)))

    def _bin_destination(self, source: Path) -> Path:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        candidate = self._bin_path / f"{stamp}_{source.name}"
        counter = 1
        while candidate.exists():
            candidate = self._bin_path / f"{stamp}_{counter}_{source.name}"
            counter += 1
        return candidate

    def delete(self, name):
        source = self._path(self._require_single(name), allow_root=False)
        if not source.exists(): raise FileNotFoundError(source)
        destination = self._bin_destination(source)
        try: shutil.move(str(source), str(destination))
        except OSError as exc: raise AleraBinError(f"Could not move {source} to the Alera bin.") from exc
        return destination

    def deletes(self, names: list) -> list[Path]:
        self._require_list(names); return [self.delete(name) for name in names]

    def perm_delete(self, name):
        target = self._path(self._require_single(name), allow_root=False)
        if not target.exists(): raise FileNotFoundError(target)
        try: shutil.rmtree(target) if target.is_dir() else target.unlink()
        except OSError as exc: raise OSError(f"Could not permanently delete {target}.") from exc
        return target

    def perm_deletes(self, names: list) -> list[Path]:
        self._require_list(names); return [self.perm_delete(name) for name in names]

    def list_bin(self) -> list[Path]: return sorted(self._bin_path.iterdir(), key=lambda p: p.name.casefold())

    def bin_information(self) -> list[dict[str, object]]:
        return [{"name": p.name, "path": str(p), "type": "folder" if p.is_dir() else "file", "size": self._size(p)} for p in self.list_bin()]

    def _find_bin_item(self, name):
        self._require_single(name)
        for item in self.list_bin():
            if item.name == str(name): return item
        raise FileNotFoundError(name)

    def restore(self, name):
        item = self._find_bin_item(name); original = item.name.split("_", 2)[-1]
        destination = self.base_path / original
        if destination.exists():
            stem, suffix = destination.stem, destination.suffix; index = 1
            while destination.exists():
                destination = self.base_path / f"{stem} (restored {index}){suffix}"; index += 1
        return Path(shutil.move(str(item), str(destination)))

    def spef_restore(self, names: list[str]) -> list[Path]:
        self._require_list(names); return [self.restore(name) for name in names]

    def restore_bin(self) -> list[Path]: return [self.restore(item.name) for item in list(self.list_bin())]

    def bin_delete(self, name):
        item = self._find_bin_item(name)
        shutil.rmtree(item) if item.is_dir() else item.unlink()

    def spef_delete(self, names: list[str]) -> None:
        self._require_list(names)
        for name in names: self.bin_delete(name)

    def clear_bin(self) -> None:
        for item in self.list_bin(): self.bin_delete(item.name)

    def list(self, path=None, *, include_hidden: bool = False) -> list[Path]:
        root = self._path(path)
        if not root.is_dir(): raise NotADirectoryError(root)
        return sorted((p for p in root.iterdir() if p.name not in self.INTERNAL and (include_hidden or not p.name.startswith("."))), key=lambda p: (p.is_file(), p.name.casefold()))

    def iter(self, path=None, *, recursive: bool = False, include_hidden: bool = False,
             files_only: bool = False, folders_only: bool = False) -> Iterator[Path]:
        if files_only and folders_only: raise AleraValidationError("files_only and folders_only cannot both be true")
        root = self._path(path); stack = [root]
        while stack:
            current = stack.pop()
            try: entries = os.scandir(current)
            except OSError: continue
            with entries:
                children: list[Path] = []
                for entry in entries:
                    p = Path(entry.path)
                    if p.name in self.INTERNAL or (not include_hidden and p.name.startswith(".")): continue
                    try: is_dir = entry.is_dir(follow_symlinks=self.follow_symlinks)
                    except OSError: continue
                    if (not files_only and not folders_only) or (files_only and not is_dir) or (folders_only and is_dir): yield p
                    if recursive and is_dir: children.append(p)
                stack.extend(reversed(children))

    def list_files(self, path=None, *, recursive=False, include_hidden=False) -> list[Path]:
        return sorted(self.iter(path, recursive=recursive, include_hidden=include_hidden, files_only=True), key=lambda p: str(p).casefold())

    def list_folders(self, path=None, *, recursive=False, include_hidden=False) -> list[Path]:
        return sorted(self.iter(path, recursive=recursive, include_hidden=include_hidden, folders_only=True), key=lambda p: str(p).casefold())

    def walk(self, path=None) -> Iterator[tuple[Path, list[Path], list[Path]]]:
        root = self._path(path); stack = [root]
        while stack:
            current = stack.pop(); dirs: list[Path] = []; files: list[Path] = []
            try: entries = os.scandir(current)
            except OSError: continue
            with entries:
                for entry in entries:
                    p = Path(entry.path)
                    if p.name in self.INTERNAL: continue
                    try:
                        if entry.is_dir(follow_symlinks=self.follow_symlinks): dirs.append(p)
                        else: files.append(p)
                    except OSError: continue
            dirs.sort(key=lambda p: p.name.casefold()); files.sort(key=lambda p: p.name.casefold())
            yield current, dirs, files; stack.extend(reversed(dirs))

    def tree(self, path=None, *, max_depth: int | None = None) -> str:
        root = self._path(path); lines = [root.name or str(root)]
        def visit(folder: Path, prefix: str, depth: int):
            if max_depth is not None and depth >= max_depth: return
            try: children = [p for p in folder.iterdir() if p.name not in self.INTERNAL and not p.name.startswith(".")]
            except OSError: return
            children.sort(key=lambda p: (p.is_file(), p.name.casefold()))
            for i, child in enumerate(children):
                last = i == len(children) - 1
                lines.append(prefix + ("└── " if last else "├── ") + child.name)
                if child.is_dir(): visit(child, prefix + ("    " if last else "│   "), depth + 1)
        visit(root, "", 0); return "\n".join(lines)

    def search(self, query: str, path=None, *, case_sensitive=False, files_only=False,
               folders_only=False, glob=False, max_results=None) -> list[Path]:
        if not isinstance(query, str) or not query: raise AleraValidationError("query must be a non-empty string.")
        if files_only and folders_only: raise AleraValidationError("files_only and folders_only cannot both be true")
        needle = query if case_sensitive else query.casefold(); matches: list[Path] = []
        for item in self.iter(path, recursive=True, include_hidden=True):
            if files_only and not item.is_file(): continue
            if folders_only and not item.is_dir(): continue
            haystack = item.name if case_sensitive else item.name.casefold()
            matched = fnmatch.fnmatchcase(haystack, needle) if glob else needle in haystack
            if matched:
                matches.append(item)
                if max_results is not None and len(matches) >= max_results: break
        return matches

    def find_by_extension(self, extension: str, path=None) -> list[Path]:
        if not isinstance(extension, str) or not extension: raise AleraValidationError("extension must be a non-empty string.")
        ext = extension if extension.startswith(".") else "." + extension
        return [p for p in self.list_files(path, recursive=True, include_hidden=True) if p.suffix.casefold() == ext.casefold()]

    def metadata(self, name) -> dict[str, object]:
        target = self._path(name); info = target.stat(follow_symlinks=False); mode = info.st_mode
        return {
            "path": str(target), "relative_path": str(target.relative_to(self.base_path)), "name": target.name,
            "type": "directory" if target.is_dir() else "symlink" if target.is_symlink() else "file",
            "size": self._size(target), "mode": stat.S_IMODE(mode), "permissions": stat.filemode(mode),
            "created": info.st_ctime, "modified": info.st_mtime, "accessed": info.st_atime,
            "inode": getattr(info, "st_ino", None), "device": getattr(info, "st_dev", None),
            "suffix": target.suffix, "mime_type": mimetypes.guess_type(target.name)[0],
            "hidden": target.name.startswith("."), "readable": os.access(target, os.R_OK),
            "writable": os.access(target, os.W_OK), "executable": os.access(target, os.X_OK),
        }

    information = metadata

    def hash(self, name, algorithm: str = "sha256", chunk_size: int = 1024 * 1024) -> str:
        self._validate_chunk_size(chunk_size)
        try: digest = hashlib.new(algorithm)
        except ValueError as exc: raise AleraValidationError(f"Unsupported hash algorithm: {algorithm}") from exc
        for chunk in self.read_bytes_chunks(name, chunk_size): digest.update(chunk)
        return digest.hexdigest()

    def hashes(self, name, algorithms: Iterable[str] = ("md5", "sha1", "sha256", "sha512"), chunk_size: int = 1024 * 1024) -> dict[str, str]:
        self._validate_chunk_size(chunk_size)
        try: digests = {algorithm: hashlib.new(algorithm) for algorithm in algorithms}
        except ValueError as exc: raise AleraValidationError(f"Unsupported hash algorithm: {exc}") from exc
        for chunk in self.read_bytes_chunks(name, chunk_size):
            for digest in digests.values(): digest.update(chunk)
        return {algorithm: digest.hexdigest() for algorithm, digest in digests.items()}

    def size(self, name) -> int: return self._size(self._path(name))
    def relative(self, name) -> Path: return self._path(name).relative_to(self.base_path)
    def absolute(self, name) -> Path: return self._path(name)

    def permissions(self, name) -> dict[str, object]:
        target = self._path(name); mode = target.stat(follow_symlinks=False).st_mode
        return {"mode": stat.S_IMODE(mode), "octal": format(stat.S_IMODE(mode), "04o"), "symbolic": stat.filemode(mode), "readable": os.access(target, os.R_OK), "writable": os.access(target, os.W_OK), "executable": os.access(target, os.X_OK)}

    def set_permissions(self, name, mode: int | str) -> Path:
        if isinstance(mode, str):
            try: mode = int(mode, 8)
            except ValueError as exc: raise AleraValidationError("mode must be octal") from exc
        if not 0 <= mode <= 0o7777: raise AleraValidationError("mode must be between 0 and 0o7777")
        target = self._path(name); os.chmod(target, mode); return target

    def replace_text(self, name, old: str, new: str, *, count: int = -1, encoding: str = "utf-8") -> int:
        if not old: raise AleraValidationError("old text must not be empty")
        text = self.read_file(name, encoding); changed = text.count(old) if count < 0 else min(text.count(old), count)
        self.write_file(name, text.replace(old, new, count), encoding); return changed

    def split_file(self, name, chunk_size: int, output_prefix: str | None = None) -> list[Path]:
        self._validate_chunk_size(chunk_size); source = self._path(name); prefix = output_prefix or source.name + ".part"
        result: list[Path] = []
        for index, chunk in enumerate(self.read_bytes_chunks(name, chunk_size), 1):
            target = self._path(f"{prefix}{index}", allow_root=False); target.write_bytes(chunk); result.append(target)
        return result

    def join_files(self, parts: Iterable[str | os.PathLike[str]], destination, *, atomic: bool = True) -> Path:
        return self.write_bytes_chunks(destination, (chunk for part in parts for chunk in self.read_bytes_chunks(part)), atomic=atomic)

    def copy_stream(self, source, destination, chunk_size: int = 1024 * 1024) -> Path:
        self._validate_chunk_size(chunk_size); return self.write_bytes_chunks(destination, self.read_bytes_chunks(source, chunk_size), atomic=True)

    def sync_metadata(self, source, destination) -> Path:
        src = self._path(source); dst = self._path(destination, allow_root=False); shutil.copystat(src, dst, follow_symlinks=False); return dst

    def link(self, target, link_name, *, hard: bool = False, overwrite: bool = False) -> Path:
        source = self._path(target); destination = self._raw_path(link_name)
        if destination.exists() or destination.is_symlink():
            if not overwrite: raise FileExistsError(destination)
            destination.unlink()
        destination.parent.mkdir(parents=True, exist_ok=True)
        if hard: os.link(source, destination)
        else: destination.symlink_to(source, target_is_directory=source.is_dir())
        return destination

    def read_link(self, name) -> Path: return Path(os.readlink(self._raw_path(name)))
    def resolve_link(self, name) -> Path: return self._path(self._raw_path(name).resolve())

    def find_empty_files(self, path=None) -> list[Path]: return [p for p in self.list_files(path, recursive=True, include_hidden=True) if p.stat().st_size == 0]
    def find_empty_folders(self, path=None) -> list[Path]: return [p for p in self.list_folders(path, recursive=True, include_hidden=True) if not any(p.iterdir())]

    def _size(self, path: Path) -> int:
        try:
            if path.is_file(): return path.stat().st_size
            if not path.is_dir(): return 0
            total = 0
            for current, _, files in os.walk(path, followlinks=self.follow_symlinks):
                for filename in files:
                    try: total += (Path(current) / filename).stat().st_size
                    except OSError: continue
            return total
        except OSError: return 0

    def stats(self, path=None) -> dict[str, object]:
        root = self._path(path); files = 0; folders = 0; bytes_total = 0
        for item in self.iter(root, recursive=True, include_hidden=True):
            try:
                if item.is_dir(): folders += 1
                elif item.is_file(): files += 1; bytes_total += item.stat().st_size
            except OSError: continue
        return {"path": str(root), "files": files, "folders": folders, "bytes": bytes_total}

    def open(self, name, mode="r", **kwargs): return self._path(name).open(mode, **kwargs)
