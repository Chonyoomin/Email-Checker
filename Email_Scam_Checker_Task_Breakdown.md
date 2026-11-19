# Local Email Scam Checker — Task Breakdown

Source: [Email_Scam_Checker_Coding_Agent_PRD.md](Email_Scam_Checker_Coding_Agent_PRD.md) (v1.0, October 25, 2026)

This document splits the PRD's seven phases into small, independently reviewable chunks. Each chunk should fit in one focused work session or pull request, have its own tests, and leave the app in a runnable state.

**How to use this file**

- Work chunks roughly in ID order. "Depends on" lists hard prerequisites; anything not listed can run in parallel.
- Record progress, commands run, results, and blockers in `docs/IMPLEMENTATION_STATUS.md` (PRD §11), not here.
- A chunk is done only when its acceptance checks actually ran and passed. Do not mark unrun checks as passed.
- PRD section references are shown as §N.

**Ground rules that apply to every chunk** (PRD §1, §9)

- Product runtime: no paid AI APIs, no cloud inference, no Jev, Qwen, LangChain, or n8n.
- Owner amendment (October 25, 2026): LangChain is allowed for separate development
  tooling running coder → reviewer → documenter; see AGENTS.md and docs/AGENT_WORKFLOW.md.
- Never turn a failure, timeout, NaN, or missing evidence into a low or zero score.
- Keep email bodies and tokens out of logs, crash output, and git.
- Never use the words "safe" or "guaranteed legitimate" in the UI.

---

## Phase 1 — Skeleton

### 1.1 Repository and tooling setup
- **Scope:** Project layout, Python version choice, dependency manager with lockfile, pytest config, linter/formatter, `.gitignore` (excludes `.env`, SQLite DBs, checkpoints, tokens).
- **Deliverables:** `pyproject.toml` + lockfile, `src/` package, `tests/` folder, `.env.example` with placeholders only, `docs/IMPLEMENTATION_STATUS.md` with all phases marked pending.
- **Acceptance:** `pytest` runs (even with zero tests) and the lockfile pins every dependency.
- **PRD:** §3, §11, §13

### 1.2 Configuration module
- **Scope:** Typed settings (Pydantic settings or equivalent): bind host (default `127.0.0.1`), port, model checkpoint path/ID, size limits (10 MiB `.eml`, 100,000 body chars, 200 links), scan deadline, queue size, dev/test mode flag.
- **Acceptance:** Unit tests cover defaults, overrides from env, and rejection of invalid values (e.g. negative limits, non-loopback host without an explicit opt-in).
- **Depends on:** 1.1
- **PRD:** §4, §7, §9

### 1.3 Pydantic contracts
- **Scope:** `EmailEvidence`, `LinkInfo`, `AuthMetadata` (with provenance), `AttachmentInfo`, `ModelAssessment`, `IndicatorResult`, `ScanResult`, and the structured error model (`code`, `message`, `retryable`).
- **Rules:** Reject unknown fields; bounded string/list sizes; probabilities finite and in [0, 1]; enumerated `source`, `status`, `score_kind`, `risk_label`; version fields on every result.
- **Acceptance:** Tests show NaN, infinity, out-of-range values, unknown fields, and oversized inputs are rejected; valid examples round-trip.
- **Depends on:** 1.1
- **PRD:** §6, §8

### 1.4 FastAPI app, health, and readiness
- **Scope:** App factory, `GET /api/health` (liveness only, no secrets), `GET /api/readiness` (reports server up vs. model loaded vs. setup required, plus config problems). Global error handler that returns the structured error model.
- **Acceptance:** Tests confirm readiness reports "setup required" when no checkpoint is configured, and health never includes secrets or paths to tokens.
- **Depends on:** 1.2, 1.3
- **PRD:** §4, §8

### 1.5 Static UI shell
- **Scope:** HTML/CSS/JS served by FastAPI. Two-panel layout (input on the left, assessment on the right), tabs for Gmail / Paste / Import `.eml`, a setup/readiness banner wired to `/api/readiness`. No scoring yet.
- **Acceptance:** App launches locally, the page loads, readiness state shows, and every control is reachable by keyboard.
- **Depends on:** 1.4
- **PRD:** §5, Phase 1 gate

### 1.6 Local security baseline
- **Scope:** Loopback bind by default, allowed Host/Origin checks, cross-site request protection on state-changing routes (POST), log redaction helper that strips body text and tokens.
- **Acceptance:** Tests show a POST with a foreign Origin is rejected, an unexpected Host header is rejected, and the redaction helper removes body/token fields from log records.
- **Depends on:** 1.4
- **PRD:** §9

**Phase 1 gate:** App launches locally; readiness and validation errors work.

---

## Phase 2 — Extraction

### 2.1 Paste input normalization
- **Scope:** Turn pasted text into `EmailEvidence` (`source = paste`). Detect whether the paste includes headers; if not, record sender/subject/auth as missing fields rather than guessing.
- **Acceptance:** Tests cover body-only paste, paste with headers, empty paste, and oversize paste.
- **Depends on:** 1.3
- **PRD:** §2, §6

### 2.2 MIME parsing for `.eml`
- **Scope:** Python `email` module parsing for multipart, text-only, and HTML-only messages; encoded headers (RFC 2047); common charsets. Pick one body representation from `multipart/alternative` instead of concatenating both. Extract sender, reply-to, subject, and attachment names/types only.
- **Acceptance:** Fixture tests for each MIME shape, a bad-charset message, a message with encoded headers, and a check that alternative parts are not duplicated.
- **Depends on:** 1.3
- **PRD:** §6, §7

### 2.3 HTML to text and link extraction
- **Scope:** Maintained HTML parser converts HTML bodies to plain text and pulls out each link's displayed text, real destination, and parsed hostname (when valid). Never fetch any URL.
- **Acceptance:** Tests include mismatched text vs. destination (`paypal.com` text pointing elsewhere), malformed URLs, `javascript:` links, and the 200-link limit being flagged rather than silently dropped.
- **Depends on:** 2.2
- **PRD:** §6, §7, §9

### 2.4 Authentication metadata with provenance
- **Scope:** Read `Authentication-Results` / SPF / DKIM / DMARC fields when present and tag where they came from (Gmail-supplied vs. imported file, unverified). Absent data is "unknown", not "failed".
- **Acceptance:** Tests confirm imported headers are marked unverified and missing headers do not count as failures.
- **Depends on:** 2.2
- **PRD:** §6

### 2.5 Limits, completeness, and fingerprint
- **Scope:** Enforce the upload, body-character, and link limits **before** expensive parsing. Fill `extraction_status`, `missing_fields`, and truncation info. Add `parser_version` and a stable content fingerprint.
- **Acceptance:** Tests show each limit produces a clear status (not a reassuring score), the fingerprint is stable for identical input and changes when content changes, and empty/malformed inputs return a clear result.
- **Depends on:** 2.1, 2.2, 2.3
- **PRD:** §6, §7

### 2.6 Message preview endpoint path
- **Scope:** Wire paste and `.eml` extraction into a preview the UI can show: sender, subject, escaped plain-text preview, extracted destinations, completeness warnings. Rendering must be escaped text only, no remote images or scripts.
- **Acceptance:** Browser smoke check confirms an HTML email containing `<script>` and remote `<img>` shows as plain text and loads nothing.
- **Depends on:** 2.5, 1.5
- **PRD:** §5, §9

**Phase 2 gate:** MIME, encoding, malformed input, link, size, and context coverage tests pass.

---

## Phase 3 — LAYA model adapter

### 3.1 LAYA verification spike
- **Scope:** Before writing adapter code, confirm LAYA's real API, checkpoint format, tokenizer/context limit, license, and load/export behavior against a chosen release. Record checkpoint ID/revision and package versions.
- **Deliverables:** Short note in `docs/` with findings and any blockers. If no usable checkpoint is available, record that as a blocker; do not substitute a remote service.
- **Acceptance:** Findings are written down with sources; no SDK methods are assumed from the PRD.
- **PRD:** §3, §11, §14

### 3.2 Adapter interface and test double
- **Scope:** A `ModelAdapter` interface the pipeline calls. A fake adapter allowed only when dev/test mode is on, and its results are visibly marked as fake in the API and UI.
- **Acceptance:** Tests confirm the fake adapter cannot be used outside dev/test mode and its output carries a "test double" marker.
- **Depends on:** 1.3
- **PRD:** §4

### 3.3 Versioned question set
- **Scope:** Define the questions sent to LAYA: one overall deception judgment plus separate `credential_theft`, `impersonation`, `payment_fraud`, and `pressure_tactics` judgments. Version the set (`question_set_version`). Treat email content as untrusted input (prompt-injection resistant framing).
- **Acceptance:** Question text and version are stored in one place; tests check the version is attached to every assessment.
- **Depends on:** 3.1
- **PRD:** §6, §9

### 3.4 Real LAYA adapter
- **Scope:** Load the checkpoint once per process, optional warm-up, reuse across scans. Count the full model input (including question overhead) against the context limit; if it doesn't fit, return needs_review with no overall score. Validate every output through `ModelAssessment`.
- **Acceptance:** Real-checkpoint smoke scan works; a second scan reuses the loaded model (measured); context overflow, NaN, invalid output, and timeout each produce a failure or needs_review, never a low score. Real-model tests are marked separately from fast unit tests.
- **Depends on:** 3.1, 3.2, 3.3, 2.5
- **PRD:** §4, §6, §7, §9

### 3.5 Scan pipeline and queue
- **Scope:** Direct Python pipeline: evidence → adapter → validation → `ScanResult`. Single inference worker, bounded queue, scan deadline, explicit busy and timeout errors. Bounded in-memory cache keyed by source fingerprint, checkpoint, question set, preprocessing, calibration, and thresholds.
- **Acceptance:** Tests show queue-full returns a retryable busy error, deadline returns a timeout error, and cache keys change when any version changes.
- **Depends on:** 3.4 (can be built against 3.2 first)
- **PRD:** §4, §8, §9

### 3.6 Scan endpoints
- **Scope:** `POST /api/scans` (pasted input or account-scoped Gmail ID) and `POST /api/scans/import` (multipart `.eml`). Reject unknown fields and invalid IDs.
- **Acceptance:** API tests cover a valid paste scan, a valid import, an oversized upload, an unknown field, and model-not-ready.
- **Depends on:** 3.5, 1.6
- **PRD:** §8

**Phase 3 gate:** Real-checkpoint smoke scan works; no fabricated fallback; warm model reused.

---

## Phase 4 — Results UI

### 4.1 Score and presentation mapping
- **Scope:** `score = round(100 × overall_scam)` labeled `uncalibrated_score`. Pre-calibration, show "Experimental assessment" instead of Low/High bands. Map indicators to predefined templates (e.g. "Possible credential solicitation"). No score on failure; no overall score when critical content is missing.
- **Acceptance:** Unit tests for each status/score_kind combination; tests confirm indicators are never combined into the overall score.
- **Depends on:** 3.5
- **PRD:** §5, §6

### 4.2 Result panel
- **Scope:** Display "Risk score: NN/100 — Uncalibrated model estimate", indicator descriptions, warnings, coverage statement, and the fixed disclosure "Linked websites and attachments were not inspected." Use text/icons alongside color.
- **Acceptance:** Smoke check confirms the disclosure always appears and the forbidden words never appear.
- **Depends on:** 4.1, 1.5
- **PRD:** §5

### 4.3 UI states and stale-result protection
- **Scope:** Distinct states: setup required, ready, queued/running, complete, incomplete evidence (needs review), failed. Clear the previous result when a new scan starts; tie each result to its scan ID and source fingerprint so it can't be shown against a different message.
- **Acceptance:** Smoke check: start scan A, switch to message B, confirm A's result never appears with B. Each state renders and is keyboard accessible.
- **Depends on:** 4.2
- **PRD:** §5, Phase 4 gate

**Phase 4 gate:** No stale results; uncalibrated display explicit; incomplete/failure behavior verified.

---

## Phase 5 — Gmail

### 5.1 Google Cloud setup guide
- **Scope:** Docs for enabling the Gmail API, setting up OAuth consent and test users, and creating the right client type for a local app. Placeholders only in `.env.example`.
- **Acceptance:** A new user can follow the steps without guessing; no real credentials committed.
- **PRD:** §7

### 5.2 Token storage via OS keyring
- **Scope:** Store refresh tokens in the OS credential store through a maintained keyring library. Document the protected-secret approach for Docker. No plaintext fallback to SQLite or files.
- **Acceptance:** Tests (with a mocked keyring) confirm save/load/delete, and that a missing keyring backend produces a clear error instead of a plaintext fallback.
- **Depends on:** 1.2
- **PRD:** §9

### 5.3 OAuth flow
- **Scope:** `POST /api/auth/gmail/start` (user-triggered) and `GET /api/auth/gmail/callback` with validated `state`. Scope limited to `gmail.readonly`. Handle token refresh and expired/revoked grants.
- **Acceptance:** Mocked tests for a bad/missing state, a denied consent, an expired token that refreshes, and a revoked grant that asks the user to reconnect.
- **Depends on:** 5.2, 1.6
- **PRD:** §7, §8

### 5.4 Gmail client with retries
- **Scope:** Wrapper around `users.messages.list`, `users.messages.get`, and `users.messages.attachments.get` (textual MIME only, when needed). Retry network/429/5xx at most twice with bounded backoff and a total deadline; no retries on auth denials or bad requests. Support cancellation.
- **Acceptance:** Mocked tests for each retry case and the no-retry cases.
- **Depends on:** 5.3
- **PRD:** §7, §9

### 5.5 Message list and selection
- **Scope:** `GET /api/messages` (paginated metadata) and `GET /api/messages/{id}` (evidence via the Phase 2 parser, with Gmail-supplied auth provenance). Reject invalid IDs and access outside the connected account. UI: Connect, Refresh, pagination, select, scan.
- **Acceptance:** Mocked API tests for pagination, invalid ID, and unauthorized account; UI smoke check of list → select → scan using mocks.
- **Depends on:** 5.4, 2.5, 3.6
- **PRD:** §5, §7, §8

### 5.6 Disconnect
- **Scope:** `POST /api/auth/gmail/disconnect` tries token revocation, always deletes local credentials, clears sensitive caches, and reports a revocation failure separately.
- **Acceptance:** Mocked tests where revocation succeeds and where it fails; in both, credentials and caches are gone afterward.
- **Depends on:** 5.3, 3.5
- **PRD:** §7, §9

### 5.7 Real-account smoke check
- **Scope:** When credentials are supplied, run connect → list → scan → disconnect against a real test account and record the result. If no credentials are available, record that as not run.
- **Depends on:** 5.5, 5.6
- **PRD:** Phase 5 gate

**Phase 5 gate:** Mocked failure tests pass; real-account smoke check documented when credentials are supplied.

---

## Phase 6 — Persistence, packaging, and baseline

### 6.1 SQLite metadata store
- **Scope:** Store versions and non-content scan metadata (timings, status, versions). Redact identifiable fields. No email content stored by default.
- **Acceptance:** Tests confirm no body text, subject, or sender address is written to the database by default.
- **Depends on:** 3.5
- **PRD:** §2, §9

### 6.2 Opt-in reviewed feedback
- **Scope:** `POST /api/feedback`. Content is kept only with explicit opt-in; support local export and deletion; keep reviewed examples separate from unverified feedback. No training side effect.
- **Acceptance:** Tests for opt-in off (no content stored), opt-in on, export, and delete.
- **Depends on:** 6.1
- **PRD:** §2, §8, §9

### 6.3 Operational metrics and timing
- **Scope:** Record retrieval, extraction, inference, and total timing per scan; cold start separately from warm scans; model memory use.
- **Acceptance:** Timings appear in `ScanResult` and the metadata store; cold vs. warm are distinguishable.
- **Depends on:** 3.5, 6.1
- **PRD:** §6, §10

### 6.4 Native run instructions
- **Scope:** README covering install, model download, launch, test commands (fast vs. real-model), and an offline check: disconnect the network and scan an imported `.eml`.
- **Acceptance:** Offline imported scan verified and recorded.
- **Depends on:** 3.6
- **PRD:** §1, §11, §13

### 6.5 Docker packaging
- **Scope:** Dockerfile and Compose file, single web worker (to avoid duplicate model memory), model volume, loopback-only port binding, documented secret handling for Gmail tokens.
- **Acceptance:** Container starts, readiness reports correctly, and an imported scan works inside it.
- **Depends on:** 6.4, 5.2
- **PRD:** §3, §4, §9

### 6.6 Evaluation dataset
- **Scope:** Labeled set of scams and legitimate lookalikes (password resets, billing, security alerts). Include prompt injection, HTML deception, missing headers, and long inputs. Group by template/thread/sender/campaign to avoid split leakage. Separate train, validation/calibration, and final test splits.
- **Acceptance:** Dataset manifest with hashes, label sources, and split membership.
- **PRD:** §10

### 6.7 Baseline evaluation report
- **Scope:** Run the baseline model on the test split. Report recall, precision, false-positive rate, confusion matrix, and uncertainty intervals where feasible. Record hardware, warm p50/p95 against the 3-second target, cold start, and any misses with causes.
- **Acceptance:** Report saved in `docs/`; makes no accuracy claims from synthetic fixtures alone.
- **Depends on:** 6.3, 6.6, 3.4
- **PRD:** §10, Phase 6 gate

**Phase 6 gate:** Offline imported scan verified; hardware/timing and model-quality limits documented.

---

## Phase 7 — Optional specialization (follow-on)

### 7.1 Training tool verification
- **Scope:** Confirm LayaStudio or upstream LAYA tooling supports the chosen objective (supervised cross-entropy vs. RLCD) and checkpoint.
- **PRD:** §12

### 7.2 Supervised tuning run
- **Scope:** Tune on verified labels only (unknown labels stay unresolved). Record dataset hashes, splits, settings, and checkpoint lineage. No training from live feedback or during a scan.
- **Depends on:** 7.1, 6.6
- **PRD:** §12

### 7.3 Calibration and thresholds
- **Scope:** Fit a versioned calibration transform on held-out validation data; tune thresholds there only. Add Brier score and reliability analysis. Enable `calibrated_probability` and Low/Review/High bands only if the held-out report supports it.
- **Depends on:** 7.2
- **PRD:** §5, §6, §10, §12

### 7.4 Candidate comparison and rollback
- **Scope:** Compare the frozen candidate with the baseline on agreed validation metrics, keep the final test set independent, and keep a rollback path to the baseline checkpoint.
- **Depends on:** 7.3
- **PRD:** Phase 7 gate

**Phase 7 gate:** Frozen candidate improves agreed validation metrics; final test remains independent; rollback available.

---

## Phase 8 - Final prototype handoff and readiness checks (PRD section 13)

### 8.1 Final readiness and handoff

- **Scope:** Reconcile current state and verify the existing final handoff checklist; no new features or training.
- **Acceptance:** Evidence for all eleven items, fresh readiness/package checks, independent approval and durable handoff.
- **Depends on:** Completed MVP phases1-6; optional Phase7 stays owner-deferred.
- **PRD:** Section 13

Owner defined this phase on November 17, 2026 as the existing final handoff scope.
Phase7 remains optional, deferred and incomplete; no training or candidate promotion
is part of Phase8. [Evidence mapping](docs/FINAL_HANDOFF.md).

- [x] Local pasted/`.eml` assessment runs using real LAYA inference — *3.4, 3.6*
- [x] Gmail read-only flow implemented; credential-dependent checks honestly reported — *5.1–5.7*
- [x] Pydantic rejects invalid estimates and malformed contracts — *1.3*
- [x] UI labels the result correctly and discloses uninspected content — *4.1–4.3*
- [x] Input/context limits and incomplete evidence cannot produce misleading reassurance — *2.5, 3.4, 4.1*
- [x] Token protection, safe rendering, origin controls, and log redaction implemented — *1.6, 2.6, 5.2*
- [x] Meaningful tests pass; real-model tests separate from fast unit tests — *all*
- [x] Native setup and Docker packaging documented with hardware/runtime limits — *6.4, 6.5*
- [x] README, `.env.example`, dependency lock, test instructions, baseline report, and phase tracker supplied — *1.1, 6.4, 6.7*
- [x] No paid AI calls, Jev, Qwen, n8n, or LangChain required — *all*
- [x] Remaining risks and unverified performance claims documented — *6.7*

**Phase 8 gate:** The checklist is evidenced, current readiness/package checks
pass, independent handoff review approves and shared memory records the exact next
action. Checklist evidence and task8.1 are independently approved in
review2 (development archive omitted); Phase8 is complete. Prototype
handoff does not imply detection reliability or completion of deferred Phase7.

## Suggested critical path

1.1 → 1.2/1.3 → 1.4 → 2.2 → 2.3 → 2.5 → **3.1** → 3.4 → 3.5 → 3.6 → 4.1 → 4.3 → 6.4

Start 3.1 (LAYA verification) early, in parallel with Phase 2: it's the biggest unknown, and a missing checkpoint blocks real inference. Phase 5 (Gmail) can proceed in parallel once 1.6 is done, and doesn't block local-input work.
