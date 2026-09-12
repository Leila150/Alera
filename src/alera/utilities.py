"""Small reusable file transformations."""

from __future__ import annotations

from pathlib import Path


class FileUtilities:
    def __init__(self, base_path: str | Path = "") -> None:
        self.base = Path(base_path or ".").expanduser().resolve()
        self.base.mkdir(parents=True, exist_ok=True)

    def _path(self, path: str | Path) -> Path:
        target = (self.base / path).resolve()
        target.relative_to(self.base)
        return target

    def touch(self, path: str | Path) -> Path:
        target = self._path(path); target.parent.mkdir(parents=True, exist_ok=True); target.touch(exist_ok=True); return target
    def truncate(self, path: str | Path, size: int = 0) -> Path:
        target = self._path(path); target.open("r+b").truncate(size); return target
    def swap(self, first: str | Path, second: str | Path) -> None:
        a, b = self._path(first), self._path(second)
        temporary = a.with_name(f".{a.name}.alera-swap")
        a.rename(temporary); b.rename(a); temporary.rename(b)
    def prepend(self, path: str | Path, text: str, encoding: str = "utf-8") -> Path:
        target = self._path(path); target.write_text(text + target.read_text(encoding=encoding), encoding=encoding); return target
    def replace_bytes(self, path: str | Path, old: bytes, new: bytes) -> int:
        target = self._path(path); data = target.read_bytes(); count = data.count(old); target.write_bytes(data.replace(old, new)); return count
    def split(self, path: str | Path, chunk_size: int) -> list[Path]:
        if chunk_size <= 0: raise ValueError("chunk_size must be positive")
        target = self._path(path); result=[]
        with target.open("rb") as handle:
            index=0
            while chunk := handle.read(chunk_size):
                part = target.with_name(f"{target.name}.part{index:04d}"); part.write_bytes(chunk); result.append(part); index += 1
        return result
    def join(self, parts: list[str | Path], destination: str | Path) -> Path:
        target = self._path(destination); target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("wb") as output:
            for part in parts: output.write(self._path(part).read_bytes())
        return target
    def deduplicate_lines(self, path: str | Path, encoding: str = "utf-8") -> int:
        target = self._path(path); lines = target.read_text(encoding=encoding).splitlines(keepends=True); unique=list(dict.fromkeys(lines)); target.write_text("".join(unique), encoding=encoding); return len(lines)-len(unique)
    def convert_encoding(self, path: str | Path, source: str, destination_encoding: str) -> Path:
        target=self._path(path); target.write_text(target.read_text(encoding=source), encoding=destination_encoding); return target
