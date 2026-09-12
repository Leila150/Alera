"""Storage and transfer calculations."""

from __future__ import annotations


class StorageCalculator:
    UNITS = ("B", "KB", "MB", "GB", "TB", "PB")

    @classmethod
    def humanize(cls, value: int | float, base: int = 1024) -> str:
        number = float(value); index = 0
        while abs(number) >= base and index < len(cls.UNITS) - 1:
            number /= base; index += 1
        return f"{number:.2f} {cls.UNITS[index]}"

    @staticmethod
    def percent(used: int, total: int) -> float:
        return (used / total * 100.0) if total else 0.0

    @staticmethod
    def estimate_time(bytes_count: int, bytes_per_second: float) -> float:
        if bytes_per_second <= 0: raise ValueError("bytes_per_second must be positive")
        return bytes_count / bytes_per_second

    @staticmethod
    def compression_ratio(original: int, compressed: int) -> float:
        return compressed / original if original else 0.0

    @staticmethod
    def savings_percent(original: int, compressed: int) -> float:
        return (1 - compressed / original) * 100 if original else 0.0
