"""Cross-platform device and operating-system information."""

from __future__ import annotations

import os
import platform
import shutil
import socket
import sys
from pathlib import Path


def _memory_linux() -> dict[str, int] | None:
    try:
        data = Path("/proc/meminfo").read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None
    values: dict[str, int] = {}
    for line in data.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0].rstrip(":") in {"MemTotal", "MemAvailable", "MemFree"}:
            values[parts[0].rstrip(":")] = int(parts[1]) * 1024
    if "MemTotal" not in values:
        return None
    total = values["MemTotal"]
    available = values.get("MemAvailable", values.get("MemFree", 0))
    return {"total": total, "available": available, "used": max(0, total - available), "free": available}


def cpu_information() -> dict[str, object]:
    return {
        "brand": platform.processor() or platform.machine() or "Unknown",
        "architecture": platform.machine(),
        "logical_cores": os.cpu_count() or 1,
        "python_implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
        "system": platform.system(),
        "release": platform.release(),
    }


def ram_information() -> dict[str, object]:
    memory = _memory_linux()
    if memory:
        return {"brand": "System memory", **memory, "unit": "bytes"}
    try:
        import ctypes
        class MemoryStatus(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("memory_load", ctypes.c_ulong), ("total", ctypes.c_ulonglong), ("avail", ctypes.c_ulonglong), ("page_total", ctypes.c_ulonglong), ("page_avail", ctypes.c_ulonglong), ("virt_total", ctypes.c_ulonglong), ("virt_avail", ctypes.c_ulonglong), ("ext_avail", ctypes.c_ulonglong)]
        status = MemoryStatus()
        status.length = ctypes.sizeof(MemoryStatus)
        if hasattr(ctypes, "windll") and ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return {"brand": "System memory", "total": status.total, "free": status.avail, "available": status.avail, "used": status.total - status.avail, "unit": "bytes"}
    except Exception:
        pass
    return {"brand": "Unknown", "total": None, "used": None, "free": None, "available": None, "unit": "bytes"}


def storage_information(path: str | os.PathLike[str] = ".") -> dict[str, object]:
    usage = shutil.disk_usage(path)
    return {"brand": "Filesystem storage", "path": str(Path(path).resolve()), "total": usage.total, "used": usage.used, "free": usage.free, "unit": "bytes"}


def gpu_information() -> dict[str, object]:
    """Return best-effort GPU information without third-party dependencies."""
    system = platform.system()
    candidates: list[str] = []
    if system == "Linux":
        drm = Path("/sys/class/drm")
        if drm.exists():
            for card in sorted(drm.glob("card[0-9]")):
                vendor = card / "device/vendor"
                device = card / "device/device"
                if vendor.exists() or device.exists():
                    candidates.append(" ".join(p.read_text(errors="ignore").strip() for p in (vendor, device) if p.exists()))
    if system == "Darwin":
        candidates.append("Apple GPU (system-reported; detailed query requires platform tools)")
    if system == "Windows":
        candidates.append("Windows GPU (detailed query requires platform APIs/tools)")
    return {"available": bool(candidates), "brand": candidates[0] if candidates else "Unknown", "devices": candidates}


def gpu_available() -> bool:
    return bool(gpu_information()["available"])


def network_information() -> dict[str, object]:
    hostname = socket.gethostname()
    try:
        addresses = sorted({item[4][0] for item in socket.getaddrinfo(hostname, None)})
    except OSError:
        addresses = []
    return {"hostname": hostname, "addresses": addresses, "fqdn": socket.getfqdn()}


def spec_information() -> dict[str, object]:
    return {
        "system": platform.system(),
        "release": platform.release(),
        "version": platform.version(),
        "machine": platform.machine(),
        "architecture": platform.architecture()[0],
        "processor": platform.processor() or "Unknown",
        "cpu": cpu_information(),
        "ram": ram_information(),
        "gpu": gpu_information(),
        "storage": storage_information(),
        "python": {"version": platform.python_version(), "implementation": platform.python_implementation(), "executable": sys.executable},
        "network": network_information(),
    }
