"""Alera: a powerful Python filesystem and system toolkit."""

from .analysis import FileAnalysis
from .analytics import FilesystemAnalytics
from .android import AndroidStorage
from .archive import ArchiveManager
from .atomic import AtomicFiles
from .backup import BackupManager
from .binary import BinaryFileManager
from .cache import FileCache
from .calculator import StorageCalculator
from .cleanup import CleanupManager
from .config import HiddenConfig
from .core import Alera
from .crash import CrashLogger
from .database import FileDatabase
from .device import cpu_information, gpu_available, gpu_information, ram_information, spec_information, storage_information
from .directory import DirectoryTools
from .disks import DiskManager
from .encryption import EncryptionManager
from .environment import environment_variables, module_available, platform_information, python_information, restrictions
from .exceptions import AleraBinError, AleraError, AleraPathError, AleraValidationError
from .explorer import FileExplorer
from .experimental import Experimental
from .health import HealthChecker
from .hidden import HiddenFiles
from .hidden_explorer import HiddenFileExplorer
from .inspector import FileInspector
from .integrity import IntegrityManager
from .internal import AleraStorage
from .links import LinkManager
from .locking import FileLock
from .metadata import MetadataManager
from .mounts import MountManager
from .network import NetworkManager
from .operations import FileEvent, OperationEngine
from .paths import PathTools
from .permissions import PermissionTools
from .processes import ProcessManager
from .recovery import RecoveryManager
from .recycle_bin import RecycleBin
from .runtime import AleraRuntime
from .search_engine import SearchEngine, SearchResult
from .search_index import SearchIndex
from .security import FileSecurity
from .snapshots import SnapshotManager
from .storage import StorageAnalyzer
from .streams import StreamTools
from .sync import SyncManager
from .temporary import TemporaryFiles
from .transactions import FileTransaction
from .utilities import FileUtilities
from .vfs import VirtualFileSystem
from .versions import VersionManager
from .watcher import FileWatcher

__all__ = [
    "Alera", "AleraRuntime", "AleraStorage", "OperationEngine", "FileEvent", "CrashLogger", "HiddenConfig", "FileExplorer", "BinaryFileManager", "Experimental",
    "HiddenFiles", "HiddenFileExplorer", "TemporaryFiles", "ArchiveManager", "FileAnalysis", "AtomicFiles",
    "FileCache", "DirectoryTools", "FileLock", "PathTools", "PermissionTools", "SnapshotManager", "StreamTools",
    "FileWatcher", "SearchEngine", "SearchResult", "SearchIndex", "StorageAnalyzer", "MetadataManager", "LinkManager",
    "BackupManager", "RecoveryManager", "HealthChecker", "FileTransaction", "FileSecurity", "RecycleBin",
    "MountManager", "AndroidStorage", "FileInspector", "VirtualFileSystem", "DiskManager", "EncryptionManager",
    "VersionManager", "SyncManager", "FileUtilities", "CleanupManager", "FileDatabase", "ProcessManager",
    "NetworkManager", "StorageCalculator", "FilesystemAnalytics", "IntegrityManager", "AleraError",
    "AleraValidationError", "AleraPathError", "AleraBinError", "cpu_information", "gpu_information", "gpu_available",
    "ram_information", "storage_information", "spec_information", "restrictions", "python_information",
    "platform_information", "environment_variables", "module_available",
]

__version__ = "0.4.0"
