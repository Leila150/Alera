"""Alera: a powerful, cross-platform Python filesystem and system toolkit."""

import inspect
import sys

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
from .power import enhance_classes
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
from .versions import VersionManager
from .vfs import VirtualFileSystem
from .watcher import FileWatcher

__all__ = [
    "Alera", "AleraRuntime", "AleraStorage", "OperationEngine", "FileEvent", "CrashLogger", "HiddenConfig",
    "FileExplorer", "BinaryFileManager", "Experimental", "HiddenFiles", "HiddenFileExplorer", "TemporaryFiles",
    "ArchiveManager", "FileAnalysis", "AtomicFiles", "FileCache", "DirectoryTools", "FileLock", "PathTools",
    "PermissionTools", "SnapshotManager", "StreamTools", "FileWatcher", "SearchEngine", "SearchResult", "SearchIndex",
    "StorageAnalyzer", "MetadataManager", "LinkManager", "BackupManager", "RecoveryManager", "HealthChecker",
    "FileTransaction", "FileSecurity", "RecycleBin", "MountManager", "AndroidStorage", "FileInspector",
    "VirtualFileSystem", "DiskManager", "EncryptionManager", "VersionManager", "SyncManager", "FileUtilities",
    "CleanupManager", "FileDatabase", "ProcessManager", "NetworkManager", "StorageCalculator", "FilesystemAnalytics",
    "IntegrityManager", "AleraError", "AleraValidationError", "AleraPathError", "AleraBinError", "cpu_information",
    "gpu_information", "gpu_available", "ram_information", "storage_information", "spec_information", "restrictions",
    "python_information", "platform_information", "environment_variables", "module_available",
]

# Public compatibility aliases. The canonical implementations keep their
# explicit names, while these common spellings make the API easier to use.
FileExplorer.read_text = FileExplorer.read_file
FileExplorer.write_text = FileExplorer.write_file
FileExplorer.append_text = FileExplorer.append_file
FileExplorer.read_binary = FileExplorer.read_binary_file
FileExplorer.write_binary = FileExplorer.write_binary_file
FileExplorer.append_binary = getattr(FileExplorer, "append_binary_file", None) or getattr(FileExplorer, "binary_append", None)
FileExplorer.files = FileExplorer.list_files
FileExplorer.folders = FileExplorer.list_folders
FileExplorer.search_extension = FileExplorer.find_by_extension

HiddenFiles.info = HiddenFiles.information
HiddenFiles.create_file = HiddenFiles.create_hidden_file
HiddenFiles.create_binary_file = HiddenFiles.create_hidden_binary
HiddenFiles.create_folder = HiddenFiles.create_hidden_folder

OperationEngine.stats = OperationEngine.statistics

# 0.5.0 universal power layer: patch every class defined inside Alera's own
# modules, including helper/dataclass classes that are not part of __all__.
# Existing domain-specific methods are never replaced.
_own_classes = []
for _module in list(sys.modules.values()):
    if _module is None or not getattr(_module, "__name__", "").startswith("alera."):
        continue
    for _name, _value in vars(_module).items():
        if inspect.isclass(_value) and getattr(_value, "__module__", "").startswith("alera."):
            _own_classes.append(_value)
enhance_classes(_own_classes)
del _own_classes, _module, _name, _value

__version__ = "0.5.0"
