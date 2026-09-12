"""Basic cross-platform network information."""

from __future__ import annotations

import socket


class NetworkManager:
    def hostname(self) -> str:
        return socket.gethostname()

    def addresses(self) -> list[str]:
        values = {info[4][0] for info in socket.getaddrinfo(self.hostname(), None) if info[4]}
        return sorted(values)

    def resolve(self, host: str) -> list[str]:
        return sorted({info[4][0] for info in socket.getaddrinfo(host, None) if info[4]})

    def connectivity(self, host: str = "1.1.1.1", port: int = 53, timeout: float = 2.0) -> bool:
        try:
            with socket.create_connection((host, port), timeout=timeout): return True
        except OSError:
            return False

    def information(self) -> dict:
        return {"hostname": self.hostname(), "addresses": self.addresses(), "internet": self.connectivity()}
