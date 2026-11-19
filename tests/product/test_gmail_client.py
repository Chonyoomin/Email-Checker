import base64
import threading
from types import SimpleNamespace

import httplib2
import pytest
from googleapiclient.errors import HttpError

from bad_email_check.config import Settings
from bad_email_check.gmail_client import GmailClient, decode_gmail_data
from bad_email_check.gmail_oauth import GmailError

SCOPE = "a" * 64


class Service:
    def __init__(self, provider):
        self.provider = provider

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def users(self):
        return self

    def messages(self):
        return self

    def attachments(self):
        return self

    def list(self, **kwargs):
        self.provider.calls.append(("list", kwargs))
        return self

    def get(self, **kwargs):
        self.provider.calls.append(("get", kwargs))
        return self

    def execute(self, num_retries):
        assert num_retries == 0
        outcome = self.provider.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        if callable(outcome):
            return outcome()
        return outcome


class Provider:
    def __init__(self):
        self.outcomes = []
        self.calls = []
        self.timeouts = []

    def service(self, credentials, timeout):
        assert credentials == "synthetic-credentials"
        assert 0 < timeout <= 5
        self.timeouts.append(timeout)
        return Service(self)


@pytest.fixture
def client(monkeypatch):
    provider = Provider()
    oauth = SimpleNamespace(
        generation=1,
        account_scope=SCOPE,
        _provider=provider,
        get_credentials=lambda: "synthetic-credentials",
    )
    client = GmailClient(oauth, Settings(_env_file=None))
    monkeypatch.setattr(
        "bad_email_check.gmail_client.GmailBudget.wait", lambda self, delay: self.remaining()
    )
    return client, provider


def http_error(status):
    return HttpError(
        httplib2.Response({"status": str(status)}), b'{"error":{"message":"synthetic-private"}}'
    )


@pytest.mark.parametrize(
    "failure", [http_error(429), http_error(500), http_error(502), OSError("synthetic-private")]
)
def test_transient_errors_retry_at_most_twice_then_succeed(client, failure):
    wrapper, provider = client
    provider.outcomes = [
        failure,
        failure,
        {"messages": [{"id": "abc123"}], "nextPageToken": "next"},
    ]
    result = wrapper.list_ids(SCOPE)
    assert result == {"ids": ["abc123"], "next_page_token": "next"}
    assert len(provider.calls) == 3
    assert all(call[1]["userId"] == "me" for call in provider.calls)


@pytest.mark.parametrize(
    "failure", [http_error(429), http_error(503), OSError("synthetic-private")]
)
def test_exhaustion_is_bounded_and_sanitized(client, failure):
    wrapper, provider = client
    provider.outcomes = [failure] * 4
    with pytest.raises(GmailError) as error:
        wrapper.list_ids(SCOPE)
    assert len(provider.calls) == 3
    assert error.value.retryable
    assert "synthetic-private" not in str(error.value)


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_auth_denial_and_bad_requests_are_not_retried(client, status):
    wrapper, provider = client
    provider.outcomes = [http_error(status)]
    with pytest.raises(GmailError) as error:
        wrapper.get_message(SCOPE, "abc123")
    assert len(provider.calls) == 1
    assert not error.value.retryable


def test_pagination_and_metadata_request_parameters(client):
    wrapper, provider = client
    provider.outcomes = [{}, {"id": "abc123", "payload": {"headers": []}}]
    assert wrapper.list_ids(SCOPE, "page-token", "is:unread")["ids"] == []
    wrapper.get_message(SCOPE, "abc123", "metadata")
    assert provider.calls[0][1]["pageToken"] == "page-token"
    assert provider.calls[0][1]["maxResults"] == 10
    assert provider.calls[1][1]["metadataHeaders"] == ["From", "Subject", "Date"]


@pytest.mark.parametrize("scope", ["b" * 64, "", "\u00e9"])
def test_other_account_scope_cannot_reach_gmail(client, scope):
    wrapper, provider = client
    with pytest.raises(GmailError, match="another Gmail"):
        wrapper.list_ids(scope)
    assert provider.calls == []


def test_deadline_cancellation_and_connection_change_prevent_calls(client):
    wrapper, provider = client
    for mode in ["deadline", "cancel", "connection"]:
        budget = wrapper.budget()
        if mode == "deadline":
            budget.deadline = 0
        elif mode == "cancel":
            budget.cancel.set()
        else:
            wrapper.oauth.generation += 1
        with pytest.raises(GmailError):
            wrapper.list_ids(SCOPE, budget=budget)
    assert provider.calls == []


def test_cancellation_after_response_discards_result_and_does_not_retry(client):
    wrapper, provider = client
    budget = wrapper.budget()

    def late():
        budget.cancel.set()
        return {"messages": [{"id": "abc123"}]}

    provider.outcomes = [late]
    with pytest.raises(GmailError) as error:
        wrapper.list_ids(SCOPE, budget=budget)
    assert error.value.code == "gmail_cancelled" and len(provider.calls) == 1


def test_actual_backoff_wait_is_interruptible():
    from bad_email_check.gmail_client import GmailBudget

    oauth = SimpleNamespace(generation=0)
    cancel = threading.Event()
    budget = GmailBudget(oauth, 10, cancel)
    cancel.set()
    with pytest.raises(GmailError):
        budget.wait(0.25)


def test_textual_mime_retrieval_only_and_byte_limit(client):
    wrapper, provider = client
    part = {"mimeType": "text/plain", "body": {"attachmentId": "part123", "size": 4}}
    provider.outcomes = [{"data": base64.urlsafe_b64encode(b"body").decode()}]
    assert wrapper.get_text_attachment(SCOPE, "abc123", part) == b"body"
    assert provider.calls[0][1]["messageId"] == "abc123"
    for invalid in [
        dict(part, filename="file.txt"),
        dict(part, mimeType="application/pdf"),
        dict(part, mimeType=None),
        {},
    ]:
        with pytest.raises(GmailError):
            wrapper.get_text_attachment(SCOPE, "abc123", invalid)
    assert len(provider.calls) == 1


@pytest.mark.parametrize(
    "payload",
    [
        {"messages": [{"id": "../bad"}]},
        {"messages": [{"id": 123}]},
        {"messages": "bad"},
        {"messages": [{"id": "abc123"}] * 11},
    ],
)
def test_invalid_remote_ids_and_lists_fail_closed(client, payload):
    wrapper, provider = client
    provider.outcomes = [payload]
    with pytest.raises(GmailError):
        wrapper.list_ids(SCOPE)


def test_invalid_id_mismatched_result_and_raw_limits(client):
    wrapper, provider = client
    with pytest.raises(GmailError):
        wrapper.get_message(SCOPE, "../bad")
    assert provider.calls == []
    provider.outcomes = [{"id": "other"}]
    with pytest.raises(GmailError):
        wrapper.get_message(SCOPE, "abc123")
    assert decode_gmail_data("Ym9keQ", 4) == b"body"
    for data in ["!" * 4, "YQ==YQ==", base64.urlsafe_b64encode(b"too big").decode()]:
        with pytest.raises(GmailError):
            decode_gmail_data(data, 4)


@pytest.mark.parametrize(
    "name,value",
    [
        ("Content-Disposition", "attachment"),
        ("content-disposition", 'ATTACHMENT; filename=""'),
        ("CONTENT-DISPOSITION", " attachment "),
    ],
)
def test_p5_4_f2_unnamed_text_attachments_are_not_message_bodies(client, name, value):
    wrapper, provider = client
    part = {
        "mimeType": "text/plain",
        "body": {"attachmentId": "part123", "size": 4},
        "headers": [{"name": name, "value": value}],
    }
    with pytest.raises(GmailError) as error:
        wrapper.get_text_attachment(SCOPE, "abc123", part)
    assert error.value.code == "gmail_unsupported_part"
    assert provider.calls == []


@pytest.fixture
def local_transport(monkeypatch):
    import time
    from http.client import HTTPConnection
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    state = {"mode": "valid", "calls": 0}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            state["calls"] += 1
            try:
                if state["mode"] == "bad_status":
                    self.wfile.write(b"invalid HTTP status\r\n")
                    return
                if state["mode"] == "slow_headers":
                    time.sleep(0.4)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                if state["mode"] == "slow":
                    for _ in range(40):
                        self.wfile.write(b"x")
                        self.wfile.flush()
                        time.sleep(0.01)
                else:
                    self.wfile.write(b"bodyx")
            except OSError, ConnectionError:
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def connection(hostname, timeout, context):
        return HTTPConnection("127.0.0.1", server.server_port, timeout=timeout)

    monkeypatch.setattr("bad_email_check.google_transport.HTTPSConnection", connection)
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)


def test_p5_4_f1_real_transport_has_three_total_physical_attempts(client, local_transport):
    from google.oauth2.credentials import Credentials

    from bad_email_check.gmail_oauth import GoogleProvider

    wrapper, _ = client
    wrapper.oauth._provider = object.__new__(GoogleProvider)
    wrapper.oauth.get_credentials = lambda: Credentials(token="synthetic-access")
    local_transport["mode"] = "bad_status"
    with pytest.raises(GmailError) as error:
        wrapper.list_ids(SCOPE)
    assert error.value.code == "gmail_network_failed"
    assert local_transport["calls"] == 3


@pytest.mark.parametrize("mode", ["slow", "slow_headers"])
def test_p5_4_f3_slow_response_is_interrupted_at_the_wall_deadline(local_transport, mode):
    import time

    from bad_email_check.google_transport import SingleAttemptHttp

    local_transport["mode"] = mode
    transport = SingleAttemptHttp(0.05)
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        transport.request("https://gmail.googleapis.com/gmail/v1/users/me/messages")
    elapsed = time.monotonic() - started
    assert elapsed < 0.2
    assert local_transport["calls"] == 1


def test_transport_streaming_size_limit_and_endpoint_guard(local_transport):
    from bad_email_check.google_transport import GoogleResponseTooLarge, SingleAttemptHttp

    transport = SingleAttemptHttp(1, max_response_bytes=4)
    with pytest.raises(GoogleResponseTooLarge):
        transport.request("https://gmail.googleapis.com/gmail/v1/users/me/messages")
    with pytest.raises(ValueError):
        transport.request("https://attacker.example/")
    assert local_transport["calls"] == 1
