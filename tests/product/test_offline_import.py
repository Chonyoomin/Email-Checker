import asyncio
import os
import socket
import sqlite3
from pathlib import Path

import httpx
import pytest

from bad_email_check.app import create_app
from bad_email_check.config import Settings

pytestmark = pytest.mark.real_model


def test_native_import_runs_real_model_with_network_blocked(tmp_path, monkeypatch, record_property):
    if os.environ.get("EMAIL_CHECK_RUN_REAL_MODEL") != "1":
        pytest.skip("Explicit real-model run required")
    attempts = []

    def denied(*args, **kwargs):
        attempts.append(True)
        raise AssertionError("Offline imported scan attempted a network connection")

    settings = Settings(
        _env_file=None,
        checkpoint_path=Path("checkpoints/laya-english"),
        gmail_client_file=None,
        metadata_db_path=tmp_path / "offline.sqlite3",
    )
    app = create_app(settings)

    async def scenario():
        with monkeypatch.context() as blocked:
            blocked.setattr(socket.socket, "connect", denied)
            blocked.setattr(socket, "create_connection", denied)
            async with app.router.lifespan_context(app):
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8000"
                ) as client:
                    readiness = (await client.get("/api/readiness")).json()
                    assert readiness["model_loaded"] and not readiness["is_test_double"]
                    raw = Path("tests/fixtures/offline_message.eml").read_bytes()
                    response = await client.post(
                        "/api/scans/import",
                        files={"file": ("offline.eml", raw)},
                        headers={"X-Email-Checker-Request": "1"},
                    )
                    assert response.status_code == 200
                    result = response.json()
                    assert result["status"] == "complete" and result["score"] is not None
                    assert (
                        result["score_kind"] == "uncalibrated_score"
                        and not result["is_test_double"]
                    )
                    assert result["runtime"]["inference_phase"] == "first"
                    assert result["runtime"]["model_tensor_bytes"] > 0
                    assert app.state.scanner.adapter.context_limit == 2048
                    assert app.state.scanner.adapter.assess_calls == 1
                    return result

    result = asyncio.run(scenario())
    assert not attempts
    with sqlite3.connect(settings.metadata_db_path) as connection:
        assert connection.execute("SELECT source,status FROM scans").fetchone() == (
            "eml",
            "complete",
        )
    record_property(
        "offline_import_metrics",
        {
            "timings": result["timings"],
            "runtime": result["runtime"],
            "network_attempts": len(attempts),
        },
    )
