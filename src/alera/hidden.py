"""Advanced hidden-file support for Alera."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Iterable, Iterator


class HiddenFiles:
    """Manage filesystem-hidden files and directories across platforms.

    Unix-like systems use the conventional leading-dot name. Windows also
    receives the native Hidden attribute. This is real filesystem metadata
    where the operating system supports it; no library can guarantee that a
    third-party file manager will obey its platform's hidden convention.
    """

    def __init__(self, base_path: str | os.PathLike[str] = "") -> None:
        self.base_path = Path(base_path or Path.cwd()).expanduser().resolve()
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _path(self, path: str | os.PathLike[str]) -> Path:
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            candidate = self.base_path / candidate
        candidate = candidate.resolve()
        try:
            candidate.relative_to(self.base_path)
        except ValueError as exc:
            raise ValueError("path escapes the HiddenFiles workspace") from exc
        return candidate

    @staticmethod
    def _windows_hidden(path: Path) -> bool:
        if os.name != "nt" or not path.exists():
            return False
        try:
            import ctypes
            attrs = ctypes.windll.kernel32.GetFileAttributesW(str(path))
            return attrs != -1 and bool(attrs & 0x2)
        except Exception:
            return False

    @staticmethod
    def _set_windows_hidden(path: Path, hidden: bool) -> None:
        if os.name != "nt" or not path.exists():
            return
        try:
            import ctypes
            attrs = ctypes.windll.kernel32.GetFileAttributesW(str(path))
            if attrs == -1:
                return
            attrs = (attrs | 0x2) if hidden else (attrs & ~0x2)
            ctypes.windll.kernel32.SetFileAttributesW(str(path), attrs)
        except Exception:
            pass

    @staticmethod
    def _dot_hidden(path: Path) -> bool:
        return path.name.startswith(".") and path.name not in {".", ".."}

    def is_hidden(self, path: str | os.PathLike[str]) -> bool:
        item = self._path(path)
        if not item.exists() and not item.is_symlink():
            return False
        return self._dot_hidden(item) or self._windows_hidden(item)

    def hidden_reason(self, path: str | os.PathLike[str]) -> str:
        item = self._path(path)
        dot = self._dot_hidden(item)
        windows = self._windows_hidden(item)
        if dot and windows:
            return "dot_name+windows_attribute"
        if dot:
            return "dot_name"
        if windows:
            return "windows_attribute"
        return "visible"

    def hide(self, path: str | os.PathLike[str]) -> Path:
        item = self._path(path)
        if not item.exists() and not item.is_symlink():
            raise FileNotFoundError(item)
        if not self._dot_hidden(item):
            target = item.with_name("." + item.name)
            if target.exists() or target.is_symlink():
                raise FileExistsError(target)
            item.rename(target)
            item = target
        self._set_windows_hidden(item, True)
        return item

    def unhide(self, path: str | os.PathLike[str]) -> Path:
        item = self._path(path)
        if not item.exists() and not item.is_symlink():
            raise FileNotFoundError(item)
        self._set_windows_hidden(item, False)
        if self._dot_hidden(item):
            target = item.with_name(item.name[1:])
            if not target.name:
                raise ValueError("cannot unhide an item with an empty name")
            if target.exists() or target.is_symlink():
                raise FileExistsError(target)
            item.rename(target)
            item = target
        return item

    def create_hidden_file(self, name: str, contents: str = "", overwrite: bool = False) -> Path:
        target = self._path(name)
        if not self._dot_hidden(target):
            target = target.with_name("." + target.name)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and not overwrite:
            raise FileExistsError(target)
        target.write_text(contents, encoding="utf-8")
        self._set_windows_hidden(target, True)
        return target

    def create_hidden_binary(self, name: str, contents: bytes, overwrite: bool = False) -> Path:
        target = self._path(name)
        if not self._dot_hidden(target):
            target = target.with_name("." + target.name)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and not overwrite:
            raise FileExistsError(target)
        target.write_bytes(bytes(contents))
        self._set_windows_hidden(target, True)
        return target

    def create_hidden_folder(self, name: str, parents: bool = False) -> Path:
        target = self._path(name)
        if not self._dot_hidden(target):
            target = target.with_name("." + target.name)
        target.mkdir(parents=parents, exist_ok=False)
        self._set_windows_hidden(target, True)
        return target

    def list_hidden(self, path: str | os.PathLike[str] = "", recursive: bool = False) -> list[Path]:
        root = self._path(path) if path else self.base_path
        items: Iterable[Path] = root.rglob("*") if recursive else root.iterdir()
        return sorted((p for p in items if self.is_hidden(p)), key=lambda p: str(p).lower())

    def list_visible(self, path: str | os.PathLike[str] = "", recursive: bool = False) -> list[Path]:
        root = self._path(path) if path else self.base_path
        items: Iterable[Path] = root.rglob("*") if recursive else root.iterdir()
        return sorted((p for p in items if not self.is_hidden(p)), key=lambda p: str(p).lower())

    def walk_hidden(self, path: str | os.PathLike[str] = "") -> Iterator[Path]:
        yield from self.list_hidden(path, recursive=True)

    def hidden_files(self, path: str | os.PathLike[str] = "", recursive: bool = False) -> list[Path]:
        return [p for p in self.list_hidden(path, recursive) if p.is_file()]

    def hidden_folders(self, path: str | os.PathLike[str] = "", recursive: bool = False) -> list[Path]:
        return [p for p in self.list_hidden(path, recursive) if p.is_dir()]

    def visible_files(self, path: str | os.PathLike[str] = "", recursive: bool = False) -> list[Path]:
        return [p for p in self.list_visible(path, recursive) if p.is_file()]

    def visible_folders(self, path: str | os.PathLike[str] = "", recursive: bool = False) -> list[Path]:
        return [p for p in self.list_visible(path, recursive) if p.is_dir()]

    def hidden_count(self, path: str | os.PathLike[str] = "") -> int:
        return len(self.list_hidden(path))

    def hide_many(self, paths: list[str | os.PathLike[str]]) -> list[Path]:
        return [self.hide(path) for path in paths]

    def unhide_many(self, paths: list[str | os.PathLike[str]]) -> list[Path]:
        return [self.unhide(path) for path in paths]

    def hide_all(self, path: str | os.PathLike[str] = "", recursive: bool = False) -> list[Path]:
        items = self.list_visible(path, recursive)
        items.sort(key=lambda p: len(p.parts), reverse=True)
        return [self.hide(p) for p in items]

    def unhide_all(self, path: str | os.PathLike[str] = "", recursive: bool = False) -> list[Path]:
        items = self.list_hidden(path, recursive)
        items.sort(key=lambda p: len(p.parts), reverse=True)
        return [self.unhide(p) for p in items]

    def reveal(self, path: str | os.PathLike[str]) -> Path:
        return self.unhide(path)

    def hidden_information(self, path: str | os.PathLike[str]) -> dict[str, object]:
        item = self._path(path)
        stat_result = item.stat() if item.exists() else None
        return {
            "path": str(item),
            "name": item.name,
            "exists": item.exists(),
            "hidden": self.is_hidden(item),
            "reason": self.hidden_reason(item),
            "type": "directory" if item.is_dir() else "file" if item.is_file() else "other",
            "size": stat_result.st_size if stat_result else 0,
            "modified": stat_result.st_mtime if stat_result else None,
            "native_windows_hidden": self._windows_hidden(item),
        }

    def copy_hidden(self, source: str | os.PathLike[str], destination: str | os.PathLike[str]) -> Path:
        src = self._path(source)
        dst = self._path(destination)
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)
        if self.is_hidden(src) and not self.is_hidden(dst):
            dst = self.hide(dst)
        return dst
