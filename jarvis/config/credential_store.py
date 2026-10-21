"""Secure API-key storage backed by the operating system credential store."""
from __future__ import annotations

import keyring


_SERVICE = "JARVIS.AI"


class CredentialStoreError(RuntimeError):
    pass


class CredentialStore:
    def __init__(self) -> None:
        self._backend = keyring.get_keyring()
        backend_name = type(self._backend).__module__
        if not backend_name.startswith("keyring.backends.Windows"):
            raise CredentialStoreError(
                "Windows Credential Manager is unavailable. Configure a working "
                "Windows keyring backend before saving API keys."
            )

    def set(self, credential_id: str, secret: str) -> None:
        secret = secret.strip()
        if not secret:
            raise ValueError("API key cannot be empty.")
        try:
            keyring.set_password(_SERVICE, credential_id, secret)
        except Exception as exc:
            raise CredentialStoreError(
                f"Could not save the key to Windows Credential Manager: {exc}"
            ) from exc

    def get(self, credential_id: str) -> str | None:
        try:
            return keyring.get_password(_SERVICE, credential_id)
        except Exception as exc:
            raise CredentialStoreError(
                f"Could not read Windows Credential Manager: {exc}"
            ) from exc

    def delete(self, credential_id: str) -> None:
        try:
            keyring.delete_password(_SERVICE, credential_id)
        except keyring.errors.PasswordDeleteError:
            return
        except Exception as exc:
            raise CredentialStoreError(
                f"Could not remove the key from Windows Credential Manager: {exc}"
            ) from exc


def mask_secret(secret: str | None) -> str:
    if not secret:
        return "Not configured"
    return f"{'*' * max(4, len(secret) - 4)}{secret[-4:]}"
