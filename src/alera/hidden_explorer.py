"""A filesystem explorer with a dedicated hidden-item view."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator

from .explorer import FileExplorer
from .hidden import HiddenFiles


class HiddenFileExplorer(FileExplorer):
    """A richer FileExplorer with explicit hidden-file navigation.

    Normal operations keep hidden items out of sight. ``show_hidden`` exposes
    hidden user files while Alera's own internal ``.alera_bin`` remains
    protected from ordinary browsing.
    """

    def __init__(self, base_path: str | Path = "", show_hidden: bool = False) -> None:
        super().__init__(base_path)
        self.hidden = HiddenFiles(self.base_path)
        self.show_hidden = bool(show_hidden)
        self.current_path = self.base_path

    def _current(self, path: str | Path = "") -> Path:
        target = self.current_path if path == "" else self._path(path)
        return target

    def set_show_hidden(self, enabled: bool = True) -> bool:
        self.show_hidden = bool(enabled)
        return self.show_hidden

    def show(self) -> bool:
        return self.set_show_hidden(True)

    def hide_view(self) -> bool:
        return self.set_show_hidden(False)

    def toggle_hidden(self) -> bool:
        self.show_hidden = not self.show_hidden
        return self.show_hidden

    def enter(self, path: str | Path) -> Path:
        """Enter a directory and make it the explorer's current location."""
        target = self._path(path)
        if not target.is_dir():
            raise NotADirectoryError(target)
        if target == self._bin_path or self._bin_path in target.parents:
            raise PermissionError("the Alera recycle bin is not browsable")
        if not self.show_hidden and self.hidden.is_hidden(target):
            raise PermissionError("hidden directory is not visible")
        self.current_path = target
        return target

    def cd(self, path: str | Path) -> Path:
        return self.enter(path)

    def up(self) -> Path:
        if self.current_path == self.base_path:
            return self.current_path
        self.current_path = self.current_path.parent
        return self.current_path

    def home(self) -> Path:
        self.current_path = self.base_path
        return self.current_path

    def pwd(self) -> Path:
        return self.current_path

    def list(self, path: str | Path = "") -> list[Path]:
        """List the current directory, respecting hidden visibility."""
        target = self._current(path)
        if target == self._bin_path or self._bin_path in target.parents:
            raise PermissionError("the Alera recycle bin is not browsable")
        if not self.show_hidden:
            return super().list(path if path else str(target))
        return sorted(
            (p for p in target.iterdir() if p != self._bin_path),
            key=lambda p: p.name.lower(),
        )

    def list_all(self, path: str | Path = "") -> list[Path]:
        """Return visible + hidden user items, excluding Alera internals."""
        target = self._current(path)
        return sorted(
            (p for p in target.iterdir() if p != self._bin_path),
            key=lambda p: p.name.lower(),
        )

    def list_hidden(self, path: str | Path = "", recursive: bool = False) -> list[Path]:
        return [p for p in self.hidden.list_hidden(path, recursive) if p != self._bin_path and self._bin_path not in p.parents]

    def list_visible(self, path: str | Path = "", recursive: bool = False) -> list[Path]:
        return self.hidden.list_visible(path, recursive)

    def hidden_files(self, path: str | Path = "", recursive: bool = False) -> list[Path]:
        return [p for p in self.list_hidden(path, recursive) if p.is_file()]

    def hidden_folders(self, path: str | Path = "", recursive: bool = False) -> list[Path]:
        return [p for p in self.list_hidden(path, recursive) if p.is_dir()]

    def hide(self, path: str | Path) -> Path:
        return self.hidden.hide(path)

    def unhide(self, path: str | Path) -> Path:
        return self.hidden.unhide(path)

    def reveal(self, path: str | Path) -> Path:
        return self.hidden.reveal(path)

    def create_hidden_file(self, name: str, contents: str = "", overwrite: bool = False) -> Path:
        return self.hidden.create_hidden_file(name, contents, overwrite)

    def create_hidden_binary(self, name: str, contents: bytes, overwrite: bool = False) -> Path:
        return self.hidden.create_hidden_binary(name, contents, overwrite)

    def create_hidden_folder(self, name: str, parents: bool = False) -> Path:
        return self.hidden.create_hidden_folder(name, parents)

    def hidden_count(self, path: str | Path = "") -> int:
        return len(self.list_hidden(path))

    def hidden_information(self, path: str | Path) -> dict[str, object]:
        return self.hidden.hidden_information(path)

    def hidden_tree(self, path: str | Path = "") -> str:
        """Build a tree containing only hidden items."""
        root = self._current(path)
        lines = [root.name or str(root)]
        hidden = self.list_hidden(root, recursive=True)
        for item in hidden:
            if self._bin_path in item.parents or item == self._bin_path:
                continue
            try:
                relative = item.relative_to(root)
            except ValueError:
                continue
            lines.append("  " * len(relative.parts) + relative.name)
        return "\n".join(lines)

    def walk(self, path: str | Path = "") -> Iterator[tuple[Path, list[Path], list[Path]]]:
        """Walk while respecting hidden visibility and excluding Alera's bin."""
        root = self._current(path)
        for current, dirs, files in os.walk(root):
            current_path = Path(current)
            if self._bin_path in current_path.parents or current_path == self._bin_path:
                dirs[:] = []
                continue
            dirs[:] = [d for d in dirs if d != self._bin_path.name]
            if not self.show_hidden:
                dirs[:] = [d for d in dirs if not self.hidden.is_hidden(current_path / d)]
                files[:] = [f for f in files if not self.hidden.is_hidden(current_path / f)]
            yield current_path, [current_path / d for d in dirs], [current_path / f for f in files]

    def search_hidden(self, pattern: str = "*", recursive: bool = True) -> list[Path]:
        """Search only hidden items using pathlib glob patterns."""
        root = self._current()
        candidates = root.rglob(pattern) if recursive else root.glob(pattern)
        return sorted(
            (p for p in candidates if self.hidden.is_hidden(p) and p != self._bin_path and self._bin_path not in p.parents),
            key=lambda p: str(p).lower(),
        )

    def refresh(self) -> list[Path]:
        """Refresh the current directory by returning its latest listing."""
        return self.list()
