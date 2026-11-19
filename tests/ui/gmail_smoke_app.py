import sys
from pathlib import Path

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "product"))

from test_gmail_messages import MailProvider
from test_gmail_oauth import FakeStore, credentials

from bad_email_check.app import create_app
from bad_email_check.config import Settings

settings = Settings(
    _env_file=None, mode="test", port=8006, model_backend="test_double",
    gmail_client_file="synthetic-unused.json",
)
app = create_app(settings)
app.state.gmail._provider = MailProvider()
app.state.gmail._store = FakeStore()
app.state.gmail._credentials = credentials()
app.state.gmail.account_scope = "a" * 64

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8006, access_log=False, proxy_headers=False)
