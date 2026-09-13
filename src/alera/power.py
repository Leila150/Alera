"""Universal power layer for Alera services."""
from __future__ import annotations

import inspect
import time
from pathlib import Path
from typing import Any, Callable


def _public_methods(instance: Any) -> dict[str, str]:
    result: dict[str, str] = {}
    for name in dir(instance):
        if name.startswith("_"):
            continue
        try:
            value = getattr(instance, name)
        except Exception:
            continue
        if callable(value):
            try:
                result[name] = str(inspect.signature(value))
            except (TypeError, ValueError):
                result[name] = "(...)"
    return result


def _public_properties(instance: Any) -> list[str]:
    result: list[str] = []
    for name in dir(instance):
        if name.startswith("_"):
            continue
        try:
            value = getattr(instance, name)
        except Exception:
            continue
        if not callable(value):
            result.append(name)
    return sorted(result)


def _capabilities(self: Any) -> dict[str, Any]:
    methods = _public_methods(self)
    return {"class": type(self).__name__, "module": type(self).__module__, "methods": methods, "method_count": len(methods), "properties": _public_properties(self)}


def _describe(self: Any) -> dict[str, Any]:
    return {"class": type(self).__name__, "module": type(self).__module__, "doc": inspect.getdoc(type(self)) or "", "capabilities": _capabilities(self)}


def _health(self: Any) -> dict[str, Any]:
    checks: dict[str, Any] = {"class": type(self).__name__, "ok": True}
    try:
        path = getattr(self, "base_path", None)
        if path is not None:
            checks["base_path"] = str(path)
            checks["base_exists"] = bool(getattr(path, "exists", lambda: True)())
        if hasattr(self, "enabled"):
            checks["enabled"] = bool(getattr(self, "enabled"))
    except Exception as exc:
        checks["ok"] = False
        checks["error"] = f"{type(exc).__name__}: {exc}"
    return checks


def _snapshot(self: Any, *, include_private: bool = False) -> dict[str, Any]:
    data: dict[str, Any] = {"class": type(self).__name__}
    for key, value in getattr(self, "__dict__", {}).items():
        if not include_private and key.startswith("_"):
            continue
        if isinstance(value, (str, int, float, bool, type(None))):
            data[key] = value
        else:
            try:
                data[key] = str(value)
            except Exception:
                data[key] = f"<{type(value).__name__}>"
    return data


def _call(self, method: str, *args: Any, **kwargs: Any) -> Any:
    if not method or method.startswith("_"):
        raise ValueError("Only public service methods may be called")
    target = getattr(self, method, None)
    if not callable(target):
        raise AttributeError(f"{type(self).__name__} has no public callable {method!r}")
    return target(*args, **kwargs)


def _timed(self, method: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        result = _call(self, method, *args, **kwargs)
        return {"ok": True, "method": method, "elapsed": time.perf_counter() - started, "result": result}
    except Exception as exc:
        return {"ok": False, "method": method, "elapsed": time.perf_counter() - started, "error_type": type(exc).__name__, "error": str(exc)}


def _has(self, name: str) -> bool:
    return bool(name) and not name.startswith("_") and hasattr(self, name)


def _safe(self, callable_: Callable[..., Any], *args: Any, default: Any = None, **kwargs: Any) -> Any:
    try:
        return callable_(*args, **kwargs)
    except Exception:
        return default


def _resource_path(self, name: str = "") -> Path:
    """Resolve a service resource while refusing workspace traversal."""
    base = getattr(self, "base_path", None)
    if base is None:
        raise AttributeError("service has no base_path")
    candidate = Path(name).expanduser() if name else Path(".")
    target = (candidate if candidate.is_absolute() else Path(base) / candidate).resolve()
    root = Path(base).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError("resource path escapes service base_path") from exc
    return target


_METHODS = {"capabilities": _capabilities, "describe": _describe, "health": _health, "snapshot": _snapshot, "call": _call, "timed": _timed, "has": _has, "safe": _safe, "resource_path": _resource_path}


def enhance_class(cls: type) -> type:
    """Install missing universal power methods while preserving domain APIs."""
    for name, function in _METHODS.items():
        if not hasattr(cls, name):
            setattr(cls, name, function)
    return cls


def enhance_instance(instance: Any) -> Any:
    enhance_class(type(instance))
    return instance


def enhance_classes(classes: list[type] | tuple[type, ...] | set[type]) -> None:
    for cls in classes:
        if isinstance(cls, type):
            enhance_class(cls)
