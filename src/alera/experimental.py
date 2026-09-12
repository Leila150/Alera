"""Experimental, advanced, and platform-specific Alera features."""

from __future__ import annotations

import contextlib
import hashlib
import json
import mimetypes
import os
import platform as _platform
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any, Iterator

from .hidden import HiddenFiles
from .hidden_explorer import HiddenFileExplorer


class Experimental:
    """Gateway for advanced and platform-specific Alera capabilities.

    Experimental functionality lives here so the stable FileExplorer API can
    remain small. The standard library is used wherever possible.
    """

    def __init__(self, base_path: str | Path = "") -> None:
        self.base_path = Path(base_path).expanduser() if str(base_path) else Path.cwd()
        self.base_path = self.base_path.resolve()
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.hidden = HiddenFiles(self.base_path)
        self.hidden_explorer = HiddenFileExplorer(self.base_path)
        self._safety_mode = True
        self._history_path = self.base_path / ".alera_recovery_history.json"

    @property
    def platform(self) -> str:
        return self.hidden.platform

    @property
    def android(self) -> bool:
        return self.hidden.platform == "android"

    @property
    def android_shared_storage(self) -> bool:
        return self.hidden.android_shared_storage

    @property
    def storage_backend(self) -> str:
        return self.hidden.storage_backend

    @property
    def safety_mode(self) -> bool:
        return self._safety_mode

    @safety_mode.setter
    def safety_mode(self, enabled: bool) -> None:
        self._safety_mode = bool(enabled)

    def allow_destructive_operations(self) -> None:
        """Explicitly disable the experimental safety gate for this instance."""
        self._safety_mode = False

    def require_destructive_access(self) -> None:
        if self._safety_mode:
            raise PermissionError("Destructive experimental operation blocked by safety_mode=True.")

    def features(self) -> dict[str, Any]:
        return {
            "platform": self.platform,
            "android": self.android,
            "android_shared_storage": self.android_shared_storage,
            "storage_backend": self.storage_backend,
            "android_actual_shared_storage_hiding": self.android and self.android_shared_storage,
            "hidden_files": True,
            "hidden_file_explorer": True,
            "symlinks": hasattr(os, "symlink"),
            "atomic_replace": hasattr(os, "replace"),
            "file_owner": hasattr(os.stat_result, "st_uid"),
            "mount_information": Path("/proc/mounts").exists(),
            "archives": ["zip", "tar", "tar.gz", "tar.bz2", "tar.xz"],
            "snapshots": True,
            "transactions": True,
            "incremental_backups": True,
            "storage_analysis": True,
            "recovery_history": True,
            "safety_mode": self.safety_mode,
        }

    # Android -----------------------------------------------------------
    def android_hidden_storage(self) -> Path | None:
        return self.hidden.android_hidden_storage if self.android else None

    def android_storage_roots(self) -> list[Path]:
        candidates = [os.environ.get("EXTERNAL_STORAGE"), "/storage/emulated/0", "/storage/self/primary", "/sdcard"]
        result: list[Path] = []
        for value in candidates:
            if value:
                path = Path(value).resolve()
                if path.exists() and path not in result:
                    result.append(path)
        return result

    def android_storage_information(self) -> dict[str, Any]:
        roots = self.android_storage_roots()
        info: dict[str, Any] = {
            "android": self.android,
            "shared_storage": self.android_shared_storage,
            "roots": [str(p) for p in roots],
            "hidden_storage": str(self.android_hidden_storage()) if self.android_hidden_storage() else None,
        }
        if roots:
            usage = shutil.disk_usage(roots[0])
            info.update(total=usage.total, used=usage.used, free=usage.free)
        return info

    def android_media_storage(self) -> dict[str, Path]:
        roots = self.android_storage_roots()
        if not roots:
            return {}
        root = roots[0]
        return {name: root / name for name in ("DCIM", "Pictures", "Movies", "Music", "Download", "Documents") if (root / name).exists()}

    # Hidden gateway ----------------------------------------------------
    def verify_hidden(self, path: str | Path) -> bool:
        return self.hidden.verify_hidden(path)

    def hide(self, path: str | Path) -> Path:
        return self.hidden.hide(path)

    def unhide(self, path: str | Path) -> Path:
        return self.hidden.unhide(path)

    def list_hidden(self, path: str | Path = "") -> list[Path]:
        return self.hidden.list_hidden(path)

    def hidden_information(self, path: str | Path) -> dict[str, Any]:
        return self.hidden.hidden_information(path)

    def cleanup_hidden(self) -> list[Path]:
        return self.hidden.cleanup_orphans()

    def explorer(self) -> HiddenFileExplorer:
        return self.hidden_explorer

    # Path / metadata ---------------------------------------------------
    def _path(self, value: str | Path, *, allow_root: bool = True) -> Path:
        candidate = Path(value).expanduser()
        path = (self.base_path / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
        try:
            path.relative_to(self.base_path)
        except ValueError as exc:
            raise ValueError(f"Path escapes experimental workspace: {value}") from exc
        if not allow_root and path == self.base_path:
            raise ValueError("The experimental workspace root cannot be targeted.")
        return path

    def metadata(self, path: str | Path) -> dict[str, Any]:
        target = self._path(path)
        st = target.stat()
        mime, encoding = mimetypes.guess_type(target.name)
        result: dict[str, Any] = {
            "path": str(target), "name": target.name, "size": st.st_size,
            "created": getattr(st, "st_birthtime", st.st_ctime), "modified": st.st_mtime, "accessed": st.st_atime,
            "mode": stat.S_IMODE(st.st_mode), "mode_octal": oct(stat.S_IMODE(st.st_mode)),
            "readable": os.access(target, os.R_OK), "writable": os.access(target, os.W_OK), "executable": os.access(target, os.X_OK),
            "is_file": target.is_file(), "is_directory": target.is_dir(), "is_symlink": target.is_symlink(),
            "mime_type": mime, "encoding": encoding,
        }
        if hasattr(st, "st_uid"):
            result["uid"] = st.st_uid
        if hasattr(st, "st_gid"):
            result["gid"] = st.st_gid
        return result

    def owner_information(self, path: str | Path) -> dict[str, Any]:
        st = self._path(path).stat()
        result: dict[str, Any] = {"uid": getattr(st, "st_uid", None), "gid": getattr(st, "st_gid", None)}
        try:
            import grp
            import pwd
            if result["uid"] is not None:
                result["user"] = pwd.getpwuid(result["uid"]).pw_name
            if result["gid"] is not None:
                result["group"] = grp.getgrgid(result["gid"]).gr_name
        except (ImportError, KeyError, OSError):
            pass
        return result

    def hash_file(self, path: str | Path, algorithm: str = "sha256", chunk_size: int = 1024 * 1024) -> str:
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        digest = hashlib.new(algorithm)
        with self._path(path).open("rb") as handle:
            for chunk in iter(lambda: handle.read(chunk_size), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def file_identity(self, path: str | Path) -> dict[str, Any]:
        target = self._path(path)
        st = target.stat()
        return {"path": str(target), "size": st.st_size, "sha256": self.hash_file(target), "device": getattr(st, "st_dev", None), "inode": getattr(st, "st_ino", None)}

    def file_signature(self, path: str | Path, algorithm: str = "sha256") -> str:
        return self.hash_file(path, algorithm)

    def verify_integrity(self, path: str | Path, expected: str, algorithm: str = "sha256") -> bool:
        return self.hash_file(path, algorithm).lower() == expected.lower()

    def same_file(self, left: str | Path, right: str | Path) -> bool:
        try:
            return os.path.samefile(self._path(left), self._path(right))
        except (FileNotFoundError, OSError):
            return self.file_signature(left) == self.file_signature(right)

    # Search / storage analysis ----------------------------------------
    def search_advanced(self, query: str = "", path: str | Path = ".", *, extension: str | None = None,
                        minimum_size: int | None = None, maximum_size: int | None = None,
                        files_only: bool = False, folders_only: bool = False, case_sensitive: bool = False) -> list[Path]:
        root = self._path(path)
        needle = query if case_sensitive else query.lower()
        ext = None if extension is None else (extension if extension.startswith(".") else "." + extension).lower()
        matches: list[Path] = []
        for item in root.rglob("*"):
            if any(part.startswith(".") for part in item.relative_to(self.base_path).parts):
                continue
            if files_only and not item.is_file():
                continue
            if folders_only and not item.is_dir():
                continue
            if needle and needle not in (item.name if case_sensitive else item.name.lower()):
                continue
            if ext and item.suffix.lower() != ext:
                continue
            if minimum_size is not None or maximum_size is not None:
                if not item.is_file():
                    continue
                size = item.stat().st_size
                if minimum_size is not None and size < minimum_size:
                    continue
                if maximum_size is not None and size > maximum_size:
                    continue
            matches.append(item)
        return sorted(matches, key=lambda p: str(p).lower())

    def duplicates(self, path: str | Path = ".") -> list[list[Path]]:
        groups: dict[tuple[int, str], list[Path]] = {}
        for item in self._path(path).rglob("*"):
            if item.is_file() and not any(x.startswith(".") for x in item.relative_to(self.base_path).parts):
                groups.setdefault((item.stat().st_size, self.hash_file(item)), []).append(item)
        return [items for items in groups.values() if len(items) > 1]

    def storage_analysis(self, path: str | Path = ".") -> dict[str, Any]:
        root = self._path(path)
        files = [p for p in root.rglob("*") if p.is_file() and not any(x.startswith(".") for x in p.relative_to(self.base_path).parts)]
        folders = [p for p in root.rglob("*") if p.is_dir() and not any(x.startswith(".") for x in p.relative_to(self.base_path).parts)]
        extensions: dict[str, int] = {}
        total = 0
        for item in files:
            size = item.stat().st_size
            total += size
            key = item.suffix.lower() or "[no extension]"
            extensions[key] = extensions.get(key, 0) + size
        largest = sorted(files, key=lambda p: p.stat().st_size, reverse=True)[:20]
        return {"files": len(files), "folders": len(folders), "total_size": total,
                "largest": [{"path": str(p), "size": p.stat().st_size} for p in largest],
                "extensions": dict(sorted(extensions.items(), key=lambda kv: kv[1], reverse=True))}

    def find_empty_files(self, path: str | Path = ".") -> list[Path]:
        return [p for p in self._path(path).rglob("*") if p.is_file() and p.stat().st_size == 0]

    def find_empty_folders(self, path: str | Path = ".") -> list[Path]:
        return [p for p in self._path(path).rglob("*") if p.is_dir() and not any(p.iterdir())]

    def find_old_files(self, days: float, path: str | Path = ".") -> list[Path]:
        cutoff = time.time() - days * 86400
        return [p for p in self._path(path).rglob("*") if p.is_file() and p.stat().st_mtime < cutoff]

    def find_large_files(self, size: int, path: str | Path = ".") -> list[Path]:
        return [p for p in self._path(path).rglob("*") if p.is_file() and p.stat().st_size >= size]

    def cleanup_empty_folders(self, path: str | Path = ".", *, dry_run: bool = True) -> list[Path]:
        targets = sorted(self.find_empty_folders(path), key=lambda p: len(p.parts), reverse=True)
        if not dry_run:
            self.require_destructive_access()
            for target in targets:
                try:
                    target.rmdir()
                except OSError:
                    pass
        return targets

    def cleanup_preview(self, path: str | Path = ".", *, older_than_days: float | None = None, minimum_size: int | None = None) -> list[Path]:
        result: set[Path] = set(self.find_empty_files(path))
        if older_than_days is not None:
            result.update(self.find_old_files(older_than_days, path))
        if minimum_size is not None:
            result.update(self.find_large_files(minimum_size, path))
        return sorted(result, key=lambda p: str(p).lower())

    # Permissions / links / secure deletion ----------------------------
    def set_mode(self, path: str | Path, mode: int | str) -> Path:
        target = self._path(path, allow_root=False)
        numeric = int(str(mode), 8) if isinstance(mode, str) else mode
        os.chmod(target, numeric)
        return target

    def set_read_only(self, path: str | Path, enabled: bool = True) -> Path:
        target = self._path(path, allow_root=False)
        current = stat.S_IMODE(target.stat().st_mode)
        mode = current & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH) if enabled else current | stat.S_IWUSR
        return self.set_mode(target, mode)

    def is_read_only(self, path: str | Path) -> bool:
        return not os.access(self._path(path), os.W_OK)

    def secure_delete(self, path: str | Path, *, passes: int = 1) -> Path:
        """Best-effort overwrite; flash storage may retain old physical blocks."""
        self.require_destructive_access()
        if passes < 1:
            raise ValueError("passes must be at least 1")
        target = self._path(path, allow_root=False)
        if not target.is_file():
            raise ValueError("secure_delete requires a regular file")
        length = target.stat().st_size
        with target.open("r+b", buffering=0) as handle:
            for _ in range(passes):
                handle.seek(0)
                remaining = length
                while remaining:
                    chunk = os.urandom(min(1024 * 1024, remaining))
                    handle.write(chunk)
                    remaining -= len(chunk)
                handle.flush()
                os.fsync(handle.fileno())
        target.unlink()
        return target

    def create_symlink(self, target: str | Path, link: str | Path) -> Path:
        destination = self._path(link, allow_root=False)
        source = Path(target).expanduser()
        if not source.is_absolute():
            source = self._path(target)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.symlink_to(source, target_is_directory=source.is_dir())
        return destination

    def symlink_target(self, path: str | Path) -> Path:
        target = self._path(path)
        if not target.is_symlink():
            raise ValueError("Path is not a symbolic link")
        return target.readlink()

    def is_symlink(self, path: str | Path) -> bool:
        return self._path(path).is_symlink()

    def resolve_link(self, path: str | Path) -> Path:
        return self._path(path).resolve()

    # Streaming ---------------------------------------------------------
    def read_chunks(self, path: str | Path, chunk_size: int = 1024 * 1024) -> Iterator[bytes]:
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        with self._path(path).open("rb") as handle:
            while True:
                chunk = handle.read(chunk_size)
                if not chunk:
                    break
                yield chunk

    def write_chunks(self, path: str | Path, chunks: Any, *, append: bool = False) -> Path:
        target = self._path(path, allow_root=False)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("ab" if append else "wb") as handle:
            for chunk in chunks:
                if not isinstance(chunk, (bytes, bytearray, memoryview)):
                    raise TypeError("chunks must contain bytes-like values")
                handle.write(bytes(chunk))
        return target

    def copy_with_progress(self, source: str | Path, destination: str | Path, chunk_size: int = 1024 * 1024) -> Iterator[dict[str, Any]]:
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        src = self._path(source)
        dst = self._path(destination, allow_root=False)
        if src.is_dir():
            raise ValueError("copy_with_progress requires a file")
        dst.parent.mkdir(parents=True, exist_ok=True)
        total = src.stat().st_size
        copied = 0
        with src.open("rb") as inp, dst.open("wb") as out:
            while True:
                chunk = inp.read(chunk_size)
                if not chunk:
                    break
                out.write(chunk)
                copied += len(chunk)
                yield {"copied": copied, "total": total, "percent": 100.0 if total == 0 else copied * 100.0 / total, "path": str(dst)}
        shutil.copystat(src, dst, follow_symlinks=True)

    # Archives ----------------------------------------------------------
    def archive_create(self, source: str | Path, archive: str | Path, format: str = "zip") -> Path:
        src = self._path(source)
        out = self._path(archive, allow_root=False)
        out.parent.mkdir(parents=True, exist_ok=True)
        fmt = format.lower().replace(".", "")
        if fmt == "zip":
            with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
                if src.is_dir():
                    for item in src.rglob("*"):
                        if item.is_file():
                            zf.write(item, item.relative_to(src))
                else:
                    zf.write(src, src.name)
        else:
            mode = {"tar": "w", "targz": "w:gz", "gz": "w:gz", "tarbz2": "w:bz2", "tarxz": "w:xz"}.get(fmt)
            if mode is None:
                raise ValueError("Unsupported archive format")
            with tarfile.open(out, mode) as tf:
                tf.add(src, arcname=src.name)
        return out

    def archive_list(self, archive: str | Path) -> list[str]:
        target = self._path(archive)
        if zipfile.is_zipfile(target):
            with zipfile.ZipFile(target) as zf:
                return zf.namelist()
        with tarfile.open(target, "r:*") as tf:
            return tf.getnames()

    def archive_test(self, archive: str | Path) -> bool:
        target = self._path(archive)
        try:
            if zipfile.is_zipfile(target):
                with zipfile.ZipFile(target) as zf:
                    return zf.testzip() is None
            with tarfile.open(target, "r:*") as tf:
                for member in tf.getmembers():
                    if member.isfile():
                        stream = tf.extractfile(member)
                        if stream:
                            while stream.read(1024 * 1024):
                                pass
            return True
        except (OSError, tarfile.TarError, zipfile.BadZipFile):
            return False

    def archive_extract(self, archive: str | Path, destination: str | Path = ".") -> Path:
        target = self._path(archive)
        out = self._path(destination)
        out.mkdir(parents=True, exist_ok=True)
        root = out.resolve()
        if zipfile.is_zipfile(target):
            with zipfile.ZipFile(target) as zf:
                for name in zf.namelist():
                    (out / name).resolve().relative_to(root)
                zf.extractall(out)
        else:
            with tarfile.open(target, "r:*") as tf:
                for member in tf.getmembers():
                    (out / member.name).resolve().relative_to(root)
                tf.extractall(out)
        return out

    def archive_password_protected(self, archive: str | Path) -> bool:
        target = self._path(archive)
        if not zipfile.is_zipfile(target):
            return False
        with zipfile.ZipFile(target) as zf:
            return any(info.flag_bits & 0x1 for info in zf.infolist())

    def archive_add(self, archive: str | Path, source: str | Path) -> Path:
        target, src = self._path(archive), self._path(source)
        if not zipfile.is_zipfile(target):
            raise ValueError("archive_add currently supports ZIP archives")
        with tempfile.TemporaryDirectory(dir=self.base_path) as temp:
            temp_archive = Path(temp) / "archive.zip"
            with zipfile.ZipFile(target, "r") as old, zipfile.ZipFile(temp_archive, "w", zipfile.ZIP_DEFLATED) as new:
                for info in old.infolist():
                    new.writestr(info, old.read(info.filename))
                if src.is_file():
                    new.write(src, src.name)
                else:
                    for item in src.rglob("*"):
                        if item.is_file():
                            new.write(item, item.relative_to(src))
            os.replace(temp_archive, target)
        return target

    def archive_remove(self, archive: str | Path, names: list[str]) -> Path:
        target = self._path(archive)
        if not zipfile.is_zipfile(target):
            raise ValueError("archive_remove currently supports ZIP archives")
        remove = set(names)
        with tempfile.TemporaryDirectory(dir=self.base_path) as temp:
            temp_archive = Path(temp) / "archive.zip"
            with zipfile.ZipFile(target, "r") as old, zipfile.ZipFile(temp_archive, "w", zipfile.ZIP_DEFLATED) as new:
                for info in old.infolist():
                    if info.filename not in remove:
                        new.writestr(info, old.read(info.filename))
            os.replace(temp_archive, target)
        return target

    def archive_update(self, archive: str | Path, *, add: str | Path | None = None, remove: list[str] | None = None) -> Path:
        if add is not None:
            self.archive_add(archive, add)
        if remove:
            self.archive_remove(archive, remove)
        return self._path(archive)

    # Snapshots / backups ----------------------------------------------
    def snapshot(self, path: str | Path = ".") -> dict[str, Any]:
        root = self._path(path)
        files: dict[str, Any] = {}
        for item in root.rglob("*"):
            if item.is_file() and not any(x.startswith(".") for x in item.relative_to(self.base_path).parts):
                files[str(item.relative_to(root))] = {"size": item.stat().st_size, "sha256": self.hash_file(item), "mtime": item.stat().st_mtime}
        return {"root": str(root), "created": time.time(), "files": files}

    def snapshot_save(self, path: str | Path, destination: str | Path) -> Path:
        target = self._path(destination, allow_root=False)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(self.snapshot(path), indent=2), encoding="utf-8")
        return target

    def snapshot_load(self, path: str | Path) -> dict[str, Any]:
        return json.loads(self._path(path).read_text(encoding="utf-8"))

    def snapshot_compare(self, old: dict[str, Any], new: dict[str, Any]) -> dict[str, list[str]]:
        a, b = old.get("files", {}), new.get("files", {})
        return {"added": sorted(set(b) - set(a)), "removed": sorted(set(a) - set(b)), "modified": sorted(k for k in set(a) & set(b) if a[k].get("sha256") != b[k].get("sha256"))}

    def backup(self, destination: str | Path, source: str | Path = ".") -> Path:
        return self.archive_create(source, destination, "zip")

    def restore_backup(self, archive: str | Path, destination: str | Path = ".") -> Path:
        return self.archive_extract(archive, destination)

    def snapshot_restore(self, archive: str | Path, destination: str | Path = ".") -> Path:
        """Restore a content backup; a metadata-only snapshot cannot recreate bytes."""
        return self.restore_backup(archive, destination)

    def backup_incremental(self, source: str | Path, destination: str | Path) -> dict[str, Any]:
        src, dst = self._path(source), self._path(destination)
        dst.mkdir(parents=True, exist_ok=True)
        manifest_path = dst / ".alera_incremental.json"
        old = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
        new: dict[str, Any] = {}
        copied: list[str] = []
        for item in src.rglob("*"):
            if not item.is_file() or any(x.startswith(".") for x in item.relative_to(self.base_path).parts):
                continue
            rel, digest = str(item.relative_to(src)), self.hash_file(item)
            new[rel] = {"sha256": digest, "size": item.stat().st_size}
            if old.get(rel, {}).get("sha256") != digest:
                target = dst / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, target)
                copied.append(rel)
        manifest_path.write_text(json.dumps(new, indent=2), encoding="utf-8")
        return {"destination": str(dst), "copied": copied, "files": len(new)}

    @contextlib.contextmanager
    def transaction(self) -> Iterator["Experimental"]:
        with tempfile.TemporaryDirectory(prefix="alera-transaction-") as temp:
            backup = Path(temp) / "workspace"
            backup.mkdir()
            for item in self.base_path.iterdir():
                if item.name in {".alera_bin", ".alera_hidden", ".alera_recovery_history.json"} or item.name.startswith(".alera_transaction"):
                    continue
                destination = backup / item.name
                if item.is_dir() and not item.is_symlink():
                    shutil.copytree(item, destination, symlinks=True)
                else:
                    shutil.copy2(item, destination, follow_symlinks=False)
            try:
                yield self
            except Exception:
                for item in list(self.base_path.iterdir()):
                    if item.name in {".alera_bin", ".alera_hidden", ".alera_recovery_history.json"}:
                        continue
                    if item.is_dir() and not item.is_symlink():
                        shutil.rmtree(item)
                    else:
                        item.unlink(missing_ok=True)
                for item in backup.iterdir():
                    destination = self.base_path / item.name
                    if item.is_dir() and not item.is_symlink():
                        shutil.copytree(item, destination, symlinks=True)
                    else:
                        shutil.copy2(item, destination, follow_symlinks=False)
                raise

    # Recovery / device -------------------------------------------------
    def record_recovery_event(self, action: str, path: str | Path, **details: Any) -> dict[str, Any]:
        history = json.loads(self._history_path.read_text(encoding="utf-8")) if self._history_path.exists() else []
        event = {"timestamp": time.time(), "action": action, "path": str(path), **details}
        history.append(event)
        self._history_path.write_text(json.dumps(history, indent=2), encoding="utf-8")
        return event

    def recovery_history(self) -> list[dict[str, Any]]:
        return json.loads(self._history_path.read_text(encoding="utf-8")) if self._history_path.exists() else []

    def mounts(self) -> list[dict[str, str]]:
        result: list[dict[str, str]] = []
        source = Path("/proc/mounts")
        if source.exists():
            for line in source.read_text(errors="replace").splitlines():
                parts = line.split()
                if len(parts) >= 3:
                    result.append({"device": parts[0], "mount": parts[1], "filesystem": parts[2]})
        return result

    def devices(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        if Path("/dev").exists():
            for item in sorted(Path("/dev").iterdir(), key=lambda p: p.name)[:500]:
                if item.is_block_device() or item.is_char_device():
                    result.append({"path": str(item), "type": "block" if item.is_block_device() else "char"})
        return result

    def filesystems(self) -> list[str]:
        return sorted({item["filesystem"] for item in self.mounts()})

    def storage_information(self, path: str | Path = ".") -> dict[str, Any]:
        target = self._path(path)
        usage = shutil.disk_usage(target)
        return {"path": str(target), "total": usage.total, "used": usage.used, "free": usage.free}

    def health_check(self) -> dict[str, Any]:
        report: dict[str, Any] = {"path": str(self.base_path), "exists": self.base_path.exists(), "readable": os.access(self.base_path, os.R_OK), "writable": os.access(self.base_path, os.W_OK)}
        with tempfile.NamedTemporaryFile(dir=self.base_path, delete=True) as handle:
            handle.write(b"alera-health")
            handle.flush()
            report["temporary_write"] = True
        report["storage"] = self.storage_information()
        report["android"] = self.android_storage_information() if self.android else None
        report["features"] = self.features()
        return report

    def test_readable(self, path: str | Path) -> bool:
        return os.access(self._path(path), os.R_OK)

    def test_writable(self, path: str | Path) -> bool:
        return os.access(self._path(path), os.W_OK)

    def test_copy(self, path: str | Path) -> bool:
        target = self._path(path)
        with tempfile.TemporaryDirectory(dir=self.base_path) as temp:
            destination = Path(temp) / target.name
            if target.is_dir():
                shutil.copytree(target, destination)
            else:
                shutil.copy2(target, destination)
            return destination.exists()

    def test_move(self, path: str | Path) -> bool:
        target = self._path(path, allow_root=False)
        with tempfile.TemporaryDirectory(dir=self.base_path) as temp:
            destination = Path(temp) / target.name
            shutil.move(str(target), str(destination))
            shutil.move(str(destination), str(target))
            return target.exists()

    def test_delete(self, path: str | Path) -> bool:
        target = self._path(path, allow_root=False)
        if target.is_dir():
            return False
        temp = target.with_name(target.name + ".alera-delete-test")
        shutil.copy2(target, temp)
        temp.unlink()
        return True

    def which(self, executable: str) -> str | None:
        return shutil.which(executable)

    def find_executable(self, executable: str) -> Path | None:
        found = shutil.which(executable)
        return Path(found) if found else None

    def current_directory(self) -> Path:
        return Path.cwd()

    def temp_directory(self) -> Path:
        return Path(tempfile.gettempdir())

    def environment(self) -> dict[str, str]:
        return dict(os.environ)

    def python_information(self) -> dict[str, Any]:
        return {"version": sys.version, "implementation": _platform.python_implementation(), "executable": sys.executable, "prefix": sys.prefix}

    def platform_information(self) -> dict[str, Any]:
        return {"system": _platform.system(), "release": _platform.release(), "version": _platform.version(), "machine": _platform.machine(), "processor": _platform.processor()}

    def open_path(self, path: str | Path) -> bool:
        target = self._path(path)
        if os.name == "nt":
            os.startfile(str(target))
            return True
        command = ["open", str(target)] if sys.platform == "darwin" else ["xdg-open", str(target)]
        try:
            subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except OSError:
            return False
