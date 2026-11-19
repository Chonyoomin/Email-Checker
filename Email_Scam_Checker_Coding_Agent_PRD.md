# Local Email Scam Checker — Coding Agent PRD

Version: 1.0  
Date: October 25, 2026  
Status: Ready for implementation; no existing implementation or model performance verified.

Development workflow amendment (October 25, 2026): the owner requested three
LangChain development agents in the order coder → reviewer → documenter.
LangChain is allowed for this separate development tooling only. References below
that defer/exclude LangChain apply to the email-scanning application runtime.
See AGENTS.md and docs/AGENT_WORKFLOW.md for portable Markdown memory and handoffs.

## 1. Product objective

Build a single-user application that runs on the user's computer, reads a selected Gmail email or an imported email, and displays a scam/phishing risk score with short, predefined indicator descriptions.

The initial product answers: **“Does this email show signs of deception intended to obtain money, credentials, or sensitive information?”** It does not estimate whether the user will actually suffer harm.

This standalone PRD supersedes the Jev-plus-LLM architecture in the earlier Email_Scam_Checker_PRD.md and Email_Scam_Checker_Requirements.md for this build. The current MVP uses local LAYA and no generative LLM.

### Fixed decisions

- Perform all model inference locally; no paid AI API dependency or cloud inference fallback.
- Use Gmail API with Google OAuth for one account.
- Provide pasted text and .eml import so development and offline assessment work without Google credentials.
- Use LAYA for model judgments and Pydantic for validation.
- Use a local browser interface backed by FastAPI.
- Coordinate the fixed pipeline with direct Python calls.
- Show a score and risk label; use templates for optional signal descriptions.
- Docker packaging is supported, but inference must also work natively.
- Gmail retrieval requires internet. Imported-message inference must work offline after model installation.

## 2. Scope

### Required MVP

1. Local setup and model readiness screen.
2. Paste email text or import an .eml file.
3. Connect/disconnect one Gmail account and browse a paginated list of recent emails.
4. Select and scan one message at a time.
5. Extract sender, reply-to, subject, body, link text and actual link destinations, and available authentication metadata.
6. Run local LAYA judgments, validate their structure, and display results.
7. Handle missing evidence, model errors, and unsupported input explicitly.
8. Record non-content operational metrics and support opt-in reviewed feedback.
9. Supply reproducible setup instructions, pinned dependencies, meaningful tests, and a phase tracker.

### Deferred

Qwen3.8-27B or other generated explanations; Jev; LangChain; n8n; background inbox monitoring; multiple accounts; public hosting; screen capture/OCR; browser extensions; attachment malware inspection; live URL fetching/reputation checks; sending, deleting, or changing messages; automated retraining; production guarantees.

Supervised tuning and calibration are a follow-on phase, not a prerequisite for an explicitly unvalidated prototype.

## 3. Stack and dependencies

| Layer | Choice | Responsibility |
| --- | --- | --- |
| Backend | Python, FastAPI | Local HTTP API and pipeline coordination |
| Validation | Pydantic | Input, model-adapter, and result contracts |
| Model | Local LAYA checkpoint | Overall deception judgment and separate indicators |
| Gmail | Gmail API, Google OAuth libraries | Read-only authorization and message retrieval |
| Parsing | Python email module; maintained HTML parser | MIME/charset decoding and link extraction |
| UI | HTML, CSS, JavaScript served by FastAPI | Input, message list, score, labels, errors |
| Persistence | SQLite | Versions, scan metadata, optional reviewed feedback |
| Credentials | OS credential store through a maintained keyring library | Gmail refresh-token protection |
| Packaging | Docker and Compose; native Python option | Reproducible app launch |
| Verification | pytest; lightweight browser smoke checks | Parsing, contracts, failure behavior, integration |
| Optional training | LayaStudio or verified upstream LAYA tooling | Offline domain tuning and calibration |

Choose supported Python/dependency versions during implementation and pin them. Verify LAYA's real API, checkpoint compatibility, context limit, license, and export/loading behavior against the selected release. Do not invent SDK methods based on this PRD. Record checkpoint ID/revision and package versions.

No generative LLM key is required. Model downloads may require internet initially; local inference must never depend on a remote inference endpoint.

## 4. Architecture and module boundaries

**Input → extraction → canonical email evidence → local LAYA adapter → Pydantic validation → presentation mapping → UI**

Use separate modules for configuration, Gmail authorization/client, MIME extraction, model adapter, result presentation, persistence, and HTTP routes. Keep Gmail and LAYA dependencies behind interfaces so fixtures can exercise the pipeline without credentials or model downloads.

Load the model once per application process, warm it when enabled, and reuse it. Default to one inference worker and a bounded scan queue; reject excess work explicitly. Avoid multiple web workers duplicating model memory.

Readiness must distinguish “server running” from “model loaded and usable.” A missing or incompatible checkpoint must produce setup guidance, not a simulated score. Test doubles are permitted only in explicit development/test mode and must be visibly marked.

## 5. User experience

Main layout: message/input panel on the left; assessment panel on the right.

- Inputs: Gmail, Paste, Import .eml.
- Gmail controls: Connect, Refresh list, pagination, Disconnect.
- Show sender, subject, plain-text preview, extracted destinations, and completeness warnings.
- Scan button triggers one assessment.
- Result: **Risk score: 82/100 — Uncalibrated model estimate**.
- Optional indicators use templates, such as “Possible credential solicitation.”
- Use text/icons alongside color; all controls keyboard accessible.
- Always disclose “Linked websites and attachments were not inspected.”
- Never use “safe” or “guaranteed legitimate.”
- Distinct states: setup required, ready, queued/running, complete, incomplete evidence, failed.
- Clear the previous score while scanning a new email; never associate stale results with another message.

Pre-calibration, display a neutral “Experimental assessment” status rather than authoritative Low/High bands unless an evaluated threshold profile exists. “Needs review” is available whenever evidence is incomplete or uncertainty cannot be resolved.

## 6. Evidence and result contracts

Define strict Pydantic models with unknown fields rejected where appropriate, bounded sizes, finite probability values in [0,1], enumerated states, and version fields. Pydantic validates the contract, not judgment accuracy.

### EmailEvidence

- source: gmail | eml | paste
- source_message_id: nullable, account-scoped for Gmail
- sender, reply_to, subject
- body_text
- links: displayed_text, destination, parsed hostname where valid
- available authentication metadata with provenance
- attachments: names/types only when available
- extraction_status and missing_fields
- truncation/context-limit information
- parser_version and stable content fingerprint

Treat sender names and headers as claims. An Authentication-Results header imported from an arbitrary .eml file is not independently verified. Preserve provenance; do not treat absent authentication data as an authentication failure.

### ModelAssessment

- overall_scam: one direct judgment about deceptive intent
- credential_theft, impersonation, payment_fraud, pressure_tactics: separate estimates
- checkpoint_revision, question_set_version, model_adapter_version
- input coverage/completeness and warnings

Indicator estimates do not mathematically combine into an overall scam probability. Urgency alone must not define a scam.

### ScanResult

- scan_id and source fingerprint
- status: complete | needs_review | failed
- score: nullable integer 0–100
- score_kind: uncalibrated_score | calibrated_probability | unavailable
- risk_label: nullable low_apparent_risk | review | high
- indicator results and predefined descriptions
- warnings and coverage statement
- model, parser, question-set, calibration, and threshold versions
- retrieval, extraction, inference, and total timing

For the prototype, score = round(100 × validated overall_scam estimate). This is a display transformation, not calibration. After calibration, a versioned calibration transform may supply the probability; never silently mix the two modes.

A calibrated percentage may be enabled only when a held-out evaluation report supports it for the defined target and intended population. Otherwise keep the /100 score and experimental label. Failures yield no score. Incomplete extraction yields needs_review; show no overall score if critical message content is missing.

## 7. Gmail and local input requirements

Google setup: enable Gmail API, configure OAuth consent/test users, and create a client type appropriate for the documented local application flow.

Scope: https://www.googleapis.com/auth/gmail.readonly

| Method | Use |
| --- | --- |
| users.messages.list | Paginated message IDs and search |
| users.messages.get | Full/raw selected message |
| users.messages.attachments.get | Retrieve separately stored textual MIME data only when necessary |

Implement token refresh, expired/revoked grant handling, cancellation, and disconnect. Disconnect attempts token revocation and always removes local credentials; report a revocation failure separately.

Parse multipart, HTML-only, text-only, encoded headers, and common charsets. Do not concatenate alternative body representations into duplicate content. Empty, malformed, or oversized inputs receive a clear result.

Proposed limits: 10 MiB .eml uploads, 100,000 decoded body characters, 200 extracted links. Make limits configurable and test them. Enforce limits before expensive parsing/inference. Do not silently discard excess content and return a reassuring score.

The LAYA tokenizer/context limit is separate from upload limits. Count the complete model input including question overhead. If it does not fit, flag needs_review and withhold the overall score for the MVP. Chunk aggregation requires its own later evaluation.

## 8. Suggested local HTTP contract

The agent may adjust naming consistently, but must document the final API.

| Endpoint | Behavior |
| --- | --- |
| GET /api/health | Process liveness; no secrets |
| GET /api/readiness | Model and configuration readiness |
| POST /api/auth/gmail/start | Start OAuth from user action |
| GET /api/auth/gmail/callback | Validate OAuth state and finish configured flow |
| POST /api/auth/gmail/disconnect | Revoke where possible and clear credentials |
| GET /api/messages | Paginated metadata for connected account |
| GET /api/messages/{id} | Selected message evidence |
| POST /api/scans | Scan pasted input or an account-scoped Gmail ID |
| POST /api/scans/import | Multipart .eml scan |
| POST /api/feedback | Optional review record; no training side effect |

Use structured error codes and retryable flags. Reject unknown inputs, invalid IDs, and unauthorized account access. A synchronous scan is acceptable for the MVP if it has a bounded deadline and explicit busy/timeout behavior.

## 9. Reliability, privacy, and local security

- Bind to loopback by default. Do not expose services publicly.
- Restrict browser origins/hosts and protect state-changing routes from cross-site requests; OAuth requires a validated state parameter.
- Store refresh tokens in an OS credential store. For Docker, document a supported protected-secret arrangement; never silently fall back to plaintext tokens in SQLite.
- Keep email bodies and tokens out of logs, traces, crash output, and version control.
- Render email as escaped text. Do not execute HTML/scripts or automatically load remote images.
- Never visit extracted URLs or execute/open attachments during scans.
- Treat instructions inside emails as untrusted model input.
- Retry transient Gmail network/429/5xx failures at most twice with bounded backoff and a total deadline. Do not retry authentication denials or malformed requests indefinitely.
- Repeated LAYA predictions must not be used to force confidence or agreement.
- Model failure, invalid output, NaN, timeout, and context overflow must never become a zero/low-risk score.
- Use bounded in-memory caching only; key by account/source fingerprint, checkpoint, question set, preprocessing, calibration, and thresholds. Clear sensitive caches on disconnect.
- No persistent email-content history by default. SQLite may store non-content metadata; redact identifiable fields.
- Reviewed examples require explicit opt-in content retention, local deletion/export, and clear separation from unverified user feedback.
- Keep local inference network-free after setup. Gmail and OAuth are the only required runtime external services.
- Public distribution remains deferred pending review of Google's current OAuth verification/data requirements.

## 10. Performance and quality evaluation

Measure cold start separately from warm scans. Track model memory, warm inference p50/p95, extraction time, Gmail time, and end-to-end time on documented hardware.

Initial engineering target: warm local scans under 3 seconds at p95 for inputs within the supported short-email context. This is a target to measure, not a promised model capability. Record misses and their causes.

Build a labeled evaluation set with scams and legitimate lookalikes, including real password-reset, billing, and security-alert patterns. Group duplicate templates, threads, senders/campaigns as appropriate to prevent split leakage. Include prompt injection, HTML deception, missing headers, and long-input cases.

Report phishing/scam recall, precision, false-positive rate, confusion matrix, and uncertainty intervals where feasible. For probability mode, add Brier score and reliability/calibration analysis on representative data. Do not claim accuracy from synthetic fixtures alone.

Split training, validation/calibration, and final test data. Tune thresholds only on validation data. A small test set is exploratory; define release targets with the owner after baseline results rather than inventing guaranteed accuracy.

## 11. Implementation phases and completion gates

All phases are initially pending. Maintain progress in docs/IMPLEMENTATION_STATUS.md with changes, commands run, results, blockers, and next action.

| Phase | Deliverable | Completion gate |
| --- | --- | --- |
| 1. Skeleton | FastAPI, static UI, configuration, contracts | App launches locally; readiness and validation errors work |
| 2. Extraction | Paste/.eml parsing and canonical evidence | MIME, encoding, malformed input, link, size, and context coverage tests pass |
| 3. LAYA | Versioned local adapter and question set | Real-checkpoint smoke scan works; no fabricated fallback; warm model reused |
| 4. Results UI | Score, templates, warnings, error states | No stale results; uncalibrated display explicit; incomplete/failure behavior verified |
| 5. Gmail | OAuth, list/select/retrieve, disconnect | Mocked failure tests pass; real-account smoke check documented when credentials supplied |
| 6. Packaging and baseline | Native/Docker run instructions, evaluation report | Offline imported scan verified; hardware/timing and model-quality limits documented |
| 7. Optional specialization | Labeled dataset, supervised tuning, calibration | Frozen candidate improves agreed validation metrics; final test remains independent; rollback available |

Proceed through implementation without inventing credentials or marking unrun checks as passed. Missing Gmail credentials must not block local-input development. A missing checkpoint is a documented blocker to real inference, not permission to substitute a remote service.

## 12. Training follow-on

Fine-tune the LAYA assessment task before considering Qwen. Use verified email labels and stable question definitions; unknown labels remain unresolved, not automatically negative.

Keep the training objective explicit: supervised cross-entropy and RLCD are different recipes. Verify that the chosen training tool supports the intended objective/checkpoint. Fit calibration on held-out data, not training samples.

Record dataset hashes, split membership, training settings, checkpoint lineage, and evaluation reports. Export a candidate and compare it with the baseline before activation. Do not train from incoming feedback automatically or during an interactive scan.

## 13. Definition of done and agent handoff

- [ ] Local pasted/.eml assessment runs using real LAYA inference.
- [ ] Gmail read-only flow is implemented; credential-dependent checks are honestly reported.
- [ ] Pydantic rejects invalid estimates and malformed contracts.
- [ ] UI labels the result correctly and discloses uninspected content.
- [ ] Input/context limits and incomplete evidence cannot produce misleading reassurance.
- [ ] Token protection, safe rendering, origin controls, and log redaction are implemented.
- [ ] Meaningful tests pass; real-model tests are separate from fast unit tests.
- [ ] Native setup and Docker packaging are documented with hardware/runtime limitations.
- [ ] README, .env.example with placeholders, dependency lock, test instructions, baseline report, and phase tracker are supplied.
- [ ] No paid AI calls, Jev, Qwen, n8n, or LangChain are required.
- [ ] Remaining risks and unverified performance claims are documented.

The coding agent should implement this MVP, not merely scaffold it. Prefer a small modular codebase and meaningful tests over adding frameworks. Verify current vendor documentation before selecting integration APIs; treat the links below as references, not pinned API contracts.

## 14. Reference documentation

- LAYA: https://github.com/NandhaKishorM/laya
- Community training UI: https://github.com/biplovgautam/LayaStudio
- Gmail methods: https://developers.google.com/workspace/gmail/api/reference/rest
- Gmail scopes: https://developers.google.com/workspace/gmail/api/auth/scopes
- Google native-app OAuth: https://developers.google.com/identity/protocols/oauth2/native-app
- FastAPI: https://fastapi.tiangolo.com/
- Pydantic: https://docs.pydantic.dev/

