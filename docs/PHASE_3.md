# Local model and scan API

LAYA 0.4.15 runs on CPU with the pinned English checkpoint in
`src/bad_email_check/laya_checkpoint.json`. Required files are SHA-256 checked.
Runtime loading never downloads weights or falls back to remote inference.

## Setup (PowerShell, Python 3.14)

```powershell
.\.venv\Scripts\python -m pip install -r requirements-dev.lock
.\.venv\Scripts\python -m pip install --no-deps --no-build-isolation -e .
.\.venv\Scripts\python -m bad_email_check.setup_checkpoint
$env:EMAIL_CHECK_CHECKPOINT_PATH = 'checkpoints/laya-english'
.\.venv\Scripts\python -m bad_email_check
```

The explicit setup command contacts Hugging Face for the pinned revision, downloads
about 843 MB of weights plus tokenizer/configuration, and verifies hashes. Run it
during setup with internet access. The application sets Hub/Transformers offline
flags and disables their telemetry before loading. Real tests also block socket
connections during loading and inference. Do not enable external email tracing.
An existing directory must contain the exact reviewed files; the application does
not fetch `CHECKPOINT_ID`. Configuration may instead live in an ignored `.env`.

Readiness distinguishes process liveness, actual model loading, and fixture mode.
Missing, modified or incompatible artifacts leave scans unavailable. One model
instance loads per app lifespan; use one web worker. Each question's actual head,
special tokens and canonical evidence must fit the 2,048-token runtime window.
This explicit runtime override keeps the checkpoint files and head limit 192
unchanged; adapter/cache identity is laya-adapter-v2-context2048. Truncation
is checked before and after inference. Overflow yields needs_review with no score.
No automatic chunking or alternate checkpoint is used.

## Endpoints and results

- `POST /api/scans`: JSON `{ "text": "email text" }` (source defaults to paste).
- Gmail input requires source, source_message_id and the current account_scope;
  OAuth, inbox selection and disconnect are documented in [Gmail runtime](GMAIL_RUNTIME.md).
- `POST /api/scans/import`: multipart with exactly one `file` ending in `.eml`.
  Byte limits apply before parsing/inference. Temporary upload files are closed
  after parsing. Scans persist [non-content metadata](METADATA.md); retaining email
  content requires explicit [feedback opt-in](FEEDBACK.md).

Send a matching local Origin or `X-Email-Checker-Request: 1`. Unknown fields and
invalid IDs are rejected. Results include fresh scan ID/fingerprint, provenance,
timings, warnings, coverage and `is_test_double`. A successful real scan transforms
only the direct overall judgment to an experimental, uncalibrated /100 score.
The nested `assessment` preserves all five validated model estimates; the current
UI renders predefined indicator descriptions and coverage warnings.
Indicators are not averaged; risk bands remain unset. Incomplete evidence yields
no score. Invalid output, NaN and exceptions return generic errors, never zero.
The UI supports interactive paste/import/Gmail scans with stale-result protection.

## Bounded execution

One inference worker has `QUEUE_SIZE` waiting slots (default 1). The default
`SCAN_DEADLINE_SECONDS` is 120; browser wait is 150 seconds. Saturation returns
retryable `scan_busy` (429); deadline expiry returns `scan_timeout` (504) without a
score. Timeout does not forcibly kill inference: its admission slot remains held
until completion, and expired queued work drains without inference. A permanently
stalled backend needs a process restart. Repeated timeouts cannot accumulate an
unbounded backlog of email evidence.

The in-memory cache stores assessments, not bodies. Keys include source/account,
fingerprint/evidence hash, checkpoint, question, adapter, parser, preprocessing,
calibration and threshold versions. Cache hits get fresh scan IDs. `CACHE_ENTRIES=0`
disables caching; disconnect clears cache and invalidates retired work. Identical
repeats can be faster through caching. Prefix
configuration names with `EMAIL_CHECK_`. No cache is persisted.

## Fixture mode and verification

Explicit `MODE=test` or development plus `MODEL_BACKEND=test_double` enables fixed
fixture judgments. Production rejects the backend and injected test doubles.
API warnings/flags and readiness banner say TEST DOUBLE. Fixtures return no real
score or coverage claim. Missing real weights never activate this backend.

```powershell
.\.venv\Scripts\python -m pytest -q -m 'not real_model'
$env:EMAIL_CHECK_RUN_REAL_MODEL = '1'
.\.venv\Scripts\python -m pytest tests/product/test_offline_import.py -q
Remove-Item Env:EMAIL_CHECK_RUN_REAL_MODEL
```

Real checks prove execution/offline/context/reuse behavior, not scam accuracy.
The vendor warns that an unrelated choice-temperature entry is clamped; all app
judgments remain explicitly uncalibrated. Initial warm scans exceeded the 3-second
engineering target. The [Phase 6 baseline](BASELINE_EVALUATION.md) now records hardware/timing and
exploratory quality limits; its warm p95 misses the target and phishing recall is
poor. Windows/Python 3.14.4 and the Linux CPU container are verified; other native
platforms remain unverified.

## Current 2,048 runtime verification

The owner requested 2,048 after offline boundary validation. Default/reuse/overflow/
socket-guard real smoke passed; a fresh live synthetic input with 838 state tokens
before question overhead completed in 15.207 s total. This is not p95, quality or a
new Gmail account check. Runtime evidence and exact artifacts (development archive omitted).

Historical verification refers to the original development workspace. Its run
archive, local data and checkpoints are not bundled. See [project history](PROJECT_HISTORY.md).
