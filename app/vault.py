"""Local AES-256 (Fernet) encryption for credentials and API keys."""

from __future__ import annotations

from cryptography.fernet import Fernet

from app.config import VAULT_KEY_PATH


class LocalVault:
    def __init__(self) -> None:
        self._key = self._load_or_create_key()
        self._fernet = Fernet(self._key)

    @staticmethod
    def _load_or_create_key() -> bytes:
        if VAULT_KEY_PATH.exists():
            return VAULT_KEY_PATH.read_bytes().strip()
        key = Fernet.generate_key()
        VAULT_KEY_PATH.write_bytes(key)
        return key

    def encrypt(self, plaintext: str) -> str:
        if not plaintext:
            return ""
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("utf-8")

    def decrypt(self, ciphertext: str) -> str:
        if not ciphertext:
            return ""
        return self._fernet.decrypt(ciphertext.encode("utf-8")).decode("utf-8")


vault = LocalVault()
