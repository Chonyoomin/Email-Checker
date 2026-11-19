# Gmail runtime

Tasks 5.3-5.6 implement OAuth, bounded retrieval, inbox controls and disconnect.
Phase 5 is complete. The real-account smoke report (development archive omitted)
records owner-confirmed connection, list/matching preview, a needs-review/no-score
scan and disconnect. It does not establish a scored Gmail inference, exact score-
withholding cause or independently verified Google-side revocation.

## Configuration and OAuth

Follow [Google setup](GMAIL_SETUP.md). Set `EMAIL_CHECK_GMAIL_CLIENT_FILE` to your
local Desktop app JSON in the ignored `.env`, then restart. Keep credentials out
of source, logs and agent memory. OAuth requires loopback-only hosting.

The backend exposes `/api/auth/gmail/start` (POST), `/callback` (GET), `/status`
(GET) and `/cancel` (POST). Local POST origin/header protections remain required.
Start returns Google's authorization URL and sets a five-minute HttpOnly,
SameSite=Lax callback cookie. Callback verifies cookie/state, consumes the pending
request, validates the read-only grant and writes the refresh token through the
[protected store](CREDENTIAL_STORAGE.md). PKCE is enabled. Tokens and Google's
callback values are never returned in the callback page. A new connection requires
disconnecting the previous one; no account-switch shortcut is supported.

Status restores a saved grant when present, refreshes expired access tokens and
returns only connection state plus an opaque account scope. Rotated refresh tokens
are saved before use; failed writes remain pending for retry. A revoked grant
requires reconnecting. Cancel invalidates only pending authorization.

## Disconnect

Disconnect invalidates pending authorization and in-flight Gmail results, clears
the assessment cache and attempts Google token revocation. Local protected tokens
are deleted even if revocation fails. The UI clears selected email content and
reports remote revocation failure separately; access can also be removed through
your Google account. A local deletion error is reported and can be retried.
Running inference cannot repopulate a cache cleared during disconnect.

## Retrieval limits

`GmailClient` calls the official Gmail client with `userId="me"`. Every request
must match the current opaque account scope. IDs and page tokens are bounded;
list pages contain at most ten messages. Each call uses its own transport.

`EMAIL_CHECK_GMAIL_DEADLINE_SECONDS` defaults to 20 seconds (maximum 120). A shared
budget covers an entire retrieval operation, including page metadata when wired
by the inbox route. Network failures, HTTP 429 and HTTP 5xx receive at most two
application retries with 0.25/0.5-second interruptible backoff. Other HTTP failures
are not retried. Per-attempt transport timeouts are capped at five seconds and
the remaining budget. An in-progress network call can finish after cancellation;
its result is discarded and no further request/retry starts.

The Google client uses a single-attempt standard-library HTTPS transport with
redirects disabled, rather than httplib2's implicit connection retries. It connects directly
to approved Google HTTPS endpoints without environment proxy configuration and
caps a response at 32 MiB. Deadline-aware streaming and an owned-socket shutdown
timer interrupt slow delivery. Oversized responses fail without retry.

The wrapper supports metadata/raw/full message retrieval. Separately stored MIME
parts are retrieved only for text/plain or text/html bodies without filenames;
ordinary file attachments are not fetched through that method. Encoded and decoded
content is size-bounded. No extracted URL is visited.

## Inbox and selection

In the Gmail tab, Connect opens Google's sign-in page. After consent, use the
callback page's Return link, choose Gmail and Refresh list. Select a message to
preview its extracted text, then Scan email. Next/Previous paginate ten entries
at a time. Selection, account and fingerprint checks discard stale results.

The HTTP contracts are listed in [API](API.md). Raw message retrieval uses Gmail's
size estimate as a preliminary gate and enforces the actual byte limit before
parsing. Authentication headers retain `gmail` provenance but are not marked
independently verified merely because the raw message came from Gmail. Retrieval
and extraction times are retained for scans. Only two retrieval workers may be
admitted; timed-out work keeps its slot until it actually finishes.

For a credential-free browser smoke, run
`python tests/ui/gmail_smoke_app.py` from the project root and open
`http://127.0.0.1:8006`. This explicitly marked test-double app uses synthetic Gmail
responses and no real model, credentials or account. Verify Refresh list > select
> Scan email and pagination. A simulated scan shows TEST DOUBLE and no real score.

Sources checked October 29, 2026: [desktop OAuth](https://developers.google.com/identity/protocols/oauth2/native-app),
[Google credentials](https://googleapis.dev/python/google-auth/latest/reference/google.oauth2.credentials.html),
[Gmail list](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/list),
[message retrieval](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/get),
[textual MIME retrieval API](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages.attachments/get),
[error handling](https://developers.google.com/workspace/gmail/api/guides/handle-errors).
