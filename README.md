# Email Checker

A local email scam-checking prototype: paste a message, import an `.eml`, or select
an email through read-only Gmail access. LAYA runs on your computer. Gmail is optional.

**Experimental model:** a low score does not establish legitimacy. The original
baseline missed 8 of 12 source-labeled phishing examples; the first specialized
candidate failed its improvement gate. [Known limits](docs/KNOWN_LIMITATIONS.md).

## Start here

- [Complete Windows setup](docs/SETUP.md): prerequisites, dependencies, model, launch and checks.
- [AI setup prompts](prompts/README.md): project installation, optional Gmail and verification.
- [Optional Gmail setup](docs/GMAIL_SETUP.md).
- [Docker](docs/DOCKER.md): optional Linux CPU container; native Windows is the primary setup.
- [Publish this folder as a new GitHub repo](PUBLISHING.md).

Python 3.14 is required by the pinned dependencies. Run PowerShell from this folder:

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-dev.lock
.\.venv\Scripts\python -m pip install --no-deps --no-build-isolation -e .
.\.venv\Scripts\python -m bad_email_check.setup_checkpoint
$env:EMAIL_CHECK_CHECKPOINT_PATH = 'checkpoints/laya-english'
.\.venv\Scripts\python -m bad_email_check
```

Open http://127.0.0.1:8000. After first-time setup, repeat only the last two commands.
The download is approximately 843 MB of weights plus configuration; dependencies
and optional Docker images require additional disk space. Setup needs internet;
paste/import inference works offline afterward. Stop the app with Ctrl+C.

Use **Preview email** to inspect extracted text, then **Scan email** for an experimental
uncalibrated score. Websites and attachments are not inspected. Inputs that exceed
the complete 2,048-token context yield no score. Runtime limits and API behavior are
in [model setup](docs/PHASE_3.md) and [the API guide](docs/API.md).

**Report a malicious email** saves an example locally only with explicit retention
consent. Load saved examples to find and delete submissions. Reports need verification
before future training; submission does not immediately change the model.
[Feedback and privacy](docs/FEEDBACK.md).

## Verify

```powershell
.\.venv\Scripts\python -m pytest -q -m "not real_model"
.\.venv\Scripts\python -m ruff check src tests/product
.\.venv\Scripts\python -m ruff format --check src tests/product
.\.venv\Scripts\python -m pip check
node --test tests/ui/*.cjs
```

Node.js is optional for running the app and required for the UI checks. To verify
real offline inference after model setup without training:

```powershell
$env:EMAIL_CHECK_RUN_REAL_MODEL = '1'
.\.venv\Scripts\python -m pytest tests/product/test_offline_import.py -q
$env:EMAIL_CHECK_RUN_REAL_MODEL = $null
```

## Development and repository contents

Start with [AGENTS.md](AGENTS.md). Codex, Claude Code or another assistant can follow
the shared Markdown workflow: **coder -> independent reviewer -> documenter**.
LangChain/Ollama development tooling is optional and separate from product scans;
[instructions](docs/AGENT_WORKFLOW.md). Do not resume deferred training automatically.

- `src/bad_email_check/`: application, local inference and optional offline training tools.
- `tests/`: synthetic fixtures, unit/UI checks and explicitly opt-in real-model checks.
- `docs/`: setup, operation, requirements, limitations and concise agent memory.
- `prompts/`: copy-paste instructions for a setup or coding assistant.
- `requirements*.lock`: separate native, Linux and development-tool dependency pins.

This is a source-only export. It contains no Git history, virtualenv, personal email,
Google client JSON, tokens, databases, corpora, reviewed labels, model weights,
training candidates or old execution logs. The original project and its local data
remain separate. [History and provenance](docs/PROJECT_HISTORY.md).

The internal Python module remains `bad_email_check` and the configuration prefix
remains `EMAIL_CHECK_`; setup commands use those stable names.
[Licensing and third-party components](THIRD_PARTY_NOTICES.md).
