# Timing and memory

`ScanResult.timings` records retrieval, extraction, the model stage, and elapsed
time through assessment creation in milliseconds. Queue wait contributes to total
time. The model stage includes tokenization and coverage/output guards. Total
time excludes metadata persistence, response serialization and browser rendering.
Measure the HTTP request separately for end-to-end comparisons.

`ScanResult.runtime` and matching SQLite columns add:

| Field | Meaning |
| --- | --- |
| `model_load_ms` | One-time checkpoint verification/loading duration for this process; null for injected adapters |
| `model_tensor_bytes` | Logical bytes in model parameters and buffers; not total inference memory |
| `process_rss_bytes` | Process resident memory when creating the result |
| `process_peak_rss_bytes` | Process lifetime peak resident memory; includes Python/dependencies and all scans |
| `inference_phase` | `first`, `warm`, `cached`, or `not_run` |

The real adapter counts completed prediction calls, so preflight overflow does not
consume the first-inference classification. Cache hits have zero inference time.
Incomplete extraction is `not_run`; fixture results remain explicitly marked.
Memory readings are supported on Windows and Linux; unavailable values are null.
RSS and peak values are whole-process observations, not isolated model allocation.

SQLite upgrades add nullable columns to existing records without deleting old
scans or opted-in feedback. These metrics contain no email content or identifiers.
Cold loading is reported separately and is not added to every scan's total.
Population p50/p95 and model-quality claims require the Phase 6 baseline report.
