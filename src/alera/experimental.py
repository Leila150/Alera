"""Experimental and platform-specific Alera features."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .hidden import HiddenFiles
from .hidden_explorer import HiddenFileExplorer


class Experimental:
    """Gateway to Alera features that are experimental or platform-specific.

    This class intentionally keeps experimental APIs separate from the stable
    FileExplorer API. Android shared-storage hiding is the primary feature
    currently exposed here.
    """

    def __init__(self, base_path: str | Path = "") -> None:
        self.base_path = Path(base_path).expanduser() if str(base_path) else Path.cwd()
        self.base_path = self.base_path.resolve()
        self.base_path.mkdir(parents=True, exist_ok=True)

        self.hidden = HiddenFiles(self.base_path)
        self.hidden_explorer = HiddenFileExplorer(self.base_path)

    @property
    def platform(self) -> str:
        """Return the detected platform used by the experimental backend."""
        return self.hidden.platform

    @property
    def android(self) -> bool:
        """Return True when Alera detects an Android environment."""
        return self.hidden.platform == "android"

    @property
    def android_shared_storage(self) -> bool:
        """Return whether shared Android internal storage is available."""
        return self.hidden.android_shared_storage

    @property
    def storage_backend(self) -> str:
        """Return the active hidden-storage backend."""
        return self.hidden.storage_backend

    def features(self) -> dict[str, Any]:
        """Describe experimental capabilities available in this environment."""
        return {
            "platform": self.platform,
            "android": self.android,
            "android_shared_storage": self.android_shared_storage,
            "storage_backend": self.storage_backend,
            "android_actual_shared_storage_hiding": self.android and self.android_shared_storage,
            "hidden_files": True,
            "hidden_file_explorer": True,
        }

    def android_hidden_storage(self) -> Path | None:
        """Return Alera's Android shared-storage hidden vault when available."""
        if not self.android:
            return None
        return self.hidden.android_hidden_storage

    def verify_hidden(self, path: str | Path) -> bool:
        """Verify that a path is currently hidden by the experimental backend."""
        return self.hidden.verify_hidden(path)

    def hide(self, path: str | Path) -> Path:
        """Hide a file or folder using the experimental hidden-storage backend."""
        return self.hidden.hide(path)

    def unhide(self, path: str | Path) -> Path:
        """Restore a previously hidden file or folder to its original path."""
        return self.hidden.unhide(path)

    def list_hidden(self, path: str | Path = "") -> list[Path]:
        """List hidden paths exposed through Alera's virtual namespace."""
        return self.hidden.list_hidden(path)

    def hidden_information(self, path: str | Path) -> dict[str, Any]:
        """Return diagnostic information about an experimental hidden path."""
        return self.hidden.hidden_information(path)

    def cleanup_hidden(self) -> list[Path]:
        """Remove orphaned experimental hidden-storage entries."""
        return self.hidden.cleanup_orphans()

    def explorer(self) -> HiddenFileExplorer:
        """Return the experimental explorer with virtual hidden-path support."""
        return self.hidden_explorer
