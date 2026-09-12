"""Alera: a powerful Python filesystem and system toolkit."""

from .analysis import FileAnalysis
from .archive import ArchiveManager
from .atomic import AtomicFiles
from .cache import FileCache
from .device import cpu_information, gpu_available, gpu_information, ram_information, spec_information, storage_information
from .directory import DirectoryTools
from .environment import environment_variables, module_available, platform_information, python_information, restrictions
from .exceptions import AleraBinError, AleraError, AleraPathError, AleraValidationError
from .explorer import FileExplorer
from .hidden import HiddenFiles
from .hidden_explorer import HiddenFileExplorer
from .locking import FileLock
from .paths import PathTools
from .permissions import PermissionTools
from .snapshots import SnapshotManager
from .streams import StreamTools
from .temporary import TemporaryFiles
from .watcher import FileWatcher

__all__ = [
    "FileExplorer", "HiddenFiles", "HiddenFileExplorer", "TemporaryFiles", "ArchiveManager",
    "FileAnalysis", "AtomicFiles", "FileCache", "DirectoryTools", "FileLock", "PathTools",
    "PermissionTools", "SnapshotManager", "StreamTools", "FileWatcher",
    "AleraError", "AleraValidationError", "AleraPathError", "AleraBinError",
    "cpu_information", "gpu_information", "gpu_available", "ram_information",
    "storage_information", "spec_information", "restrictions", "python_information",
    "platform_information", "environment_variables", "module_available",
]

__version__ = "0.1.0"
