"""Convenient text and binary streaming helpers."""
from __future__ import annotations
from pathlib import Path
from typing import BinaryIO, Iterator, TextIO

class StreamTools:
    """Read and write very large files incrementally."""
    @staticmethod
    def read_bytes(file: str | Path, chunk_size: int = 1024 * 1024) -> Iterator[bytes]:
        if chunk_size <= 0: raise ValueError("chunk_size must be greater than zero.")
        with Path(file).expanduser().open("rb") as handle:
            while chunk := handle.read(chunk_size): yield chunk

    @staticmethod
    def read_lines(file: str | Path, encoding: str = "utf-8") -> Iterator[str]:
        with Path(file).expanduser().open("r", encoding=encoding) as handle:
            yield from handle

    @staticmethod
    def write_chunks(file: str | Path, chunks, *, append: bool = False) -> Path:
        target = Path(file).expanduser(); target.parent.mkdir(parents=True, exist_ok=True)
        mode = "ab" if append else "wb"
        with target.open(mode) as handle:
            for chunk in chunks:
                if not isinstance(chunk, (bytes, bytearray, memoryview)): raise TypeError("chunks must contain bytes-like values.")
                handle.write(bytes(chunk))
        return target

    @staticmethod
    def copy(source: str | Path, destination: str | Path, chunk_size: int = 1024 * 1024) -> Path:
        target = Path(destination).expanduser(); target.parent.mkdir(parents=True, exist_ok=True)
        with Path(source).expanduser().open("rb") as src, target.open("wb") as dst:
            while chunk := src.read(chunk_size): dst.write(chunk)
        return target
