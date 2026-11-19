import logging

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict

from bad_email_check.app import create_app
from bad_email_check.config import Settings
from bad_email_check.security import RedactionFilter, redact


class ProbeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: int


@pytest.fixture
def app():
    application = create_app(Settings(_env_file=None, mode="test"))

    @application.post("/test/probe")
    async def probe(payload: ProbeInput):
        return {"value": payload.value}

    @application.get("/test/failure")
    async def failure():
        raise ValueError("private email body and token")

    return application


@pytest.fixture
def client(app):
    with TestClient(app, base_url="http://127.0.0.1:8000") as session:
        yield session


def test_liveness_has_no_configuration_or_secrets(client):
    assert client.get("/api/health").json() == {"status": "running"}


def test_readiness_missing_checkpoint(client):
    response = client.get("/api/readiness")
    assert response.status_code == 200
    assert response.json()["server_running"] is True
    assert response.json()["model_loaded"] is False
    assert response.json()["status"] == "setup_required"
    assert response.json()["code"] == "checkpoint_missing"


@pytest.mark.parametrize("exists", [False, True])
def test_configured_checkpoint_never_fakes_readiness(tmp_path, exists):
    checkpoint = tmp_path / "private-checkpoint"
    if exists:
        checkpoint.mkdir()
    app = create_app(Settings(_env_file=None, checkpoint_path=checkpoint))
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        response = client.get("/api/readiness")
    assert response.json()["model_loaded"] is False
    assert response.json()["code"] == "checkpoint_unavailable"
    assert str(checkpoint) not in response.text


@pytest.mark.parametrize("host", ["evil.example:8000", "localhost.evil:8000", "localhost:9000"])
def test_foreign_host_rejected(client, host):
    response = client.get("/api/health", headers={"Host": host})
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_host"


def test_duplicate_host_rejected(client):
    response = client.get(
        "/api/health", headers=[("Host", "127.0.0.1:8000"), ("Host", "evil.example:8000")]
    )
    assert response.status_code == 400


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "https://evil.example"},
        {"Origin": "null"},
        {},
        {"Origin": "http://127.0.0.1:8000", "Sec-Fetch-Site": "cross-site"},
        {"X-Email-Checker-Request": "1", "Sec-Fetch-Site": "same-site"},
    ],
)
def test_cross_site_posts_rejected(client, headers):
    response = client.post("/test/probe", json={"value": 1}, headers=headers)
    assert response.status_code == 403


@pytest.mark.parametrize(
    "headers", [{"Origin": "http://127.0.0.1:8000"}, {"X-Email-Checker-Request": "1"}]
)
def test_local_state_change_allowed(client, headers):
    assert client.post("/test/probe", json={"value": 1}, headers=headers).json() == {"value": 1}


def test_validation_errors_do_not_reflect_input(client):
    response = client.post(
        "/test/probe", json={"value": "PRIVATE_TOKEN"}, headers={"Origin": "http://127.0.0.1:8000"}
    )
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
    assert response.json()["retryable"] is False
    assert "PRIVATE_TOKEN" not in response.text


def test_internal_errors_are_generic(client, caplog):
    with caplog.at_level(logging.ERROR, logger="bad_email_check"):
        response = client.get("/test/failure")
    assert response.status_code == 500
    assert response.json()["code"] == "internal_error"
    assert "private" not in response.text + caplog.text
    assert "token" not in response.text + caplog.text


def test_redaction_handles_nested_secrets_and_raw_logs():
    data = {
        "body_text": "private",
        "nested": [{"refresh_token": "secret", "duration_ms": 4}],
        "Authorization": "Bearer private",
        "email-body": "private",
    }
    cleaned = redact(data)
    assert "private" not in str(cleaned)
    assert "secret" not in str(cleaned)
    assert cleaned["nested"][0]["duration_ms"] == 4
    record = logging.LogRecord("test", logging.ERROR, "", 1, data, (), None)
    assert RedactionFilter().filter(record)
    assert "private" not in record.getMessage()
    raw = logging.LogRecord("test", logging.ERROR, "", 1, "private %s", ("token",), None)
    RedactionFilter().filter(raw)
    assert raw.getMessage() == "Operational event"


def test_shell_and_assets(client):
    response = client.get("/")
    assert response.status_code == 200
    assert 'role="tablist"' in response.text
    assert "Linked websites and attachments were not inspected." in response.text
    assert "No assessment yet" in response.text
    for path in ("/static/app.css", "/static/app.js"):
        assert client.get(path).status_code == 200
    assert "default-src 'self'" in response.headers["Content-Security-Policy"]
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_unknown_route_structured_error(client):
    response = client.get("/api/unknown")
    assert response.status_code == 404
    assert response.json()["code"] == "http_error"
