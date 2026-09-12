"""Python/runtime environment helpers."""

from __future__ import annotations

import importlib.util
import os
import platform
import site
import sys
import sysconfig
from pathlib import Path


def restrictions() -> dict[str, object]:
    """Describe practical runtime limitations visible from Python."""
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "executable": sys.executable,
        "cwd": str(Path.cwd()),
        "home": str(Path.home()),
        "prefix": sys.prefix,
        "base_prefix": sys.base_prefix,
        "virtual_environment": sys.prefix != sys.base_prefix,
        "user_site": site.getusersitepackages(),
        "site_packages": site.getsitepackages() if hasattr(site, "getsitepackages") else [],
        "filesystem_encoding": sys.getfilesystemencoding(),
        "max_path": os.pathconf("/", "PC_PATH_MAX") if hasattr(os, "pathconf") else None,
        "environment_variables": len(os.environ),
    }


def python_information() -> dict[str, object]:
    return {
        "version": platform.python_version(),
        "implementation": platform.python_implementation(),
        "compiler": platform.python_compiler(),
        "executable": sys.executable,
        "prefix": sys.prefix,
        "path": list(sys.path),
        "config": sysconfig.get_paths(),
    }


def module_available(module: str) -> bool:
    if not isinstance(module, str) or not module.strip():
        return False
    return importlib.util.find_spec(module) is not None


def environment_variables() -> dict[str, str]:
    return dict(os.environ)


def platform_information() -> dict[str, str]:
    return {
        "system": platform.system(),
        "node": platform.node(),
        "release": platform.release(),
        "version": platform.version(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "architecture": platform.architecture()[0],
    }
