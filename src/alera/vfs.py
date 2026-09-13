"""High-performance in-memory virtual filesystem for Alera."""
from __future__ import annotations

import fnmatch
import hashlib
import io
import mimetypes
import time
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Iterable, Iterator


@dataclass(slots=True, frozen=True)
class VirtualStat:
    path: str
    kind: str
    size: int
    modified: float
    sha256: str | None


class _WriteBack(io.BytesIO):
    def __init__(self, initial: bytes, save) -> None:
        super().__init__(initial)
        self._save = save

    def close(self) -> None:
        if not self.closed:
            self._save(self.getvalue())
        super().close()


class VirtualFileSystem:
    """A feature-rich, deterministic filesystem that never touches disk."""

    def __init__(self) -> None:
        self._files: dict[str, bytes] = {}
        self._dirs: set[str] = {"."}
        self._modified: dict[str, float] = {".": time.time()}
        self._modes: dict[str, int] = {}
        self._snapshots: dict[str, dict] = {}

    @staticmethod
    def _norm(path: str) -> str:
        value = str(PurePosixPath(str(path).replace("\\", "/"))).lstrip("/") or "."
        if value == ".." or value.startswith("../") or "/../" in value:
            raise ValueError("Path escapes the virtual filesystem")
        return value.rstrip("/") or "."

    def _touch(self, path: str) -> None:
        self._modified[path] = time.time()

    def _parent(self, path: str) -> str:
        parent = str(PurePosixPath(path).parent)
        return parent if parent != "" else "."

    def create_folder(self, path: str) -> None:
        path = self._norm(path)
        if path == ".":
            return
        parts = path.split("/")
        for index in range(1, len(parts) + 1):
            current = "/".join(parts[:index])
            self._dirs.add(current)
            self._modified.setdefault(current, time.time())

    mkdir = create_folder

    def create_folders(self, paths: Iterable[str]) -> None:
        for path in paths:
            self.create_folder(path)

    def create_file(self, path: str, data: str | bytes = b"") -> None:
        path = self._norm(path)
        if path == ".":
            raise ValueError("A file cannot be named .")
        self.create_folder(self._parent(path))
        self._files[path] = data.encode("utf-8") if isinstance(data, str) else bytes(data)
        self._modified[path] = time.time()

    touch = create_file

    def exists(self, path: str) -> bool:
        path = self._norm(path)
        return path in self._files or path in self._dirs

    def is_file(self, path: str) -> bool:
        return self._norm(path) in self._files

    def is_dir(self, path: str) -> bool:
        return self._norm(path) in self._dirs

    def read(self, path: str, encoding: str = "utf-8", errors: str = "strict") -> str:
        return self._files[self._norm(path)].decode(encoding, errors)

    def read_bytes(self, path: str) -> bytes:
        return self._files[self._norm(path)]

    def write(self, path: str, data: str | bytes, encoding: str = "utf-8") -> None:
        self.create_file(path, data.encode(encoding) if isinstance(data, str) else data)

    def append(self, path: str, data: str | bytes, encoding: str = "utf-8") -> None:
        path = self._norm(path)
        current = self._files.get(path, b"")
        self.write(path, current + (data.encode(encoding) if isinstance(data, str) else bytes(data)))

    def open(self, path: str, mode: str = "rb", encoding: str = "utf-8"):
        path = self._norm(path)
        binary = "b" in mode
        writing = any(flag in mode for flag in "wax+")
        if "r" in mode and path not in self._files and not writing:
            raise FileNotFoundError(path)
        initial = self._files.get(path, b"")
        if "w" in mode:
            initial = b""
        if "x" in mode and path in self._files:
            raise FileExistsError(path)
        if binary:
            stream = _WriteBack(initial, lambda data: self.write(path, data)) if writing else io.BytesIO(initial)
            if "a" in mode:
                stream.seek(0, 2)
            return stream
        text = io.TextIOWrapper(_WriteBack(initial, lambda data: self.write(path, data)), encoding=encoding)
        if "a" in mode:
            text.seek(0, 2)
        return text

    def delete(self, path: str) -> None:
        path = self._norm(path)
        if path in self._files:
            del self._files[path]
            self._modified.pop(path, None)
            return
        if path in self._dirs:
            prefix = path + "/"
            for key in list(self._files):
                if key.startswith(prefix):
                    del self._files[key]
            for key in list(self._modified):
                if key == path or key.startswith(prefix):
                    del self._modified[key]
            self._dirs = {key for key in self._dirs if key != path and not key.startswith(prefix)}
            return
        raise FileNotFoundError(path)

    remove = delete

    def copy(self, source: str, destination: str) -> None:
        source, destination = self._norm(source), self._norm(destination)
        if source in self._files:
            self.create_file(destination, self._files[source])
            return
        if source not in self._dirs:
            raise FileNotFoundError(source)
        self.create_folder(destination)
        prefix = source + "/"
        for directory in sorted(self._dirs):
            if directory.startswith(prefix):
                self.create_folder(destination + "/" + directory[len(prefix):])
        for path, data in list(self._files.items()):
            if path.startswith(prefix):
                self.create_file(destination + "/" + path[len(prefix):], data)

    def move(self, source: str, destination: str) -> None:
        self.copy(source, destination)
        self.delete(source)

    rename = move

    def list(self, path: str = ".") -> list[str]:
        path = self._norm(path)
        if not self.exists(path):
            raise FileNotFoundError(path)
        prefix = "" if path == "." else path.rstrip("/") + "/"
        values: set[str] = set()
        for candidate in (*self._files.keys(), *self._dirs):
            if candidate.startswith(prefix) and candidate != path:
                values.add(candidate[len(prefix):].split("/")[0])
        return sorted(values)

    def iter_paths(self, path: str = ".", recursive: bool = True) -> Iterator[str]:
        path = self._norm(path)
        if path != "." and not self.exists(path):
            raise FileNotFoundError(path)
        prefix = "" if path == "." else path + "/"
        for candidate in sorted((*self._files.keys(), *self._dirs)):
            if candidate == "." or not candidate.startswith(prefix):
                continue
            if recursive or "/" not in candidate[len(prefix):]:
                yield candidate

    def walk(self, path: str = ".") -> Iterator[tuple[str, list[str], list[str]]]:
        path = self._norm(path)
        directories = [p for p in self._dirs if p == path or p.startswith(path + "/")]
        for directory in sorted(directories):
            children = self.list(directory)
            dirs = sorted(name for name in children if self.is_dir(directory + "/" + name if directory != "." else name))
            files = sorted(name for name in children if self.is_file(directory + "/" + name if directory != "." else name))
            yield directory, dirs, files

    def find(self, pattern: str = "*", path: str = ".", *, files_only: bool = False, dirs_only: bool = False) -> list[str]:
        results = []
        for candidate in self.iter_paths(path):
            if files_only and not self.is_file(candidate):
                continue
            if dirs_only and not self.is_dir(candidate):
                continue
            if fnmatch.fnmatch(candidate, pattern) or fnmatch.fnmatch(PurePosixPath(candidate).name, pattern):
                results.append(candidate)
        return results

    search = find

    def stat(self, path: str) -> VirtualStat:
        path = self._norm(path)
        if self.is_file(path):
            data = self._files[path]
            digest = hashlib.sha256(data).hexdigest()
            return VirtualStat(path, "file", len(data), self._modified.get(path, 0.0), digest)
        if self.is_dir(path):
            size = sum(len(data) for key, data in self._files.items() if key.startswith(path + "/") or (path == "." and key in self._files))
            return VirtualStat(path, "directory", size, self._modified.get(path, 0.0), None)
        raise FileNotFoundError(path)

    information = stat

    def hash(self, path: str, algorithm: str = "sha256") -> str:
        digest = hashlib.new(algorithm)
        if self.is_file(path):
            digest.update(self.read_bytes(path))
        elif self.is_dir(path):
            for candidate in self.find("*", path, files_only=True):
                digest.update(candidate.encode())
                digest.update(self.read_bytes(candidate))
        else:
            raise FileNotFoundError(path)
        return digest.hexdigest()

    def tree(self, path: str = ".") -> str:
        lines = [path]
        for candidate in self.iter_paths(path):
            depth = 0 if path == "." else candidate[len(path):].count("/")
            lines.append("  " * (depth + 1) + PurePosixPath(candidate).name)
        return "\n".join(lines)

    def snapshot(self, name: str | None = None) -> dict:
        snap = {"files": dict(self._files), "directories": sorted(self._dirs), "modified": dict(self._modified), "modes": dict(self._modes)}
        if name:
            self._snapshots[str(name)] = snap
        return snap

    def restore(self, snapshot: dict | str) -> None:
        if isinstance(snapshot, str):
            snapshot = self._snapshots[snapshot]
        self._files = {str(k): bytes(v) for k, v in snapshot.get("files", {}).items()}
        self._dirs = set(snapshot.get("directories", ["."]))
        self._dirs.add(".")
        self._modified = {str(k): float(v) for k, v in snapshot.get("modified", {}).items()}
        self._modes = {str(k): int(v) for k, v in snapshot.get("modes", {}).items()}

    def snapshot_names(self) -> list[str]:
        return sorted(self._snapshots)

    def transaction(self):
        owner = self
        original = owner.snapshot()
        class _Transaction:
            def __enter__(self_inner):
                return owner
            def commit(self_inner):
                self_inner.committed = True
            def __exit__(self_inner, exc_type, exc, tb):
                if exc_type is not None or not getattr(self_inner, "committed", False):
                    owner.restore(original)
                return False
        return _Transaction()

    def export(self, destination: str) -> None:
        from pathlib import Path
        root = Path(destination)
        root.mkdir(parents=True, exist_ok=True)
        for directory in self._dirs:
            if directory != ".":
                (root / directory).mkdir(parents=True, exist_ok=True)
        for path, data in self._files.items():
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)

    def import_directory(self, source: str, destination: str = ".") -> int:
        from pathlib import Path
        root = Path(source)
        destination = self._norm(destination)
        count = 0
        for current, dirs, files in __import__("os").walk(root):
            relative = Path(current).relative_to(root)
            folder = destination if str(relative) == "." else self._norm(f"{destination}/{relative.as_posix()}")
            self.create_folder(folder)
            for filename in files:
                self.create_file(f"{folder}/{filename}", (Path(current) / filename).read_bytes())
                count += 1
        return count

    def mime_type(self, path: str) -> str | None:
        return mimetypes.guess_type(PurePosixPath(self._norm(path)).name)[0]

    def chmod(self, path: str, mode: int) -> None:
        path = self._norm(path)
        if not self.exists(path):
            raise FileNotFoundError(path)
        self._modes[path] = int(mode)

    def mode(self, path: str) -> int | None:
        return self._modes.get(self._norm(path))
