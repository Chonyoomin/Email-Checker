# Project history retained as a summary

This clean source export starts a new repository history. Development-run archives,
local paths/process IDs, raw predictions, public corpora, owner-reviewed labels,
credentials, databases and training checkpoints are not copied. They remain in the
original workspace. Historical statements in operational guides refer to that
workspace, not tests freshly run after a new user's installation.

Implementation reached the original prototype handoff: phases 1-6 and 8 completed.
Optional Phase 7 remains owner-deferred and incomplete. The rejected candidate is
not shipped or activated. The current code uses the original pinned baseline.

Historical baseline evidence: 24 public source-labeled cases produced TP4/FN8/FP0/TN12;
all four scored authored deceptive fixtures also fell below the evaluation cutoff.
Warm pipeline p95 was 10.484 seconds on a Ryzen 5 9600X Windows machine. The first
specialized candidate and baseline both produced TP0/FP2/FN2/TN7 on eleven reviewed
validation messages. These small historical results do not establish reliability.

Google account smoke checks previously covered connect/list/matching preview/
needs-review-without-score/disconnect. Scored Gmail accuracy and independent Google-side
revocation were not established. Docker verification used synthetic protected-store
tokens; a real Docker Gmail flow was not verified.

The clean export's own checks are recorded in [the bootstrap report](runs/bootstrap/REPORT.md).
Cold installation and account-specific setup require fresh verification. Development
agents must not claim historical artifacts are present or resume deferred training.
