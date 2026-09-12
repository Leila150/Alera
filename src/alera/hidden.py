"""Hidden-file support for Alera."""

from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import Iterable


class HiddenFiles:
    """Create, detect, hide, unhide, and enumerate hidden filesystem items.

    On Unix-like systems Alera uses the conventional leading-dot convention.
    On Windows it also uses the native FILE_ATTRIBUTE_HIDDEN flag when the
    platform APIs are available.  This makes the hidden state visible to
    normal operating-system file explorers rather than merely hiding it from
    Alera's own listings.
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
            if hidden:
                attrs |= 0x2
            else:
                attrs &= ~0x2
            ctypes.windll.kernel32.SetFileAttributesW(str(path), attrs)
        except Exception:
            pass

    def is_hidden(self, path: str | os.PathLike[str]) -> bool:
        """Return whether an existing item is hidden by the OS convention."""
        item = self._path(path)
        if not item.exists() and not item.is_symlink():
            return False
        return item.name.startswith(".") or self._windows_hidden(item)

    def hide(self, path: str | os.PathLike[str]) -> Path:
        """Hide an item using the native filesystem convention where possible."""
        item = self._path(path)
        if not item.exists() and not item.is_symlink():
            raise FileNotFoundError(item)

        if not item.name.startswith("."):
            target = item.with_name("." + item.name)
            if target.exists() or target.is_symlink():
                raise FileExistsError(target)
            item.rename(target)
            item = target
        self._set_windows_hidden(item, True)
        return item

    def unhide(self, path: str | os.PathLike[str]) -> Path:
        """Remove hidden state and restore a conventional non-hidden name."""
        item = self._path(path)
        if not item.exists() and not item.is_symlink():
            raise FileNotFoundError(item)

        self._set_windows_hidden(item, False)
        if item.name.startswith(".") and item.name not in {".", ".."}:
            target = item.with_name(item.name[1:])
            if target.exists() or target.is_symlink():
                raise FileExistsError(target)
            item.rename(target)
            item = target
        return item

    def create_hidden_file(self, name: str, contents: str = "") -> Path:
        """Create a hidden text file."""
        target = self._path(name)
        if not target.name.startswith("."):
            target = target.with_name("." + target.name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(contents, encoding="utf-8")
        self._set_windows_hidden(target, True)
        return target

    def create_hidden_folder(self, name: str) -> Path:
        """Create a hidden directory."""
        target = self._path(name)
        if not target.name.startswith("."):
            target = target.with_name("." + target.name)
        target.mkdir(parents=True, exist_ok=False)
        self._set_windows_hidden(target, True)
        return target

    def list_hidden(self, path: str | os.PathLike[str] = "", recursive: bool = False) -> list[Path]:
        """List hidden files and folders."""
        root = self._path(path) if path else self.base_path
        if recursive:
            items: Iterable[Path] = (p for p in root.rglob("*") if p != root)
        else:
            items = root.iterdir()
        return sorted((p for p in items if self.is_hidden(p)), key=lambda p: str(p).lower())

    def list_visible(self, path: str | os.PathLike[str] = "", recursive: bool = False) -> list[Path]:
        """List only items that are not hidden."""
        root = self._path(path) if path else self.base_path
        if recursive:
            items: Iterable[Path] = (p for p in root.rglob("*") if p != root)
        else:
            items = root.iterdir()
        return sorted((p for p in items if not self.is_hidden(p)), key=lambda p: str(p).lower())

    def hidden_count(self, path: str | os.PathLike[str] = "") -> int:
        return len(self.list_hidden(path))

    def hide_many(self, paths: list[str | os.PathLike[str]]) -> list[Path]:
        return [self.hide(path) for path in paths]

    def unhide_many(self, paths: list[str | os.PathLike[str]]) -> list[Path]:
        return [self.unhide(path) for path in paths]

    def reveal(self, path: str | os.PathLike[str]) -> Path:
        """Alias for unhide()."""
        return self.unhide(path)

    def hidden_information(self, path: str | os.PathLike[str]) -> dict[str, object]:
        item = self._path(path)
        return {
            "path": str(item),
            "name": item.name,
            "exists": item.exists(),
            "hidden": self.is_hidden(item),
            "type": "directory" if item.is_dir() else "file" if item.is_file() else "other",
            "native_windows_hidden": self._windows_hidden(item),
        }
