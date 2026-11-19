from uuid import uuid4

from .contracts import EmailEvidence, IndicatorResult, ModelAssessment, ScanResult, Timings

INDICATOR_DESCRIPTIONS = {
    "credential_theft": "Possible credential solicitation.",
    "impersonation": "Possible impersonation of a trusted person or organization.",
    "payment_fraud": "Possible deceptive request for money or payment.",
    "pressure_tactics": "Possible pressure tactics. Urgency alone does not establish deception.",
}


def present_assessment(
    evidence: EmailEvidence,
    assessment: ModelAssessment | None,
    timings: Timings,
    *,
    is_test_double: bool = False,
) -> ScanResult:
    critical_missing = not bool(evidence.body_text.strip())
    complete = (
        evidence.extraction_status == "complete"
        and not critical_missing
        and not evidence.truncated
        and not evidence.context_limit_exceeded
        and assessment is not None
        and assessment.input_complete
        and assessment.input_coverage == 1.0
        and not is_test_double
    )
    status = (
        "failed"
        if evidence.extraction_status == "failed"
        else "complete"
        if complete
        else "needs_review"
    )
    warnings = evidence.warnings + (assessment.warnings if assessment else [])
    if is_test_double:
        warnings.append("TEST DOUBLE: simulated judgments are not a real email assessment.")
    return ScanResult(
        scan_id=str(uuid4()),
        source_fingerprint=evidence.fingerprint,
        status=status,
        score=round(100 * assessment.overall_scam) if complete else None,
        score_kind="uncalibrated_score" if complete else "unavailable",
        assessment_label={
            "complete": "Experimental assessment",
            "needs_review": "Needs review",
            "failed": "Assessment failed",
        }[status],
        indicators=[
            IndicatorResult(
                indicator=name,
                estimate=getattr(assessment, name),
                description=description,
            )
            for name, description in INDICATOR_DESCRIPTIONS.items()
        ]
        if complete
        else [],
        warnings=list(dict.fromkeys(warnings))[:100],
        coverage_statement=(
            "Complete model input checked. Experimental, uncalibrated model estimate."
            if complete
            else "No overall score: input coverage or assessment is incomplete."
        ),
        critical_content_missing=critical_missing,
        parser_version=evidence.parser_version,
        checkpoint_revision=assessment.checkpoint_revision if assessment else None,
        question_set_version=assessment.question_set_version if assessment else None,
        model_adapter_version=assessment.model_adapter_version if assessment else None,
        is_test_double=is_test_double,
        assessment=assessment,
        timings=timings,
    )
