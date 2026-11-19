# Exploratory specialization evaluation

The November17 candidate failed the owner validation gate: phishing recall did not
improve without additional false alerts. Both baseline and candidate missed2/2
reviewed phishing emails and flagged2/9 legitimate emails at raw0.5. Candidate is
rejected; baseline remains active. Phase7 is incomplete.

Temperature fitting improved Brier0.2571 ->0.2168 on the same11 validation examples
used to fit it. This is exploratory fit-sample behavior, not an independent
probability-reliability estimate. Two positives and small historical/redacted samples
cannot support calibrated probabilities or risk bands; all remain disabled. The
validation threshold search also detected neither phishing example.

Exact report, provenance and limitations (development archive omitted),
independent review (development archive omitted). Final test remains unpredicted.
More verified representative data and a new predeclared candidate are needed before
retrying the quality gate. New feedback submissions remain unverified until review;
scans and feedback never train automatically.

Historical verification refers to the original development workspace. Its run
archive, local data and checkpoints are not bundled. See [project history](PROJECT_HISTORY.md).
