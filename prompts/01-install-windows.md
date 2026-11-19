# Copy-paste prompt: install the project

```text
Set up this repository on my Windows computer. Read AGENTS.md, README.md,
docs/SETUP.md and the required project memory first. Confirm the working directory
is this clean repository, not a parent or another project.

For this setup task I authorize creating or reusing this checkout's .venv,
installing the exact requirements-dev.lock dependencies and this project into that
virtualenv, and downloading/verifying the public pinned English LAYA checkpoint
under this checkout's checkpoints/laya-english (about 843 MB of weights plus
dependencies). This is the bounded setup exception to the normal no-install rule.
Do not install system-wide tools or change global Python, PATH, security settings
or unrelated environments. If Python 3.14 is missing, tell me how to install it and
stop dependent setup. Do not replace dependency pins or model revisions.

Follow docs/SETUP.md. Do not overwrite an existing .env or checkpoint. Reuse verified
artifacts. Configure only the local checkpoint path, loopback host and an available
port; leave Gmail disabled. Do not inspect Google credential contents, tokens,
saved emails or retained feedback. Do not train, fit calibration or activate a
candidate. Do not run the broad real_model marker, which includes a training spike.

Run fast Python tests, Ruff lint/format and pip check. Run all Node UI tests if Node
is available; report them unrun if it is missing. After checkpoint setup, run only
tests/product/test_offline_import.py with EMAIL_CHECK_RUN_REAL_MODEL=1, then remove
that temporary flag. Use authored synthetic input only. Start one local web worker,
check readiness and give me the local URL and restart/stop commands.

Perform an independent review of the setup and executed checks, fix any setup
findings, then document commands/results, generic blockers and next action in shared
memory. Never call an unrun check passed. Keep the result concise. Do not commit,
push, publish, sign in to Google, read credentials or resume deferred training.
```
