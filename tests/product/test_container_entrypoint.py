import io
import sys
from types import SimpleNamespace

import pytest

from bad_email_check import container_entrypoint


def test_import_only_start_does_not_touch_secret_store(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.delenv("EMAIL_CHECK_GMAIL_CLIENT_FILE", raising=False)
    calls = []
    monkeypatch.setattr(container_entrypoint, "start_app", lambda: calls.append("started"))
    monkeypatch.setattr(
        container_entrypoint.subprocess,
        "run",
        lambda *a, **k: pytest.fail("Unexpected secret operation"),
    )
    container_entrypoint.main()
    assert calls == ["started"]


@pytest.mark.parametrize("password", [b"", b"a" * 4097, b"invalid\0password"])
def test_invalid_unlock_secret_fails_without_echoing_it(tmp_path, monkeypatch, capsys, password):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("EMAIL_CHECK_GMAIL_CLIENT_FILE", "synthetic.json")
    monkeypatch.setattr(container_entrypoint.Path, "open", lambda *a, **k: io.BytesIO(password))
    monkeypatch.setattr(container_entrypoint, "start_app", lambda: pytest.fail("Should not start"))
    with pytest.raises(SystemExit) as error:
        container_entrypoint.main()
    assert error.value.code == 2
    assert capsys.readouterr().err == "Could not unlock Docker protected credential storage.\n"


def test_explicit_secret_unlocks_private_service_before_app(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("EMAIL_CHECK_GMAIL_CLIENT_FILE", "synthetic.json")
    monkeypatch.setattr(
        container_entrypoint.Path, "open", lambda *a, **k: io.BytesIO(b"synthetic-passphrase\n")
    )
    calls = []

    def run(command, **kwargs):
        assert kwargs["input"] == b"synthetic-passphrase"
        assert command == ["gnome-keyring-daemon", "--unlock", "--components=secrets"]
        calls.append("unlock")

    monkeypatch.setattr(container_entrypoint.subprocess, "run", run)
    monkeypatch.setitem(
        sys.modules,
        "secretstorage",
        SimpleNamespace(
            dbus_init=lambda: None,
            get_default_collection=lambda _: SimpleNamespace(is_locked=lambda: False),
        ),
    )
    monkeypatch.setattr(container_entrypoint, "start_app", lambda: calls.append("started"))
    container_entrypoint.main()
    assert calls == ["unlock", "started"]
