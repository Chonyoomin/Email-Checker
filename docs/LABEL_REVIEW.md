# Verified labels for Phase 7

This optional workflow is deferred and is not part of application installation.
No datasets or reviewed labels are bundled. On an explicit request to resume this
workflow, first prepare the historical baseline dataset using the
[dataset guide](EVALUATION_DATASET.md). Its exact manifest must match the pinned
baseline hash before the specialization tool will accept it. Stop on a mismatch;
do not disable the integrity check or treat provider labels as human reviews.

Task 7.2 cannot use Phase 6 provider labels as independently verified training
labels. The local review tool presents redacted public examples without source
labels, model scores or split membership. It runs no model, training or Gmail code.
Existing `.impeccable.md` owner-approved calm/minimal/light styling is retained.

```powershell
.\.venv\Scripts\python -m bad_email_check.specialization_data --download
.\.venv\Scripts\python -m bad_email_check.label_review --port 8010
```

Preparation reuses the 12 reserved training and 12 validation records, and selects
24 fresh final-test records from groups excluded from the entire published Phase 6
cohort. Source hashes, groups and data are validated before serving. It refuses to
overwrite an existing cohort. Newly downloaded source CSVs are removed; existing
source inputs are preserved. Public records remain outside Git and agent memory.

Open http://127.0.0.1:8010 in a regular browser:

1. Read the text and extracted destinations. Nothing is rendered as email HTML;
   destinations are literal text and never opened by the tool.
2. Choose deceptive intent, legitimate communication, or cannot determine.
3. Check that you reviewed it yourself, then Save and next. No source label is
   preselected. Unknown remains unresolved and must not become a negative target.
4. After all 48 decisions, explicitly agree to a validation policy and Finish review.

The policy choices use a fixed raw estimate cutoff of 0.5. They require increased
phishing recall with no additional false alerts, increased recall within an explicit
additional-alert budget, or fewer false alerts without reduced recall. A policy is
not agreed merely because it appears as the default choice. Finalizing is the
explicit agreement and freezes the decisions; it does not start training or activate
a model. Source labels can disagree with the owner decisions and never override them.

`reviewed-labels.json` contains decisions, timestamps and hashes only. Its owner
review flag is a local human attestation, not independent identity verification.
Save failures leave the in-memory state unchanged. Reload resumes at the first
unreviewed message. Only one server may write a cohort at a time; an OS lock is held
for its lifespan and released on exit/crash. Do not delete or replace the lock file
while a server is running. State is restored after locking, so stale server objects
cannot overwrite a frozen review. Frozen reviews reject edits; corrected decisions require a new
review revision before any new training. Do not manually change a frozen review and
call it the same verified dataset.

Known labels, both classes and sufficient independent groups will be checked again
before a supervised run. Unresolved examples may require more reviewed data. No
retained Gmail feedback is imported, no candidate exists yet, and the active
checkpoint remains unchanged. Agent verification uses synthetic UI/API fixtures;
actual public email text must not be copied into chat, reports or agent context.

Historical verification refers to the original development workspace. Its run
archive, local data and checkpoints are not bundled. See [project history](PROJECT_HISTORY.md).
