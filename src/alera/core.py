"""Convenient coordinator for Alera's dedicated services."""

from __future__ import annotations

from .analytics import FilesystemAnalytics
from .android import AndroidStorage
from .backup import BackupManager
from .cleanup import CleanupManager
from .encryption import EncryptionManager
from .explorer import FileExplorer
from .hidden import HiddenFiles
from .inspector import FileInspector
from .integrity import IntegrityManager
from .network import NetworkManager
from .processes import ProcessManager
from .search_engine import SearchEngine
from .sync import SyncManager
from .utilities import FileUtilities
from .vfs import VirtualFileSystem
from .versions import VersionManager


class Alera:
    """Expose Alera services while keeping their implementations separate."""

    def __init__(self, base_path: str = "") -> None:
        self.base_path = base_path or "."
        self.files = FileExplorer(self.base_path)
        self.search = SearchEngine(self.base_path)
        self.inspector = FileInspector(self.base_path)
        self.hidden = HiddenFiles(self.base_path)
        self.android = AndroidStorage()
        self.backup = BackupManager(self.base_path)
        self.cleanup = CleanupManager(self.base_path)
        self.encryption = EncryptionManager(self.base_path)
        self.integrity = IntegrityManager(self.base_path)
        self.network = NetworkManager()
        self.processes = ProcessManager()
        self.sync = SyncManager()
        self.utilities = FileUtilities(self.base_path)
        self.vfs = VirtualFileSystem()
        self.versions = VersionManager(self.base_path)
        self.analytics = FilesystemAnalytics(self.base_path)

    def information(self) -> dict:
        return {
            "base_path": str(self.files.base),
            "services": [name for name in vars(self) if not name.startswith("_") and name != "base_path"],
        }
