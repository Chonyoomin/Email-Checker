# Reproduce an exploratory baseline

Use the native Python 3.14 environment and already installed pinned checkpoint.
Preparation is an explicit online public-data step; model evaluation blocks
network connections. No Gmail credentials, retained user feedback or new model
downloads are used.

```powershell
.\.venv\Scripts\python -m bad_email_check.evaluation_dataset --download
$baselineManifestHash = (Get-FileHash data/evaluation/manifest.json -Algorithm SHA256).Hash.ToLowerInvariant()
.\.venv\Scripts\python -m bad_email_check.baseline --manifest-sha256 $baselineManifestHash --output data/baseline-new
.\.venv\Scripts\python -m bad_email_check.baseline_report data/baseline-new/results.json local-baseline.md
```

Freeze and record the manifest hash before predictions. The original approved
manifest and original run hash are preserved in the run reports. Byte serialization
such as line endings can change the hash across platforms; compare the approved
record IDs/content hashes before treating a new preparation as an equivalent set.
Never change examples after observing test results and call it the same holdout.

The runner evaluates all and only test records once, with cache disabled, and
preserves partial non-content outputs after each case. It refuses to overwrite an
existing results file. Use a new output directory for an intentional new run;
repeated predictions must not be used to select more reassuring estimates.

`results.json` retains per-ID labels, decisions, timings and memory observations,
not bodies or headers. `summary.json` and the rendered Markdown separate public
agreement metrics from synthetic safety outcomes. SQLite contains the normal
non-content metadata. A stopped/partial run cannot be rendered as a completed
baseline. Reports require the dataset/provider-label/representation/pretraining
limits in [dataset documentation](EVALUATION_DATASET.md).

The fixed 0.5 raw-estimate cutoff is an evaluation convention. It does not calibrate
probabilities, fit a threshold from the final test split, change UI risk bands,
or trigger training. Group bootstrap intervals have small-sample/boundary limits;
the report's Wilson intervals are an independent-email reference, not cluster-correct.
Timing is local pipeline time as defined in [metrics](METRICS.md), not Gmail or
browser end-to-end latency.

The approved [baseline](BASELINE_EVALUATION.md) and exact run evidence (development archive omitted)
retain the original byte hashes. Per-run Git attributes disable text conversion
for new exact artifacts; historical sources/locks are not globally renormalized.
Source/lock hashes are byte hashes too: line-ending conversion in another checkout
can change them without establishing equivalent execution. Review provenance and
the frozen record/content identities before treating a new run as comparable.

Historical verification refers to the original development workspace. Its run
archive, local data and checkpoints are not bundled. See [project history](PROJECT_HISTORY.md).
