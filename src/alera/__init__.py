"""Alera: a powerful Python filesystem and system toolkit."""

from .device import cpu_information, gpu_available, gpu_information, ram_information, spec_information, storage_information
from .environment import environment_variables, module_available, platform_information, python_information, restrictions
from .exceptions import AleraBinError, AleraError, AleraPathError, AleraValidationError
from .explorer import FileExplorer
from .temporary import TemporaryFiles

__all__ = [
    "FileExplorer",
    "TemporaryFiles",
    "AleraError",
    "AleraValidationError",
    "AleraPathError",
    "AleraBinError",
    "cpu_information",
    "gpu_information",
    "gpu_available",
    "ram_information",
    "storage_information",
    "spec_information",
    "restrictions",
    "python_information",
    "platform_information",
    "environment_variables",
    "module_available",
]

__version__ = "0.1.0"
