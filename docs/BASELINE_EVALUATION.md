# Exploratory baseline evaluation

This small, redacted historical set does not establish accuracy for current Gmail.
At the fixed 0.5 evaluation cutoff, public phishing recall was
33.3%: 8 of 12 scored source-positive emails
fell below the cutoff. 4 of 4 scored synthetic deception cases
also fell below it. These results do not support relying on the score to establish legitimacy.

## Frozen inputs and execution

- Dataset manifest SHA-256: `57cec9d3a8c96774e60de3aab0c782109a60f6d3f51f64d12faa203ff1db7642`.
- Held-out records: 34; train/validation were not predicted.
- Completed real prediction calls: 31; one model reused; cache disabled.
- Guarded network attempts: 0 during loading/scans.
- Fixed raw-estimate cutoff: 0.5; no tuning, calibration or new UI risk band.
- Checkpoint: `55cf4c4ebb4ebe31b2550e8bdf3bd21b99753851`.
- Adapter: `laya-adapter-v2-context2048`; questions: `email-deception-v1`.
- Parser: `2.0.0`.
- Input context: 2048 tokens; head: 192.

## Public-corpus results

Enron non-spam is a proxy for legitimate; Nazario provides source-labeled phishing.
These labels were not newly adjudicated. Synthetic cases are excluded from this table.

| True source label | Predicted phishing | Predicted negative | Abstained/no score |
| --- | --- | --- | --- |
| Phishing | 4 | 8 | 0 |
| Non-spam proxy | 0 | 12 | 0 |

| Metric | Point estimate | Group-bootstrap 95% interval |
| --- | --- | --- |
| Precision | 100.0% | 100.0% to 100.0% |
| Phishing recall | 33.3% | 7.1% to 63.6% |
| Operational false-alert rate | 0.0% | 0.0% to 0.0% |
| Scored coverage | 100.0% | 100.0% to 100.0% |

Precision = TP/(TP+FP). Recall includes positive abstentions in its denominator.
Operational false-alert rate = FP/(FP+TN+negative abstentions), over ALL source negatives.
Conditional false-positive rate on scored negatives, FP/(FP+TN), is 0.0%.
Abstentions never silently become correct negative predictions.

Intervals resample 23 complete public groups 2000 times, seed 20261029.
Small-sample percentile intervals can degenerate at 0%/100%; that does not establish
zero error or certainty. Wilson reference intervals assume independent emails and
are NOT cluster-correct: precision 51.0% to 100.0%; recall 13.8% to 60.9%; false_positive_rate 0.0% to 24.2%.

## Synthetic safety cases

These authored cases test behavior; they are not pooled with public examples for accuracy.

| Case | Intended fixture label | Status | Decision |
| --- | --- | --- | --- |
| password_reset | legitimate | complete | negative |
| billing | legitimate | complete | negative |
| security_alert | legitimate | complete | negative |
| credential_theft | deception | complete | negative |
| payment_fraud | deception | complete | negative |
| prompt_injection | deception | complete | negative |
| html_deception | deception | complete | negative |
| missing_headers | legitimate | failed | no score |
| long_legitimate | legitimate | needs_review | no score |
| long_phishing | deception | needs_review | no score |

Long inputs withhold scores. The malformed missing-header fixture fails extraction.
Other scored fixture decisions are measured model behavior, not legitimacy assurances.

## Hardware and timing

AMD Ryzen 5 9600X 6-Core Processor; 12 logical CPUs; Windows 11; AMD64.
Python 3.14.4; Torch 2.14.1+cpu; 4 Torch threads; CPU inference.
Physical RAM: 33396543488 bytes. Logical model tensor bytes:
1685175832. Peak process RSS:
2901123072 bytes, including Python/dependencies and all scans.

| Measurement | Observed |
| --- | --- |
| Cold verification/load | 19.698 s |
| First inference | 6.709 s |
| Warm scored count | 30 |
| Warm model-stage p50 / p95 | 4.649 s / 10.481 s |
| Warm extraction p50 / p95 | 0.001 s / 0.002 s |
| Warm pipeline p50 / p95 | 4.650 s / 10.484 s |

The initial warm p95 <3-second engineering target was **NOT met** in this sample.
Model-stage time dominates extraction; no kernel-level cause was profiled.
Warm statistics include scored warm runs only, excluding first inference, cache hits
and extraction/context abstentions. Cold load is separate. Pipeline total excludes
metadata persistence, response serialization and browser overhead. HTTP/browser/Gmail
retrieval p95 was not measured. Short redacted cases do not characterize every input
up to the 2,048-token boundary. Single cold/first samples are not latency guarantees.

## Limits and next action

Source age, balanced short-input sampling, provider-label uncertainty, redaction and
plaintext wrapper changes limit transfer to current mail and deployment prevalence.
Precision depends on prevalence. Grouping cannot prove separation from unknown campaigns
or from the checkpoint's undisclosed pretraining/training data: no contamination-free
model holdout is established. See [dataset documentation](EVALUATION_DATASET.md) for attribution and transformations.

Estimates remain uncalibrated. No probability-mode claim, UI risk threshold, fine-tuning
or automatic training is enabled. Preserve per-ID numeric results and source hashes;
review errors with representative, verified labels before optional Phase 7. Do not
interpret a below-cutoff score as evidence that an email is legitimate.


Reproduce with [baseline instructions](BASELINE_RUN.md). The task report (development archive omitted)
and independent review (development archive omitted) retain gate evidence and
limitations. Exact per-ID results (development archive omitted),
summary (development archive omitted) and
unaltered generated report (development archive omitted) are preserved.

Historical verification refers to the original development workspace. Its run
archive, local data and checkpoints are not bundled. See [project history](PROJECT_HISTORY.md).
