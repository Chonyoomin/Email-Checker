import logging

import pytest
from pydantic import ValidationError

from bad_email_check.contracts import EmailEvidence, ScanResult
from bad_email_check.security import RedactionFilter


@pytest.mark.parametrize("tokens,limit,flag", [(100, 10, False), (10, 100, True)])
def test_p1_f1_inconsistent_coverage_rejected(tokens, limit, flag):
    with pytest.raises(ValidationError, match="Token counts"):
        EmailEvidence(
            source="paste",
            body_text="example",
            extraction_status="incomplete",
            parser_version="1",
            fingerprint="a" * 64,
            model_input_tokens=tokens,
            context_limit_tokens=limit,
            context_limit_exceeded=flag,
        )


def test_p1_f1_valid_overflow_must_be_incomplete():
    values = dict(
        source="paste",
        body_text="example",
        parser_version="1",
        fingerprint="a" * 64,
        model_input_tokens=100,
        context_limit_tokens=10,
        context_limit_exceeded=True,
    )
    assert EmailEvidence(**values, extraction_status="incomplete").context_limit_exceeded
    with pytest.raises(ValidationError, match="cannot be complete"):
        EmailEvidence(**values, extraction_status="complete")


@pytest.mark.parametrize("label", ["low_apparent_risk", "high"])
def test_p1_f2_unavailable_result_cannot_have_risk_band(label):
    with pytest.raises(ValidationError, match="authoritative risk band"):
        ScanResult(
            scan_id="test",
            source_fingerprint="a" * 64,
            parser_version="1",
            status="needs_review",
            score_kind="unavailable",
            risk_label=label,
            threshold_version="test",
            coverage_statement="Missing evidence",
        )


def test_p1_f3_log_extras_are_redacted():
    logger = logging.getLogger("review_regression")
    record = logger.makeRecord(
        "review_regression",
        logging.INFO,
        "",
        1,
        {"event": "scan_failed"},
        (),
        None,
        extra={
            "body_text": "private-body",
            "access_token": "private-token",
            "metadata": {"refresh_token": "nested-secret", "elapsed_ms": 3},
        },
    )
    RedactionFilter().filter(record)
    assert record.body_text == "[REDACTED]"
    assert record.access_token == "[REDACTED]"
    assert record.metadata["refresh_token"] == "[REDACTED]"
    assert record.metadata["elapsed_ms"] == 3
    assert "private-body" not in str(record.__dict__)
    assert "private-token" not in str(record.__dict__)
    assert "nested-secret" not in str(record.__dict__)
