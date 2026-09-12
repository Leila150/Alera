"""Core filesystem explorer for Alera."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
from pathlib import Path
from typing import Iterator

from .exceptions import AleraPathError, AleraValidationError


class FileExplorer:
    """A safe, batteries-included filesystem helper.

    ``base_path`` is optional. An empty value means the current working directory.
    Every operation is restricted to the explorer root.
    """

    def __init__(self, base_path: str | os.PathLike[str] = "") -> None:
        raw = Path(base_path).expanduser() if str(base_path) else Path.cwd()
        try:
            self.base_path = raw.resolve()
        except OSError as exc:
            raise AleraPathError(f"Unable to resolve base path: {raw}") from exc
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _path(self, path: str | os.PathLike[str] | None, *, allow_root: bool = True) -> Path:
        if path is None or str(path) == "":
            result = self.base_path
        else:
            candidate = Path(path).expanduser()
            result = candidate.resolve() if candidate.is_absolute() else (self.base_path / candidate).resolve()
        if not allow_root and result == self.base_path:
            raise AleraPathError("The explorer root cannot be targeted by this operation.")
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

    def exists(self, path: str | os.PathLike[str]) -> bool:
        return self._path(path).exists()

    def is_file(self, path: str | os.PathLike[str]) -> bool:
        return self._path(path).is_file()

    def is_folder(self, path: str | os.PathLike[str]) -> bool:
        return self._path(path).is_dir()

    def create_folder(self, name: str | os.PathLike[str], path: str | os.PathLike[str] | None = None) -> Path:
        name = self._require_single(name)
        target = self._path(Path(path or "") / name, allow_root=False)
        target.mkdir(parents=True, exist_ok=False)
        return target

    def create_folders(self, names: list[str | os.PathLike[str]], path: str | os.PathLike[str] | None = None) -> list[Path]:
        self._require_list(names)
        return [self.create_folder(name, path) for name in names]

    def create_file(self, name: str | os.PathLike[str], contents: str = "") -> Path:
        name = self._require_single(name)
        if not isinstance(contents, str):
            raise AleraValidationError("contents must be a string.")
        target = self._path(name, allow_root=False)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("x", encoding="utf-8", newline="") as handle:
            handle.write(contents)
        return target

    def create_binary_file(self, name: str | os.PathLike[str], contents: bytes | bytearray | memoryview) -> Path:
        name = self._require_single(name)
        if not isinstance(contents, (bytes, bytearray, memoryview)):
            raise AleraValidationError("Binary contents must be bytes-like.")
        target = self._path(name, allow_root=False)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as handle:
            handle.write(bytes(contents))
        return target

    def read_file(self, name: str | os.PathLike[str], encoding: str = "utf-8") -> str:
        with self._path(name).open("r", encoding=encoding) as handle:
            return handle.read()

    def read_binary_file(self, name: str | os.PathLike[str]) -> bytes:
        with self._path(name).open("rb") as handle:
            return handle.read()

    def write_file(self, name: str | os.PathLike[str], contents: str, encoding: str = "utf-8") -> Path:
        if not isinstance(contents, str):
            raise AleraValidationError("contents must be a string.")
        target = self._path(name, allow_root=False)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding=encoding, newline="") as handle:
            handle.write(contents)
        return target

    def append_file(self, name: str | os.PathLike[str], contents: str, encoding: str = "utf-8") -> Path:
        if not isinstance(contents, str):
            raise AleraValidationError("contents must be a string.")
        target = self._path(name, allow_root=False)
        with target.open("a", encoding=encoding, newline="") as handle:
            handle.write(contents)
        return target

    def write_binary_file(self, name: str | os.PathLike[str], contents: bytes | bytearray | memoryview) -> Path:
        if not isinstance(contents, (bytes, bytearray, memoryview)):
            raise AleraValidationError("Binary contents must be bytes-like.")
        target = self._path(name, allow_root=False)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("wb") as handle:
            handle.write(bytes(contents))
        return target

    def rename(self, old: str | os.PathLike[str], new: str | os.PathLike[str]) -> Path:
        source = self._path(old, allow_root=False)
        destination = self._path(new, allow_root=False)
        destination.parent.mkdir(parents=True, exist_ok=True)
        return source.rename(destination)

    def copy(self, source: str | os.PathLike[str], destination: str | os.PathLike[str]) -> Path:
        src = self._path(source, allow_root=False)
        dst = self._path(destination, allow_root=False)
        if src.is_dir():
            if dst == src or src in dst.parents:
                raise AleraPathError("A directory cannot be copied into itself or one of its children.")
            return Path(shutil.copytree(src, dst, dirs_exist_ok=True))
        dst.parent.mkdir(parents=True, exist_ok=True)
        return Path(shutil.copy2(src, dst))

    def move(self, source: str | os.PathLike[str], destination: str | os.PathLike[str]) -> Path:
        src = self._path(source, allow_root=False)
        dst = self._path(destination, allow_root=False)
        if src.is_dir() and (dst == src or src in dst.parents):
            raise AleraPathError("A directory cannot be moved into itself or one of its children.")
        dst.parent.mkdir(parents=True, exist_ok=True)
        return Path(shutil.move(str(src), str(dst)))

    def delete(self, name: str | os.PathLike[str]) -> Path:
        """Permanently delete one file or directory, recursively when needed.

        There is no recycle bin, trash directory, backup copy, or restore operation.
        """
        name = self._require_single(name)
        target = self._path(name, allow_root=False)
        if not target.exists():
            raise FileNotFoundError(target)
        try:
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
        except OSError as exc:
            raise OSError(f"Could not permanently delete {target}.") from exc
        return target

    def deletes(self, names: list[str | os.PathLike[str]]) -> list[Path]:
        """Permanently delete every item in a required list."""
        self._require_list(names)
        return [self.delete(name) for name in names]

    def list(self, path: str | os.PathLike[str] | None = None, *, include_hidden: bool = False) -> list[Path]:
        root = self._path(path)
        if not root.is_dir():
            raise NotADirectoryError(root)
        return sorted((p for p in root.iterdir() if include_hidden or not p.name.startswith(".")), key=lambda p: (p.is_file(), p.name.lower()))

    def list_files(self, path: str | os.PathLike[str] | None = None, *, recursive: bool = False, include_hidden: bool = False) -> list[Path]:
        root = self._path(path)
        iterator = root.rglob("*") if recursive else root.iterdir()
        return sorted((p for p in iterator if p.is_file() and (include_hidden or not any(part.startswith(".") for part in p.relative_to(self.base_path).parts))), key=lambda p: str(p).lower())

    def list_folders(self, path: str | os.PathLike[str] | None = None, *, recursive: bool = False, include_hidden: bool = False) -> list[Path]:
        root = self._path(path)
        iterator = root.rglob("*") if recursive else root.iterdir()
        return sorted((p for p in iterator if p.is_dir() and (include_hidden or not any(part.startswith(".") for part in p.relative_to(self.base_path).parts))), key=lambda p: str(p).lower())

    def walk(self, path: str | os.PathLike[str] | None = None) -> Iterator[tuple[Path, list[Path], list[Path]]]:
        root = self._path(path)
        for current, dirs, files in os.walk(root):
            current_path = Path(current)
            yield current_path, [current_path / d for d in dirs], [current_path / f for f in files]

    def tree(self, path: str | os.PathLike[str] | None = None, *, max_depth: int | None = None) -> str:
        root = self._path(path)
        lines = [root.name or str(root)]

        def visit(folder: Path, prefix: str, depth: int) -> None:
            if max_depth is not None and depth >= max_depth:
                return
            children = sorted((p for p in folder.iterdir() if not p.name.startswith(".")), key=lambda p: (p.is_file(), p.name.lower()))
            for index, child in enumerate(children):
                last = index == len(children) - 1
                lines.append(prefix + ("└── " if last else "├── ") + child.name)
                if child.is_dir():
                    visit(child, prefix + ("    " if last else "│   "), depth + 1)

        visit(root, "", 0)
        return "\n".join(lines)

    def search(self, query: str, path: str | os.PathLike[str] | None = None, *, case_sensitive: bool = False, files_only: bool = False) -> list[Path]:
        if not isinstance(query, str) or not query:
            raise AleraValidationError("query must be a non-empty string.")
        root = self._path(path)
        needle = query if case_sensitive else query.lower()
        matches = []
        for item in root.rglob("*"):
            if files_only and not item.is_file():
                continue
            haystack = item.name if case_sensitive else item.name.lower()
            if needle in haystack:
                matches.append(item)
        return sorted(matches, key=lambda p: str(p).lower())

    def find_by_extension(self, extension: str, path: str | os.PathLike[str] | None = None) -> list[Path]:
        if not isinstance(extension, str) or not extension:
            raise AleraValidationError("extension must be a non-empty string.")
        ext = extension if extension.startswith(".") else "." + extension
        return sorted((p for p in self.list_files(path, recursive=True) if p.suffix.lower() == ext.lower()), key=lambda p: str(p).lower())

    def replace_text(self, name: str | os.PathLike[str], old: str, new: str, *, count: int = -1, encoding: str = "utf-8") -> int:
        text = self.read_file(name, encoding)
        updated = text.replace(old, new, count)
        self.write_file(name, updated, encoding)
        return text.count(old) if count < 0 else min(text.count(old), count)

    def file_hash(self, name: str | os.PathLike[str], algorithm: str = "sha256", chunk_size: int = 1024 * 1024) -> str:
        if chunk_size <= 0:
            raise AleraValidationError("chunk_size must be greater than zero.")
        target = self._path(name)
        try:
            digest = hashlib.new(algorithm)
        except ValueError as exc:
            raise AleraValidationError(f"Unknown hash algorithm: {algorithm}") from exc
        with target.open("rb") as handle:
            for chunk in iter(lambda: handle.read(chunk_size), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def metadata(self, name: str | os.PathLike[str]) -> dict[str, object]:
        target = self._path(name)
        info = target.stat()
        return {
            "name": target.name,
            "path": str(target),
            "type": "folder" if target.is_dir() else "file",
            "size": self._size(target),
            "created": info.st_ctime,
            "modified": info.st_mtime,
            "accessed": info.st_atime,
            "mode": stat.filemode(info.st_mode),
            "readonly": not os.access(target, os.W_OK),
        }

    def json_metadata(self, name: str | os.PathLike[str]) -> str:
        return json.dumps(self.metadata(name), indent=2)

    @staticmethod
    def _size(path: Path) -> int:
        if path.is_file():
            return path.stat().st_size
        return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())

    def size(self, name: str | os.PathLike[str]) -> int:
        return self._size(self._path(name))

    def free_space(self, path: str | os.PathLike[str] | None = None) -> int:
        return shutil.disk_usage(self._path(path)).free

    def disk_usage(self, path: str | os.PathLike[str] | None = None) -> dict[str, int]:
        usage = shutil.disk_usage(self._path(path))
        return {"total": usage.total, "used": usage.used, "free": usage.free}

    def temporary_file(self, *, suffix: str = "", prefix: str = "alera-") -> Path:
        fd, name = tempfile.mkstemp(suffix=suffix, prefix=prefix, dir=self.base_path)
        os.close(fd)
        return Path(name)

    def temporary_folder(self, *, prefix: str = "alera-") -> Path:
        return Path(tempfile.mkdtemp(prefix=prefix, dir=self.base_path))

    def permissions(self, name: str | os.PathLike[str]) -> dict[str, bool]:
        mode = self._path(name).stat().st_mode
        return {
            "owner_read": bool(mode & stat.S_IRUSR),
            "owner_write": bool(mode & stat.S_IWUSR),
            "owner_execute": bool(mode & stat.S_IXUSR),
            "group_read": bool(mode & stat.S_IRGRP),
            "group_write": bool(mode & stat.S_IWGRP),
            "group_execute": bool(mode & stat.S_IXGRP),
            "other_read": bool(mode & stat.S_IROTH),
            "other_write": bool(mode & stat.S_IWOTH),
            "other_execute": bool(mode & stat.S_IXOTH),
        }

    def set_readonly(self, name: str | os.PathLike[str], readonly: bool = True) -> Path:
        target = self._path(name)
        mode = target.stat().st_mode
        if readonly:
            mode &= ~stat.S_IWUSR
        else:
            mode |= stat.S_IWUSR
        target.chmod(mode)
        return target
