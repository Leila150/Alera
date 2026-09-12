"""Cross-process file locking utilities."""
from __future__ import annotations
import os
import time
from pathlib import Path
from .exceptions import AleraPathError, AleraValidationError

class FileLock:
    """Portable best-effort exclusive lock based on an atomic lock file."""
    def __init__(self, path: str | os.PathLike[str], timeout: float = 10.0, poll: float = 0.05) -> None:
        if timeout < 0 or poll <= 0:
            raise AleraValidationError("timeout must be non-negative and poll must be positive.")
        self.target = Path(path).expanduser().resolve()
        self.lock_path = Path(str(self.target) + ".alera.lock")
        self.timeout, self.poll = timeout, poll
        self._owned = False

    def acquire(self) -> bool:
        """Wait until the lock can be acquired."""
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(str(os.getpid()))
                self._owned = True
                return True
            except FileExistsError:
                if time.monotonic() >= deadline:
                    return False
                time.sleep(self.poll)

    def release(self) -> None:
        if not self._owned:
            return
        try:
            self.lock_path.unlink()
        except FileNotFoundError:
            pass
        self._owned = False

    def __enter__(self) -> "FileLock":
        if not self.acquire():
            raise TimeoutError(f"Could not acquire lock: {self.target}")
        return self

    def __exit__(self, *_: object) -> None:
        self.release()
