import pytest
from pydantic import ValidationError

from bad_email_check.config import Settings
from bad_email_check.contracts import ModelAssessment, ScanResult, Timings
from bad_email_check.extraction import extract_paste
from bad_email_check.presentation import present_assessment


@pytest.fixture
def evidence():
    return extract_paste("Synthetic example body", Settings(_env_file=None, mode="test"))


@pytest.fixture
def assessment():
    return ModelAssessment(
        overall_scam=0.82,
        credential_theft=0.1,
        impersonation=0.2,
        payment_fraud=0.3,
        pressure_tactics=0.4,
        checkpoint_revision="fixture",
        question_set_version="questions-v1",
        model_adapter_version="adapter-v1",
        input_complete=True,
        input_coverage=1.0,
    )


@pytest.mark.parametrize(
    "overall,expected", [(0.0, 0), (0.005, 0), (0.015, 2), (0.82, 82), (1.0, 100)]
)
@pytest.mark.parametrize("indicator_value", [0.0, 1.0])
def test_direct_overall_score_and_neutral_label(
    evidence, assessment, overall, expected, indicator_value
):
    data = assessment.model_dump()
    data.update(overall_scam=overall)
    data.update(
        dict.fromkeys(
            ["credential_theft", "impersonation", "payment_fraud", "pressure_tactics"],
            indicator_value,
        )
    )
    result = present_assessment(evidence, ModelAssessment(**data), Timings())
    assert result.score == expected
    assert result.score_kind == "uncalibrated_score"
    assert result.assessment_label == "Experimental assessment"
    assert result.risk_label is None
    assert result.calibration_version is None and result.threshold_version is None
    assert len(result.indicators) == 4
    assert all(item.estimate == indicator_value for item in result.indicators)
    assert ScanResult.model_validate_json(result.model_dump_json()) == result


def test_predefined_templates_and_provenance(evidence, assessment):
    result = present_assessment(evidence, assessment, Timings(total_ms=5))
    assert [item.description for item in result.indicators] == [
        "Possible credential solicitation.",
        "Possible impersonation of a trusted person or organization.",
        "Possible deceptive request for money or payment.",
        "Possible pressure tactics. Urgency alone does not establish deception.",
    ]
    assert [item.estimate for item in result.indicators] == [0.1, 0.2, 0.3, 0.4]
    assert result.assessment == assessment
    assert result.source_fingerprint == evidence.fingerprint
    assert result.checkpoint_revision == assessment.checkpoint_revision
    assert result.timings.total_ms == 5


@pytest.mark.parametrize(
    "changes,status",
    [
        ({"extraction_status": "failed"}, "failed"),
        ({"extraction_status": "incomplete"}, "needs_review"),
        ({"extraction_status": "incomplete", "body_text": ""}, "needs_review"),
        ({"extraction_status": "incomplete", "truncated": True}, "needs_review"),
        ({"extraction_status": "incomplete", "context_limit_exceeded": True}, "needs_review"),
    ],
)
def test_incomplete_evidence_withholds_even_complete_assessment(
    evidence, assessment, changes, status
):
    evidence = type(evidence).model_validate({**evidence.model_dump(), **changes})
    result = present_assessment(evidence, assessment, Timings())
    assert result.status == status
    assert result.assessment_label == (
        "Assessment failed" if status == "failed" else "Needs review"
    )
    assert result.score is None and result.score_kind == "unavailable"
    assert result.risk_label is None and result.indicators == []
    assert result.critical_content_missing == (not bool(evidence.body_text))


@pytest.mark.parametrize("complete,coverage", [(False, 1.0), (True, 0.9), (False, 0.0)])
def test_partial_model_coverage_withholds_score(evidence, assessment, complete, coverage):
    assessment.input_complete = complete
    assessment.input_coverage = coverage
    result = present_assessment(evidence, assessment, Timings())
    assert result.status == "needs_review"
    assert result.score is None and not result.indicators


@pytest.mark.parametrize("fake,missing", [(False, True), (True, False)])
def test_absent_or_simulated_assessment_has_no_presentation_score(
    evidence, assessment, fake, missing
):
    result = present_assessment(
        evidence, None if missing else assessment, Timings(), is_test_double=fake
    )
    assert result.status == "needs_review" and result.score_kind == "unavailable"
    assert result.score is None and not result.indicators
    assert result.is_test_double == fake
    assert any("TEST DOUBLE" in warning for warning in result.warnings) == fake


@pytest.mark.parametrize("status", ["complete", "needs_review", "failed"])
@pytest.mark.parametrize("kind", ["uncalibrated_score", "calibrated_probability", "unavailable"])
def test_status_score_kind_contract_matrix(evidence, assessment, status, kind):
    data = present_assessment(evidence, assessment, Timings()).model_dump()
    data.update(status=status, score_kind=kind, score=None if kind == "unavailable" else 82)
    if kind == "calibrated_probability":
        data["calibration_version"] = "contract-fixture-only"
    valid = (
        (status == "complete" and kind != "unavailable")
        or status == "needs_review"
        or (status == "failed" and kind == "unavailable")
    )
    if valid:
        assert ScanResult(**data).score_kind == kind
    else:
        with pytest.raises(ValidationError):
            ScanResult(**data)
