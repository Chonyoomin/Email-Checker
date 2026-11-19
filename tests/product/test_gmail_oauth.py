import json
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient
from google.auth.exceptions import RefreshError

from bad_email_check.app import create_app
from bad_email_check.config import Settings
from bad_email_check.gmail_oauth import GMAIL_SCOPE, GmailError, GoogleProvider
from bad_email_check.token_store import CredentialStoreError

HEADERS = {"X-Email-Checker-Request": "1"}


class FakeStore:
    def __init__(self):
        self.tokens = {}

    def load(self, scope):
        return self.tokens.get(scope)

    def save(self, scope, token):
        self.tokens[scope] = token

    def delete(self, scope):
        self.tokens.pop(scope, None)


def credentials(valid=True, scopes=None):
    return SimpleNamespace(
        token="synthetic-access",
        refresh_token="synthetic-refresh",
        valid=valid,
        scopes=[GMAIL_SCOPE],
        granted_scopes=scopes or [GMAIL_SCOPE],
    )


class FakeFlow:
    def authorization_url(self, **kwargs):
        assert kwargs == {
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "false",
        }
        return "https://accounts.google.com/o/oauth2/auth?synthetic=1", "synthetic-state"


class FakeProvider:
    store_scope = "synthetic-client-scope"

    def __init__(self):
        self.refreshes = 0
        self.exchanges = 0
        self.refresh_error = None
        self.output = credentials()

    def new_flow(self, redirect):
        assert redirect == "http://127.0.0.1:8000/api/auth/gmail/callback"
        return FakeFlow()

    def exchange(self, flow, code):
        self.exchanges += 1
        return self.output

    def restore(self, token):
        assert token == "synthetic-refresh"
        return credentials(valid=False)

    def refresh(self, creds):
        self.refreshes += 1
        if self.refresh_error:
            raise self.refresh_error
        creds.valid = True

    def identity(self, creds):
        return "a" * 64

    def revoke(self, token):
        assert token == "synthetic-refresh"
        return True


@pytest.fixture
def session():
    app = create_app(Settings(_env_file=None, mode="test", gmail_client_file="synthetic.json"))
    app.state.gmail._provider = FakeProvider()
    app.state.gmail._store = FakeStore()
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        yield client, app.state.gmail


def start(client):
    response = client.post("/api/auth/gmail/start", headers=HEADERS)
    assert response.status_code == 200
    assert "httponly" in response.headers["set-cookie"].lower()
    assert "samesite=lax" in response.headers["set-cookie"].lower()
    return response


def test_connect_stores_only_refresh_token_and_consumes_state(session):
    client, oauth = session
    start(client)
    response = client.get("/api/auth/gmail/callback?state=synthetic-state&code=synthetic-code")
    assert response.status_code == 200
    assert oauth._store.tokens == {"synthetic-client-scope": "synthetic-refresh"}
    assert client.get("/api/auth/gmail/status").json()["account_scope"] == "a" * 64
    assert (
        client.get("/api/auth/gmail/callback?state=synthetic-state&code=synthetic-code").status_code
        == 400
    )
    assert oauth._provider.exchanges == 1
    assert "synthetic-access" not in response.text
    assert client.post("/api/auth/gmail/start", headers=HEADERS).status_code == 409


@pytest.mark.parametrize(
    "query",
    [
        "code=x",
        "state=wrong&code=x",
        "state=%C3%A9&code=x",
        "state=synthetic-state&state=other&code=x",
    ],
)
def test_bad_state_rejected_without_exchange(session, query):
    client, oauth = session
    start(client)
    response = client.get("/api/auth/gmail/callback?" + query)
    assert response.status_code == 400
    assert oauth._provider.exchanges == 0
    assert oauth.pending is not None


def test_cookie_is_required_and_error_with_bad_state_cannot_cancel_connection(session):
    client, oauth = session
    start(client)
    client.cookies.clear()
    assert client.get("/api/auth/gmail/callback?state=synthetic-state&code=x").status_code == 400
    assert client.get("/api/auth/gmail/callback?state=wrong&error=access_denied").status_code == 400
    assert oauth.pending is not None
    assert oauth._provider.exchanges == 0


def test_denial_missing_code_expiry_and_cancel_consume_pending(session):
    client, oauth = session
    for query in ("state=synthetic-state&error=access_denied", "state=synthetic-state"):
        start(client)
        assert client.get("/api/auth/gmail/callback?" + query).status_code == 400
        assert oauth.pending is None
    start(client)
    oauth.pending.expires = 0
    assert client.get("/api/auth/gmail/callback?state=synthetic-state&code=x").status_code == 400
    start(client)
    assert client.post("/api/auth/gmail/cancel", headers=HEADERS).json()["cancelled"]
    assert oauth.pending is None
    assert oauth._provider.exchanges == 0


@pytest.mark.parametrize("scopes", [[], ["https://mail.google.com/"], [GMAIL_SCOPE, "openid"]])
def test_denied_or_broader_scope_never_saves_connection(session, scopes):
    client, oauth = session
    oauth._provider.output.granted_scopes = scopes
    oauth._provider.output.scopes = scopes
    start(client)
    assert client.get("/api/auth/gmail/callback?state=synthetic-state&code=x").status_code == 403
    assert oauth._store.tokens == {}


def test_refresh_and_reconnect_revoked_grant_without_leaking_tokens(session):
    client, oauth = session
    oauth._store.save(oauth._provider.store_scope, "synthetic-refresh")
    assert client.get("/api/auth/gmail/status").json()["connected"]
    assert oauth._provider.refreshes == 1
    oauth._credentials.valid = False
    oauth._provider.refresh_error = RefreshError("synthetic-private", {"error": "invalid_grant"})
    response = client.get("/api/auth/gmail/status")
    assert response.status_code == 401
    assert response.json()["code"] == "gmail_reconnect_required"
    assert "synthetic-private" not in response.text
    assert oauth._store.tokens == {} and oauth.account_scope is None


def test_retryable_refresh_error_does_not_delete_grant(session):
    client, oauth = session
    oauth._store.save(oauth._provider.store_scope, "synthetic-refresh")
    oauth._provider.refresh_error = RefreshError("synthetic-private", retryable=True)
    response = client.get("/api/auth/gmail/status")
    assert response.status_code == 503 and response.json()["retryable"]
    assert oauth._store.tokens


def test_unconfigured_app_reports_setup_without_reading_credentials():
    with TestClient(
        create_app(Settings(_env_file=None)), base_url="http://127.0.0.1:8000"
    ) as client:
        assert client.get("/api/auth/gmail/status").json()["code"] == "gmail_setup_required"
        assert client.post("/api/auth/gmail/start", headers=HEADERS).status_code == 503


def test_real_flow_uses_pkce_and_only_readonly_scope(tmp_path):
    path = tmp_path / "synthetic.json"
    path.write_text(
        json.dumps(
            {
                "installed": {
                    "client_id": "synthetic.apps.googleusercontent.com",
                    "client_secret": "synthetic-secret",
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                }
            }
        )
    )
    flow = GoogleProvider(path).new_flow("http://127.0.0.1:8000/api/auth/gmail/callback")
    url, state = flow.authorization_url(access_type="offline")
    query = parse_qs(urlsplit(url).query)
    assert query["scope"] == [GMAIL_SCOPE]
    assert query["code_challenge_method"] == ["S256"]
    assert query["state"] == [state]


def test_client_file_rejects_web_client_or_untrusted_endpoints(tmp_path):
    path = tmp_path / "synthetic.json"
    for config in [
        {"web": {}},
        {
            "installed": {
                "auth_uri": "https://attacker.example/",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        },
    ]:
        path.write_text(json.dumps(config))
        with pytest.raises(GmailError, match="valid local Desktop"):
            GoogleProvider(path)


def test_p5_3_f1_explicit_empty_grant_cannot_fall_back_to_requested_scope(session):
    client, oauth = session
    oauth._provider.output.granted_scopes = []
    start(client)
    assert client.get("/api/auth/gmail/callback?state=synthetic-state&code=x").status_code == 403
    assert oauth._store.tokens == {}
    assert oauth._credentials is None
    oauth._store.save(oauth._provider.store_scope, "synthetic-refresh")

    def refresh(creds):
        creds.valid = True
        creds.granted_scopes = []

    oauth._provider.refresh = refresh
    assert client.get("/api/auth/gmail/status").status_code == 403
    assert oauth.account_scope is None


def test_p5_3_f2_rotated_refresh_survives_restart(session):
    client, oauth = session
    oauth._store.save(oauth._provider.store_scope, "synthetic-refresh")

    def rotate(creds):
        creds.valid = True
        creds.refresh_token = "synthetic-rotated"

    oauth._provider.refresh = rotate
    assert client.get("/api/auth/gmail/status").json()["connected"]
    assert oauth._store.load(oauth._provider.store_scope) == "synthetic-rotated"

    oauth._credentials = None
    oauth.account_scope = None

    def restore(token):
        assert token == "synthetic-rotated"
        restored = credentials(valid=False)
        restored.refresh_token = token
        return restored

    oauth._provider.restore = restore
    assert client.get("/api/auth/gmail/status").json()["connected"]


@pytest.mark.parametrize("outcome", [True, False, RuntimeError("synthetic-private")])
def test_disconnect_always_removes_local_grant_and_invalidates(session, outcome):
    client, oauth = session
    start(client)
    oauth._credentials = credentials()
    oauth.account_scope = "a" * 64
    oauth._store.save(oauth._provider.store_scope, "synthetic-refresh")
    invalidated = []
    oauth.invalidate = lambda: invalidated.append(True)
    generation = oauth.generation

    def revoke(token):
        assert oauth._credentials is None and oauth.account_scope is None
        assert invalidated
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    oauth._provider.revoke = revoke
    response = client.post("/api/auth/gmail/disconnect", headers=HEADERS)
    assert response.status_code == 200
    assert response.json() == {"disconnected": True, "revocation_failed": outcome is not True}
    assert "synthetic-private" not in response.text
    assert oauth._store.tokens == {} and oauth.pending is None
    assert oauth.generation == generation + 1
    assert not client.get("/api/auth/gmail/status").json()["connected"]
    assert client.get("/api/auth/gmail/callback?state=synthetic-state&code=x").status_code == 400


def test_disconnect_delete_failure_is_reported_and_retryable(session, monkeypatch):
    client, oauth = session
    oauth._store.save(oauth._provider.store_scope, "synthetic-refresh")
    original = oauth._store.delete

    def fail(scope):
        raise CredentialStoreError("synthetic-private")

    monkeypatch.setattr(oauth._store, "delete", fail)
    response = client.post("/api/auth/gmail/disconnect", headers=HEADERS)
    assert response.status_code == 503
    assert response.json()["code"] == "credential_store_failed"
    assert "synthetic-private" not in response.text
    monkeypatch.setattr(oauth._store, "delete", original)
    assert client.post("/api/auth/gmail/disconnect", headers=HEADERS).json()["disconnected"]
    assert oauth._store.tokens == {}


def test_disconnect_unconfigured_is_idempotent():
    with TestClient(
        create_app(Settings(_env_file=None)), base_url="http://127.0.0.1:8000"
    ) as client:
        for _ in range(2):
            assert client.post("/api/auth/gmail/disconnect", headers=HEADERS).json() == {
                "disconnected": True,
                "revocation_failed": False,
            }


def test_p5_3_f2_rotated_refresh_write_failure_remains_retryable(session, monkeypatch):
    client, oauth = session
    oauth._store.save(oauth._provider.store_scope, "synthetic-refresh")
    original_save = oauth._store.save

    def fail(*args):
        raise CredentialStoreError("synthetic-private")

    def rotate(creds):
        creds.valid = True
        creds.refresh_token = "synthetic-rotated"

    oauth._provider.refresh = rotate
    monkeypatch.setattr(oauth._store, "save", fail)
    response = client.get("/api/auth/gmail/status")
    assert response.status_code == 503 and response.json()["code"] == "credential_store_failed"
    assert "synthetic-private" not in response.text
    assert oauth._refresh_needs_save
    assert oauth._store.load(oauth._provider.store_scope) == "synthetic-refresh"
    monkeypatch.setattr(oauth._store, "save", original_save)
    assert client.get("/api/auth/gmail/status").json()["connected"]
    assert oauth._store.load(oauth._provider.store_scope) == "synthetic-rotated"
