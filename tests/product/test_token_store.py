import traceback

import keyring
import pytest
from keyring.errors import PasswordDeleteError

from bad_email_check import token_store
from bad_email_check.token_store import (
    CredentialStoreError,
    CredentialStoreUnavailable,
    RefreshTokenStore,
    credential_service,
)


class MemoryKeyring:
    priority = 5

    def __init__(self):
        self.values = {}
        self.calls = []

    def set_password(self, service, username, password):
        self.calls.append("save")
        self.values[service, username] = password

    def get_password(self, service, username):
        self.calls.append("load")
        return self.values.get((service, username))

    def delete_password(self, service, username):
        self.calls.append("delete")
        self.values.pop((service, username), None)


@pytest.fixture
def backend(monkeypatch):
    backend = MemoryKeyring()
    monkeypatch.setattr(token_store, "native_keyring", lambda: backend)
    return backend


def test_save_load_replace_and_delete_are_account_scoped(backend):
    store = RefreshTokenStore()
    assert store.load("account-a") is None
    store.save("account-a", "synthetic-token-a")
    store.save("account-b", "synthetic-token-b")
    assert store.load("account-a") == "synthetic-token-a"
    assert store.load("account-b") == "synthetic-token-b"
    store.save("account-a", "synthetic-replacement")
    assert store.load("account-a") == "synthetic-replacement"
    store.delete("account-a")
    store.delete("account-a")
    assert store.load("account-a") is None
    assert store.load("account-b") == "synthetic-token-b"
    assert "account-a" not in str(list(backend.values))


@pytest.mark.parametrize("operation", ["save", "load", "delete"])
def test_backend_errors_are_generic_and_do_not_fall_back(backend, monkeypatch, tmp_path, operation):
    monkeypatch.chdir(tmp_path)
    store = RefreshTokenStore()
    synthetic_token = "synthetic-private-token"
    store.save("account", synthetic_token)

    def fail(*args):
        raise RuntimeError("synthetic-private-token synthetic-account")

    monkeypatch.setattr(
        backend,
        {"save": "set_password", "load": "get_password", "delete": "delete_password"}[operation],
        fail,
    )
    with pytest.raises(CredentialStoreError) as error:
        if operation == "save":
            store.save("account", synthetic_token)
        else:
            getattr(store, operation)("account")
    formatted = "".join(traceback.format_exception(error.value))
    assert "synthetic-private-token" not in formatted
    assert "synthetic-account" not in formatted
    assert not list(tmp_path.iterdir())


def test_delete_race_is_idempotent_but_denial_is_not_hidden(backend, monkeypatch):
    store = RefreshTokenStore()
    store.save("account", "synthetic-token")

    def denied(*args):
        raise PasswordDeleteError("synthetic-secret")

    monkeypatch.setattr(backend, "delete_password", denied)
    with pytest.raises(CredentialStoreError, match="Could not remove"):
        store.delete("account")

    def removed(service, username):
        backend.values.pop((service, username))
        raise PasswordDeleteError("Already removed")

    monkeypatch.setattr(backend, "delete_password", removed)
    store.delete("account")
    assert store.load("account") is None


@pytest.mark.parametrize("value", [None, True, "", " ", "a" * 257, "\ud800"])
def test_invalid_account_scope_never_reaches_backend(backend, value):
    store = RefreshTokenStore()
    for operation in (
        lambda: store.save(value, "synthetic"),
        lambda: store.load(value),
        lambda: store.delete(value),
    ):
        with pytest.raises(ValueError):
            operation()
    assert backend.calls == []


@pytest.mark.parametrize("value", [None, True, "", " ", "a" * 1025, "\ud800"])
def test_invalid_token_is_rejected_without_writing(backend, value):
    with pytest.raises(ValueError):
        RefreshTokenStore().save("account", value)
    assert backend.calls == []


def test_invalid_stored_token_is_a_sanitized_storage_failure(backend):
    backend.values[credential_service("account"), "refresh-token"] = ""
    with pytest.raises(CredentialStoreError, match="Could not read"):
        RefreshTokenStore().load("account")


def test_missing_native_backend_fails_closed(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(token_store.sys, "platform", "unsupported-platform")
    with pytest.raises(CredentialStoreUnavailable, match="no file fallback"):
        RefreshTokenStore()
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("priority", [0, -1])
def test_unusable_native_backend_is_not_selected(monkeypatch, priority):
    from keyring.backends import Windows

    monkeypatch.setattr(token_store.sys, "platform", "win32")
    monkeypatch.setattr(
        Windows, "WinVaultKeyring", lambda: type("Unavailable", (), {"priority": priority})()
    )
    with pytest.raises(CredentialStoreUnavailable):
        RefreshTokenStore()


def test_plaintext_configuration_cannot_replace_explicit_native_backend(monkeypatch):
    from keyring.backends import Windows

    backend = MemoryKeyring()
    monkeypatch.setattr(token_store.sys, "platform", "win32")
    monkeypatch.setenv("PYTHON_KEYRING_BACKEND", "keyrings.alt.file.PlaintextKeyring")
    monkeypatch.setattr(Windows, "WinVaultKeyring", lambda: backend)

    def forbid_discovery():
        pytest.fail("Automatic keyring discovery must not run")

    monkeypatch.setattr(keyring, "get_keyring", forbid_discovery)
    store = RefreshTokenStore()
    store.save("account", "synthetic-token")
    assert store.load("account") == "synthetic-token"
