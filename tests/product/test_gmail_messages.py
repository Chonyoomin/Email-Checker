import base64
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from test_gmail_oauth import FakeProvider, FakeStore, credentials
from test_scans import StubAdapter

from bad_email_check.app import create_app
from bad_email_check.config import Settings

SCOPE = "a" * 64
HEADERS = {"X-Email-Checker-Request": "1"}
RAW = (
    b"From: sender@example.org\nSubject: Synthetic example\n"
    b"Authentication-Results: example.org; spf=pass\n\nSynthetic body"
)


@pytest.mark.parametrize("revoked", [True, False])
def test_disconnect_clears_populated_cache_and_protected_token(session, revoked):
    client, app = session
    oauth = app.state.gmail
    oauth._store.save(oauth._provider.store_scope, "synthetic-refresh")
    oauth._provider.revoke = lambda token: revoked
    response = client.post(
        "/api/scans",
        json={"source": "gmail", "source_message_id": "abc123", "account_scope": SCOPE},
        headers=HEADERS,
    )
    assert response.status_code == 200 and app.state.scanner.cache
    response = client.post("/api/auth/gmail/disconnect", headers=HEADERS)
    assert response.json() == {"disconnected": True, "revocation_failed": not revoked}
    assert not app.state.scanner.cache and not oauth._store.tokens


def test_disconnect_during_inference_discards_result_and_prevents_cache_repopulation(session):
    client, app = session
    entered = threading.Event()
    release = threading.Event()

    def wait():
        entered.set()
        assert release.wait(5)

    app.state.scanner.adapter.behavior = wait
    with ThreadPoolExecutor() as executor:
        future = executor.submit(
            client.post,
            "/api/scans",
            json={"source": "gmail", "source_message_id": "abc123", "account_scope": SCOPE},
            headers=HEADERS,
        )
        try:
            assert entered.wait(5)
            response = client.post("/api/auth/gmail/disconnect", headers=HEADERS)
            assert response.status_code == 200
        finally:
            release.set()
        response = future.result(timeout=5)
    assert response.status_code == 409
    assert response.json()["code"] == "gmail_cancelled"
    assert app.state.scanner.cache == {}


def test_p5_6_f1_queued_gmail_cannot_repopulate_cache_after_disconnect(session, monkeypatch):
    client, app = session
    entered = threading.Event()
    queued = threading.Event()
    release = threading.Event()
    original_submit = app.state.scanner.executor.submit

    def submit(function, evidence, *args):
        future = original_submit(function, evidence, *args)
        if evidence.source == "gmail":
            queued.set()
        return future

    def wait():
        entered.set()
        assert release.wait(5)

    monkeypatch.setattr(app.state.scanner.executor, "submit", submit)
    app.state.scanner.adapter.behavior = wait
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(
            client.post, "/api/scans", json={"text": "Blocker"}, headers=HEADERS
        )
        try:
            assert entered.wait(5)
            gmail = executor.submit(
                client.post,
                "/api/scans",
                json={"source": "gmail", "source_message_id": "abc123", "account_scope": SCOPE},
                headers=HEADERS,
            )
            assert queued.wait(5)
            assert client.post("/api/auth/gmail/disconnect", headers=HEADERS).status_code == 200
        finally:
            release.set()
        assert first.result(timeout=5).status_code == 200
        assert gmail.result(timeout=5).status_code == 409
    assert app.state.scanner.cache == {}


class MessageService:
    def __init__(self, provider):
        self.provider = provider
        self.arguments = {}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def users(self):
        return self

    def messages(self):
        return self

    def list(self, **kwargs):
        self.arguments = kwargs
        self.operation = "list"
        return self

    def get(self, **kwargs):
        self.arguments = kwargs
        self.operation = "get"
        return self

    def execute(self, num_retries):
        assert num_retries == 0 and self.arguments["userId"] == "me"
        self.provider.calls.append((self.operation, self.arguments))
        if self.operation == "list":
            if self.arguments.get("pageToken"):
                return {"messages": [{"id": "def456"}]}
            return {"messages": [{"id": "abc123"}], "nextPageToken": "next-page"}
        if self.arguments["format"] == "metadata":
            subject = (
                "Synthetic example" if self.arguments["id"] == "abc123" else "Synthetic second page"
            )
            return {
                "id": self.arguments["id"],
                "sizeEstimate": self.provider.size,
                "payload": {
                    "headers": [
                        {"name": "From", "value": "sender@example.org"},
                        {"name": "Subject", "value": subject},
                    ]
                },
            }
        raw = (
            RAW
            if self.arguments["id"] == "abc123"
            else RAW.replace(b"Synthetic example", b"Synthetic second page")
        )
        return {"id": self.arguments["id"], "raw": base64.urlsafe_b64encode(raw).decode()}


class MailProvider(FakeProvider):
    def __init__(self):
        super().__init__()
        self.calls = []
        self.size = len(RAW)

    def service(self, creds, timeout):
        return MessageService(self)


@pytest.fixture
def session():
    app = create_app(
        Settings(_env_file=None, mode="test", gmail_client_file="synthetic.json"), StubAdapter()
    )
    app.state.gmail._provider = MailProvider()
    app.state.gmail._store = FakeStore()
    app.state.gmail._credentials = credentials()
    app.state.gmail.account_scope = SCOPE
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        yield client, app


def test_paginated_messages_and_account_scope(session):
    client, _ = session
    response = client.get("/api/messages", params={"account_scope": SCOPE})
    assert response.status_code == 200
    data = response.json()
    assert data["account_scope"] == SCOPE
    assert data["messages"][0]["id"] == "abc123"
    assert data["messages"][0]["subject"] == "Synthetic example"
    assert data["next_page_token"] == "next-page"
    second = client.get(
        "/api/messages", params={"account_scope": SCOPE, "page_token": data["next_page_token"]}
    ).json()
    assert second["messages"][0]["id"] == "def456" and second["next_page_token"] is None
    assert second["messages"][0]["subject"] == "Synthetic second page"


def test_selected_evidence_and_scan_use_canonical_parser_and_gmail_provenance(session):
    client, _ = session
    response = client.get("/api/messages/abc123", params={"account_scope": SCOPE})
    assert response.status_code == 200
    evidence = response.json()["evidence"]
    assert evidence["source"] == "gmail" and evidence["source_message_id"] == "abc123"
    assert evidence["account_scope"] == SCOPE
    assert evidence["authentication"][0]["provenance"] == "gmail"
    assert not evidence["authentication"][0]["independently_verified"]
    result = client.post(
        "/api/scans",
        json={"source": "gmail", "source_message_id": "abc123", "account_scope": SCOPE},
        headers=HEADERS,
    ).json()
    assert result["score"] == 80
    assert result["source_fingerprint"] == evidence["fingerprint"]
    assert result["timings"]["retrieval_ms"] > 0


def test_gmail_metadata_excludes_content_and_account_identifiers(session):
    client, app = session
    response = client.post(
        "/api/scans",
        json={"source": "gmail", "source_message_id": "abc123", "account_scope": SCOPE},
        headers=HEADERS,
    )
    assert response.status_code == 200
    path = app.state.settings.metadata_db_path
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT source FROM scans").fetchone() == ("gmail",)
    for private in (SCOPE.encode(), b"abc123", b"sender@example.org", b"Synthetic body"):
        assert private not in path.read_bytes()


def test_p6_1_f1_disconnect_during_metadata_write_withholds_gmail_score(session, monkeypatch):
    client, app = session
    entered = threading.Event()
    release = threading.Event()
    original = app.state.metadata.record

    def record(*args):
        entered.set()
        assert release.wait(5)
        original(*args)

    monkeypatch.setattr(app.state.metadata, "record", record)
    with ThreadPoolExecutor() as executor:
        scan = executor.submit(
            client.post,
            "/api/scans",
            json={"source": "gmail", "source_message_id": "abc123", "account_scope": SCOPE},
            headers=HEADERS,
        )
        try:
            assert entered.wait(5)
            assert client.post("/api/auth/gmail/disconnect", headers=HEADERS).status_code == 200
        finally:
            release.set()
        response = scan.result(timeout=5)
    assert response.status_code == 409
    assert response.json()["code"] == "gmail_cancelled"
    assert "score" not in response.json()


@pytest.mark.parametrize("route", ["/api/messages", "/api/messages/abc123"])
def test_account_mismatch_never_requests_messages(session, route):
    client, app = session
    response = client.get(route, params={"account_scope": "b" * 64})
    assert response.status_code == 403
    assert app.state.gmail._provider.calls == []


def test_gmail_scan_rejects_other_account_and_invalid_id(session):
    client, app = session
    for message_id, scope, expected in [("abc123", "b" * 64, 403), ("../bad", SCOPE, 422)]:
        response = client.post(
            "/api/scans",
            json={"source": "gmail", "source_message_id": message_id, "account_scope": scope},
            headers=HEADERS,
        )
        assert response.status_code == expected
    assert app.state.gmail._provider.calls == []


def test_duplicate_unknown_query_and_invalid_message_are_rejected(session):
    client, app = session
    for route in [
        "/api/messages?account_scope=" + SCOPE + "&unknown=x",
        "/api/messages?account_scope=" + SCOPE + "&account_scope=" + SCOPE,
        "/api/messages/invalid!?account_scope=" + SCOPE,
    ]:
        assert client.get(route).status_code == 422
    assert app.state.gmail._provider.calls == []


def test_oversized_message_rejected_before_raw_fetch(session):
    client, app = session
    app.state.gmail._provider.size = app.state.settings.max_upload_bytes + 1
    response = client.get("/api/messages/abc123", params={"account_scope": SCOPE})
    assert response.status_code == 413
    assert len(app.state.gmail._provider.calls) == 1
    assert app.state.gmail._provider.calls[0][1]["format"] == "metadata"


def test_timed_out_mailbox_workers_retain_admission_until_actual_completion(session, monkeypatch):
    client, app = session
    gate = threading.Event()
    monkeypatch.setattr(
        app.state,
        "settings",
        app.state.settings.model_copy(update={"gmail_deadline_seconds": 0.02}),
    )

    def blocked(scope, page_token, query, budget):
        gate.wait(2)
        budget.remaining()

    monkeypatch.setattr(app.state.mailbox, "list_page", blocked)
    try:
        assert client.get("/api/messages", params={"account_scope": SCOPE}).status_code == 504
        assert client.get("/api/messages", params={"account_scope": SCOPE}).status_code == 504
        assert client.get("/api/messages", params={"account_scope": SCOPE}).status_code == 429
    finally:
        gate.set()
