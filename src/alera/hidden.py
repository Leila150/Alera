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
    """Manage hidden files using Alera internal storage by default.

    ``storage="internal"`` stores hidden objects below ``.alera/hidden``.
    ``storage="android"`` opts into Android shared storage when available.
    ``enabled=False`` disables the subsystem.
    """

    _ANDROID_HIDDEN_DIR = ".alera_hidden"
    _ANDROID_NOMEDIA = ".nomedia"
    _ANDROID_TOKEN_BYTES = 32

    def __init__(self, base_path: str | os.PathLike[str] = "", *, enabled: bool = True, storage: str = "internal") -> None:
        self.base_path = Path(base_path or Path.cwd()).expanduser().resolve()
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.enabled = bool(enabled)
        self.requested_storage = self._validate_storage(storage)
        self._android_storage_root = self._detect_android_shared_storage()
        self._android_vault = self._select_vault()
        self._android_manifest = self._android_vault / "index.json"
        if self.enabled and self.requested_storage == "android" and self.mobile:
            self._initialize_android_storage()

    @staticmethod
    def _validate_storage(storage: str) -> str:
        value = str(storage).strip().lower()
        if value not in {"internal", "android"}:
            raise ValueError("storage must be 'internal' or 'android'")
        return value

    def _select_vault(self) -> Path:
        if self.requested_storage == "android" and self._android_storage_root is not None:
            return self._android_storage_root / self._ANDROID_HIDDEN_DIR
        return self.base_path / ".alera" / "hidden"

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
        if not self.enabled:
            return "disabled"
        if self.requested_storage == "android" and self.mobile and self._android_storage_root is not None:
            return "android_shared_storage"
        return "alera_internal_storage"

    def configure(self, *, enabled: bool | None = None, storage: str | None = None) -> "HiddenFiles":
        if enabled is not None:
            self.enabled = bool(enabled)
        if storage is not None:
            self.requested_storage = self._validate_storage(storage)
        self._android_vault = self._select_vault()
        self._android_manifest = self._android_vault / "index.json"
        if self.enabled and self.requested_storage == "android" and self.mobile:
            self._initialize_android_storage()
        return self

    def _require_enabled(self) -> None:
        if not self.enabled:
            raise RuntimeError("Alera hidden storage is disabled by hidden_config")

    def _detect_android_shared_storage(self) -> Path | None:
        if not self.mobile:
            return None
        candidates: list[Path] = []
        external = os.environ.get("EXTERNAL_STORAGE")
        if external:
            candidates.append(Path(external).expanduser())
        candidates.extend((Path("/storage/emulated/0"), Path("/storage/self/primary"), Path("/sdcard")))
        parts = self.base_path.parts
        for index, part in enumerate(parts):
            if part == "storage" and len(parts) > index + 3 and parts[index + 1] == "emulated" and parts[index + 2] == "0":
                candidates.insert(0, Path(*parts[: index + 3]))
                break
        for candidate in candidates:
            try:
                candidate = candidate.resolve()
                if candidate.exists() and candidate.is_dir():
                    return candidate
            except OSError:
                pass
        return None

    def _initialize_android_storage(self) -> None:
        self._android_vault.mkdir(parents=True, exist_ok=True)
        self._protect(self._android_vault, True)
        nomedia = self._android_vault / self._ANDROID_NOMEDIA
        if not nomedia.exists():
            try:
                nomedia.write_bytes(b"")
            except OSError:
                pass
        self._protect(nomedia, False)
        if not self._android_manifest.exists():
            self._save_manifest({})

    @staticmethod
    def _protect(path: Path, directory: bool) -> None:
        try:
            path.chmod(0o700 if directory else 0o600)
        except OSError:
            pass

    def _save_manifest(self, data: dict[str, dict[str, object]]) -> None:
        self._android_vault.mkdir(parents=True, exist_ok=True)
        temporary = self._android_vault / ".index.tmp"
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.flush()
            try:
                os.fsync(handle.fileno())
            except OSError:
                pass
        os.replace(temporary, self._android_manifest)
        self._protect(self._android_manifest, False)

    def _load_manifest(self) -> dict[str, dict[str, object]]:
        try:
            data = json.loads(self._android_manifest.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

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

    def _new_stored_path(self) -> Path:
        self._android_vault.mkdir(parents=True, exist_ok=True)
        while True:
            candidate = self._android_vault / secrets.token_hex(self._ANDROID_TOKEN_BYTES)
            if not candidate.exists():
                return candidate

    def _record(self, original: Path, stored: Path) -> None:
        data = self._load_manifest()
        try:
            relative = str(original.relative_to(self.base_path))
        except ValueError:
            relative = original.name
        data[str(original)] = {"stored": str(stored), "name": original.name, "relative": relative}
        self._save_manifest(data)

    def _record_for(self, original: Path) -> dict[str, object] | None:
        return self._load_manifest().get(str(original))

    def _unrecord(self, original: Path) -> None:
        data = self._load_manifest()
        data.pop(str(original), None)
        self._save_manifest(data)

    @staticmethod
    def _dot_hidden(path: Path) -> bool:
        return path.name.startswith(".") and path.name not in {".", ".."}

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

    def is_hidden(self, path: str | os.PathLike[str]) -> bool:
        self._require_enabled()
        item = self._path(path)
        if self.mobile and self.requested_storage == "android" and self._record_for(item) is not None:
            return True
        if not item.exists() and not item.is_symlink():
            return False
        return self._dot_hidden(item) or self._windows_hidden(item)

    def hidden_reason(self, path: str | os.PathLike[str]) -> str:
        self._require_enabled()
        item = self._path(path)
        if self.mobile and self.requested_storage == "android" and self._record_for(item) is not None:
            return "android_shared_storage_randomized"
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
        self._require_enabled()
        if not item.exists() and not item.is_symlink():
            raise FileNotFoundError(item)
        if self._record_for(item) is not None:
            return item
        if item == self._android_vault or self._android_vault in item.parents:
            raise ValueError("cannot hide an item inside hidden storage")
        if self._android_storage_root is not None and item != self._android_storage_root and self._android_storage_root not in item.parents:
            raise ValueError("Android hidden items must originate on shared storage")
        self._initialize_android_storage()
        stored = self._new_stored_path()
        shutil.move(str(item), str(stored))
        self._protect(stored, stored.is_dir())
        self._record(item, stored)
        return item

    def _unhide_android(self, item: Path) -> Path:
        self._require_enabled()
        record = self._record_for(item)
        if record is None:
            raise FileNotFoundError(f"no hidden item registered for {item}")
        stored = Path(str(record["stored"]))
        if not stored.exists() and not stored.is_symlink():
            self._unrecord(item)
            raise FileNotFoundError(stored)
        if item.exists() or item.is_symlink():
            raise FileExistsError(item)
        item.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(stored), str(item))
        self._unrecord(item)
        return item

    def hide(self, path: str | os.PathLike[str]) -> Path:
        item = self._path(path)
        self._require_enabled()
        if self.mobile and self.requested_storage == "android":
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
        self._require_enabled()
        if self.mobile and self.requested_storage == "android":
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
        self._require_enabled()
        if self.mobile and self.requested_storage == "android":
            if target.exists() and not overwrite:
                raise FileExistsError(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(contents, encoding="utf-8")
            return self._hide_android(target)
        target = target if self._dot_hidden(target) else target.with_name("." + target.name)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and not overwrite:
            raise FileExistsError(target)
        target.write_text(contents, encoding="utf-8")
        self._set_windows_hidden(target, True)
        return target

    def create_hidden_binary(self, name: str, contents: bytes, overwrite: bool = False) -> Path:
        target = self._path(name)
        self._require_enabled()
        if self.mobile and self.requested_storage == "android":
            if target.exists() and not overwrite:
                raise FileExistsError(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(bytes(contents))
            return self._hide_android(target)
        target = target if self._dot_hidden(target) else target.with_name("." + target.name)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and not overwrite:
            raise FileExistsError(target)
        target.write_bytes(bytes(contents))
        self._set_windows_hidden(target, True)
        return target

    def create_hidden_folder(self, name: str, parents: bool = False) -> Path:
        target = self._path(name)
        self._require_enabled()
        if self.mobile and self.requested_storage == "android":
            target.mkdir(parents=parents, exist_ok=False)
            return self._hide_android(target)
        target = target if self._dot_hidden(target) else target.with_name("." + target.name)
        target.mkdir(parents=parents, exist_ok=False)
        self._set_windows_hidden(target, True)
        return target

    def list_hidden(self, path: str | os.PathLike[str] = "", recursive: bool = False) -> list[Path]:
        self._require_enabled()
        root = self._path(path) if path else self.base_path
        if self.mobile and self.requested_storage == "android":
            result: list[Path] = []
            for original in self._load_manifest():
                candidate = Path(original)
                try:
                    candidate.relative_to(root)
                except ValueError:
                    continue
                if recursive or candidate.parent == root:
                    result.append(candidate)
            return sorted(result, key=lambda p: str(p).lower())
        items: Iterable[Path] = root.rglob("*") if recursive else root.iterdir()
        return sorted((p for p in items if self.is_hidden(p)), key=lambda p: str(p).lower())

    def list_visible(self, path: str | os.PathLike[str] = "", recursive: bool = False) -> list[Path]:
        self._require_enabled()
        root = self._path(path) if path else self.base_path
        items: Iterable[Path] = root.rglob("*") if recursive else root.iterdir()
        if self.mobile and self.requested_storage == "android":
            hidden = {str(p) for p in self.list_hidden(root, recursive=True)}
            return sorted((p for p in items if str(p) not in hidden and self._android_vault not in p.parents and p != self._android_vault), key=lambda p: str(p).lower())
        return sorted((p for p in items if not self.is_hidden(p)), key=lambda p: str(p).lower())

    def hidden_files(self, path: str | os.PathLike[str] = "", recursive: bool = False) -> list[Path]:
        if self.mobile and self.requested_storage == "android":
            manifest = self._load_manifest()
            return [p for p in self.list_hidden(path, recursive) if Path(str(manifest[str(p)]["stored"])).is_file()]
        return [p for p in self.list_hidden(path, recursive) if p.is_file()]

    def hidden_folders(self, path: str | os.PathLike[str] = "", recursive: bool = False) -> list[Path]:
        if self.mobile and self.requested_storage == "android":
            manifest = self._load_manifest()
            return [p for p in self.list_hidden(path, recursive) if Path(str(manifest[str(p)]["stored"])).is_dir()]
        return [p for p in self.list_hidden(path, recursive) if p.is_dir()]

    def visible_files(self, path: str | os.PathLike[str] = "", recursive: bool = False) -> list[Path]:
        return [p for p in self.list_visible(path, recursive) if p.is_file()]

    def visible_folders(self, path: str | os.PathLike[str] = "", recursive: bool = False) -> list[Path]:
        return [p for p in self.list_visible(path, recursive) if p.is_dir()]

    def walk_hidden(self, path: str | os.PathLike[str] = "") -> Iterator[Path]:
        yield from self.list_hidden(path, recursive=True)

    def hide_many(self, paths: list[str | os.PathLike[str]]) -> list[Path]:
        return [self.hide(path) for path in paths]

    def unhide_many(self, paths: list[str | os.PathLike[str]]) -> list[Path]:
        return [self.unhide(path) for path in paths]

    def hide_all(self, path: str | os.PathLike[str] = "") -> list[Path]:
        root = self._path(path) if path else self.base_path
        candidates = [p for p in root.iterdir() if not self.is_hidden(p) and p != self._android_vault]
        return self.hide_many(candidates)

    def unhide_all(self, path: str | os.PathLike[str] = "") -> list[Path]:
        return self.unhide_many(self.list_hidden(path))

    def verify_hidden(self, path: str | os.PathLike[str]) -> bool:
        self._require_enabled()
        item = self._path(path)
        if self.mobile and self.requested_storage == "android":
            record = self._record_for(item)
            return bool(record and Path(str(record.get("stored", ""))).exists())
        return self.is_hidden(item)

    def hidden_information(self, path: str | os.PathLike[str] = "") -> dict[str, object]:
        self._require_enabled()
        item = self._path(path) if path else self._android_vault
        info: dict[str, object] = {
            "path": str(item),
            "enabled": self.enabled,
            "requested_storage": self.requested_storage,
            "backend": self.storage_backend,
            "platform": self.platform,
            "shared_storage": str(self._android_storage_root) if self._android_storage_root else None,
        }
        if self.mobile and self.requested_storage == "android":
            record = self._record_for(item)
            if record:
                info["stored_path"] = record.get("stored")
                info["verified"] = self.verify_hidden(item)
        elif item.exists():
            st = item.stat()
            info.update(size=st.st_size, modified=st.st_mtime, is_file=item.is_file(), is_directory=item.is_dir(), reason=self.hidden_reason(item))
        return info

    def cleanup_orphans(self) -> list[Path]:
        self._require_enabled()
        if not (self.mobile and self.requested_storage == "android"):
            return []
        manifest = self._load_manifest()
        referenced = {str(Path(str(record.get("stored", ""))).resolve()) for record in manifest.values()}
        removed: list[Path] = []
        for child in self._android_vault.iterdir() if self._android_vault.exists() else []:
            if child.name in {self._ANDROID_NOMEDIA, "index.json", ".index.tmp"}:
                continue
            if str(child.resolve()) not in referenced:
                try:
                    if child.is_dir() and not child.is_symlink():
                        shutil.rmtree(child)
                    else:
                        child.unlink()
                    removed.append(child)
                except OSError:
                    pass
        return removed

    def information(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "requested_storage": self.requested_storage,
            "backend": self.storage_backend,
            "platform": self.platform,
            "vault": str(self._android_vault),
            "hidden_count": self.hidden_count() if self.enabled else 0,
        }
