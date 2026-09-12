"""Symbolic-link utilities."""
from __future__ import annotations

import os
from pathlib import Path


class LinkManager:
    """Create and inspect symbolic links safely inside a workspace."""

    def __init__(self, base_path: str | Path = "") -> None:
        self.base_path = (Path(base_path).expanduser() if str(base_path) else Path.cwd()).resolve()
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _path(self, value: str | Path) -> Path:
        p = (self.base_path / value).resolve(strict=False) if not Path(value).is_absolute() else Path(value)
        p.absolute()
        if not p.parent.resolve().is_relative_to(self.base_path):
            raise ValueError("Link path escapes workspace")
        return p

    def create(self, link: str | Path, target: str | Path, *, relative: bool = True) -> Path:
        link_path = self._path(link)
        target_path = self._path(target)
        link_path.parent.mkdir(parents=True, exist_ok=True)
        target_value = os.path.relpath(target_path, link_path.parent) if relative else str(target_path)
        link_path.symlink_to(target_value, target_is_directory=target_path.is_dir())
        return link_path

    def is_link(self, value: str | Path) -> bool:
        return self._path(value).is_symlink()

    def target(self, value: str | Path) -> Path:
        return self._path(value).readlink()

    def resolve(self, value: str | Path) -> Path:
        return self._path(value).resolve()

    def remove(self, value: str | Path) -> None:
        p = self._path(value)
        if not p.is_symlink():
            raise ValueError("Path is not a symbolic link")
        p.unlink()
