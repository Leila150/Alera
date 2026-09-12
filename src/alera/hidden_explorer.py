"""Cross-platform hidden-aware filesystem explorer."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator

from .explorer import FileExplorer
from .hidden import HiddenFiles


class HiddenFileExplorer(FileExplorer):
    """FileExplorer with real Android shared-storage hidden support.

    On Android, hidden objects may no longer physically exist at their public
    path because they are stored under Alera's randomized shared-storage
    directory. This explorer therefore treats hidden paths as virtual paths
    and exposes them alongside normal files without leaking the randomized
    storage names.
    """

    def __init__(self, base_path: str | Path = "", show_hidden: bool = False) -> None:
        super().__init__(base_path)
        self.hidden = HiddenFiles(self.base_path)
        self.show_hidden = bool(show_hidden)
        self.current_path = self.base_path

    @property
    def platform(self) -> str:
        return self.hidden.platform

    @property
    def mobile(self) -> bool:
        return self.hidden.mobile

    @property
    def desktop(self) -> bool:
        return self.hidden.desktop

    def _current(self, path: str | Path = "") -> Path:
        return self.current_path if path == "" else self._path(path)

    def _android_record(self, path: Path) -> dict[str, object] | None:
        if not self.mobile:
            return None
        return self.hidden._android_record_for(path)

    def _physical(self, path: Path) -> Path:
        """Resolve an Android virtual hidden path to its physical path."""
        if not self.mobile:
            return path
        record = self._android_record(path)
        if record:
            return Path(str(record["stored"]))

        hidden = self.hidden.list_hidden(self.base_path, recursive=True)
        best: tuple[Path, dict[str, object]] | None = None
        for original in hidden:
            try:
                relative = path.relative_to(original)
            except ValueError:
                continue
            record = self._android_record(original)
            if record and (best is None or len(original.parts) > len(best[0].parts)):
                best = (original, record)
        if best is None:
            return path
        return Path(str(best[1]["stored"])) / path.relative_to(best[0])

    def _virtual_children(self, path: Path) -> list[Path]:
        physical = self._physical(path)
        if not physical.is_dir():
            return []
        return sorted(
            (path / item.name for item in physical.iterdir()),
            key=lambda p: p.name.lower(),
        )

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
        target = self._path(path)
        if target == self._bin_path or self._bin_path in target.parents:
            raise PermissionError("the Alera recycle bin is not browsable")
        physical = self._physical(target)
        if not physical.is_dir():
            raise NotADirectoryError(target)
        if not self.show_hidden and self.hidden.is_hidden(target):
            raise PermissionError("hidden directory is not visible")
        self.current_path = target
        return target

    def cd(self, path: str | Path) -> Path:
        return self.enter(path)

    def up(self) -> Path:
        if self.current_path != self.base_path:
            self.current_path = self.current_path.parent
        return self.current_path

    def home(self) -> Path:
        self.current_path = self.base_path
        return self.current_path

    def pwd(self) -> Path:
        return self.current_path

    def list(self, path: str | Path = "") -> list[Path]:
        target = self._current(path)
        if target == self._bin_path or self._bin_path in target.parents:
            raise PermissionError("the Alera recycle bin is not browsable")
        visible = self.hidden.list_visible(target)
        if not self.show_hidden:
            return visible
        hidden = self.hidden.list_hidden(target)
        if self.mobile and self.hidden.is_hidden(target):
            hidden = self._virtual_children(target)
        return sorted(set(visible + hidden), key=lambda p: p.name.lower())

    def list_all(self, path: str | Path = "") -> list[Path]:
        target = self._current(path)
        return self.list(target) if self.show_hidden else self.hidden.list_visible(target)

    def list_hidden(self, path: str | Path = "", recursive: bool = False) -> list[Path]:
        return [
            p for p in self.hidden.list_hidden(path, recursive)
            if p != self._bin_path and self._bin_path not in p.parents
        ]

    def list_visible(self, path: str | Path = "", recursive: bool = False) -> list[Path]:
        return self.hidden.list_visible(path, recursive)

    def hidden_files(self, path: str | Path = "", recursive: bool = False) -> list[Path]:
        return self.hidden.hidden_files(path, recursive)

    def hidden_folders(self, path: str | Path = "", recursive: bool = False) -> list[Path]:
        return self.hidden.hidden_folders(path, recursive)

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

    def hide_all(self, path: str | Path = "", recursive: bool = False) -> list[Path]:
        return self.hidden.hide_all(path or self.current_path, recursive)

    def unhide_all(self, path: str | Path = "", recursive: bool = False) -> list[Path]:
        return self.hidden.unhide_all(path or self.current_path, recursive)

    def hidden_count(self, path: str | Path = "") -> int:
        return len(self.list_hidden(path))

    def hidden_information(self, path: str | Path) -> dict[str, object]:
        return self.hidden.hidden_information(path)

    def hidden_tree(self, path: str | Path = "") -> str:
        root = self._current(path)
        lines = [root.name or str(root)]
        for item in self.list_hidden(root, recursive=True):
            try:
                relative = item.relative_to(root)
            except ValueError:
                continue
            lines.append("  " * len(relative.parts) + relative.name)
        return "\n".join(lines)

    def walk(self, path: str | Path = "") -> Iterator[tuple[Path, list[Path], list[Path]]]:
        root = self._current(path)
        if self.mobile and self.hidden.is_hidden(root):
            physical = self._physical(root)
            for current, dirs, files in os.walk(physical):
                current_physical = Path(current)
                relative = current_physical.relative_to(physical)
                current_virtual = root / relative
                yield current_virtual, [current_virtual / d for d in dirs], [current_virtual / f for f in files]
            return

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
        candidates = self.hidden.list_hidden(self._current(), recursive=recursive)
        return sorted((p for p in candidates if p.match(pattern)), key=lambda p: str(p).lower())

    def refresh(self) -> list[Path]:
        return self.list()

    def information(self) -> dict[str, object]:
        return {
            "path": str(self.current_path),
            "platform": self.platform,
            "mobile": self.mobile,
            "desktop": self.desktop,
            "show_hidden": self.show_hidden,
            "hidden_count": self.hidden_count(),
            "storage_backend": self.hidden.storage_backend,
            "android_shared_storage": str(self.hidden.android_shared_storage) if self.mobile and self.hidden.android_shared_storage else None,
            "android_hidden_storage": str(self.hidden.android_hidden_storage) if self.mobile else None,
        }
