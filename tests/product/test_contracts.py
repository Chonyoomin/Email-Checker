import pytest
from pydantic import ValidationError

from bad_email_check.contracts import (
    AttachmentInfo,
    AuthMetadata,
    EmailEvidence,
    ErrorResponse,
    IndicatorResult,
    LinkInfo,
    ModelAssessment,
    ScanResult,
    Timings,
)


def evidence(**overrides):
    return {
        "source": "paste",
        "body_text": "Example message",
        "extraction_status": "complete",
        "parser_version": "1",
        "fingerprint": "a" * 64,
        **overrides,
    }


def assessment(**overrides):
    return {
        "overall_scam": 0.5,
        "credential_theft": 0.1,
        "impersonation": 0.2,
        "payment_fraud": 0.3,
        "pressure_tactics": 0.4,
        "checkpoint_revision": "test",
        "question_set_version": "1",
        "model_adapter_version": "1",
        "input_complete": True,
        "input_coverage": 1.0,
        **overrides,
    }


def result(**overrides):
    return {
        "scan_id": "test",
        "source_fingerprint": "b" * 64,
        "status": "complete",
        "score": 50,
        "score_kind": "uncalibrated_score",
        "coverage_statement": "Complete",
        "parser_version": "1",
        "checkpoint_revision": "fixture",
        "question_set_version": "1",
        "model_adapter_version": "1",
        **overrides,
    }


@pytest.mark.parametrize(
    "value", [float("nan"), float("inf"), -float("inf"), -0.1, 1.1, "0.5", True]
)
@pytest.mark.parametrize(
    "field",
    [
        "overall_scam",
        "credential_theft",
        "impersonation",
        "payment_fraud",
        "pressure_tactics",
        "input_coverage",
    ],
)
def test_invalid_estimates(field, value):
    with pytest.raises(ValidationError):
        ModelAssessment(**assessment(**{field: value}))


@pytest.mark.parametrize(
    "data",
    [
        evidence(extra="unknown"),
        evidence(source="unknown"),
        evidence(body_text="x" * 100_001),
        evidence(body_text=""),
        evidence(truncated=True),
        evidence(context_limit_exceeded=True),
        evidence(source="gmail"),
        evidence(fingerprint="invalid"),
        evidence(links=[{"displayed_text": "x", "destination": "https://example.org"}] * 201),
    ],
)
def test_invalid_evidence(data):
    with pytest.raises(ValidationError):
        EmailEvidence(**data)


@pytest.mark.parametrize(
    "data",
    [
        result(status="failed"),
        result(critical_content_missing=True),
        result(score=-1),
        result(score=101),
        result(score=True),
        result(score_kind="calibrated_probability"),
        result(risk_label="low_apparent_risk"),
        result(score=None),
        result(checkpoint_revision=None),
        result(score_kind="unavailable"),
        result(status="unknown"),
    ],
)
def test_invalid_results(data):
    with pytest.raises(ValidationError):
        ScanResult(**data)


def test_imported_auth_is_unverified():
    with pytest.raises(ValidationError):
        AuthMetadata(
            name="Authentication-Results",
            value="pass",
            provenance="imported_header",
            independently_verified=True,
        )


@pytest.mark.parametrize(
    "model",
    [
        LinkInfo(
            displayed_text="Example", destination="https://example.org", hostname="example.org"
        ),
        AttachmentInfo(name="invoice.pdf", content_type="application/pdf"),
        AuthMetadata(
            name="Authentication-Results", value="claimed pass", provenance="imported_header"
        ),
        EmailEvidence(**evidence()),
        EmailEvidence(
            **evidence(source="gmail", source_message_id="123", account_scope="account-1")
        ),
        ModelAssessment(**assessment()),
        IndicatorResult(
            indicator="credential_theft", estimate=0.2, description="Possible solicitation."
        ),
        ScanResult(**result()),
        ScanResult(**result(status="failed", score=None, score_kind="unavailable")),
        Timings(total_ms=2.5),
        ErrorResponse(code="invalid_input", message="Invalid input."),
    ],
)
def test_contracts_roundtrip_and_reject_extra_fields(model):
    assert type(model).model_validate_json(model.model_dump_json()) == model
    with pytest.raises(ValidationError):
        type(model).model_validate({**model.model_dump(), "unexpected": "field"})
