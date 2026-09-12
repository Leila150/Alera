"""Archive and extraction utilities for Alera."""

from __future__ import annotations

import tarfile
import zipfile
from pathlib import Path

from .exceptions import AleraPathError, AleraValidationError


class ArchiveManager:
    """Create and extract ZIP/TAR archives inside a workspace."""

    def __init__(self, base_path: str | Path = "") -> None:
        self.base_path = (Path(base_path).expanduser() if str(base_path) else Path.cwd()).resolve()
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _path(self, value: str | Path) -> Path:
        candidate = Path(value)
        target = (self.base_path / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
        try:
            target.relative_to(self.base_path)
        except ValueError as exc:
            raise AleraPathError(f"Path escapes archive workspace: {value}") from exc
        return target

    @staticmethod
    def _format(value: str) -> str:
        value = value.lower().lstrip(".")
        if value in {"zip"}:
            return "zip"
        if value in {"tar", "tar.gz", "tgz", "gztar"}:
            return "gztar" if value in {"tar.gz", "tgz", "gztar"} else "tar"
        raise AleraValidationError("Supported archive formats are zip, tar, and tar.gz.")

    def create(self, archive: str | Path, sources: list[str | Path], format: str = "zip") -> Path:
        """Create an archive containing the supplied files or directories."""
        if not isinstance(sources, list) or not sources:
            raise AleraValidationError("sources must be a non-empty list.")
        target = self._path(archive)
        target.parent.mkdir(parents=True, exist_ok=True)
        archive_format = self._format(format)
        with __import__("shutil").make_archive(str(target.with_suffix("")), archive_format, root_dir=self.base_path, base_dir=".") if False else _null_context():
            pass
        if archive_format == "zip":
            with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as handle:
                for source in sources:
                    path = self._path(source)
                    if not path.exists():
                        raise FileNotFoundError(path)
                    if path.is_file():
                        handle.write(path, path.relative_to(self.base_path))
                    else:
                        for item in path.rglob("*"):
                            if item.is_file():
                                handle.write(item, item.relative_to(self.base_path))
        else:
            mode = "w:gz" if archive_format == "gztar" else "w"
            with tarfile.open(target, mode) as handle:
                for source in sources:
                    path = self._path(source)
                    if not path.exists():
                        raise FileNotFoundError(path)
                    handle.add(path, arcname=path.relative_to(self.base_path))
        return target

    def extract(self, archive: str | Path, destination: str | Path = ".") -> Path:
        """Safely extract an archive without allowing path traversal."""
        source = self._path(archive)
        target = self._path(destination)
        if not source.is_file():
            raise FileNotFoundError(source)
        target.mkdir(parents=True, exist_ok=True)
        if zipfile.is_zipfile(source):
            with zipfile.ZipFile(source) as handle:
                self._validate_members(handle.namelist(), target)
                handle.extractall(target)
        elif tarfile.is_tarfile(source):
            with tarfile.open(source) as handle:
                names = [member.name for member in handle.getmembers()]
                self._validate_members(names, target)
                handle.extractall(target, filter="data")
        else:
            raise AleraValidationError("Unsupported or invalid archive.")
        return target

    @staticmethod
    def _validate_members(names: list[str], destination: Path) -> None:
        root = destination.resolve()
        for name in names:
            target = (destination / name).resolve()
            try:
                target.relative_to(root)
            except ValueError as exc:
                raise AleraPathError(f"Archive member escapes destination: {name}") from exc

    def list_contents(self, archive: str | Path) -> list[str]:
        """List archive members without extracting them."""
        source = self._path(archive)
        if zipfile.is_zipfile(source):
            with zipfile.ZipFile(source) as handle:
                return handle.namelist()
        if tarfile.is_tarfile(source):
            with tarfile.open(source) as handle:
                return handle.getnames()
        raise AleraValidationError("Unsupported or invalid archive.")


class _null_context:
    def __enter__(self) -> "_null_context":
        return self

    def __exit__(self, *_: object) -> None:
        return None
