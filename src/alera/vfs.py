"""A small in-memory filesystem useful for testing and transformations."""

from __future__ import annotations

import io
from pathlib import PurePosixPath


class VirtualFileSystem:
    """Store files and directories entirely in memory."""

    def __init__(self) -> None:
        self._files: dict[str, bytes] = {}
        self._dirs: set[str] = {"."}

    def _norm(self, path: str) -> str:
        value = str(PurePosixPath(path)).lstrip("/") or "."
        if value == ".." or value.startswith("../") or "/../" in value:
            raise ValueError("Path escapes the virtual filesystem")
        return value

    def create_folder(self, path: str) -> None:
        path = self._norm(path)
        if path == ".":
            return
        parts = path.split("/")
        for index in range(1, len(parts) + 1):
            self._dirs.add("/".join(parts[:index]))

    def create_file(self, path: str, data: str | bytes = b"") -> None:
        path = self._norm(path)
        if path == ".":
            raise ValueError("A file cannot be named .")
        parent = str(PurePosixPath(path).parent)
        self.create_folder(parent)
        self._files[path] = data.encode("utf-8") if isinstance(data, str) else bytes(data)

    def exists(self, path: str) -> bool:
        path = self._norm(path)
        return path in self._files or path in self._dirs

    def read(self, path: str, encoding: str = "utf-8") -> str:
        return self._files[self._norm(path)].decode(encoding)

    def read_bytes(self, path: str) -> bytes:
        return self._files[self._norm(path)]

    def write(self, path: str, data: str | bytes) -> None:
        self.create_file(path, data)

    def delete(self, path: str) -> None:
        path = self._norm(path)
        if path in self._files:
            del self._files[path]
            return
        if path in self._dirs:
            prefix = path + "/"
            self._files = {k: v for k, v in self._files.items() if not k.startswith(prefix)}
            self._dirs = {k for k in self._dirs if k != path and not k.startswith(prefix)}
            return
        raise FileNotFoundError(path)

    def list(self, path: str = ".") -> list[str]:
        path = self._norm(path)
        prefix = "" if path == "." else path.rstrip("/") + "/"
        values = set()
        for candidate in (*self._files.keys(), *self._dirs):
            if candidate.startswith(prefix) and candidate != path:
                remainder = candidate[len(prefix):]
                values.add(remainder.split("/")[0])
        return sorted(values)

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

    def snapshot(self) -> dict:
        return {"files": dict(self._files), "directories": sorted(self._dirs)}

    def restore(self, snapshot: dict) -> None:
        self._files = {str(k): bytes(v) for k, v in snapshot.get("files", {}).items()}
        self._dirs = set(snapshot.get("directories", ["."]))
        self._dirs.add(".")

    def open(self, path: str, mode: str = "rb") -> io.BytesIO:
        path = self._norm(path)
        if "r" in mode and path not in self._files:
            raise FileNotFoundError(path)
        initial = self._files.get(path, b"")
        stream = io.BytesIO(initial)
        if "a" in mode:
            stream.seek(0, 2)
        return stream
