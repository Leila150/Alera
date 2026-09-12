"""Cross-platform network diagnostics and connectivity helpers."""
from __future__ import annotations

import socket
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse


class NetworkManager:
    """DNS, addressing, ports, latency, URL, and batch network diagnostics."""

    def hostname(self) -> str:
        return socket.gethostname()

    def fqdn(self) -> str:
        return socket.getfqdn()

    def addresses(self, host: str | None = None) -> list[str]:
        host = host or self.hostname()
        try:
            return sorted({info[4][0] for info in socket.getaddrinfo(host, None) if info[4]})
        except OSError:
            return []

    def resolve(self, host: str, family: int = socket.AF_UNSPEC) -> list[str]:
        return self.addresses(host) if family == socket.AF_UNSPEC else sorted({info[4][0] for info in socket.getaddrinfo(host, None, family=family) if info[4]})

    def reverse(self, address: str) -> str | None:
        try: return socket.gethostbyaddr(address)[0]
        except OSError: return None

    @staticmethod
    def _port(port: int) -> int:
        port = int(port)
        if not 1 <= port <= 65535: raise ValueError("port must be between 1 and 65535")
        return port

    def port_open(self, host: str, port: int, timeout: float = 2.0) -> bool:
        port = self._port(port)
        if timeout <= 0: raise ValueError("timeout must be positive")
        try:
            with socket.create_connection((host, port), timeout=timeout): return True
        except OSError: return False

    def scan_ports(self, host: str, ports: list[int] | range, timeout: float = 0.5, workers: int = 32) -> dict[int, bool]:
        if timeout <= 0 or workers <= 0: raise ValueError("timeout and workers must be positive")
        ports = [self._port(p) for p in ports]
        result: dict[int, bool] = {}
        with ThreadPoolExecutor(max_workers=min(workers, max(1, len(ports)))) as pool:
            futures = {pool.submit(self.port_open, host, port, timeout): port for port in ports}
            for future in as_completed(futures): result[futures[future]] = future.result()
        return dict(sorted(result.items()))

    def latency(self, host: str = "1.1.1.1", port: int = 53, timeout: float = 2.0) -> float | None:
        start = time.perf_counter()
        try:
            with socket.create_connection((host, self._port(port)), timeout=timeout): return (time.perf_counter() - start) * 1000
        except OSError: return None

    def connectivity(self, host: str = "1.1.1.1", port: int = 53, timeout: float = 2.0) -> bool:
        return self.port_open(host, port, timeout)

    def url_probe(self, url: str, timeout: float = 5.0) -> dict[str, object]:
        """Probe a URL's host/port without requiring third-party HTTP packages."""
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname: raise ValueError("URL must be HTTP(S) with a hostname")
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        start = time.perf_counter()
        try:
            with socket.create_connection((parsed.hostname, port), timeout=timeout):
                return {"url": url, "host": parsed.hostname, "port": port, "reachable": True, "latency_ms": (time.perf_counter() - start) * 1000}
        except OSError as exc:
            return {"url": url, "host": parsed.hostname, "port": port, "reachable": False, "latency_ms": None, "error": str(exc)}

    def batch_latency(self, hosts: list[str], port: int = 53, timeout: float = 2.0, workers: int = 16) -> dict[str, float | None]:
        if workers <= 0: raise ValueError("workers must be positive")
        with ThreadPoolExecutor(max_workers=min(workers, max(1, len(hosts)))) as pool:
            futures = {pool.submit(self.latency, host, port, timeout): host for host in hosts}
            return {futures[f]: f.result() for f in as_completed(futures)}

    def information(self) -> dict[str, object]:
        latency = self.latency()
        return {"hostname": self.hostname(), "fqdn": self.fqdn(), "addresses": self.addresses(), "internet": latency is not None, "latency_ms": latency}
