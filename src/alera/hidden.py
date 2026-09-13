"""Configurable hidden-file storage for Alera."""

from __future__ import annotations

import json
import os
import secrets
import shutil
import sys
from pathlib import Path
from typing import Iterator


class HiddenFiles:
    """Hide files behind a virtual original path.

    The default backend is ``.alera/hidden``. Android shared storage is
    opt-in with ``storage="android"``. Hidden storage can be disabled.
    """

    _ANDROID_HIDDEN_DIR = ".alera_hidden"
    _ANDROID_NOMEDIA = ".nomedia"
    _TOKEN_BYTES = 32

    def __init__(self, base_path: str | os.PathLike[str] = "", *, enabled: bool = True, storage: str = "internal") -> None:
        self.base_path = Path(base_path or Path.cwd()).expanduser().resolve()
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.enabled = bool(enabled)
        self.requested_storage = self._validate_storage(storage)
        self._android_storage_root = self._detect_android_storage()
        self._vault = self._select_vault()
        self._manifest = self._vault / "index.json"
        if self.enabled:
            self._initialize_backend()

    @staticmethod
    def _validate_storage(value: str) -> str:
        value = str(value).strip().lower()
        if value not in {"internal", "android"}:
            raise ValueError("storage must be 'internal' or 'android'")
        return value

    @property
    def platform(self) -> str:
        if os.name == "nt": return "windows"
        if sys.platform.startswith("android"): return "android"
        if sys.platform == "darwin": return "macos"
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
        return self._vault

    @property
    def storage_backend(self) -> str:
        if not self.enabled:
            return "disabled"
        if self.requested_storage == "android" and self.mobile and self._android_storage_root:
            return "android_shared_storage"
        return "alera_internal_storage"

    @property
    def vault(self) -> Path:
        return self._vault

    def configure(self, *, enabled: bool | None = None, storage: str | None = None) -> "HiddenFiles":
        if enabled is not None:
            self.enabled = bool(enabled)
        if storage is not None:
            self.requested_storage = self._validate_storage(storage)
        self._vault = self._select_vault()
        self._manifest = self._vault / "index.json"
        if self.enabled:
            self._initialize_backend()
        return self

    def _select_vault(self) -> Path:
        if self.requested_storage == "android" and self.mobile and self._android_storage_root:
            return self._android_storage_root / self._ANDROID_HIDDEN_DIR
        return self.base_path / ".alera" / "hidden"

    def _detect_android_storage(self) -> Path | None:
        if not self.mobile:
            return None
        candidates = []
        if os.environ.get("EXTERNAL_STORAGE"):
            candidates.append(Path(os.environ["EXTERNAL_STORAGE"]))
        candidates += [Path("/storage/emulated/0"), Path("/storage/self/primary"), Path("/sdcard")]
        for part_index, part in enumerate(self.base_path.parts):
            if part == "storage" and len(self.base_path.parts) > part_index + 2 and self.base_path.parts[part_index + 1] == "emulated" and self.base_path.parts[part_index + 2] == "0":
                candidates.insert(0, Path(*self.base_path.parts[:part_index + 3]))
                break
        for candidate in candidates:
            try:
                candidate = candidate.expanduser().resolve()
                if candidate.is_dir():
                    return candidate
            except OSError:
                pass
        return None

    def _initialize_backend(self) -> None:
        self._vault.mkdir(parents=True, exist_ok=True)
        try:
            self._vault.chmod(0o700)
        except OSError:
            pass
        if self.requested_storage == "android" and self.mobile:
            nomedia = self._vault / self._ANDROID_NOMEDIA
            try:
                nomedia.touch(exist_ok=True)
                nomedia.chmod(0o600)
            except OSError:
                pass
        if not self._manifest.exists():
            self._save_manifest({})

    def _require_enabled(self) -> None:
        if not self.enabled:
            raise RuntimeError("Alera hidden storage is disabled by hidden_config")

    def _path(self, value: str | os.PathLike[str]) -> Path:
        candidate = Path(value).expanduser()
        if not candidate.is_absolute():
            candidate = self.base_path / candidate
        candidate = candidate.resolve()
        try:
            candidate.relative_to(self.base_path)
        except ValueError as exc:
            raise ValueError("path escapes the HiddenFiles workspace") from exc
        return candidate

    def _load_manifest(self) -> dict[str, dict[str, object]]:
        try:
            data = json.loads(self._manifest.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save_manifest(self, data: dict[str, dict[str, object]]) -> None:
        self._vault.mkdir(parents=True, exist_ok=True)
        temporary = self._vault / ".index.tmp"
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.flush()
            try: os.fsync(handle.fileno())
            except OSError: pass
        os.replace(temporary, self._manifest)

    def _stored_path(self) -> Path:
        self._initialize_backend()
        while True:
            path = self._vault / secrets.token_hex(self._TOKEN_BYTES)
            if not path.exists():
                return path

    def _record(self, original: Path, stored: Path) -> None:
        data = self._load_manifest()
        data[str(original)] = {
            "stored": str(stored),
            "name": original.name,
            "relative": str(original.relative_to(self.base_path)),
            "is_file": original.is_file(),
            "is_directory": original.is_dir(),
        }
        self._save_manifest(data)

    def _record_for(self, original: Path) -> dict[str, object] | None:
        return self._load_manifest().get(str(original))

    def _unrecord(self, original: Path) -> None:
        data = self._load_manifest()
        data.pop(str(original), None)
        self._save_manifest(data)

    def _hide_to_vault(self, item: Path) -> Path:
        self._require_enabled()
        if not item.exists() and not item.is_symlink():
            raise FileNotFoundError(item)
        if self._vault == item or self._vault in item.parents:
            raise ValueError("cannot hide Alera's own hidden storage")
        if self._record_for(item):
            return item
        stored = self._stored_path()
        shutil.move(str(item), str(stored))
        self._record(item, stored)
        return item

    def _restore_from_vault(self, item: Path) -> Path:
        self._require_enabled()
        record = self._record_for(item)
        if not record:
            raise FileNotFoundError(f"hidden item not found: {item}")
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
        return self._hide_to_vault(self._path(path))

    def unhide(self, path: str | os.PathLike[str]) -> Path:
        return self._restore_from_vault(self._path(path))

    def is_hidden(self, path: str | os.PathLike[str]) -> bool:
        self._require_enabled()
        return self._record_for(self._path(path)) is not None

    def hidden_reason(self, path: str | os.PathLike[str]) -> str:
        self._require_enabled()
        return self.storage_backend if self.is_hidden(path) else "visible"

    def create_hidden_file(self, name: str, contents: str = "", overwrite: bool = False) -> Path:
        self._require_enabled()
        target = self._path(name)
        if target.exists() and not overwrite:
            raise FileExistsError(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(contents, encoding="utf-8")
        return self._hide_to_vault(target)

    def create_hidden_binary(self, name: str, contents: bytes, overwrite: bool = False) -> Path:
        self._require_enabled()
        target = self._path(name)
        if target.exists() and not overwrite:
            raise FileExistsError(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(bytes(contents))
        return self._hide_to_vault(target)

    def create_hidden_folder(self, name: str, parents: bool = False) -> Path:
        self._require_enabled()
        target = self._path(name)
        target.mkdir(parents=parents, exist_ok=False)
        return self._hide_to_vault(target)

    def list_hidden(self, path: str | os.PathLike[str] = "", recursive: bool = False) -> list[Path]:
        self._require_enabled()
        root = self._path(path) if path else self.base_path
        result = []
        for original in self._load_manifest():
            candidate = Path(original)
            try:
                candidate.relative_to(root)
            except ValueError:
                continue
            if recursive or candidate.parent == root:
                result.append(candidate)
        return sorted(result, key=lambda p: str(p).lower())

    def list_visible(self, path: str | os.PathLike[str] = "", recursive: bool = False) -> list[Path]:
        self._require_enabled()
        root = self._path(path) if path else self.base_path
        hidden = {str(p) for p in self.list_hidden(root, True)}
        items = root.rglob("*") if recursive else root.iterdir()
        return sorted((p for p in items if str(p) not in hidden and self._vault not in p.parents and p != self._vault and not p.name.startswith(".")), key=lambda p: str(p).lower())

    def hidden_files(self, path: str | os.PathLike[str] = "", recursive: bool = False) -> list[Path]:
        manifest = self._load_manifest()
        return [p for p in self.list_hidden(path, recursive) if Path(str(manifest[str(p)]["stored"])).is_file()]

    def hidden_folders(self, path: str | os.PathLike[str] = "", recursive: bool = False) -> list[Path]:
        manifest = self._load_manifest()
        return [p for p in self.list_hidden(path, recursive) if Path(str(manifest[str(p)]["stored"])).is_dir()]

    def visible_files(self, path: str | os.PathLike[str] = "", recursive: bool = False) -> list[Path]:
        return [p for p in self.list_visible(path, recursive) if p.is_file()]

    def visible_folders(self, path: str | os.PathLike[str] = "", recursive: bool = False) -> list[Path]:
        return [p for p in self.list_visible(path, recursive) if p.is_dir()]

    def walk_hidden(self, path: str | os.PathLike[str] = "") -> Iterator[Path]:
        yield from self.list_hidden(path, recursive=True)

    def hide_many(self, paths: list[str | os.PathLike[str]]) -> list[Path]:
        return [self.hide(p) for p in paths]

    def unhide_many(self, paths: list[str | os.PathLike[str]]) -> list[Path]:
        return [self.unhide(p) for p in paths]

    def hide_all(self, path: str | os.PathLike[str] = "") -> list[Path]:
        root = self._path(path) if path else self.base_path
        return self.hide_many([p for p in root.iterdir() if p != self._vault and not p.name.startswith(".")])

    def unhide_all(self, path: str | os.PathLike[str] = "") -> list[Path]:
        return self.unhide_many(self.list_hidden(path))

    def verify_hidden(self, path: str | os.PathLike[str]) -> bool:
        record = self._record_for(self._path(path))
        return bool(record and Path(str(record.get("stored", ""))).exists())

    def hidden_information(self, path: str | os.PathLike[str] = "") -> dict[str, object]:
        self._require_enabled()
        item = self._path(path) if path else self._vault
        record = self._record_for(item)
        return {
            "path": str(item),
            "enabled": self.enabled,
            "requested_storage": self.requested_storage,
            "backend": self.storage_backend,
            "vault": str(self._vault),
            "stored_path": record.get("stored") if record else None,
            "verified": self.verify_hidden(item) if record else False,
        }

    def cleanup_orphans(self) -> list[Path]:
        self._require_enabled()
        manifest = self._load_manifest()
        referenced = {str(Path(str(v.get("stored", ""))).resolve()) for v in manifest.values()}
        removed: list[Path] = []
        if not self._vault.exists():
            return removed
        for child in self._vault.iterdir():
            if child.name in {"index.json", ".index.tmp", self._ANDROID_NOMEDIA}:
                continue
            if str(child.resolve()) not in referenced:
                try:
                    shutil.rmtree(child) if child.is_dir() and not child.is_symlink() else child.unlink()
                    removed.append(child)
                except OSError:
                    pass
        return removed

    def hidden_count(self, path: str | os.PathLike[str] = "") -> int:
        return len(self.list_hidden(path))

    def information(self) -> dict[str, object]:
        return {"enabled": self.enabled, "requested_storage": self.requested_storage, "backend": self.storage_backend, "platform": self.platform, "vault": str(self._vault), "hidden_count": self.hidden_count() if self.enabled else 0}
