import hashlib
import json
import secrets
import threading
import time
from dataclasses import dataclass
from urllib.parse import urlencode, urlsplit

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.credentials import Credentials
from google_auth_httplib2 import AuthorizedHttp
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

from .google_transport import SingleAttemptHttp
from .token_store import CredentialStoreError, RefreshTokenStore

GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
TOKEN_URI = "https://oauth2.googleapis.com/token"


class GmailError(Exception):
    def __init__(self, code, message, status=503, retryable=False):
        self.code = code
        self.message = message
        self.status = status
        self.retryable = retryable
        super().__init__(message)


class GoogleProvider:
    def __init__(self, path):
        try:
            with path.open("rb") as source:
                encoded = source.read(65_537)
            if len(encoded) > 65_536:
                raise ValueError
            config = json.loads(encoded)["installed"]
            if (
                config["auth_uri"]
                not in {
                    "https://accounts.google.com/o/oauth2/auth",
                    "https://accounts.google.com/o/oauth2/v2/auth",
                }
                or config["token_uri"] != TOKEN_URI
                or not isinstance(config["client_id"], str)
                or not config["client_id"].endswith(".apps.googleusercontent.com")
                or not isinstance(config["client_secret"], str)
                or not config["client_secret"]
            ):
                raise ValueError
            self._config = {"installed": config}
            self.store_scope = (
                "gmail-client:" + hashlib.sha256(config["client_id"].encode()).hexdigest()
            )
        except Exception:
            raise GmailError(
                "gmail_setup_required", "Configure a valid local Desktop app JSON."
            ) from None

    def new_flow(self, redirect_uri):
        return Flow.from_client_config(
            self._config,
            scopes=[GMAIL_SCOPE],
            redirect_uri=redirect_uri,
            autogenerate_code_verifier=True,
        )

    def exchange(self, flow, code):
        flow.fetch_token(code=code, timeout=10, allow_redirects=False)
        return flow.credentials

    def restore(self, refresh_token):
        config = self._config["installed"]
        return Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri=TOKEN_URI,
            client_id=config["client_id"],
            client_secret=config["client_secret"],
            scopes=[GMAIL_SCOPE],
        )

    def refresh(self, credentials):
        class BoundedRequest(GoogleRequest):
            def __init__(self):
                super().__init__()
                self.deadline = time.monotonic() + 20

            def __call__(self, *args, **kwargs):
                remaining = self.deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError
                kwargs["timeout"] = min(10, remaining)
                return super().__call__(*args, **kwargs)

        credentials.refresh(BoundedRequest())

    def service(self, credentials, timeout=10):
        http = AuthorizedHttp(credentials, http=SingleAttemptHttp(timeout), refresh_status_codes=())
        return build("gmail", "v1", http=http, cache_discovery=False, static_discovery=True)

    def identity(self, credentials):
        with self.service(credentials) as service:
            email = service.users().getProfile(userId="me").execute(num_retries=0)["emailAddress"]
        if not isinstance(email, str) or not email or len(email) > 320:
            raise ValueError
        return hashlib.sha256((self.store_scope + ":" + email.casefold()).encode()).hexdigest()

    def revoke(self, token):
        transport = SingleAttemptHttp(5, max_response_bytes=65_536)
        try:
            response, _ = transport.request(
                "https://oauth2.googleapis.com/revoke",
                method="POST",
                body=urlencode({"token": token}),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            return response.status == 200
        finally:
            transport.close()


@dataclass(repr=False)
class PendingAuthorization:
    flow: object
    state: str
    browser_nonce: str
    expires: float


class GmailOAuth:
    def __init__(self, settings, invalidate=lambda: None):
        self.settings = settings
        self.invalidate = invalidate
        self._provider = None
        self._store = None
        self._credentials = None
        self._refresh_needs_save = False
        self.account_scope = None
        self.pending = None
        self.generation = 0
        self.lock = threading.RLock()

    def ensure_setup(self):
        if self.settings.gmail_client_file is None:
            raise GmailError("gmail_setup_required", "Configure the local Gmail Desktop app JSON.")
        if self.settings.allow_non_loopback or self.settings.host not in {
            "localhost",
            "127.0.0.1",
            "::1",
        }:
            raise GmailError("gmail_setup_required", "Gmail OAuth requires loopback-only hosting.")
        if self._provider is None:
            self._provider = GoogleProvider(self.settings.gmail_client_file)
        if self._store is None:
            try:
                self._store = RefreshTokenStore()
            except CredentialStoreError:
                raise GmailError(
                    "credential_store_unavailable", "Protected credential storage is unavailable."
                ) from None

    def store_call(self, operation, *args):
        try:
            return getattr(self._store, operation)(self._provider.store_scope, *args)
        except CredentialStoreError:
            raise GmailError(
                "credential_store_failed", "Protected credential storage failed."
            ) from None

    def validate_credentials(self, credentials):
        granted = (
            credentials.scopes if credentials.granted_scopes is None else credentials.granted_scopes
        )
        if set(granted or []) != {GMAIL_SCOPE} or not credentials.token:
            raise GmailError("gmail_scope_denied", "Grant Gmail read-only access to connect.", 403)

    def get_credentials(self):
        with self.lock:
            self.ensure_setup()
            if self._credentials is None:
                token = self.store_call("load")
                if token is None:
                    raise GmailError("gmail_not_connected", "Connect Gmail first.", 401)
                self._credentials = self._provider.restore(token)
            credentials = self._credentials
            try:
                if not credentials.valid:
                    previous_refresh = credentials.refresh_token
                    self._provider.refresh(credentials)
                    self._refresh_needs_save = (
                        self._refresh_needs_save or credentials.refresh_token != previous_refresh
                    )
                self.validate_credentials(credentials)
                if self._refresh_needs_save:
                    self.store_call("save", credentials.refresh_token)
                    self._refresh_needs_save = False
                if self.account_scope is None:
                    self.account_scope = self._provider.identity(credentials)
            except RefreshError as error:
                if error.retryable:
                    raise GmailError(
                        "gmail_refresh_failed", "Gmail refresh failed. Try again.", 503, True
                    ) from None
                self._credentials = None
                self._refresh_needs_save = False
                self.account_scope = None
                self.generation += 1
                self.invalidate()
                self.store_call("delete")
                raise GmailError(
                    "gmail_reconnect_required",
                    "Gmail access expired or was revoked. Reconnect.",
                    401,
                ) from None
            except GmailError:
                raise
            except Exception:
                raise GmailError(
                    "gmail_refresh_failed", "Could not refresh the Gmail connection.", 503, True
                ) from None
            return credentials

    def status(self):
        try:
            self.get_credentials()
        except GmailError as error:
            if error.code in {"gmail_not_connected", "gmail_setup_required"}:
                return {"connected": False, "account_scope": None, "code": error.code}
            raise
        return {"connected": True, "account_scope": self.account_scope, "code": "connected"}

    def start(self, redirect_uri):
        with self.lock:
            self.ensure_setup()
            if self._credentials is not None or self.store_call("load") is not None:
                raise GmailError(
                    "gmail_already_connected",
                    "Disconnect Gmail before connecting another account.",
                    409,
                )
            parsed = urlsplit(redirect_uri)
            if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
                raise GmailError("gmail_setup_required", "Gmail OAuth requires a local callback.")
            flow = self._provider.new_flow(redirect_uri)
            url, state = flow.authorization_url(
                access_type="offline", prompt="consent", include_granted_scopes="false"
            )
            nonce = secrets.token_urlsafe(32)
            self.pending = PendingAuthorization(flow, state, nonce, time.monotonic() + 300)
            self.generation += 1
            return url, nonce

    def callback(self, state, nonce, code, error):
        with self.lock:
            pending = self.pending
            if (
                pending is None
                or not state
                or not nonce
                or not state.isascii()
                or not nonce.isascii()
                or not secrets.compare_digest(pending.state, state)
                or not secrets.compare_digest(pending.browser_nonce, nonce)
            ):
                raise GmailError(
                    "oauth_invalid_state",
                    "The Gmail connection request is invalid. Start again.",
                    400,
                )
            self.pending = None
            if time.monotonic() > pending.expires:
                raise GmailError(
                    "oauth_expired", "The Gmail connection request expired. Start again.", 400
                )
            if error:
                raise GmailError("oauth_denied", "Gmail permission was not granted.", 400)
            if not code:
                raise GmailError(
                    "oauth_missing_code", "Google did not return a connection code.", 400
                )
            try:
                credentials = self._provider.exchange(pending.flow, code)
                self.validate_credentials(credentials)
                if not credentials.refresh_token:
                    raise GmailError(
                        "gmail_refresh_missing", "Reconnect and grant offline Gmail access.", 400
                    )
                account_scope = self._provider.identity(credentials)
                self.store_call("save", credentials.refresh_token)
                self._credentials = credentials
                self._refresh_needs_save = False
                self.account_scope = account_scope
                self.invalidate()
            except GmailError:
                raise
            except Exception:
                raise GmailError(
                    "oauth_exchange_failed", "Could not finish connecting Gmail. Start again.", 502
                ) from None

    def cancel(self):
        with self.lock:
            self.pending = None
            self.generation += 1

    def disconnect(self):
        with self.lock:
            credentials = self._credentials
            self.pending = None
            self._credentials = None
            self._refresh_needs_save = False
            self.account_scope = None
            self.generation += 1
            self.invalidate()
            if self.settings.gmail_client_file is None and self._provider is None:
                return {"disconnected": True, "revocation_failed": False}
            self.ensure_setup()
            revocation_failed = False
            try:
                token = credentials.refresh_token if credentials is not None else None
                if not token:
                    token = self.store_call("load")
                if token:
                    revocation_failed = not self._provider.revoke(token)
            except Exception:
                revocation_failed = True
            finally:
                self.store_call("delete")
            return {"disconnected": True, "revocation_failed": revocation_failed}
