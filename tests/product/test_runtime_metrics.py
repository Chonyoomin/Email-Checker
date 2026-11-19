import sqlite3
import sys

from fastapi.testclient import TestClient
from test_scans import HEADERS, StubAdapter

from bad_email_check.app import create_app
from bad_email_check.config import Settings
from bad_email_check.metadata_store import MetadataStore
from bad_email_check.runtime_metrics import process_memory


def test_api_and_database_distinguish_first_warm_cached_and_not_run(tmp_path, monkeypatch):
    adapter = StubAdapter()
    adapter.model_tensor_bytes = 123456
    monkeypatch.setattr("bad_email_check.laya_adapter.LayaAdapter", lambda _: adapter)
    settings = Settings(
        _env_file=None,
        mode="test",
        checkpoint_path=tmp_path,
        metadata_db_path=tmp_path / "metadata.sqlite3",
    )
    app = create_app(settings)
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        results = [
            client.post("/api/scans", json={"text": text}, headers=HEADERS).json()
            for text in ("One", "One", "Two")
        ]
        results.append(
            client.post(
                "/api/scans/import", files={"file": ("empty.eml", b"")}, headers=HEADERS
            ).json()
        )
    assert [item["runtime"]["inference_phase"] for item in results] == [
        "first",
        "cached",
        "warm",
        "not_run",
    ]
    assert results[1]["timings"]["inference_ms"] == 0
    assert adapter.calls == 2
    for item in results:
        assert item["runtime"]["model_load_ms"] > 0
        assert item["runtime"]["model_tensor_bytes"] == 123456
    with sqlite3.connect(settings.metadata_db_path) as connection:
        rows = connection.execute(
            "SELECT inference_phase, model_load_ms, model_tensor_bytes FROM scans ORDER BY rowid"
        ).fetchall()
    assert [row[0] for row in rows] == ["first", "cached", "warm", "not_run"]
    assert all(row[1] > 0 and row[2] == 123456 for row in rows)


def test_native_process_memory_is_measured_when_supported():
    rss, peak = process_memory()
    if sys.platform == "win32" or sys.platform.startswith("linux"):
        assert rss > 0 and peak >= rss


def test_existing_metadata_database_is_upgraded_without_losing_rows(tmp_path):
    settings = Settings(_env_file=None, mode="test", metadata_db_path=tmp_path / "metadata.sqlite3")
    with TestClient(
        create_app(settings, StubAdapter()), base_url="http://127.0.0.1:8000"
    ) as client:
        scan_id = client.post("/api/scans", json={"text": "Existing"}, headers=HEADERS).json()[
            "scan_id"
        ]
    with sqlite3.connect(settings.metadata_db_path) as connection:
        for name in (
            "model_load_ms",
            "model_tensor_bytes",
            "process_rss_bytes",
            "process_peak_rss_bytes",
            "inference_phase",
        ):
            connection.execute(f"ALTER TABLE scans DROP COLUMN {name}")
        connection.execute("PRAGMA user_version = 2")
    MetadataStore(settings.metadata_db_path).initialize()
    with TestClient(
        create_app(settings, StubAdapter()), base_url="http://127.0.0.1:8000"
    ) as client:
        assert client.post("/api/scans", json={"text": "New"}, headers=HEADERS).status_code == 200
    with sqlite3.connect(settings.metadata_db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM scans").fetchone() == (2,)
        assert connection.execute(
            "SELECT model_load_ms FROM scans WHERE scan_id = ?", (scan_id,)
        ).fetchone() == (None,)


def test_linux_memory_collection_and_unavailable_values(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(
        "bad_email_check.runtime_metrics.Path.read_text", lambda _: "VmRSS: 20 kB\nVmHWM: 30 kB\n"
    )
    assert process_memory() == (20480, 30720)
    monkeypatch.setattr("bad_email_check.runtime_metrics.Path.read_text", lambda _: "unavailable")
    assert process_memory() == (None, None)
