"""Portable authenticated file encryption."""

from __future__ import annotations

import hashlib
import hmac
import os
from pathlib import Path


class EncryptionManager:
    """Encrypt files with password-derived authenticated encryption primitives.

    The format is portable and dependency-free. For high-value secrets, an
    audited cryptography library remains preferable.
    """

    MAGIC = b"ALERAENC1"

    def __init__(self, base_path: str | Path = "") -> None:
        self.base = Path(base_path or ".").expanduser().resolve()
        self.base.mkdir(parents=True, exist_ok=True)

    def _path(self, path: str | Path) -> Path:
        target = (self.base / path).resolve()
        target.relative_to(self.base)
        return target

    @staticmethod
    def _derive(password: str, salt: bytes) -> bytes:
        return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 250_000, dklen=32)

    @staticmethod
    def _crypt(data: bytes, key: bytes, nonce: bytes) -> bytes:
        output = bytearray()
        for counter, offset in enumerate(range(0, len(data), 64)):
            block = hashlib.sha256(key + nonce + counter.to_bytes(8, "big") + b"0").digest()
            block += hashlib.sha256(key + nonce + counter.to_bytes(8, "big") + b"1").digest()
            chunk = data[offset:offset + 64]
            output.extend(a ^ b for a, b in zip(chunk, block))
        return bytes(output)

    def encrypt(self, source: str | Path, destination: str | Path, password: str) -> Path:
        plain = self._path(source).read_bytes()
        salt, nonce = os.urandom(16), os.urandom(16)
        key = self._derive(password, salt)
        cipher = self._crypt(plain, key, nonce)
        tag = hmac.new(key, self.MAGIC + salt + nonce + cipher, hashlib.sha256).digest()
        target = self._path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(self.MAGIC + salt + nonce + tag + cipher)
        return target

    def decrypt(self, source: str | Path, destination: str | Path, password: str) -> Path:
        raw = self._path(source).read_bytes()
        header = len(self.MAGIC)
        if not raw.startswith(self.MAGIC) or len(raw) < header + 64:
            raise ValueError("Invalid Alera encrypted file")
        pos = header
        salt, nonce, tag = raw[pos:pos + 16], raw[pos + 16:pos + 32], raw[pos + 32:pos + 64]
        cipher = raw[pos + 64:]
        key = self._derive(password, salt)
        expected = hmac.new(key, self.MAGIC + salt + nonce + cipher, hashlib.sha256).digest()
        if not hmac.compare_digest(tag, expected):
            raise ValueError("Wrong password or corrupted encrypted file")
        target = self._path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(self._crypt(cipher, key, nonce))
        return target

    def generate_key(self, length: int = 32) -> str:
        if length <= 0:
            raise ValueError("length must be positive")
        return os.urandom(length).hex()
