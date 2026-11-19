import pytest


@pytest.fixture(autouse=True)
def isolated_metadata_path(tmp_path, monkeypatch):
    monkeypatch.setenv("EMAIL_CHECK_METADATA_DB_PATH", str(tmp_path / "metadata.sqlite3"))
