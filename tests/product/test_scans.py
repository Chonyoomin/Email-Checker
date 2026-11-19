import asyncio
import threading
import time
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from bad_email_check.app import create_app
from bad_email_check.config import Settings
from bad_email_check.contracts import ModelAssessment
from bad_email_check.extraction import extract_paste
from bad_email_check.laya_adapter import CoverageError
from bad_email_check.model_adapter import AdapterIdentity
from bad_email_check.model_adapter import TestDoubleAdapter as FixtureAdapter
from bad_email_check.questions import QUESTION_SET_VERSION
from bad_email_check.scan_service import ScanError, ScanService

HEADERS = {"X-Email-Checker-Request": "1"}


class StubAdapter:
    def __init__(self, behavior=None):
        self.identity = AdapterIdentity("unit-fixture", "unit-v1", QUESTION_SET_VERSION, False)
        self.behavior = behavior
        self.calls = 0

    def assess(self, evidence):
        self.calls += 1
        if self.behavior:
            self.behavior()
        return ModelAssessment(
            overall_scam=0.8,
            credential_theft=0.0,
            impersonation=0.0,
            payment_fraud=0.0,
            pressure_tactics=0.0,
            checkpoint_revision=self.identity.checkpoint_revision,
            question_set_version=self.identity.question_set_version,
            model_adapter_version=self.identity.adapter_version,
            input_complete=True,
            input_coverage=1.0,
        )


@pytest.fixture
def settings():
    return Settings(_env_file=None, mode="test")


@pytest.fixture
def client(settings):
    with TestClient(
        create_app(settings, StubAdapter()), base_url="http://127.0.0.1:8000"
    ) as session:
        yield session


def test_valid_paste_scan_is_versioned_and_uses_only_overall(client):
    response = client.post("/api/scans", json={"text": "Example body"}, headers=HEADERS)
    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "complete"
    assert result["score"] == 80
    assert result["score_kind"] == "uncalibrated_score"
    assert result["question_set_version"] == QUESTION_SET_VERSION
    assert result["assessment"]["overall_scam"] == 0.8
    assert result["assessment"]["credential_theft"] == 0.0
    assert result["assessment"]["question_set_version"] == QUESTION_SET_VERSION
    assert result["risk_label"] is None
    assert len(result["source_fingerprint"]) == 64


def test_valid_multipart_import(client):
    response = client.post(
        "/api/scans/import",
        files={
            "file": (
                "example.eml",
                b"From: sender@example.org\nSubject: Example\n\nBody",
                "message/rfc822",
            )
        },
        headers=HEADERS,
    )
    assert response.status_code == 200
    assert response.json()["score"] == 80


@pytest.mark.parametrize(
    "data",
    [
        {"text": "body", "unknown": True},
        {"source": "gmail", "source_message_id": "../bad", "account_scope": "a"},
        {"source": "gmail", "source_message_id": "123"},
        {"text": ""},
        {"text": True},
        {"source": "paste", "text": "body", "account_scope": "a"},
    ],
)
def test_invalid_scan_inputs(client, data):
    response = client.post("/api/scans", json=data, headers=HEADERS)
    assert response.status_code == 422
    assert "score" not in response.json()


def test_valid_gmail_id_cannot_access_unconnected_account(client):
    response = client.post(
        "/api/scans",
        json={"source": "gmail", "source_message_id": "abc123", "account_scope": "unconnected"},
        headers=HEADERS,
    )
    assert response.status_code == 503
    assert response.json()["code"] == "gmail_setup_required"


def test_missing_model_never_falls_back_to_fake(settings):
    with TestClient(create_app(settings), base_url="http://127.0.0.1:8000") as client:
        response = client.post("/api/scans", json={"text": "body"}, headers=HEADERS)
    assert response.status_code == 503
    assert response.json()["code"] == "model_not_ready"
    assert "score" not in response.json()


def test_oversized_import_and_wrong_field_rejected():
    settings = Settings(_env_file=None, mode="test", max_upload_bytes=10)
    with TestClient(
        create_app(settings, StubAdapter()), base_url="http://127.0.0.1:8000"
    ) as client:
        response = client.post(
            "/api/scans/import", files={"file": ("x.eml", b"x" * 11)}, headers=HEADERS
        )
        assert response.status_code == 413
        response = client.post(
            "/api/scans/import", files={"wrong": ("x.eml", b"body")}, headers=HEADERS
        )
        assert response.status_code == 422


def test_incomplete_or_failed_extraction_never_runs_model(settings):
    adapter = StubAdapter()
    with TestClient(create_app(settings, adapter), base_url="http://127.0.0.1:8000") as client:
        response = client.post("/api/scans", json={"text": " "}, headers=HEADERS)
    assert response.json()["status"] == "failed"
    assert response.json()["score"] is None
    assert adapter.calls == 0


def test_fake_is_explicit_in_api_and_ui(settings):
    settings = settings.model_copy(update={"model_backend": "test_double"})
    with TestClient(create_app(settings), base_url="http://127.0.0.1:8000") as client:
        ready = client.get("/api/readiness").json()
        result = client.post("/api/scans", json={"text": "body"}, headers=HEADERS).json()
        script = client.get("/static/app.js").text
    assert ready["is_test_double"] and not ready["model_loaded"]
    assert "TEST DOUBLE" in ready["message"]
    assert result["is_test_double"] and result["score"] is None
    assert any("TEST DOUBLE" in warning for warning in result["warnings"])
    assert "TEST DOUBLE" in script


def test_production_rejects_test_double_backend_and_injection(settings):
    with pytest.raises(ValueError):
        Settings(_env_file=None, model_backend="test_double")
    with pytest.raises(ValueError, match="Production"):
        create_app(Settings(_env_file=None), FixtureAdapter(settings))


@pytest.mark.parametrize(
    "failure,expected",
    [
        (lambda: (_ for _ in ()).throw(CoverageError()), "needs_review"),
        (lambda: (_ for _ in ()).throw(RuntimeError("PRIVATE_BODY")), "model_failed"),
    ],
)
def test_context_and_model_failure_never_return_zero_score(settings, failure, expected):
    with TestClient(
        create_app(settings, StubAdapter(failure)), base_url="http://127.0.0.1:8000"
    ) as client:
        response = client.post("/api/scans", json={"text": "body"}, headers=HEADERS)
    assert response.json().get("score") is None
    assert "PRIVATE_BODY" not in response.text
    assert response.json().get("status", response.json().get("code")) == expected


def test_nan_and_invalid_output_return_failure(settings):
    adapter = StubAdapter()
    original = adapter.assess

    def invalid(evidence):
        return original(evidence).model_copy(update={"overall_scam": float("nan")})

    adapter.assess = invalid
    with TestClient(create_app(settings, adapter), base_url="http://127.0.0.1:8000") as client:
        response = client.post("/api/scans", json={"text": "body"}, headers=HEADERS)
    assert response.status_code == 502
    assert "score" not in response.json()


def test_cache_is_bounded_clearable_and_allocates_new_scan_id(settings):
    adapter = StubAdapter()
    service = ScanService(settings.model_copy(update={"cache_entries": 1}), adapter)

    async def scenario():
        first = extract_paste("first", settings)
        a = await service.scan(first, time.monotonic(), 0.0)
        b = await service.scan(first, time.monotonic(), 0.0)
        assert a.scan_id != b.scan_id and a.source_fingerprint == b.source_fingerprint
        assert adapter.calls == 1
        await service.scan(extract_paste("second", settings), time.monotonic(), 0.0)
        assert len(service.cache) == 1
        await service.scan(first, time.monotonic(), 0.0)
        assert adapter.calls == 3
        service.clear_cache()
        assert not service.cache

    try:
        asyncio.run(scenario())
    finally:
        service.close()


def test_cache_keys_change_with_every_version_and_account(settings):
    adapter = StubAdapter()
    service = ScanService(settings, adapter)
    evidence = extract_paste("body", settings)
    original = service.cache_key(evidence)
    for field in ("checkpoint_revision", "adapter_version", "question_set_version"):
        identity = adapter.identity
        adapter.identity = replace(identity, **{field: "changed"})
        assert service.cache_key(evidence) != original
        adapter.identity = identity
    for field in ("preprocessing", "calibration", "thresholds"):
        versions = service.cache_versions
        service.cache_versions = replace(versions, **{field: "changed"})
        assert service.cache_key(evidence) != original
        service.cache_versions = versions
    for field, value in (
        ("parser_version", "changed"),
        ("account_scope", "different"),
        ("fingerprint", "f" * 64),
    ):
        assert service.cache_key(evidence.model_copy(update={field: value})) != original
    service.close()


def test_queue_is_bounded_and_only_one_inference_runs(settings):
    gate = threading.Event()
    entered = threading.Event()

    def block():
        entered.set()
        assert gate.wait(2)

    adapter = StubAdapter(block)
    service = ScanService(settings, adapter)

    async def scenario():
        first = asyncio.create_task(
            service.scan(extract_paste("first", settings), time.monotonic(), 0)
        )
        assert await asyncio.to_thread(entered.wait, 1)
        second = asyncio.create_task(
            service.scan(extract_paste("second", settings), time.monotonic(), 0)
        )
        await asyncio.sleep(0)
        with pytest.raises(ScanError) as error:
            await service.scan(extract_paste("third", settings), time.monotonic(), 0)
        assert error.value.code == "scan_busy" and error.value.retryable
        assert adapter.calls == 1
        gate.set()
        await asyncio.gather(first, second)
        assert adapter.calls == 2

    try:
        asyncio.run(scenario())
    finally:
        gate.set()
        service.close()


def test_timeout_retains_running_worker_slot(settings):
    gate = threading.Event()
    adapter = StubAdapter(lambda: gate.wait(2))
    service = ScanService(settings.model_copy(update={"scan_deadline_seconds": 0.03}), adapter)

    async def scenario():
        with pytest.raises(ScanError) as error:
            await service.scan(extract_paste("body", settings), time.monotonic(), 0)
        assert error.value.code == "scan_timeout" and error.value.retryable
        assert service.slots.acquire(blocking=False)
        assert not service.slots.acquire(blocking=False)
        service.slots.release()

    try:
        asyncio.run(scenario())
    finally:
        gate.set()
        service.close()


def test_p3_f1_repeated_timeouts_cannot_accumulate_retained_evidence(settings):
    gate = threading.Event()
    adapter = StubAdapter(lambda: gate.wait(2))
    service = ScanService(settings.model_copy(update={"scan_deadline_seconds": 0.01}), adapter)

    async def scenario():
        outcomes = []
        for index in range(8):
            with pytest.raises(ScanError) as error:
                await service.scan(extract_paste(f"body {index}", settings), time.monotonic(), 0)
            outcomes.append(error.value.code)
        assert outcomes[:2] == ["scan_timeout", "scan_timeout"]
        assert outcomes[2:] == ["scan_busy"] * 6
        assert service.executor._work_queue.qsize() <= 1
        assert adapter.calls == 1

    try:
        asyncio.run(scenario())
    finally:
        gate.set()
        service.close()


def test_expired_queue_drains_without_unhandled_future_logs(settings):
    gate = threading.Event()
    adapter = StubAdapter(lambda: gate.wait(2))
    service = ScanService(settings.model_copy(update={"scan_deadline_seconds": 0.01}), adapter)

    async def scenario():
        errors = []
        asyncio.get_running_loop().set_exception_handler(
            lambda loop, context: errors.append(context)
        )
        for text in ("first", "second"):
            with pytest.raises(ScanError, match="deadline"):
                await service.scan(extract_paste(text, settings), time.monotonic(), 0)
        gate.set()
        await asyncio.sleep(0.05)
        assert errors == []
        assert adapter.calls == 1
        assert not service.cache

    try:
        asyncio.run(scenario())
    finally:
        gate.set()
        service.close()
