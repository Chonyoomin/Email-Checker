# Docker packaging

Use Linux containers and Docker Compose. Install Docker Desktop/Engine separately.
The existing pinned checkpoint must already be under `checkpoints/laya-english`.
The build installs Linux CPU dependencies and OS Secret Service support; no model
is downloaded into the image. The build context allowlist excludes credentials,
`.env`, databases, checkpoints, Git history and test data.

```powershell
docker compose build
docker compose up -d --wait
```

Open http://127.0.0.1:8000 and import an `.eml`. `docker compose down` stops this
project; keep the data volume unless intentionally deleting retained feedback and
metadata. Do not use multiple replicas/workers. The image runs as UID 10001 with
one web worker, a read-only root filesystem and a temporary `/tmp`. Give Docker
enough RAM for its VM plus the service's 6 GiB limit; CPU use is capped at four.
The checkpoint is mounted read-only; `scan-data` retains SQLite and any encrypted
keyring. Model loading verifies the same artifact hashes as native use.

Default Compose publishes only host loopback. The app binds all interfaces inside
the isolated bridge container with explicit opt-in; Gmail is disabled in this
configuration because OAuth requires loopback-only hosting. Imported scans need
no internet after image/checkpoint setup. A missing/modified model remains setup
required, not a test-double fallback. Access logging is disabled.

## Optional Gmail with protected storage

The separate `compose.gmail.yaml` uses host networking and binds the app to
127.0.0.1, preserving the native OAuth loopback restriction. It is intended for
Linux Docker Engine; Docker Desktop requires supported, explicitly enabled host
networking. Default bridge Compose does not enable that feature automatically.
Do not publish this service publicly or expose the D-Bus session.

Supply a private Desktop app JSON and a separate nonempty UTF-8 keyring passphrase
file outside the repository. Protect both using host user permissions. The raw
passphrase file is limited to 4,096 bytes including line endings; trailing line
endings are removed. Runtime secret mounts must be readable by UID 10001. On
Linux, use a narrowly scoped file ACL for that UID or equivalent host permission
arrangement; a host-owner-only 0600 file with another UID may be unreadable inside
the container. Do not make secrets world-readable. Compose file-secret mounts may
preserve host permissions rather than honoring `uid`/`mode` overrides. Keep the same
passphrase to unlock an existing persistent keyring. Never put tokens, passphrases
or client contents in Compose, Docker build args, image layers, SQLite or logs.

```powershell
$env:GMAIL_CLIENT_SECRET_FILE = 'ABSOLUTE_PRIVATE_CLIENT_JSON_PATH'
$env:KEYRING_UNLOCK_SECRET_FILE = 'ABSOLUTE_PRIVATE_PASSPHRASE_FILE_PATH'
docker compose -f compose.gmail.yaml up -d --build
```

These Compose secrets are runtime file mounts, not encryption of the original
host files. A private D-Bus session and GNOME Keyring protect refresh tokens in the
encrypted persistent keyring; the passphrase is read through stdin without logging.
Wrong/missing/empty secrets or a locked service prevent startup. There is no
plaintext token-file fallback. Google sign-in/consent remains user-driven through
the regular browser. Do not share the data volume across concurrent services.

Official references: [Compose secrets](https://docs.docker.com/compose/how-tos/use-secrets/),
[host networking](https://docs.docker.com/engine/network/drivers/host/),
[keyring unlock](https://manpages.debian.org/unstable/gnome-keyring/gnome-keyring-daemon.1.en.html),
[Linux Secret Service library](https://pypi.org/project/SecretStorage/).
Container execution and protected-store verification are reported separately in
the task 6.5 run evidence; documentation alone is not a passed container check.

Task 6.5 verification (development archive omitted) passed actual image build,
readiness, real imported scan and synthetic protected-store restart/deletion.
The verification container/network were stopped afterward; image/data were kept.
Real Google sign-in through the optional Gmail profile remains untested.

Historical verification refers to the original development workspace. Its run
archive, local data and checkpoints are not bundled. See [project history](PROJECT_HISTORY.md).
