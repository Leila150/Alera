"""Cross-platform hidden-file support for Alera."""

from __future__ import annotations

import json
import os
import secrets
import shutil
import sys
from pathlib import Path
from typing import Iterable, Iterator


class HiddenFiles:
    """Manage hidden files on Android shared storage and desktop systems.

    Android stores hidden objects on shared internal storage, not Python's
    private application directory. Objects are placed below a dot-prefixed
    directory with unpredictable names, while a small manifest preserves the
    original paths. This is substantially stronger than simply renaming a
    visible file to ``.file``.

    Android has no universal hidden attribute for arbitrary shared-storage
    files. A file manager that deliberately reveals dot-prefixed directories
    can still discover Alera's hidden directory; standard Python cannot force
    every third-party file manager to hide it.
    """

    _ANDROID_HIDDEN_DIR = ".alera_hidden"
    _ANDROID_NOMEDIA = ".nomedia"
    _ANDROID_TOKEN_BYTES = 32

    def __init__(self, base_path: str | os.PathLike[str] = "") -> None:
        self.base_path = Path(base_path or Path.cwd()).expanduser().resolve()
        self.base_path.mkdir(parents=True, exist_ok=True)
        self._android_storage_root = self._detect_android_shared_storage()
        self._android_vault = (
            self._android_storage_root / self._ANDROID_HIDDEN_DIR
            if self._android_storage_root is not None
            else self.base_path / self._ANDROID_HIDDEN_DIR
        )
        self._android_manifest = self._android_vault / "index.json"
        if self.mobile:
            self._initialize_android_storage()

    @property
    def platform(self) -> str:
        if os.name == "nt":
            return "windows"
        if sys.platform.startswith("android"):
            return "android"
        if sys.platform == "darwin":
            return "macos"
        if sys.platform.startswith("linux"):
            return "android" if os.environ.get("ANDROID_ROOT") or os.environ.get("ANDROID_DATA") else "linux"
        return "unknown"

    @property
    def mobile(self) -> bool:
        return self.platform == "android"

    @property
    def desktop(self) -> bool:
        return not self.mobile

    @property
    def android_shared_storage(self) -> Path | None:
        return self._android_storage_root

    @property
    def android_hidden_storage(self) -> Path:
        return self._android_vault

    @property
    def storage_backend(self) -> str:
        if self.mobile and self._android_storage_root is not None:
            return "android_shared_internal_storage"
        if self.mobile:
            return "android_workspace_storage"
        return "filesystem"

    def _detect_android_shared_storage(self) -> Path | None:
        if not self.mobile:
            return None
        candidates: list[Path] = []
        external = os.environ.get("EXTERNAL_STORAGE")
        if external:
            candidates.append(Path(external).expanduser())
        candidates.extend((Path("/storage/emulated/0"), Path("/sdcard")))
        parts = self.base_path.parts
        for index, part in enumerate(parts):
            if part == "storage" and len(parts) > index + 3 and parts[index + 1] == "emulated":
                candidate = Path(*parts[: index + 3])
                if candidate.name == "0":
                    candidates.insert(0, candidate)
                    break
        for candidate in candidates:
            try:
                candidate = candidate.resolve()
                if candidate.exists() and candidate.is_dir():
                    return candidate
            except OSError:
                continue
        return None

    def _initialize_android_storage(self) -> None:
        self._android_vault.mkdir(parents=True, exist_ok=True)
        self._protect_android_path(self._android_vault, True)
        nomedia = self._android_vault / self._ANDROID_NOMEDIA
        if not nomedia.exists():
            try:
                nomedia.write_bytes(b"")
            except OSError:
                pass
        self._protect_android_path(nomedia, False)
        if not self._android_manifest.exists():
            self._atomic_write_manifest({})

    @staticmethod
    def _protect_android_path(path: Path, directory: bool) -> None:
        try:
            path.chmod(0o700 if directory else 0o600)
        except OSError:
            pass

    def _atomic_write_manifest(self, data: dict[str, dict[str, object]]) -> None:
        self._android_vault.mkdir(parents=True, exist_ok=True)
        temporary = self._android_vault / ".index.tmp"
        payload = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)
        with temporary.open("w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            try:
                os.fsync(handle.fileno())
            except OSError:
                pass
        self._protect_android_path(temporary, False)
        os.replace(temporary, self._android_manifest)
        self._protect_android_path(self._android_manifest, False)

    def _load_android_manifest(self) -> dict[str, dict[str, object]]:
        if not self._android_manifest.exists():
            return {}
        try:
            data = json.loads(self._android_manifest.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save_android_manifest(self, data: dict[str, dict[str, object]]) -> None:
        self._atomic_write_manifest(data)

    def _path(self, path: str | os.PathLike[str]) -> Path:
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            candidate = self.base_path / candidate
        candidate = candidate.resolve()
        try:
            candidate.relative_to(self.base_path)
        except ValueError as exc:
            raise ValueError("path escapes the HiddenFiles workspace") from exc
        return candidate

    def _android_record(self, original: Path, stored: Path) -> None:
        data = self._load_android_manifest()
        try:
            relative = str(original.relative_to(self.base_path))
        except ValueError:
            relative = original.name
        data[str(original)] = {"stored": str(stored), "name": original.name, "relative": relative}
        self._save_android_manifest(data)

    def _android_record_for(self, original: Path) -> dict[str, object] | None:
        return self._load_android_manifest().get(str(original))

    def _android_unrecord(self, original: Path) -> None:
        data = self._load_android_manifest()
        data.pop(str(original), None)
        self._save_android_manifest(data)

    def _new_android_name(self) -> Path:
        while True:
            candidate = self._android_vault / secrets.token_hex(self._ANDROID_TOKEN_BYTES)
            if not candidate.exists():
                return candidate

    @staticmethod
    def _windows_hidden(path: Path) -> bool:
        if os.name != "nt" or not path.exists():
            return False
        try:
            import ctypes
            attrs = ctypes.windll.kernel32.GetFileAttributesW(str(path))
            return attrs != -1 and bool(attrs & 0x2)
        except Exception:
            return False

    @staticmethod
    def _set_windows_hidden(path: Path, hidden: bool) -> None:
        if os.name != "nt" or not path.exists():
            return
        try:
            import ctypes
            attrs = ctypes.windll.kernel32.GetFileAttributesW(str(path))
            if attrs == -1:
                return
            attrs = (attrs | 0x2) if hidden else (attrs & ~0x2)
            ctypes.windll.kernel32.SetFileAttributesW(str(path), attrs)
        except Exception:
            pass

    @staticmethod
    def _dot_hidden(path: Path) -> bool:
        return path.name.startswith(".") and path.name not in {".", ".."}

    def is_hidden(self, path: str | os.PathLike[str]) -> bool:
        item = self._path(path)
        if self.mobile and self._android_record_for(item) is not None:
            return True
        if not item.exists() and not item.is_symlink():
            return False
        return self._dot_hidden(item) or self._windows_hidden(item)

    def hidden_reason(self, path: str | os.PathLike[str]) -> str:
        item = self._path(path)
        if self.mobile and self._android_record_for(item) is not None:
            return "android_shared_internal_storage_randomized"
        dot = self._dot_hidden(item)
        windows = self._windows_hidden(item)
        if dot and windows:
            return "dot_name+windows_attribute"
        if dot:
            return "dot_name"
        if windows:
            return "windows_attribute"
        return "visible"

    def _hide_android(self, item: Path) -> Path:
        if not item.exists() and not item.is_symlink():
            raise FileNotFoundError(item)
        if self._android_record_for(item) is not None:
            return item
        if item == self._android_vault or self._android_vault in item.parents:
            raise ValueError("cannot hide an item inside Alera's hidden storage")
        if self._android_storage_root is not None and item != self._android_storage_root and self._android_storage_root not in item.parents:
            raise ValueError("Android hidden items must originate on shared internal storage")
        self._initialize_android_storage()
        stored = self._new_android_name()
        shutil.move(str(item), str(stored))
        self._protect_android_path(stored, stored.is_dir())
        self._android_record(item, stored)
        return item

    def _unhide_android(self, item: Path) -> Path:
        record = self._android_record_for(item)
        if record is None:
            raise FileNotFoundError(f"no Android hidden item registered for {item}")
        stored = Path(str(record["stored"]))
        if not stored.exists() and not stored.is_symlink():
            self._android_unrecord(item)
            raise FileNotFoundError(stored)
        if item.exists() or item.is_symlink():
            raise FileExistsError(item)
        item.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(stored), str(item))
        self._android_unrecord(item)
        return item

    def hide(self, path: str | os.PathLike[str]) -> Path:
        item = self._path(path)
        if self.mobile:
            return self._hide_android(item)
        if not item.exists() and not item.is_symlink():
            raise FileNotFoundError(item)
        if not self._dot_hidden(item):
            target = item.with_name("." + item.name)
            if target.exists() or target.is_symlink():
                raise FileExistsError(target)
            item.rename(target)
            item = target
        self._set_windows_hidden(item, True)
        return item

    def unhide(self, path: str | os.PathLike[str]) -> Path:
        item = self._path(path)
        if self.mobile:
            return self._unhide_android(item)
        if not item.exists() and not item.is_symlink():
            raise FileNotFoundError(item)
        self._set_windows_hidden(item, False)
        if self._dot_hidden(item):
            target = item.with_name(item.name[1:])
            if not target.name:
                raise ValueError("cannot unhide an item with an empty name")
            if target.exists() or target.is_symlink():
                raise FileExistsError(target)
            item.rename(target)
            item = target
        return item

    def create_hidden_file(self, name: str, contents: str = "", overwrite: bool = False) -> Path:
        target = self._path(name)
        if self.mobile:
            if target.exists() and not overwrite:
                raise FileExistsError(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(contents, encoding="utf-8")
            return self._hide_android(target)
        if not self._dot_hidden(target):
            target = target.with_name("." + target.name)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and not overwrite:
            raise FileExistsError(target)
        target.write_text(contents, encoding="utf-8")
        self._set_windows_hidden(target, True)
        return target

    def create_hidden_binary(self, name: str, contents: bytes, overwrite: bool = False) -> Path:
        target = self._path(name)
        if self.mobile:
            if target.exists() and not overwrite:
                raise FileExistsError(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(bytes(contents))
            return self._hide_android(target)
        if not self._dot_hidden(target):
            target = target.with_name("." + target.name)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and not overwrite:
            raise FileExistsError(target)
        target.write_bytes(bytes(contents))
        self._set_windows_hidden(target, True)
        return target

    def create_hidden_folder(self, name: str, parents: bool = False) -> Path:
        target = self._path(name)
        if self.mobile:
            target.mkdir(parents=parents, exist_ok=False)
            return self._hide_android(target)
        if not self._dot_hidden(target):
            target = target.with_name("." + target.name)
        target.mkdir(parents=parents, exist_ok=False)
        self._set_windows_hidden(target, True)
        return target

    def list_hidden(self, path: str | os.PathLike[str] = "", recursive: bool = False) -> list[Path]:
        root = self._path(path) if path else self.base_path
        if self.mobile:
            paths: list[Path] = []
            for original in self._load_android_manifest():
                candidate = Path(original)
                try:
                    candidate.relative_to(root)
                except ValueError:
                    continue
                if recursive or candidate.parent == root:
                    paths.append(candidate)
            return sorted(paths, key=lambda p: str(p).lower())
        items: Iterable[Path] = root.rglob("*") if recursive else root.iterdir()
        return sorted((p for p in items if self.is_hidden(p)), key=lambda p: str(p).lower())

    def list_visible(self, path: str | os.PathLike[str] = "", recursive: bool = False) -> list[Path]:
        root = self._path(path) if path else self.base_path
        items: Iterable[Path] = root.rglob("*") if recursive else root.iterdir()
        if self.mobile:
            hidden = {str(p) for p in self.list_hidden(root, recursive=True)}
            return sorted((p for p in items if str(p) not in hidden and p != self._android_vault), key=lambda p: str(p).lower())
        return sorted((p for p in items if not self.is_hidden(p)), key=lambda p: str(p).lower())

    def walk_hidden(self, path: str | os.PathLike[str] = "") -> Iterator[Path]:
        yield from self.list_hidden(path, recursive=True)

    def hidden_files(self, path: str | os.PathLike[str] = "", recursive: bool = False) -> list[Path]:
        if self.mobile:
            data = self._load_android_manifest()
            return [p for p in self.list_hidden(path, recursive) if Path(str(data[str(p)]["stored"])).is_file()]
        return [p for p in self.list_hidden(path, recursive) if p.is_file()]

    def hidden_folders(self, path: str | os.PathLike[str] = "", recursive: bool = False) -> list[Path]:
        if self.mobile:
            data = self._load_android_manifest()
            return [p for p in self.list_hidden(path, recursive) if Path(str(data[str(p)]["stored"])).is_dir()]
        return [p for p in self.list_hidden(path, recursive) if p.is_dir()]

    def visible_files(self, path: str | os.PathLike[str] = "", recursive: bool = False) -> list[Path]:
        return [p for p in self.list_visible(path, recursive) if p.is_file()]

    def visible_folders(self, path: str | os.PathLike[str] = "", recursive: bool = False) -> list[Path]:
        return [p for p in self.list_visible(path, recursive) if p.is_dir()]

    def hidden_count(self, path: str | os.PathLike[str] = "") -> int:
        return len(self.list_hidden(path))

    def hide_many(self, paths: list[str | os.PathLike[str]]) -> list[Path]:
        return [self.hide(path) for path in paths]

    def unhide_many(self, paths: list[str | os.PathLike[str]]) -> list[Path]:
        return [self.unhide(path) for path in paths]

    def hide_all(self, path: str | os.PathLike[str] = "", recursive: bool = False) -> list[Path]:
        items = self.list_visible(path, recursive)
        items.sort(key=lambda p: len(p.parts), reverse=True)
        return [self.hide(p) for p in items]

    def unhide_all(self, path: str | os.PathLike[str] = "", recursive: bool = False) -> list[Path]:
        items = self.list_hidden(path, recursive)
        items.sort(key=lambda p: len(p.parts), reverse=True)
        return [self.unhide(p) for p in items]

    def reveal(self, path: str | os.PathLike[str]) -> Path:
        return self.unhide(path)

    def verify_hidden(self, path: str | os.PathLike[str]) -> bool:
        item = self._path(path)
        if self.mobile:
            record = self._android_record_for(item)
            return record is not None and Path(str(record["stored"])).exists()
        return self.is_hidden(item)

    def cleanup_orphans(self) -> list[Path]:
        if not self.mobile:
            return []
        data = self._load_android_manifest()
        stale = [Path(original) for original, record in data.items() if not Path(str(record.get("stored", ""))).exists()]
        for item in stale:
            data.pop(str(item), None)
        if stale:
            self._save_android_manifest(data)
        return stale

    def copy_hidden(self, source: str | os.PathLike[str], destination: str | os.PathLike[str]) -> Path:
        src = self._path(source)
        dst = self._path(destination)
        if self.mobile and self._android_record_for(src) is not None:
            raise ValueError("Android hidden items must be unhidden before copying")
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)
        if self.is_hidden(src) and not self.is_hidden(dst):
            dst = self.hide(dst)
        return dst

    def hidden_information(self, path: str | os.PathLike[str]) -> dict[str, object]:
        item = self._path(path)
        stat_result = item.stat() if item.exists() else None
        result: dict[str, object] = {
            "path": str(item),
            "name": item.name,
            "exists": item.exists(),
            "hidden": self.is_hidden(item),
            "reason": self.hidden_reason(item),
            "platform": self.platform,
            "mobile": self.mobile,
            "desktop": self.desktop,
            "storage_backend": self.storage_backend,
            "type": "directory" if item.is_dir() else "file" if item.is_file() else "other",
            "size": stat_result.st_size if stat_result else 0,
            "modified": stat_result.st_mtime if stat_result else None,
            "native_windows_hidden": self._windows_hidden(item),
        }
        if self.mobile:
            record = self._android_record_for(item)
            result["android_shared_storage"] = str(self._android_storage_root) if self._android_storage_root else None
            result["android_hidden_storage"] = str(self._android_vault)
            result["stored_path"] = record.get("stored") if record else None
            result["verify"] = self.verify_hidden(item)
        return result
