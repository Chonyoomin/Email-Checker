import sqlite3

import pytest
from fastapi.testclient import TestClient
from test_scans import HEADERS, StubAdapter

from bad_email_check.app import create_app
from bad_email_check.config import Settings
from bad_email_check.metadata_store import MetadataError, MetadataStore


@pytest.mark.parametrize("source", ["paste", "eml"])
def test_scan_persists_only_allowlisted_metadata(tmp_path, source):
    path = tmp_path / "metadata.sqlite3"
    raw = b"From: private-sender@example.org\nSubject: PRIVATE_SUBJECT\n\nPRIVATE_BODY"
    app = create_app(Settings(_env_file=None, mode="test", metadata_db_path=path), StubAdapter())
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        if source == "paste":
            response = client.post("/api/scans", json={"text": raw.decode()}, headers=HEADERS)
        else:
            response = client.post(
                "/api/scans/import", files={"file": ("private.eml", raw)}, headers=HEADERS
            )
        assert response.status_code == 200
        result = response.json()
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        row = dict(connection.execute("SELECT * FROM scans").fetchone())
    assert row["scan_id"] == result["scan_id"]
    assert row["source"] == source and row["status"] == "complete"
    assert row["inference_ms"] == result["timings"]["inference_ms"]
    assert row["model_adapter_version"] == result["model_adapter_version"]
    assert set(row).isdisjoint(
        {"source_fingerprint", "account_scope", "source_message_id", "warnings", "assessment"}
    )
    database = path.read_bytes()
    for secret in (b"private-sender", b"PRIVATE_SUBJECT", b"PRIVATE_BODY", b"private.eml"):
        assert secret not in database


def test_metadata_failures_are_generic(tmp_path):
    store = MetadataStore(tmp_path / "missing" / "metadata.sqlite3")
    store.path.parent.mkdir()
    store.path.mkdir()
    with pytest.raises(MetadataError, match="Local metadata storage is unavailable"):
        store.initialize()


def test_metadata_write_failure_returns_structured_error(tmp_path):
    app = create_app(
        Settings(_env_file=None, mode="test", metadata_db_path=tmp_path / "store.sqlite3"),
        StubAdapter(),
    )
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        app.state.metadata.path = tmp_path / "missing" / "private-name.sqlite3"
        response = client.post("/api/scans", json={"text": "Synthetic body"}, headers=HEADERS)
    assert response.status_code == 503
    assert response.json()["code"] == "metadata_unavailable"
    assert "private-name" not in response.text
