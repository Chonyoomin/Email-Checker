# Email Checker clean export verification

November 17, 2026. Owner requested a separate GitHub-ready source folder and chose
Email Checker (`email-checker`). Assembly, coder checks and independent review are complete; the prepared
source folder is approved. This report describes the export, not a new machine installation.

## Changes

Source, tests, optional development-agent tooling, pinned locks and Docker files
were copied using an allowlist. Visible application branding, package/console name
and Compose image name use Email Checker. The Python module `bad_email_check` and
`EMAIL_CHECK_` settings remain stable. Runtime algorithms were not changed.

README, complete Windows setup, optional Gmail guidance, copy-paste AI setup/
verification/development prompts and owner-run GitHub publication instructions are
provided. Model-quality limits and deferred training remain explicit. No project
license was assigned; the source had no LICENSE file.

The original repository and local data remain separate. No old Git history,
virtualenv, credentials, tokens, databases, personal email, corpus, reviewed labels,
model weights, rejected candidate or original run logs were copied. Synthetic test
fixtures are intentional. Historical results are summarized in PROJECT_HISTORY.md;
the original run archive is not reproduced.

## Executed checks

- Post-branding fast suite: 398 passed, five real-model tests deselected, 14.06s.
- Node UI checks: 36 passed. Ruff lint/format: 64 files passed.
- Focused app/config branding checks: 39 passed.
- Clean-name wheel and source package built with existing dependencies in 3.50s.
  Package names, member counts and SHA-256 values are recorded in report.json.
- Link and private-path audit: no broken local Markdown links or private paths.
- Explicit code import audit by the reviewer resolved inside this export.

Tests used the existing source virtualenv, with this folder as the working directory.
Independent review1 approved the final prepared folder. Generated test/build caches
and package outputs were removed from the source folder before final audit.

## Unrun and next action

No clean-machine/clean-virtualenv dependency install, checkpoint download, real-model
execution from the export, Google sign-in, training or GitHub publication was run.
First-time setup must download the pinned baseline and verify the local environment.
No model or private data is bundled. A successful synthetic/unit check is not an
accuracy claim. Phase 7 remains deferred and its rejected candidate stays inactive.

Next: the owner chooses
visibility/license and publishes using PUBLISHING.md. No remote repository exists
as a result of this preparation.

Additional export privacy check: nine Git-ignore cases passed; raw `.eml`, `.mbox`
and `.msg` files are ignored except the authored `tests/fixtures/*.eml` files.
Reviewer independently passed398 fast/five real excluded14.89s,36 Node and Ruff64;
imports resolved inside the copy, links/private paths passed, and code parity was
checked except the two intended visible-branding files. Final approval confirmed
the cleaned folder and completed documentation audit.

## Final disposition

[Independent review1](REVIEW_1.md) approves the prepared folder with no findings.
Branding, guides/prompts, private-state exclusion, code parity and portable links
are verified. Cold setup, Google sign-in, real-model execution from the copy and
publication remain explicitly unrun. No remote repository or new project license
was created. The owner may now follow the setup and publishing guides.
