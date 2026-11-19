import pytest
from fastapi.testclient import TestClient

from bad_email_check.app import create_app
from bad_email_check.config import Settings

LOCAL_HEADERS = {"X-Email-Checker-Request": "1"}


@pytest.fixture
def client():
    with TestClient(
        create_app(Settings(_env_file=None, mode="test")), base_url="http://127.0.0.1:8000"
    ) as session:
        yield session


def test_paste_preview_returns_evidence_without_score(client):
    response = client.post("/api/previews/paste", json={"text": "Body text"}, headers=LOCAL_HEADERS)
    assert response.status_code == 200
    data = response.json()
    assert data["evidence"]["body_text"] == "Body text"
    assert data["evidence"]["source"] == "paste"
    assert "score" not in data
    assert "has not been checked" in data["coverage_statement"]


def test_eml_preview_returns_subject_and_inert_text(client):
    raw = (
        b"Subject: <script>alert(1)</script>\nContent-Type: text/html\n\n"
        b'<p>Example</p><img src="https://network-check.invalid/pixel">'
        b'<a href="javascript:alert(1)">&lt;img onerror=alert(2)&gt;</a>'
    )
    response = client.post(
        "/api/previews/import",
        content=raw,
        headers={**LOCAL_HEADERS, "Content-Type": "message/rfc822"},
    )
    assert response.status_code == 200
    assert response.json()["evidence"]["subject"] == "<script>alert(1)</script>"
    assert response.json()["evidence"]["links"][0]["hostname"] is None


@pytest.mark.parametrize("data", [{}, {"text": ""}, {"text": 1}, {"text": "body", "unknown": True}])
def test_invalid_paste_rejected_without_reflection(client, data):
    response = client.post("/api/previews/paste", json=data, headers=LOCAL_HEADERS)
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_paste"


def test_broken_json_generic_error(client):
    response = client.post(
        "/api/previews/paste",
        content=b'{"PRIVATE_BODY":',
        headers={**LOCAL_HEADERS, "Content-Type": "application/json"},
    )
    assert response.status_code == 422
    assert "PRIVATE_BODY" not in response.text


def test_foreign_origin_cannot_preview(client):
    response = client.post(
        "/api/previews/paste", json={"text": "body"}, headers={"Origin": "https://evil.example"}
    )
    assert response.status_code == 403


def test_import_requires_raw_eml_content_type(client):
    response = client.post("/api/previews/import", json={"text": "body"}, headers=LOCAL_HEADERS)
    assert response.status_code == 415


def test_oversized_stream_without_content_length_is_rejected_before_parser(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Oversized upload must not reach extraction")

    monkeypatch.setattr("bad_email_check.previews.extract_eml", forbidden)
    with TestClient(
        create_app(Settings(_env_file=None, max_upload_bytes=10)), base_url="http://127.0.0.1:8000"
    ) as session:
        response = session.post(
            "/api/previews/import",
            content=iter([b"x" * 5, b"x" * 6]),
            headers={**LOCAL_HEADERS, "Content-Type": "message/rfc822"},
        )
    assert response.status_code == 413


def test_declared_oversized_upload_rejected(client):
    response = client.post(
        "/api/previews/import",
        content=b"small",
        headers={**LOCAL_HEADERS, "Content-Type": "message/rfc822", "Content-Length": "999999999"},
    )
    assert response.status_code == 413


def test_preview_responses_are_not_cacheable(client):
    response = client.post("/api/previews/paste", json={"text": "body"}, headers=LOCAL_HEADERS)
    assert response.headers["cache-control"] == "no-store"
    assert "default-src 'self'" in response.headers["content-security-policy"]


def test_ui_uses_text_only_dom_sinks(client):
    script = client.get("/static/app.js").text
    assert "innerHTML" not in script
    assert "insertAdjacentHTML" not in script
    assert "document.createElement('li')" in script
    assert "previewController !== controller" in script
    assert "clearPreview" in script
