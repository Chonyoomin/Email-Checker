import sqlite3
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from test_scans import HEADERS, StubAdapter

from bad_email_check.app import create_app
from bad_email_check.config import Settings
from bad_email_check.extraction import extract_paste


@pytest.fixture
def session(tmp_path):
    settings = Settings(_env_file=None, mode="test", metadata_db_path=tmp_path / "metadata.sqlite3")
    adapter = StubAdapter()
    app = create_app(settings, adapter)
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        evidence = extract_paste(
            "From: private@example.org\nSubject: RETAIN_SUBJECT\n\nRETAIN_BODY", settings
        )
        scan = client.post("/api/scans", json={"text": "Synthetic scan"}, headers=HEADERS).json()
        yield (
            client,
            settings.metadata_db_path,
            adapter,
            {
                "scan_id": scan["scan_id"],
                "label": "scam",
                "evidence": evidence.model_dump(),
            },
        )


@pytest.mark.parametrize("reviewed", [False, True])
def test_default_off_does_not_save_supplied_content(session, reviewed):
    client, path, adapter, payload = session
    payload["reviewed"] = reviewed
    response = client.post("/api/feedback", json=payload, headers=HEADERS)
    assert response.status_code == 200 and not response.json()["content_retained"]
    with sqlite3.connect(path) as connection:
        table = "reviewed_examples" if reviewed else "feedback"
        other = "feedback" if reviewed else "reviewed_examples"
        assert connection.execute(f"SELECT content_json FROM {table}").fetchone() == (None,)
        assert connection.execute(f"SELECT COUNT(*) FROM {other}").fetchone() == (0,)
    assert b"RETAIN_BODY" not in path.read_bytes()
    assert b"private@example.org" not in path.read_bytes()
    assert adapter.calls == 1


@pytest.mark.parametrize("reviewed", [False, True])
def test_opt_in_exports_and_deletes_retained_content(session, reviewed):
    client, path, _, payload = session
    payload.update(retain_content=True, reviewed=reviewed)
    response = client.post("/api/feedback", json=payload, headers=HEADERS)
    feedback_id = response.json()["feedback_id"]
    assert response.json()["content_retained"]
    exported = client.get("/api/feedback/export", headers=HEADERS).json()["records"]
    assert len(exported) == 1 and exported[0]["reviewed"] is reviewed
    assert exported[0]["evidence"]["body_text"] == "RETAIN_BODY"
    assert "account_scope" not in exported[0]["evidence"]
    assert b"RETAIN_BODY" in path.read_bytes()
    assert client.delete(f"/api/feedback/{feedback_id}", headers=HEADERS).json() == {
        "deleted": True
    }
    assert client.get("/api/feedback/export", headers=HEADERS).json()["records"] == []
    assert b"RETAIN_BODY" not in path.read_bytes()


def test_unknown_scan_and_invalid_opt_in_fail(session):
    client, _, _, payload = session
    assert (
        client.post(
            "/api/feedback", json={**payload, "scan_id": str(uuid4())}, headers=HEADERS
        ).status_code
        == 404
    )
    for change in (
        {"scan_id": "invalid"},
        {"reviewed": True, "label": "unknown"},
        {"retain_content": True, "evidence": None},
    ):
        assert (
            client.post("/api/feedback", json={**payload, **change}, headers=HEADERS).status_code
            == 422
        )


def test_export_pagination_and_local_request_protection(session):
    client, _, _, payload = session
    ids = []
    for reviewed in (False, True):
        response = client.post(
            "/api/feedback", json={**payload, "reviewed": reviewed}, headers=HEADERS
        )
        ids.append(response.json()["feedback_id"])
    first = client.get("/api/feedback/export?limit=1", headers=HEADERS).json()
    second = client.get(
        "/api/feedback/export", params={"limit": 1, "after": first["next_after"]}, headers=HEADERS
    ).json()
    assert {first["records"][0]["feedback_id"], second["records"][0]["feedback_id"]} == set(ids)
    assert second["next_after"] is None
    assert client.get("/api/feedback/export").status_code == 403
    assert client.get("/api/feedback/export?limit=1&limit=2", headers=HEADERS).status_code == 422
    assert (
        client.delete(
            f"/api/feedback/{ids[0]}", headers={"Origin": "https://attacker.example"}
        ).status_code
        == 403
    )


def test_metadata_only_feedback_listing_recovers_retained_records_without_email_content(session):
    client, _, adapter, payload = session
    saved = client.post(
        "/api/feedback", json={**payload, "retain_content": True}, headers=HEADERS
    ).json()
    response = client.get("/api/feedback/export?include_content=false&limit=1", headers=HEADERS)
    assert response.status_code == 200
    record = response.json()["records"][0]
    assert record["feedback_id"] == saved["feedback_id"]
    assert record["content_retained"] is True and record["reviewed"] is False
    assert set(record) == {
        "feedback_id",
        "scan_id",
        "created_at",
        "label",
        "content_retained",
        "reviewed",
    }
    assert "RETAIN_" not in response.text and "private@example.org" not in response.text
    assert (
        client.delete(f"/api/feedback/{record['feedback_id']}", headers=HEADERS).status_code == 200
    )
    assert (
        client.get("/api/feedback/export?include_content=false", headers=HEADERS).json()["records"]
        == []
    )
    assert client.get("/api/feedback/export?include_content=false").status_code == 403
    assert adapter.calls == 1
