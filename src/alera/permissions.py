"""Portable file permission helpers."""
from __future__ import annotations
import os
import stat
from pathlib import Path
from .exceptions import AleraPathError, AleraValidationError

class PermissionTools:
    """Inspect and modify POSIX-style permission bits where supported."""
    def __init__(self, base_path: str | os.PathLike[str] = "") -> None:
        self.base_path = (Path(base_path).expanduser() if str(base_path) else Path.cwd()).resolve()

    def path(self, value: str | os.PathLike[str]) -> Path:
        target = (self.base_path / value).resolve() if not Path(value).is_absolute() else Path(value).resolve()
        try: target.relative_to(self.base_path)
        except ValueError as exc: raise AleraPathError(f"Path escapes permission workspace: {value}") from exc
        return target

    def mode(self, file: str | os.PathLike[str]) -> int:
        return stat.S_IMODE(self.path(file).stat().st_mode)

    def octal(self, file: str | os.PathLike[str]) -> str:
        return format(self.mode(file), "04o")

    def readable(self, file: str | os.PathLike[str]) -> bool: return os.access(self.path(file), os.R_OK)
    def writable(self, file: str | os.PathLike[str]) -> bool: return os.access(self.path(file), os.W_OK)
    def executable(self, file: str | os.PathLike[str]) -> bool: return os.access(self.path(file), os.X_OK)

    def set_mode(self, file: str | os.PathLike[str], mode: int | str) -> Path:
        if isinstance(mode, str):
            try: mode = int(mode, 8)
            except ValueError as exc: raise AleraValidationError("mode must be an octal value.") from exc
        if not 0 <= mode <= 0o7777: raise AleraValidationError("mode must be between 0 and 0o7777.")
        target = self.path(file); os.chmod(target, mode); return target
