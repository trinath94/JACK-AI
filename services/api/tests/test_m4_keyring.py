"""Real Windows Credential Manager round trip (runs on the Windows CI runner)."""

from __future__ import annotations

import sys
import uuid

import pytest

from jack_api.ai.credentials import KeyringStore, default_store


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Credential Manager only")
def test_windows_credential_manager_round_trip() -> None:
    store = default_store()
    assert isinstance(store, KeyringStore) and store.secure
    assert "Windows" in store.kind or "WinVault" in store.kind, store.kind
    name = f"jack-ci-test:{uuid.uuid4()}"
    secret = "sk-ant-ci-" + uuid.uuid4().hex
    try:
        store.set(name, secret)
        assert store.get(name) == secret
    finally:
        store.delete(name)
    assert store.get(name) is None


@pytest.mark.skipif(sys.platform == "win32", reason="non-Windows behaviour")
def test_no_plaintext_fallback_without_secure_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    import keyring
    from keyring.backends import fail

    monkeypatch.delenv("JACK_INSECURE_TEST_CREDENTIALS", raising=False)
    monkeypatch.setattr(keyring, "get_keyring", lambda: fail.Keyring())
    store = default_store()
    ok, detail = store.available()
    assert ok is False and "No secure credential store" in (detail or "")
