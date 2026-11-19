# Complete setup: Windows and PowerShell

Run every command from the repository root, the folder containing `pyproject.toml`.
The pinned native environment targets 64-bit Windows and Python 3.14. Other native
platforms have not been verified; see [Docker](DOCKER.md) for the Linux CPU route.

## 1. Prerequisites

Install Python 3.14 from [python.org](https://www.python.org/downloads/windows/).
Install Git if cloning or publishing. Node.js is optional for the application and
needed for the UI test command. Docker is optional. System-wide installers are
handled by the user; the AI prompt authorizes only project-local setup.

```powershell
py -3.14 --version
git --version
```

If the Python launcher is unavailable, use the full path to a verified Python 3.14
executable instead of `py -3.14`. A different Python minor version is unsupported by
these locks. No GPU or paid AI API key is required. Allow several GB of free disk
for dependencies and the checkpoint. The measured original process peaked near
2.9 GB RSS on a 32 GB Windows machine; this is not a universal minimum or speed guarantee.

## 2. Obtain and open the project

Extract the clean folder or clone your new repository, then change into its root.
Do not run setup from the parent folder containing the old project. To use a coding
assistant, paste [the installation prompt](../prompts/01-install-windows.md) instead
of manually repeating sections 3-6.

## 3. Create an isolated environment

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-dev.lock
.\.venv\Scripts\python -m pip install --no-deps --no-build-isolation -e .
.\.venv\Scripts\python -m pip check
```

Activation is unnecessary because commands explicitly name the virtualenv Python.
Runtime-only installs can use `requirements.lock`, but the command above includes
the build backend, tests and linter needed for development. Do not mix the Windows,
Linux and optional-agent locks or replace pins with latest versions.

## 4. Download the reviewed checkpoint

```powershell
.\.venv\Scripts\python -m bad_email_check.setup_checkpoint
```

The downloader fetches only the public pinned Hugging Face revision and verifies
the hashes in `src/bad_email_check/laya_checkpoint.json`. It uses
`checkpoints/laya-english` by default and does not need a Hugging Face token.
Approximately 843 MB of weights plus tokenizer/config files are downloaded. Keep
the ignored checkpoint directory locally; never add it to Git. This export includes
no model weights. Runtime loading does not download missing files.

## 5. Configure and launch

For one shell session:

```powershell
$env:EMAIL_CHECK_CHECKPOINT_PATH = 'checkpoints/laya-english'
.\.venv\Scripts\python -m bad_email_check
```

For persistent local settings, copy `.env.example` to `.env` only if `.env` does not
already exist, then set `EMAIL_CHECK_CHECKPOINT_PATH=checkpoints/laya-english`.
Leave the Gmail client path empty initially. Existing environment variables override
`.env`. The default URL is http://127.0.0.1:8000; change `EMAIL_CHECK_PORT` if occupied.
Keep the host at loopback. Use one worker. Stop with Ctrl+C.

## 6. Verify with synthetic input

Open the app and wait for **Local model ready**. Paste this authored example:

```text
From: synthetic@example.org
Subject: Lunch

Lunch is at noon.
```

Preview, then scan. Confirm an experimental uncalibrated result or an explicit
incomplete/error state; never infer accuracy from this example. Test import using
`tests/fixtures/offline_message.eml`. The automated nontraining offline check is:

```powershell
$env:EMAIL_CHECK_RUN_REAL_MODEL = '1'
.\.venv\Scripts\python -m pytest tests/product/test_offline_import.py -q
$env:EMAIL_CHECK_RUN_REAL_MODEL = $null
```

Run the [fast checks](../README.md#verify) separately. Do not run the entire
`real_model` marker by default: it also includes an optional training spike.

## 7. Optional Gmail and Docker

Paste/import needs no Google configuration. For Gmail, follow [Gmail setup](GMAIL_SETUP.md)
and handle Google sign-in yourself. For containers, follow [Docker](DOCKER.md) after
obtaining the same checkpoint. A native credential store is not copied into a container.

## Troubleshooting

| Symptom | Action |
| --- | --- |
| Setup required | Check the checkpoint path, SHA-verified files and Python/lock versions. No fallback model is used. |
| Address already in use | Stop only the process you own, or choose another `EMAIL_CHECK_PORT`. |
| Import/dependency failure | Verify Python 3.14 and the matching lock; capture a generic error, not secrets. Do not silently change versions. |
| No score on a long email | The complete input exceeds the 2,048-token limit; incomplete evidence is withheld. |
| Scan appears slow | CPU inference can take seconds to tens of seconds; the original warm p95 was about 10.5 seconds. |
| SDK temperature warning | The inherited checkpoint temperature configuration has a clamped unrelated choice entry. Results remain uncalibrated. |
| Gmail unavailable | Recheck Cloud project, Desktop client, test user, scope and OS credential store; paste/import still works. |

The repository's validation report states what was tested. A clean-machine dependency
installation, your Google account and your hardware must be checked on their own.
