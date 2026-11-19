import os
import subprocess
import sys
from pathlib import Path

from .__main__ import main as start_app


def main():
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp/runtime"))
    runtime.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.environ.get("EMAIL_CHECK_GMAIL_CLIENT_FILE"):
        try:
            with Path("/run/secrets/keyring_unlock").open("rb") as source:
                password = source.read(4097)
            if len(password) > 4096:
                raise ValueError
            password = password.rstrip(b"\r\n")
            if not password or b"\0" in password:
                raise ValueError
            password.decode("utf-8")
            subprocess.run(
                ["gnome-keyring-daemon", "--unlock", "--components=secrets"],
                input=password,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
                timeout=10,
            )
            import secretstorage

            connection = secretstorage.dbus_init()
            if secretstorage.get_default_collection(connection).is_locked():
                raise ValueError
        except Exception:
            print("Could not unlock Docker protected credential storage.", file=sys.stderr)
            raise SystemExit(2) from None
    start_app()


if __name__ == "__main__":
    main()
