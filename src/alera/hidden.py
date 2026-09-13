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
    """Manage hidden files with a selectable storage backend.

    The default backend is Alera's private ``.alera/hidden`` directory.
    Android shared storage is opt-in through ``storage="android"``.
    ``enabled=False`` disables hidden storage without breaking Alera startup.
    """

    _ANDROID_HIDDEN_DIR = ".alera_hidden"
    _ANDROID_NOMEDIA = ".nomedia"
    _ANDROID_TOKEN_BYTES = 32

    def __init__(self, base_path: str | os.PathLike[str] = "", *, enabled: bool = True, storage: str = "internal") -> None:
        self.base_path = Path(base_path or Path.cwd()).expanduser().resolve()
        self.base_path.mkdir(parents=True, exist_ok=True)
        storage = str(storage).strip().lower()
        if storage not in {"internal", "android"}:
            raise ValueError("storage must be 'internal' or 'android'")
        self.enabled = bool(enabled)
        self.requested_storage = storage
        self._android_storage_root = self._detect_android_shared_storage()
        self._android_vault = self._internal_vault()
        if self.requested_storage == "android" and self._android_storage_root is not None:
            self._android_vault = self._android_storage_root / self._ANDROID_HIDDEN_DIR
        self._android_manifest = self._android_vault / "index.json"
        if self.enabled and self.requested_storage == "android" and self.mobile:
            self._initialize_android_storage()

    def _internal_vault(self) -> Path:
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
            storage = str(storage).strip().lower()
            if storage not in {"internal", "android"}:
                raise ValueError("storage must be 'internal' or 'android'")
            self.requested_storage = storage
        self._android_vault = self._internal_vault()
        if self.requested_storage == "android" and self.mobile and self._android_storage_root is not None:
            self._android_vault = self._android_storage_root / self._ANDROID_HIDDEN_DIR
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
        self._require_enabled()
        item = self._path(path)
        if self.mobile and self.requested_storage == "android" and self._android_record_for(item) is not None:
            return True
        if not item.exists() and not item.is_symlink():
            return False
        return self._dot_hidden(item) or self._windows_hidden(item)

    def hidden_reason(self, path: str | os.PathLike[str]) -> str:
        self._require_enabled()
        item = self._path(path)
        if self.mobile and self.requested_storage == "android" and self._android_record_for(item) is not None:
            return "android_shared_storage_randomized"
        dot = self._dot_hidden(item)
        windows = self._windows_hidden(item)
        if dot and windows:
            return "dotfile+windows_attribute"
        if dot:
            return "dotfile"
        if windows:
            return "windows_attribute"
        return "none"
