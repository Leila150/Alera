"""Cross-platform network information and connectivity helpers."""
from __future__ import annotations

import socket
import time


class NetworkManager:
    """Inspect local addressing, DNS, ports, and basic connectivity."""

    def hostname(self) -> str:
        return socket.gethostname()

    def fqdn(self) -> str:
        return socket.getfqdn()

    def addresses(self, host: str | None = None) -> list[str]:
        host = host or self.hostname()
        values = {info[4][0] for info in socket.getaddrinfo(host, None) if info[4]}
        return sorted(values)

    def resolve(self, host: str, family: int = 0) -> list[str]:
        return sorted({info[4][0] for info in socket.getaddrinfo(host, None, family=family) if info[4]})

    def port_open(self, host: str, port: int, timeout: float = 2.0) -> bool:
        if not 1 <= int(port) <= 65535:
            raise ValueError("port must be between 1 and 65535")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        try:
            with socket.create_connection((host, int(port)), timeout=timeout):
                return True
        except OSError:
            return False

    def latency(self, host: str = "1.1.1.1", port: int = 53, timeout: float = 2.0) -> float | None:
        start = time.perf_counter()
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return (time.perf_counter() - start) * 1000
        except OSError:
            return None

    def connectivity(self, host: str = "1.1.1.1", port: int = 53, timeout: float = 2.0) -> bool:
        return self.port_open(host, port, timeout)

    def information(self) -> dict:
        latency = self.latency()
        return {"hostname": self.hostname(), "fqdn": self.fqdn(), "addresses": self.addresses(), "internet": latency is not None, "latency_ms": latency}
