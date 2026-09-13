"""Convenient coordinator for Alera's dedicated services."""

from __future__ import annotations

from .analytics import FilesystemAnalytics
from .android import AndroidStorage
from .backup import BackupManager
from .binary import BinaryFileManager
from .calculator import StorageCalculator
from .cleanup import CleanupManager
from .config import HiddenConfig, install_experimental_config
from .crash import CrashLogger
from .database import FileDatabase
from .disks import DiskManager
from .encryption import EncryptionManager
from .explorer import FileExplorer
from .experimental import Experimental
from .health import HealthChecker
from .hidden import HiddenFiles
from .inspector import FileInspector
from .integrity import IntegrityManager
from .internal import AleraStorage
from .metadata import MetadataManager
from .network import NetworkManager
from .operations import OperationEngine
from .permissions import PermissionTools
from .power import enhance_instance
from .processes import ProcessManager
from .recycle_bin import RecycleBin
from .runtime import AleraRuntime
from .search_engine import SearchEngine
from .search_index import SearchIndex
from .security import FileSecurity
from .storage import StorageAnalyzer
from .sync import SyncManager
from .transactions import FileTransaction
from .utilities import FileUtilities
from .versions import VersionManager
from .vfs import VirtualFileSystem
from .watcher import FileWatcher

install_experimental_config()


class Alera:
    """Unified entry point for Alera's filesystem/system services."""

    def __init__(self, base_path: str = "") -> None:
        self.base_path = base_path or "."
        self.internal = AleraStorage(self.base_path)
        self.operations = OperationEngine()
        self.crash = CrashLogger(self.base_path)
        self.crash.install()

        self.files = FileExplorer(self.base_path)
        self.files.INTERNAL = frozenset(set(self.files.INTERNAL) | {".alera"})
        self.files._bin_path = self.internal.path("bin")
        self.files._bin_path.mkdir(parents=True, exist_ok=True)

        # BinaryFileManager is the real binary service. Keep it separate from
        # FileExplorer so binary-only methods are never lost behind an alias.
        self.binary = BinaryFileManager(self.base_path)
        self.binary.INTERNAL = frozenset(set(self.binary.INTERNAL) | {".alera"})
        self.binary._bin_path = self.files._bin_path

        self.bin = RecycleBin(self.base_path)
        self.bin.bin_path = self.internal.path("bin")
        self.bin._manifest_path = self.bin.bin_path / self.bin.MANIFEST
        self.bin._journal_path = self.bin.bin_path / self.bin.JOURNAL
        self.bin._manifest = self.bin._load()
        self.bin._repair_manifest()

        self.search = SearchEngine(self.base_path, index_path=self.internal.path("index/search.sqlite3"))
        self.search.INTERNAL = frozenset(set(self.search.INTERNAL) | {".alera"})
        self.search_index = SearchIndex(self.base_path, database=self.internal.path("index/search_index.sqlite3"))
        self.inspector = FileInspector(self.base_path)

        self.hidden = HiddenFiles(self.base_path, enabled=True, storage="internal")
        self.experimental = Experimental(self.base_path)
        self._hidden_config = HiddenConfig(self.internal.path("config/experimental.json")).load()
        self._hidden_config.bind(lambda enabled, storage: self.hidden.configure(enabled=enabled, storage=storage))
        self.hidden.configure(enabled=self._hidden_config.enabled, storage=self._hidden_config.storage)
        self.experimental._hidden_config = self._hidden_config

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

        # Small compatibility aliases for the public binary facade.
        for alias, target in {
            "crc32": "binary_crc32",
            "adler32": "binary_adler32",
            "statistics": "binary_statistics",
            "hexdump": "binary_hexdump",
            "frequency": "binary_frequency",
            "entropy": "binary_entropy",
            "compare": "binary_compare",
            "compare_range": "binary_compare_range",
            "read": "binary_read",
            "write": "binary_write",
            "append": "binary_append",
            "hash": "binary_hash",
            "hashes": "binary_hashes",
        }.items():
            if not hasattr(self.binary, alias) and hasattr(self.binary, target):
                setattr(self.binary, alias, getattr(self.binary, target))

        for value in vars(self).values():
            if value is not self.operations and hasattr(value, "__dict__"):
                try:
                    value.operations = self.operations
                    enhance_instance(value)
                except Exception:
                    pass

        self.runtime = AleraRuntime(self)
        enhance_instance(self.runtime)
        enhance_instance(self)

    @property
    def hidden_config(self) -> HiddenConfig:
        """Experimental hidden-storage configuration."""
        return self._hidden_config

    def information(self) -> dict:
        services = {name: type(value).__name__ for name, value in vars(self).items() if name != "base_path" and not name.startswith("_")}
        return {
            "base_path": str(self.files.base_path),
            "internal": self.internal.information(),
            "hidden_config": self.hidden_config.as_dict(),
            "hidden": self.hidden.information() if self.hidden.enabled else {"enabled": False, "backend": "disabled"},
            "operations": self.operations.statistics(),
            "crash_logging": {"directory": str(self.crash.directory), "installed": self.crash.installed},
            "runtime": {"uptime": self.runtime.uptime, "shutdown": self.runtime.shutdown_state},
            "services": services,
        }

    def diagnostics(self, *, deep: bool = False) -> dict:
        """Return a complete runtime diagnostic report."""
        return self.runtime.diagnostics(include_services=True, deep=deep)

    def close(self) -> None:
        """Gracefully shut down runtime-owned resources."""
        self.runtime.shutdown()

    def service(self, name: str):
        if not name or name.startswith("_"):
            raise ValueError("Invalid service name")
        try:
            return getattr(self, name)
        except AttributeError as exc:
            raise KeyError(name) from exc

    def __enter__(self) -> "Alera":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()
