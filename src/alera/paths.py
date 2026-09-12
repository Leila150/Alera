"""Advanced path utilities."""
from __future__ import annotations
import os
from pathlib import Path
from .exceptions import AleraPathError

class PathTools:
    """Normalize, classify, and manipulate paths safely."""
    def __init__(self, base_path: str | os.PathLike[str] = "") -> None:
        self.base_path = (Path(base_path).expanduser() if str(base_path) else Path.cwd()).resolve()
        self.base_path.mkdir(parents=True, exist_ok=True)

    def resolve(self, value: str | os.PathLike[str]) -> Path:
        target = (self.base_path / value).resolve() if not Path(value).is_absolute() else Path(value).resolve()
        try: target.relative_to(self.base_path)
        except ValueError as exc: raise AleraPathError(f"Path escapes workspace: {value}") from exc
        return target

    def relative(self, value: str | os.PathLike[str]) -> Path: return self.resolve(value).relative_to(self.base_path)
    def absolute(self, value: str | os.PathLike[str]) -> Path: return self.resolve(value)
    def parent(self, value: str | os.PathLike[str]) -> Path: return self.resolve(value).parent
    def name(self, value: str | os.PathLike[str]) -> str: return self.resolve(value).name
    def suffix(self, value: str | os.PathLike[str]) -> str: return self.resolve(value).suffix
    def stem(self, value: str | os.PathLike[str]) -> str: return self.resolve(value).stem
    def hidden(self, value: str | os.PathLike[str]) -> bool: return self.resolve(value).name.startswith(".")
    def parts(self, value: str | os.PathLike[str]) -> tuple[str, ...]: return self.resolve(value).parts
    def same(self, first: str | os.PathLike[str], second: str | os.PathLike[str]) -> bool:
        try: return os.path.samefile(self.resolve(first), self.resolve(second))
        except FileNotFoundError: return self.resolve(first) == self.resolve(second)
