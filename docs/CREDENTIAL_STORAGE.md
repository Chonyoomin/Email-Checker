# Protected Gmail token storage

Task 5.2. Storage is implemented as `RefreshTokenStore` in
`src/bad_email_check/token_store.py`; OAuth routes use it for refresh credentials.
Unit tests use synthetic tokens and mocked backends. Native OAuth account evidence
is recorded in the Phase 5 report (development archive omitted); Docker synthetic
protected-store verification is recorded below. Real Docker Google sign-in is untested.

## Native use

The store uses keyring 25.7.0 and explicitly selects the platform's protected
backend: Windows Credential Manager (`WinVaultKeyring`), macOS Keychain, or Linux
Secret Service. It does not use automatic plugin discovery or keyring config
files to choose a backend. Plaintext, null, chained and third-party backends are
not selected. See [keyring's backend documentation](https://keyring.readthedocs.io/en/latest/).

`save(account_scope, refresh_token)`, `load(account_scope)` and
`delete(account_scope)` address one account-scoped entry. Account identifiers are
hashed in the service name. Loading an absent entry returns `None`; deleting an
absent entry succeeds. Replacing an entry does not change other account entries.
The refresh token limit is 2,048 UTF-16 bytes for compatibility with Windows
credential storage. No file, SQLite or environment-variable token fallback exists.

Backend initialization raises `CredentialStoreUnavailable` when unavailable.
Locked, denied or failed operations raise `CredentialStoreError` with generic
messages. A failed deletion remains an error if the entry still exists. OAuth/disconnect routes surface these failures and must never claim success from
an unsuccessful protected write/removal. Access tokens are transient; only
refresh tokens belong in this store. Do not put tokens or backend exceptions into
logs, feedback, chat or shared project memory.

Windows dependencies are pinned in the runtime/development locks. macOS/Linux
backend names are supported by the interface, but native operation there is
unverified; Docker uses the separate `requirements-linux.lock`, not the Windows
lock. Headless Linux container verification is described below.

## Docker protected-secret arrangement

Task 6.5 packages the Linux CPU image with a dedicated Secret Service under UID 10001,
a private D-Bus session and encrypted persistent GNOME keyring. Actual synthetic
save -> container restart/load/delete -> restart/absence checks passed without
plaintext token material in keyring files. See container evidence (development archive omitted)
and [deployment instructions](DOCKER.md). Native macOS operation remains unverified.

The default bridge Compose profile disables Gmail. Optional loopback host-network
Gmail requires deployment-specific setup and a separate private Desktop-client
JSON plus protected keyring-unlock runtime file. Its actual Google sign-in/callback/
retrieval flow remains untested in Docker. Never mount/export Windows refresh
tokens or expose the user's desktop D-Bus collection.

Runtime secret files must be readable by UID 10001 using narrowly scoped host
permissions/ACLs, not world-readable. Compose file secrets are mounts, not encryption
of the host originals. The raw nonempty UTF-8 unlock file is capped at 4096 bytes,
including line endings; trailing line endings are removed. Keep it outside source,
Compose environment, image layers and logs. Refresh tokens remain in the encrypted
credential service, never in JSON/token files, SQLite or plaintext app volumes.
Missing/wrong/empty unlock secrets or a locked backend fail closed.

## Verification

Run `python -m pytest -q tests/product/test_token_store.py` in the project virtualenv.
Mocked checks cover account separation, replacement, absence/idempotent deletion,
read/write/delete errors, invalid values, missing backend and rejection of
plaintext backend selection. OS credential access and Google sign-in are separate
checks requiring explicit authorization; mock tests do not establish either. Docker verification used only synthetic tokens.

Phase 6 packaging and synthetic protected-store gates are complete;
final evidence (development archive omitted) preserves the Docker Google-flow
limit and all prior storage checks. No training or real Docker Google credentials
were used in that evaluation cycle.

Historical verification refers to the original development workspace. Its run
archive, local data and checkpoints are not bundled. See [project history](PROJECT_HISTORY.md).
