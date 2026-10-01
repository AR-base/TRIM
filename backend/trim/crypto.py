"""Encryption of connector credentials at rest (Fernet: AES-128-CBC + HMAC-SHA256)."""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken


class SecretBoxError(RuntimeError):
    pass


class SecretBox:
    def __init__(self, key: str) -> None:
        if not key:
            raise SecretBoxError("TRIM_ENCRYPTION_KEY is not set; generate one with `trim key create`")
        try:
            self._fernet = Fernet(key.encode())
        except (ValueError, TypeError) as exc:
            raise SecretBoxError("TRIM_ENCRYPTION_KEY is not a valid Fernet key") from exc

    @staticmethod
    def generate_key() -> str:
        return Fernet.generate_key().decode()

    def encrypt(self, plaintext: str) -> bytes:
        return self._fernet.encrypt(plaintext.encode())

    def decrypt(self, ciphertext: bytes) -> str:
        try:
            return self._fernet.decrypt(ciphertext).decode()
        except InvalidToken as exc:
            raise SecretBoxError("could not decrypt secret: wrong key or tampered data") from exc
