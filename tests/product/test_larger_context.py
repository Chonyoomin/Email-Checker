import json
import socket
import time
from pathlib import Path

import pytest

from bad_email_check.config import Settings
from bad_email_check.extraction import extract_eml
from bad_email_check.laya_adapter import CoverageError, LayaAdapter
from bad_email_check.questions import email_questions, evidence_state

pytestmark = [pytest.mark.real_model]


def test_larger_context_offline_boundaries_and_real_inference(monkeypatch, record_property):
    import os

    if os.environ.get("EMAIL_CHECK_RUN_REAL_MODEL") != "1":
        pytest.skip("Explicit real-model run required")
    attempts = []

    def denied(*args, **kwargs):
        attempts.append(True)
        raise AssertionError("Local inference attempted network access")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    started = time.monotonic()
    adapter = LayaAdapter(Path("checkpoints/laya-english"))
    cold_seconds = time.monotonic() - started
    agent_identity = id(adapter.agent)
    questions = email_questions()
    internal = {name: adapter.agent._to_internal(question) for name, question in questions.items()}

    def sized_evidence(repetitions):
        raw = (
            "From: sender@example.org\nReply-To: replies@example.org\nSubject: Synthetic agenda\n"
            "Authentication-Results: example.org; spf=pass; dkim=pass\n\n"
            "Meeting details https://calendar.example.org/agenda\n"
            + "agenda " * repetitions
            + "\nEnd of synthetic email."
        ).encode()
        return extract_eml(raw, Settings(_env_file=None))

    def encoded(evidence, limit):
        return adapter.agent._encode_state(
            evidence_state(evidence),
            list(questions),
            internal,
            max_len=limit,
            head_max_len=adapter.head_limit,
        )

    def boundary(limit):
        low, high = 0, limit * 2
        while low < high:
            middle = (low + high + 1) // 2
            items = encoded(sized_evidence(middle), 8192)
            if max(len(item["ids"]) for item in items) <= limit:
                low = middle
            else:
                high = middle - 1
        return low

    results = []
    for limit in (1024, 2048):
        repetitions = boundary(limit)
        evidence = sized_evidence(repetitions)
        items = encoded(evidence, limit)
        lengths = [len(item["ids"]) for item in items]
        assert max(lengths) == limit
        assert all(not item["state_stats"]["truncated"] for item in items)
        assert all(item["state_stats"]["state_tokens_dropped"] == 0 for item in items)
        assert len(items) == 5
        assert all(
            item["options"]["options_distinct"] == item["options"]["options"] for item in items
        )
        adapter.context_limit = 512
        before = adapter.assess_calls
        with pytest.raises(CoverageError):
            adapter.assess(evidence)
        assert adapter.assess_calls == before
        adapter.context_limit = limit
        started = time.monotonic()
        assessment = adapter.assess(evidence)
        seconds = time.monotonic() - started
        assert assessment.input_complete and assessment.input_coverage == 1.0
        assert adapter.last_input_tokens == limit
        assert id(adapter.agent) == agent_identity
        overflow = sized_evidence(repetitions + 1)
        overflow_items = encoded(overflow, 8192)
        assert max(len(item["ids"]) for item in overflow_items) == limit + 1
        before = adapter.assess_calls
        with pytest.raises(CoverageError):
            adapter.assess(overflow)
        assert adapter.assess_calls == before
        results.append(
            {
                "context_limit": limit,
                "sequence_lengths": lengths,
                "inference_seconds": seconds,
                "within_default_scan_deadline": seconds
                < Settings(_env_file=None).scan_deadline_seconds,
                "complete": True,
                "overflow_rejected_before_prediction": True,
                "assessment": assessment.model_dump(),
            }
        )
        print(json.dumps({"context_result": results[-1]}), flush=True)
    assert not attempts
    record_property(
        "larger_context_validation",
        json.dumps(
            {
                "cold_load_seconds": cold_seconds,
                "network_attempts": len(attempts),
                "results": results,
            }
        ),
    )
