"""Convenient coordinator for Alera's dedicated services."""

from __future__ import annotations

from .analytics import FilesystemAnalytics
from .android import AndroidStorage
from .backup import BackupManager
from .calculator import StorageCalculator
from .cleanup import CleanupManager
from .database import FileDatabase
from .disks import DiskManager
from .encryption import EncryptionManager
from .explorer import FileExplorer
from .health import HealthChecker
from .hidden import HiddenFiles
from .inspector import FileInspector
from .integrity import IntegrityManager
from .metadata import MetadataManager
from .network import NetworkManager
from .permissions import PermissionTools
from .processes import ProcessManager
from .recycle_bin import RecycleBin
from .search_engine import SearchEngine
from .security import FileSecurity
from .storage import StorageAnalyzer
from .sync import SyncManager
from .transactions import FileTransaction
from .utilities import FileUtilities
from .versions import VersionManager
from .vfs import VirtualFileSystem
from .watcher import FileWatcher


class Alera:
    """Unified entry point for Alera's filesystem and system services."""

    def __init__(self, base_path: str = "") -> None:
        self.base_path = base_path or "."
        self.files = FileExplorer(self.base_path)
        self.bin = RecycleBin(self.base_path)
        self.search = SearchEngine(self.base_path)
        self.inspector = FileInspector(self.base_path)
        self.hidden = HiddenFiles(self.base_path)
        self.android = AndroidStorage()
        self.backup = BackupManager(self.base_path)
        self.cleanup = CleanupManager(self.base_path)
        self.encryption = EncryptionManager(self.base_path)
        self.integrity = IntegrityManager(self.base_path)
        self.database = FileDatabase(self.base_path)
        self.metadata = MetadataManager(self.base_path)
        self.storage = StorageAnalyzer(self.base_path)
        self.disk = DiskManager()
        self.calculator = StorageCalculator()
        self.health = HealthChecker(self.base_path)
        self.security = FileSecurity(self.base_path)
        self.permissions = PermissionTools(self.base_path)
        self.network = NetworkManager()
        self.processes = ProcessManager()
        self.sync = SyncManager()
        self.transactions = FileTransaction(self.base_path)
        self.utilities = FileUtilities(self.base_path)
        self.vfs = VirtualFileSystem()
        self.versions = VersionManager(self.base_path)
        self.analytics = FilesystemAnalytics(self.base_path)
        self.watcher = FileWatcher(self.base_path)

    def information(self) -> dict:
        services = {name: type(value).__name__ for name, value in vars(self).items() if name != "base_path" and not name.startswith("_")}
        return {"base_path": str(self.files.base_path), "services": services}

    def service(self, name: str):
        """Return a service by attribute name."""
        if not name or name.startswith("_"): raise ValueError("Invalid service name")
        try: return getattr(self, name)
        except AttributeError as exc: raise KeyError(name) from exc
