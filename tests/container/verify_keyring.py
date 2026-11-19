import json
import os
import sys
from pathlib import Path

from bad_email_check import container_entrypoint
from bad_email_check.token_store import RefreshTokenStore

assert os.getuid() == 10001
container_entrypoint.start_app = lambda: None
container_entrypoint.main()
store = RefreshTokenStore()
scope = "synthetic-docker-test"
token = "synthetic-refresh-for-container-verification"
phase = sys.argv[1]
if phase == "save":
    assert store.load(scope) is None
    store.save(scope, token)
    assert store.load(scope) == token
elif phase == "delete":
    assert store.load(scope) == token
    store.delete(scope)
    assert store.load(scope) is None
elif phase == "verify_deleted":
    assert store.load(scope) is None
else:
    raise ValueError("Unknown synthetic verification phase")
files = list((Path(os.environ["XDG_DATA_HOME"]) / "keyrings").glob("*.keyring"))
assert files and all(token.encode() not in path.read_bytes() for path in files)
print(json.dumps({"phase": phase, "uid": os.getuid(), "protected_store_check": "passed"}))
