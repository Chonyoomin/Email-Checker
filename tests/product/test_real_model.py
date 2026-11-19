import os
import socket
import time
from pathlib import Path

import pytest

from bad_email_check.config import Settings
from bad_email_check.extraction import extract_paste
from bad_email_check.laya_adapter import CoverageError, LayaAdapter

pytestmark = [
    pytest.mark.real_model,
    pytest.mark.skipif(
        os.environ.get("EMAIL_CHECK_RUN_REAL_MODEL") != "1",
        reason="Explicit real-model run required",
    ),
]


def test_real_offline_checkpoint_smoke_reuse_and_context(monkeypatch, record_property):
    attempts = []

    def denied(*args, **kwargs):
        attempts.append("connection attempted")
        raise AssertionError("Network connections are forbidden during local inference")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    started = time.monotonic()
    adapter = LayaAdapter(Path("checkpoints/laya-english"))
    assert adapter.context_limit == 2048
    assert adapter.model_tensor_bytes > 0
    record_property("model_tensor_bytes", adapter.model_tensor_bytes)
    record_property("cold_load_seconds", time.monotonic() - started)
    identity = id(adapter.agent)
    for index, text in enumerate(
        ("Lunch tomorrow?", "Please enter your password at https://login.example.org.")
    ):
        evidence = extract_paste(
            "From: sender@example.org\nSubject: Example\n\n" + text, Settings(_env_file=None)
        )
        started = time.monotonic()
        assessment = adapter.assess(evidence)
        record_property(f"inference_{index}_seconds", time.monotonic() - started)
        assert assessment.input_complete and assessment.input_coverage == 1.0
        assert assessment.checkpoint_revision == adapter.identity.checkpoint_revision
        assert 0 <= assessment.overall_scam <= 1
        assert id(adapter.agent) == identity
        assert adapter.last_input_tokens <= adapter.context_limit
    assert adapter.assess_calls == 2
    with pytest.raises(CoverageError):
        adapter.assess(extract_paste("long content " * 2_000, Settings(_env_file=None)))
    assert adapter.assess_calls == 2
    assert attempts == []
