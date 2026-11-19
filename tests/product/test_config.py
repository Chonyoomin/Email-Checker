import pytest
from pydantic import ValidationError

from bad_email_check.config import Settings


@pytest.fixture(autouse=True)
def isolate_environment(monkeypatch):
    import os

    for name in list(os.environ):
        if name.startswith("EMAIL_CHECK_"):
            monkeypatch.delenv(name)


def test_defaults():
    settings = Settings(_env_file=None)
    assert (settings.host, settings.port) == ("127.0.0.1", 8000)
    assert settings.max_upload_bytes == 10 * 1024 * 1024
    assert settings.max_body_characters == 100_000
    assert settings.max_links == 200
    assert settings.queue_size == 1
    assert settings.scan_deadline_seconds == 120
    assert settings.mode == "production"


def test_environment_and_empty_checkpoint(monkeypatch):
    monkeypatch.setenv("EMAIL_CHECK_PORT", "8123")
    monkeypatch.setenv("EMAIL_CHECK_MAX_LINKS", "50")
    monkeypatch.setenv("EMAIL_CHECK_CHECKPOINT_PATH", "")
    monkeypatch.setenv("EMAIL_CHECK_MODE", "test")
    settings = Settings(_env_file=None)
    assert settings.port == 8123
    assert settings.max_links == 50
    assert settings.checkpoint_path is None
    assert settings.mode == "test"


@pytest.mark.parametrize(
    "values",
    [
        {"port": 0},
        {"port": 65536},
        {"queue_size": 0},
        {"max_upload_bytes": -1},
        {"max_body_characters": 0},
        {"max_links": -1},
        {"scan_deadline_seconds": 0},
        {"scan_deadline_seconds": float("inf")},
        {"mode": "fake"},
        {"host": "0.0.0.0"},
        {"host": "192.168.1.2"},
        {"host": "attacker.example"},
        {"host": "localhost.attacker"},
        {"unknown": True},
    ],
)
def test_invalid_configuration(values):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **values)


def test_explicit_nonloopback_optin():
    assert Settings(_env_file=None, host="0.0.0.0", allow_non_loopback=True).host == "0.0.0.0"


def test_ipv6_origins():
    settings = Settings(_env_file=None, host="::1")
    assert "http://[::1]:8000" in settings.origins
    assert "http://::1:8000" not in settings.origins


def test_env_example_loads():
    assert Settings(_env_file=".env.example").checkpoint_path is None
