"""Storage, size, ratio, and transfer calculations."""

from __future__ import annotations


class StorageCalculator:
    UNITS = ("B", "KB", "MB", "GB", "TB", "PB", "EB")

    @classmethod
    def humanize(cls, value: int | float, base: int = 1024) -> str:
        if base <= 1:
            raise ValueError("base must be greater than 1")
        number = float(value)
        index = 0
        while abs(number) >= base and index < len(cls.UNITS) - 1:
            number /= base
            index += 1
        return f"{number:.2f} {cls.UNITS[index]}"

    @classmethod
    def parse(cls, value: str, base: int = 1024) -> int:
        if base <= 1:
            raise ValueError("base must be greater than 1")
        parts = value.strip().upper().split()
        if len(parts) != 2 or parts[1] not in cls.UNITS:
            raise ValueError("Expected a value such as '10 MB'")
        number = float(parts[0])
        return int(number * (base ** cls.UNITS.index(parts[1])))

    @staticmethod
    def percent(used: int, total: int) -> float:
        if used < 0 or total < 0:
            raise ValueError("sizes cannot be negative")
        return (used / total * 100.0) if total else 0.0

    @staticmethod
    def estimate_time(bytes_count: int, bytes_per_second: float) -> float:
        if bytes_count < 0 or bytes_per_second <= 0:
            raise ValueError("bytes_count must be non-negative and speed must be positive")
        return bytes_count / bytes_per_second

    @staticmethod
    def compression_ratio(original: int, compressed: int) -> float:
        if original < 0 or compressed < 0:
            raise ValueError("sizes cannot be negative")
        return compressed / original if original else 0.0

    @staticmethod
    def savings_percent(original: int, compressed: int) -> float:
        if original < 0 or compressed < 0:
            raise ValueError("sizes cannot be negative")
        return (1 - compressed / original) * 100 if original else 0.0
