"""Secret storage for provider credentials (Section 20: encrypted credentials, Windows
Credential Manager).

* Windows: ``keyring``'s Windows Credential Manager backend (DPAPI-protected, per user).
* macOS/Linux: whichever secure keyring backend is available (Keychain, Secret Service).
* No secure backend: storing secrets is refused. JACK never falls back to a plaintext file.
  Tests and CI may opt into a process-lifetime in-memory store with
  ``JACK_INSECURE_TEST_CREDENTIALS=1``; it is announced in the API as insecure.

Values never leave this module except to the provider that needs them; the API exposes
only whether a secret is set and a short hint.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Protocol

from jack_api.redaction import register_secret

log = logging.getLogger(__name__)
SERVICE = "JACK AI"


class CredentialStoreUnavailable(Exception):
    pass


class CredentialStore(Protocol):
    kind: str
    secure: bool

    def available(self) -> tuple[bool, str | None]: ...
    def get(self, name: str) -> str | None: ...
    def set(self, name: str, value: str) -> None: ...
    def delete(self, name: str) -> None: ...


class KeyringStore:
    secure = True

    def __init__(self) -> None:
        import keyring

        self._kr = keyring
        backend = type(keyring.get_keyring())
        self.kind = f"{backend.__module__}.{backend.__name__}"

    def available(self) -> tuple[bool, str | None]:
        return True, None

    def get(self, name: str) -> str | None:
        value = self._kr.get_password(SERVICE, name)
        if value:
            register_secret(value)
        return value

    def set(self, name: str, value: str) -> None:
        register_secret(value)
        self._kr.set_password(SERVICE, name, value)

    def delete(self, name: str) -> None:
        import keyring.errors

        try:
            self._kr.delete_password(SERVICE, name)
        except keyring.errors.PasswordDeleteError:
            pass


class MemoryStore:
    """Process-lifetime store for tests only. Not persistent, not secure."""

    kind = "memory (tests only)"
    secure = False

    def __init__(self) -> None:
        self._data: dict[str, str] = {}
        self._lock = threading.Lock()

    def available(self) -> tuple[bool, str | None]:
        return True, "In-memory test store: secrets are lost when JACK stops"

    def get(self, name: str) -> str | None:
        with self._lock:
            return self._data.get(name)

    def set(self, name: str, value: str) -> None:
        register_secret(value)
        with self._lock:
            self._data[name] = value

    def delete(self, name: str) -> None:
        with self._lock:
            self._data.pop(name, None)


class UnavailableStore:
    kind = "none"
    secure = False

    def __init__(self, reason: str) -> None:
        self._reason = reason

    def available(self) -> tuple[bool, str | None]:
        return False, self._reason

    def get(self, name: str) -> str | None:
        return None

    def set(self, name: str, value: str) -> None:
        raise CredentialStoreUnavailable(self._reason)

    def delete(self, name: str) -> None:
        return None


def default_store() -> CredentialStore:
    if os.environ.get("JACK_INSECURE_TEST_CREDENTIALS") == "1":
        log.warning("using the in-memory TEST credential store (JACK_INSECURE_TEST_CREDENTIALS=1)")
        return MemoryStore()
    try:
        import keyring
        from keyring.backends import fail

        backend = keyring.get_keyring()
        if isinstance(backend, fail.Keyring) or getattr(backend, "priority", 0) <= 0:
            return UnavailableStore(
                "No secure credential store is available on this system "
                "(Windows Credential Manager, macOS Keychain or Secret Service)")
        return KeyringStore()
    except Exception as exc:  # noqa: BLE001 - backend discovery failures are reported
        return UnavailableStore(f"Credential store error: {exc}")


def hint(secret: str | None) -> str | None:
    """A recognisable but useless fragment, e.g. 'sk-ant-…7Q2a'."""
    if not secret:
        return None
    prefix = "sk-ant-" if secret.startswith("sk-ant-") else ""
    return f"{prefix}…{secret[-4:]}"
