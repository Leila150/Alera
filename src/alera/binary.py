"""Maximum binary operations for Alera's unified FileExplorer.

BinaryFileManager remains as a compatibility class, while every binary-only
operation is also attached to FileExplorer so Alera has one core explorer API.
"""
from __future__ import annotations

import base64
import bz2
import gzip
import hashlib
import lzma
import math
import mmap
import os
import struct
import tempfile
import zlib
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import BinaryIO

from .exceptions import AleraValidationError
from .explorer import FileExplorer


class BinaryFileManager(FileExplorer):
    """Compatibility facade exposing FileExplorer plus maximum binary tools."""

    BINARY_CHUNK_SIZE = 1024 * 1024

    def _binary_path(self, path):
        target = self._path(path)
        if target.exists() and target.is_dir():
            raise IsADirectoryError(target)
        return target

    @staticmethod
    def _bytes(value) -> bytes:
        if not isinstance(value, (bytes, bytearray, memoryview)):
            raise AleraValidationError("value must be bytes-like")
        return bytes(value)

    def binary_open(self, path, mode="rb", **kwargs) -> BinaryIO:
        if "b" not in mode: raise AleraValidationError("binary_open requires binary mode")
        return self._binary_path(path).open(mode, **kwargs)

    def binary_read(self, path, *, offset=0, length=None) -> bytes:
        if offset < 0 or (length is not None and length < 0): raise AleraValidationError("offset and length must be non-negative")
        with self.binary_open(path, "rb") as f:
            f.seek(offset); return f.read() if length is None else f.read(length)

    def binary_read_chunks(self, path, chunk_size=BINARY_CHUNK_SIZE, *, offset=0, length=None) -> Iterator[bytes]:
        self._validate_chunk_size(chunk_size)
        if offset < 0 or (length is not None and length < 0): raise AleraValidationError("offset and length must be non-negative")
        remaining = length
        with self.binary_open(path, "rb") as f:
            f.seek(offset)
            while True:
                amount = chunk_size if remaining is None else min(chunk_size, remaining)
                if amount <= 0: return
                chunk = f.read(amount)
                if not chunk: return
                yield chunk
                if remaining is not None:
                    remaining -= len(chunk)
                    if remaining <= 0: return

    def binary_write(self, path, data, *, offset=None, atomic=False) -> Path:
        data = self._bytes(data); target = self._binary_path(path); target.parent.mkdir(parents=True, exist_ok=True)
        if offset is not None and offset < 0: raise AleraValidationError("offset must be non-negative")
        if atomic and offset is not None: raise AleraValidationError("atomic offset writes are not supported")
        if atomic:
            fd, temp = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
            try:
                with os.fdopen(fd, "wb") as f: f.write(data); f.flush(); os.fsync(f.fileno())
                os.replace(temp, target)
            finally:
                try: os.unlink(temp)
                except FileNotFoundError: pass
            return target
        with target.open("wb" if offset is None else "r+b") as f:
            if offset is not None: f.seek(offset)
            f.write(data); f.flush()
        return target

    def binary_append(self, path, data) -> Path:
        target = self._binary_path(path); target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("ab") as f: f.write(self._bytes(data)); f.flush()
        return target

    def binary_write_chunks(self, path, chunks: Iterable[bytes], *, atomic=False, append=False) -> Path:
        target = self._binary_path(path); target.parent.mkdir(parents=True, exist_ok=True)
        if atomic and append: raise AleraValidationError("atomic and append cannot be combined")
        temp = None
        if atomic:
            fd, temp = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent); stream = os.fdopen(fd, "wb")
        else: stream = target.open("ab" if append else "wb")
        try:
            with stream as f:
                for chunk in chunks: f.write(self._bytes(chunk))
                f.flush(); os.fsync(f.fileno())
            if atomic: os.replace(temp, target); temp = None
            return target
        finally:
            if temp:
                try: os.unlink(temp)
                except FileNotFoundError: pass

    def binary_copy(self, source, destination, *, chunk_size=BINARY_CHUNK_SIZE, overwrite=False, preserve_metadata=True) -> Path:
        self._validate_chunk_size(chunk_size); src, dst = self._binary_path(source), self._binary_path(destination)
        if not src.is_file(): raise FileNotFoundError(src)
        if src == dst: raise AleraValidationError("source and destination are identical")
        if dst.exists() and not overwrite: raise FileExistsError(dst)
        dst.parent.mkdir(parents=True, exist_ok=True)
        with src.open("rb") as inp, dst.open("wb") as out:
            for chunk in iter(lambda: inp.read(chunk_size), b""): out.write(chunk)
            out.flush(); os.fsync(out.fileno())
        if preserve_metadata:
            import shutil; shutil.copystat(src, dst, follow_symlinks=False)
        return dst

    def binary_compare(self, left, right, *, chunk_size=BINARY_CHUNK_SIZE) -> bool:
        self._validate_chunk_size(chunk_size); a, b = self._binary_path(left), self._binary_path(right)
        if a.stat().st_size != b.stat().st_size: return False
        with a.open("rb") as x, b.open("rb") as y:
            while True:
                ax, by = x.read(chunk_size), y.read(chunk_size)
                if ax != by: return False
                if not ax: return True

    def binary_compare_range(self, left, right, *, offset=0, length=None, chunk_size=BINARY_CHUNK_SIZE) -> bool:
        a, b = self.binary_read_chunks(left, chunk_size, offset=offset, length=length), self.binary_read_chunks(right, chunk_size, offset=offset, length=length); end = object()
        while True:
            x, y = next(a, end), next(b, end)
            if x is end or y is end: return x is y
            if x != y: return False

    def binary_hash(self, path, algorithm="sha256", *, chunk_size=BINARY_CHUNK_SIZE) -> str:
        self._validate_chunk_size(chunk_size)
        try: digest = hashlib.new(algorithm)
        except ValueError as exc: raise AleraValidationError(f"Unsupported hash algorithm: {algorithm}") from exc
        for chunk in self.binary_read_chunks(path, chunk_size): digest.update(chunk)
        return digest.hexdigest()

    def binary_hashes(self, path, algorithms=("md5", "sha1", "sha256", "sha512"), *, chunk_size=BINARY_CHUNK_SIZE) -> dict[str, str]:
        try: digests = {name: hashlib.new(name) for name in dict.fromkeys(algorithms)}
        except ValueError as exc: raise AleraValidationError("Unsupported hash algorithm") from exc
        for chunk in self.binary_read_chunks(path, chunk_size):
            for digest in digests.values(): digest.update(chunk)
        return {name: digest.hexdigest() for name, digest in digests.items()}

    def binary_crc32(self, path, *, chunk_size=BINARY_CHUNK_SIZE) -> int:
        value = 0
        for chunk in self.binary_read_chunks(path, chunk_size): value = zlib.crc32(chunk, value)
        return value & 0xffffffff

    def binary_adler32(self, path, *, chunk_size=BINARY_CHUNK_SIZE) -> int:
        value = 1
        for chunk in self.binary_read_chunks(path, chunk_size): value = zlib.adler32(chunk, value)
        return value & 0xffffffff

    def binary_frequency(self, path, *, chunk_size=BINARY_CHUNK_SIZE) -> list[int]:
        counts = [0] * 256
        for chunk in self.binary_read_chunks(path, chunk_size):
            for byte in chunk: counts[byte] += 1
        return counts

    def binary_entropy(self, path, *, chunk_size=BINARY_CHUNK_SIZE) -> float:
        counts = self.binary_frequency(path, chunk_size=chunk_size); total = sum(counts)
        return -sum((n/total) * math.log2(n/total) for n in counts if n) if total else 0.0

    def binary_statistics(self, path, *, chunk_size=BINARY_CHUNK_SIZE) -> dict[str, object]:
        counts = self.binary_frequency(path, chunk_size=chunk_size); total = sum(counts); zero = counts[0]; printable = sum(counts[32:127])
        return {"size": total, "entropy": self.binary_entropy(path, chunk_size=chunk_size), "unique_bytes": sum(bool(n) for n in counts), "zero_bytes": zero, "zero_ratio": zero/total if total else 0.0, "printable_bytes": printable, "printable_ratio": printable/total if total else 0.0, "byte_frequency": counts}

    def binary_find(self, path, needle, *, start=0, chunk_size=BINARY_CHUNK_SIZE, max_results=None) -> list[int]:
        needle = self._bytes(needle)
        if not needle: raise AleraValidationError("needle must not be empty")
        overlap = len(needle)-1; carry = b""; position = start; results = []
        for chunk in self.binary_read_chunks(path, chunk_size, offset=start):
            data = carry + chunk; base = position-len(carry); cursor = 0
            while True:
                index = data.find(needle, cursor)
                if index < 0: break
                results.append(base+index)
                if max_results is not None and len(results) >= max_results: return results
                cursor = index+1
            carry = data[-overlap:] if overlap else b""; position += len(chunk)
        return results

    def binary_replace(self, path, old, new, *, count=-1, atomic=True, chunk_size=BINARY_CHUNK_SIZE) -> int:
        old, new = self._bytes(old), self._bytes(new)
        if not old: raise AleraValidationError("old must not be empty")
        self._validate_chunk_size(chunk_size); target = self._binary_path(path); fd, temp = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent); changed = 0; carry = b""
        try:
            with os.fdopen(fd, "wb") as out:
                for chunk in self.binary_read_chunks(target, chunk_size):
                    data = carry + chunk; safe = max(0, len(data)-len(old)+1); head, carry = data[:safe], data[safe:]
                    limit = -1 if count < 0 else max(0, count-changed); before = head.count(old)
                    out.write(head.replace(old, new, limit)); changed += before if limit < 0 else min(before, limit)
                limit = -1 if count < 0 else max(0, count-changed); before = carry.count(old); out.write(carry.replace(old, new, limit)); changed += before if limit < 0 else min(before, limit)
                out.flush(); os.fsync(out.fileno())
            os.replace(temp, target); temp = None; return changed
        finally:
            if temp:
                try: os.unlink(temp)
                except FileNotFoundError: pass

    def binary_slice(self, source, destination, start, end=None, *, chunk_size=BINARY_CHUNK_SIZE) -> Path:
        if start < 0 or (end is not None and end < start): raise AleraValidationError("invalid slice")
        return self.binary_write_chunks(destination, self.binary_read_chunks(source, chunk_size, offset=start, length=None if end is None else end-start), atomic=True)

    def binary_split(self, source, output_directory, *, chunk_size=BINARY_CHUNK_SIZE, prefix=None, digits=6) -> list[Path]:
        self._validate_chunk_size(chunk_size); src = self._binary_path(source); out = self._path(output_directory); out.mkdir(parents=True, exist_ok=True); prefix = prefix or src.name; result = []
        with src.open("rb") as f:
            index = 0
            while chunk := f.read(chunk_size):
                part = out / f"{prefix}.part{index:0{digits}d}"; part.write_bytes(chunk); result.append(part); index += 1
        return result

    def binary_join(self, parts, destination, *, chunk_size=BINARY_CHUNK_SIZE, atomic=True) -> Path:
        return self.binary_write_chunks(destination, (chunk for part in parts for chunk in self.binary_read_chunks(part, chunk_size)), atomic=atomic)

    def binary_hexdump(self, path, *, offset=0, length=256, width=16) -> str:
        data = self.binary_read(path, offset=offset, length=length); lines = []
        for index in range(0, len(data), width):
            chunk = data[index:index+width]; hx = " ".join(f"{b:02x}" for b in chunk); text = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk); lines.append(f"{offset+index:08x}  {hx:<{width*3-1}}  |{text}|")
        return "\n".join(lines)

    def binary_mmap(self, path, *, access=mmap.ACCESS_READ):
        handle = self.binary_open(path, "rb")
        try: return mmap.mmap(handle.fileno(), 0, access=access)
        except Exception: handle.close(); raise

    def binary_read_struct(self, path, offset, fmt, *, endian="native"):
        prefix = {"little":"<", "big":">", "native":"=", "":"="}.get(endian)
        if prefix is None: raise AleraValidationError("invalid endian")
        size = struct.calcsize(prefix+fmt); data = self.binary_read(path, offset=offset, length=size)
        if len(data) != size: raise EOFError("not enough bytes")
        return struct.unpack(prefix+fmt, data)

    def binary_write_struct(self, path, offset, fmt, values, *, endian="native") -> Path:
        prefix = {"little":"<", "big":">", "native":"=", "":"="}.get(endian)
        if prefix is None: raise AleraValidationError("invalid endian")
        return self.binary_write(path, struct.pack(prefix+fmt, *(values if isinstance(values, tuple) else (values,))), offset=offset)

    def binary_to_base64(self, path) -> str: return base64.b64encode(self.binary_read(path)).decode("ascii")
    def binary_from_base64(self, value, destination) -> Path:
        try: return self.binary_write(destination, base64.b64decode(value, validate=True), atomic=True)
        except Exception as exc: raise AleraValidationError("invalid Base64") from exc
    def binary_to_hex(self, path) -> str: return self.binary_read(path).hex()
    def binary_from_hex(self, value, destination) -> Path:
        try: return self.binary_write(destination, bytes.fromhex(value), atomic=True)
        except ValueError as exc: raise AleraValidationError("invalid hexadecimal data") from exc

    def binary_compress(self, source, destination, *, algorithm="gzip", level=6, chunk_size=BINARY_CHUNK_SIZE) -> Path:
        src, dst = self._binary_path(source), self._binary_path(destination); dst.parent.mkdir(parents=True, exist_ok=True); algorithm = algorithm.lower()
        if algorithm not in {"gzip", "bz2", "lzma"}: raise AleraValidationError("algorithm must be gzip, bz2, or lzma")
        opener = {"gzip":gzip.open, "bz2":bz2.open, "lzma":lzma.open}[algorithm]; kwargs = {"compresslevel":level} if algorithm != "lzma" else {"preset":level}
        with src.open("rb") as inp, opener(dst, "wb", **kwargs) as out:
            for chunk in iter(lambda: inp.read(chunk_size), b""): out.write(chunk)
        return dst

    def binary_decompress(self, source, destination, *, algorithm="gzip", chunk_size=BINARY_CHUNK_SIZE) -> Path:
        src, dst = self._binary_path(source), self._binary_path(destination); dst.parent.mkdir(parents=True, exist_ok=True); algorithm = algorithm.lower()
        if algorithm not in {"gzip", "bz2", "lzma"}: raise AleraValidationError("algorithm must be gzip, bz2, or lzma")
        with {"gzip":gzip.open, "bz2":bz2.open, "lzma":lzma.open}[algorithm](src, "rb") as inp, dst.open("wb") as out:
            for chunk in iter(lambda: inp.read(chunk_size), b""): out.write(chunk)
        return dst

    def binary_sparse(self, path, size, *, offset=0) -> Path:
        if size < 0 or offset < 0: raise AleraValidationError("size and offset must be non-negative")
        target = self._binary_path(path); target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("wb") as f:
            if size: f.seek(offset+size-1); f.write(b"\0")
        return target

    def binary_signature(self, path, *, length=64) -> dict[str, object]:
        data = self.binary_read(path, length=length); signatures = {b"\x7fELF":"ELF",b"MZ":"PE/Windows executable",b"PK\x03\x04":"ZIP/container",b"\x89PNG\r\n\x1a\n":"PNG",b"%PDF":"PDF",b"\xff\xd8\xff":"JPEG",b"GIF87a":"GIF",b"GIF89a":"GIF",b"SQLite format 3\x00":"SQLite",b"\x1f\x8b":"GZIP",b"BZh":"BZIP2",b"\xfd7zXZ\x00":"XZ"}
        return {"type": next((name for magic,name in signatures.items() if data.startswith(magic)), "unknown"), "magic":data[:16].hex(), "size":self.size(path)}

    def binary_files(self, path=None, *, recursive=True, include_hidden=False, extensions=None, min_size=None, max_size=None) -> list[Path]:
        allowed = None if extensions is None else {"."+str(e).lower().lstrip(".") for e in extensions}; result=[]
        for item in self.list_files(path, recursive=recursive, include_hidden=include_hidden):
            size=self._safe_stat_size(item)
            if allowed is not None and item.suffix.lower() not in allowed: continue
            if min_size is not None and size < min_size: continue
            if max_size is not None and size > max_size: continue
            result.append(item)
        return result

    def binary_folders(self, path=None, *, recursive=True, include_hidden=False, min_files=1) -> list[Path]:
        result=[]
        for folder in self.list_folders(path, recursive=recursive, include_hidden=include_hidden):
            try: count=sum(1 for e in os.scandir(folder) if e.is_file(follow_symlinks=False))
            except OSError: continue
            if count >= min_files: result.append(folder)
        return result

    def binary_folder_information(self, path=None, *, recursive=True, include_hidden=False) -> dict[str, object]:
        root=self._path(path); files=self.binary_files(root,recursive=recursive,include_hidden=include_hidden); sizes=[self._safe_stat_size(p) for p in files]
        return {"path":str(root),"files":len(files),"folders":len(self.binary_folders(root,recursive=recursive,include_hidden=include_hidden,min_files=0)),"bytes":sum(sizes),"largest":max(sizes,default=0),"smallest":min(sizes,default=0),"average":sum(sizes)/len(sizes) if sizes else 0,"extensions":self.extensions(root,include_hidden=include_hidden)}

    def binary_folder_hash(self, path=None, algorithm="sha256", *, recursive=True, include_hidden=False) -> str:
        root=self._path(path); digest=hashlib.new(algorithm)
        for file in sorted(self.binary_files(root,recursive=recursive,include_hidden=include_hidden),key=lambda p:p.relative_to(root).as_posix()):
            digest.update(file.relative_to(root).as_posix().encode()+b"\0")
            for chunk in self.binary_read_chunks(file): digest.update(chunk)
        return digest.hexdigest()

    def binary_folder_statistics(self, path=None, *, recursive=True, include_hidden=False) -> dict[str,object]:
        files=self.binary_files(path,recursive=recursive,include_hidden=include_hidden); total=sum(self._safe_stat_size(p) for p in files); weighted=sum(self.binary_entropy(p)*self._safe_stat_size(p) for p in files)
        return {"files":len(files),"bytes":total,"weighted_entropy":weighted/total if total else 0.0,"zero_bytes":sum(self.binary_statistics(p)["zero_bytes"] for p in files)}

    def binary_folder_replace(self, path, old, new, *, count=-1, recursive=True, include_hidden=False) -> dict[str,object]:
        changed=[]; replacements=0
        for file in self.binary_files(path,recursive=recursive,include_hidden=include_hidden):
            n=self.binary_replace(file,old,new,count=count)
            if n: changed.append(file); replacements+=n
        return {"files_changed":changed,"replacements":replacements}

    def binary_folder_hashes(self, path=None, algorithm="sha256", *, recursive=True, include_hidden=False) -> dict[str,str]:
        root=self._path(path); return {str(p.relative_to(root)):self.binary_hash(p,algorithm) for p in self.binary_files(root,recursive=recursive,include_hidden=include_hidden)}

    def binary_duplicate_groups(self, path=None, *, recursive=True, include_hidden=False, minimum_size=1) -> list[list[Path]]:
        groups={}
        for file in self.binary_files(path,recursive=recursive,include_hidden=include_hidden,min_size=minimum_size): groups.setdefault((self._safe_stat_size(file),self.binary_hash(file)),[]).append(file)
        return [v for v in groups.values() if len(v)>1]

    def binary_snapshot(self, path=None, *, recursive=True, include_hidden=False, hashes=True) -> dict[str,dict[str,object]]:
        root=self._path(path); result={}
        for file in self.binary_files(root,recursive=recursive,include_hidden=include_hidden):
            info=file.stat(); result[str(file.relative_to(root))]={"size":info.st_size,"mtime_ns":info.st_mtime_ns,"sha256":self.binary_hash(file) if hashes else None}
        return result

    def binary_tree(self, path=None, *, include_hidden=False, show_sizes=True) -> str: return self.tree(path,include_hidden=include_hidden,show_sizes=show_sizes)

    def binary_copy_folder(self, source, destination, *, recursive=True, include_hidden=False, overwrite=False, chunk_size=BINARY_CHUNK_SIZE) -> Path:
        src=self._path(source); dst=self._path(destination,allow_root=False); dst.mkdir(parents=True,exist_ok=True)
        for file in self.binary_files(src,recursive=recursive,include_hidden=include_hidden): self.binary_copy(file,dst/file.relative_to(src),chunk_size=chunk_size,overwrite=overwrite)
        return dst

    def binary_verify_folder(self, path, manifest, *, algorithm="sha256") -> dict[str,list[str]]:
        current=self.binary_folder_hashes(path,algorithm=algorithm); expected={str(k):str(v) for k,v in manifest.items()}
        return {"added":sorted(set(current)-set(expected)),"removed":sorted(set(expected)-set(current)),"modified":sorted(k for k in set(current)&set(expected) if current[k]!=expected[k])}

    def binary_apply_xor(self, source, destination, key, *, chunk_size=BINARY_CHUNK_SIZE) -> Path:
        key=self._bytes(key)
        if not key: raise AleraValidationError("key must not be empty")
        def chunks():
            position=0
            for chunk in self.binary_read_chunks(source,chunk_size):
                yield bytes(byte^key[(position+i)%len(key)] for i,byte in enumerate(chunk)); position+=len(chunk)
        return self.binary_write_chunks(destination,chunks(),atomic=True)

    def binary_patch(self, source, destination, *, chunk_size=BINARY_CHUNK_SIZE) -> Path:
        if self.size(source)!=self.size(destination): raise AleraValidationError("patch requires equal-sized files")
        fd,temp=tempfile.mkstemp(prefix=".alera-patch-"); os.close(fd); patch=Path(temp)
        with patch.open("wb") as out:
            out.write(b"ALERAP1\0")
            for a,b in zip(self.binary_read_chunks(source,chunk_size),self.binary_read_chunks(destination,chunk_size)): out.write(bytes(x^y for x,y in zip(a,b)))
        return patch

    def binary_apply_patch(self, source, patch, destination, *, chunk_size=BINARY_CHUNK_SIZE) -> Path:
        patch=Path(patch)
        with patch.open("rb") as p:
            if p.read(8)!=b"ALERAP1\0": raise AleraValidationError("invalid Alera binary patch")
            chunks=[]
            for original in self.binary_read_chunks(source,chunk_size):
                delta=p.read(len(original))
                if len(delta)!=len(original): raise AleraValidationError("truncated patch")
                chunks.append(bytes(a^b for a,b in zip(original,delta)))
            if p.read(1): raise AleraValidationError("patch contains extra data")
        return self.binary_write_chunks(destination,chunks,atomic=True)


# Merge the binary API into the core explorer. Existing FileExplorer methods
# are deliberately never overwritten.
for _name, _method in BinaryFileManager.__dict__.items():
    if _name.startswith("_") or _name == "BINARY_CHUNK_SIZE": continue
    if callable(_method) and not hasattr(FileExplorer, _name): setattr(FileExplorer, _name, _method)
FileExplorer.binary = property(lambda self: self)
