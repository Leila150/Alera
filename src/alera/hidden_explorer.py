"""A filesystem explorer that treats hidden items as a separate view."""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

from .explorer import FileExplorer
from .hidden import HiddenFiles


class HiddenFileExplorer(FileExplorer):
    """Extended FileExplorer with first-class hidden-file navigation."""

    def __init__(self, base_path: str | Path = "", show_hidden: bool = False) -> None:
        super().__init__(base_path)
        self.hidden = HiddenFiles(self.base_path)
        self.show_hidden = bool(show_hidden)

    def set_show_hidden(self, enabled: bool = True) -> bool:
        """Enable or disable hidden items in normal listings."""
        self.show_hidden = bool(enabled)
        return self.show_hidden

    def toggle_hidden(self) -> bool:
        """Toggle visibility of hidden items and return the new state."""
        self.show_hidden = not self.show_hidden
        return self.show_hidden

    def list(self, path: str | Path = "") -> list[Path]:
        """List the workspace, optionally including hidden items."""
        if self.show_hidden:
            target = self._path(path) if path else self.base_path
            return sorted(target.iterdir(), key=lambda p: p.name.lower())
        return super().list(path)

    def list_hidden(self, path: str | Path = "", recursive: bool = False) -> list[Path]:
        return self.hidden.list_hidden(path, recursive=recursive)

    def list_visible(self, path: str | Path = "", recursive: bool = False) -> list[Path]:
        return self.hidden.list_visible(path, recursive=recursive)

    def hide(self, path: str | Path) -> Path:
        return self.hidden.hide(path)

    def unhide(self, path: str | Path) -> Path:
        return self.hidden.unhide(path)

    def reveal(self, path: str | Path) -> Path:
        return self.hidden.reveal(path)

    def create_hidden_file(self, name: str, contents: str = "") -> Path:
        return self.hidden.create_hidden_file(name, contents)

    def create_hidden_folder(self, name: str) -> Path:
        return self.hidden.create_hidden_folder(name)

    def hidden_count(self, path: str | Path = "") -> int:
        return self.hidden.hidden_count(path)

    def hidden_information(self, path: str | Path) -> dict[str, object]:
        return self.hidden.hidden_information(path)

    def walk(self, path: str | Path = "") -> Iterator[tuple[Path, list[Path], list[Path]]]:
        """Walk the workspace while respecting show_hidden."""
        root = self._path(path) if path else self.base_path
        if self.show_hidden:
            for current, dirs, files in __import__("os").walk(root):
                current_path = Path(current)
                yield current_path, [current_path / d for d in dirs], [current_path / f for f in files]
            return
        yield from super().walk(path)
