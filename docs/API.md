# Local API

Default base URL: `http://127.0.0.1:8000`.

| Endpoint | Result |
| --- | --- |
| `GET /` | Local setup/input/assessment shell |
| `GET /static/app.css`, `/static/app.js` | Local UI assets |
| `POST /api/feedback` | Record owner feedback; content retention defaults off |
| `GET /api/feedback/export` | Export bounded pages; local request header required |
| `DELETE /api/feedback/{id}` | Delete feedback and opted-in content |
| `GET /api/health` | `{"status":"running"}`; liveness only |
| `GET /api/readiness` | Versioned server/model/setup status; no checkpoint paths |
| `GET /openapi.json` | Implemented API schema |
| `POST /api/previews/paste` | JSON `{text}` to extraction evidence and preview status |
| `POST /api/previews/import` | Raw `.eml` bytes to extraction evidence and preview status |
| `POST /api/scans` | Paste scan or selected account-scoped Gmail scan |
| `POST /api/scans/import` | Multipart `.eml` scan using the loaded local model |
| `GET /api/auth/gmail/status` | Connection state and opaque account scope |
| `POST /api/auth/gmail/start`, `/cancel` | Start/cancel browser-bound OAuth |
| `POST /api/auth/gmail/disconnect` | Delete local grant/cache; report remote revocation failure separately |
| `GET /api/auth/gmail/callback` | Validate state/cookie and complete OAuth |
| `GET /api/messages?account_scope=...` | Up to ten message summaries; optional `page_token` and `q` |
| `GET /api/messages/{id}?account_scope=...` | Canonical selected-message extraction preview |

Readiness reports `ready` after loading the pinned local checkpoint, or an explicit
fixture backend. `model_loaded=true` means a real model is loaded;
`is_test_double=true` identifies fixture mode. Missing/invalid artifacts report
`checkpoint_missing`/`checkpoint_unavailable`; they never trigger downloads.
`scans_available` indicates whether the API can accept scans. Checkpoint paths
are not exposed. Development/test mode is explicitly reported.

Errors use `{schema_version, code, message, retryable}`. Invalid requests return
422 without echoing input; unknown routes return 404. Internal errors are generic.
Gmail requires the configured Desktop client and protected credential store;
see [runtime behavior](GMAIL_RUNTIME.md). Feedback supports explicit opt-in retention, paginated local export and deletion;
see [feedback contracts](FEEDBACK.md). Disconnect returns `{disconnected, revocation_failed}`
only after local credential deletion succeeds.

Host must be a configured local authority with its exact port. State-changing
requests require a matching Origin; non-browser local clients without an Origin
must send `X-Email-Checker-Request: 1`. Foreign/null/duplicate origins and cross-site
fetch metadata are rejected. CORS is not enabled. Security headers apply to assets
and errors. Access logging and proxy-header trust are disabled in the launcher.

## Preview requests

Paste uses `Content-Type: application/json`; its text field accepts body-only text
or a message with headers. Unknown fields and invalid JSON return a generic 422.
Import uses `Content-Type: message/rfc822` or `application/octet-stream` with raw
bytes, not multipart. Both routes enforce the same local request protections.

Preview responses contain `schema_version`, `evidence`, `status`, and
`coverage_statement`. Status is `complete`, `needs_review`, or `failed`; it describes
extraction only. No score or model assessment is returned. Content is not saved.
Warnings and missing fields describe coverage; absent authentication is unknown.
Imported/pasted authentication headers are unverified claims, including pass claims.

Byte limits apply while streaming (even without Content-Length) before MIME parsing.
Oversized HTTP bodies return 413; invalid media types 415; upload timeout 408.
The default import limit is 10 MiB. Paste JSON is separately bounded to allow JSON
escaping, then decoded text is checked against the configured byte/character limits.
The contract caps body length at 100,000 characters and links at 200; configured
lower limits apply. Header blocks are capped at 64 KiB, MIME parts at 200, and
selected-body nesting at 30. Attachment/authentication metadata counts are bounded.

Oversized decoded bodies are withheld rather than passed to HTML parsing. Partial
evidence is explicitly incomplete; missing body produces failed extraction. Link
limits and cropped fields are flagged. HTML alternatives are preferred to preserve
displayed text vs destination; alternative bodies are not duplicated. Mixed inline
text parts are joined within the character budget. Attachment content is not decoded.
HTML scripts/styles are omitted, remote images are not fetched, and UI evidence is
inserted only as text. Extracted destinations remain non-clickable text, including
malformed/unsupported URLs. Duplicate HTML href destinations are retained and flagged.

Model context is explicitly unchecked in preview responses. The tested
`with_context_coverage` helper requires a caller-supplied tokenizer and complete
model input (including questions/metadata), flags overflow/failure, and returns no
score. Real scans use the pinned LAYA adapter described in
[local model and scan API](PHASE_3.md), with actual sequence checks and a second
returned-truncation guard. Preview endpoints remain extraction-only.

Implementation references: [Python email parser](https://docs.python.org/3.14/library/email.parser.html),
[MIME messages](https://docs.python.org/3.14/library/email.message.html),
[HTMLParser](https://docs.python.org/3.14/library/html.parser.html),
[bounded request streaming](https://starlette.dev/requests/).

## Scan presentation

Successful complete real scans include `assessment_label: "Experimental assessment"`,
`score: round(100 * overall_scam)` and `score_kind: "uncalibrated_score"`.
`risk_label`, calibration and threshold versions remain null; no evaluated risk
bands or calibrated probabilities are generated. Indicators never combine into
an overall score.

`indicators` supplies all four independent estimates with predefined descriptions:
credential solicitation, impersonation, deceptive payment request and pressure
tactics. These are model estimates, not thresholded findings. The pressure text
explicitly states that urgency alone does not establish deception.

Incomplete evidence/context/model coverage, missing assessment and test-double
output have `status: "needs_review"`, `assessment_label: "Needs review"`, null score,
`score_kind: "unavailable"` and empty indicators. Failed extraction instead uses
`status: "failed"` and `assessment_label: "Assessment failed"`, also without a score.
Model execution errors remain structured HTTP errors. Warnings, coverage, timings,
source fingerprint and available assessment provenance are preserved.
`runtime` distinguishes cold load, first/warm/cached/not_run model stages and
logical model/process memory; see [metrics](METRICS.md). Returned scan metadata
uses the [non-content allowlist](METADATA.md).

The result panel and state/stale-result handling are complete. The Phase 5 account
smoke (development archive omitted) verified Gmail connection/list/matching preview,
a needs-review/no-score scan and disconnect. It does not establish a scored Gmail
inference, exact token count/offending field or independently verified Google-side
revocation. The reported no-score category was local input coverage.

The [Phase 6 baseline](BASELINE_EVALUATION.md) documents poor phishing recall and
the missed speed target. A numeric API estimate is not a legitimacy assurance;
no calibrated probabilities or new UI risk bands are enabled.
