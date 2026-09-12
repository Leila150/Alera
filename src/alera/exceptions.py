"""Alera exception hierarchy."""


class AleraError(Exception):
    """Base exception for all Alera-specific errors."""


class AleraValidationError(AleraError, ValueError):
    """Raised when an Alera argument is invalid."""


class AleraPathError(AleraError, OSError):
    """Raised when a path cannot be used safely."""
