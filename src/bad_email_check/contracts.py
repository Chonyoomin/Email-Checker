from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ShortText = Annotated[str, Field(max_length=1_000)]
Version = Annotated[str, Field(min_length=1, max_length=300)]
Probability = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
Warnings = Annotated[list[ShortText], Field(max_length=100)]
Fingerprint = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, validate_assignment=True)
    schema_version: Literal["1.0"] = "1.0"


class LinkInfo(Contract):
    displayed_text: Annotated[str, Field(max_length=5_000)]
    destination: Annotated[str, Field(max_length=8_192)]
    hostname: Annotated[str, Field(max_length=253)] | None = None


class AuthMetadata(Contract):
    name: ShortText
    value: Annotated[str, Field(max_length=8_192)]
    provenance: Literal["gmail", "imported_header", "pasted_header"]
    independently_verified: bool = False

    @model_validator(mode="after")
    def validate_provenance(self):
        if self.provenance != "gmail" and self.independently_verified:
            raise ValueError("Imported authentication claims are not independently verified")
        return self


class AttachmentInfo(Contract):
    name: ShortText
    content_type: Annotated[str, Field(max_length=255)]


class EmailEvidence(Contract):
    source: Literal["gmail", "eml", "paste"]
    source_message_id: ShortText | None = None
    account_scope: ShortText | None = None
    sender: ShortText | None = None
    reply_to: ShortText | None = None
    subject: ShortText | None = None
    body_text: Annotated[str, Field(max_length=100_000)]
    links: Annotated[list[LinkInfo], Field(max_length=200)] = Field(default_factory=list)
    authentication: Annotated[list[AuthMetadata], Field(max_length=100)] = Field(
        default_factory=list
    )
    attachments: Annotated[list[AttachmentInfo], Field(max_length=100)] = Field(
        default_factory=list
    )
    extraction_status: Literal["complete", "incomplete", "failed"]
    missing_fields: Warnings = Field(default_factory=list)
    warnings: Warnings = Field(default_factory=list)
    truncated: bool = False
    context_limit_exceeded: bool = False
    model_input_tokens: Annotated[int, Field(ge=0)] | None = None
    context_limit_tokens: Annotated[int, Field(gt=0)] | None = None
    parser_version: Version
    fingerprint: Fingerprint

    @model_validator(mode="after")
    def validate_source(self):
        if self.source == "gmail" and (not self.account_scope or not self.source_message_id):
            raise ValueError("Gmail evidence requires an account-scoped message ID")
        if self.model_input_tokens is not None and self.context_limit_tokens is not None:
            overflow = self.model_input_tokens > self.context_limit_tokens
            if overflow != self.context_limit_exceeded:
                raise ValueError("Token counts and context overflow flag disagree")
        if self.extraction_status == "complete" and (
            not self.body_text.strip() or self.truncated or self.context_limit_exceeded
        ):
            raise ValueError("Critical missing content or coverage cannot be complete")
        return self


class ModelAssessment(Contract):
    overall_scam: Probability
    credential_theft: Probability
    impersonation: Probability
    payment_fraud: Probability
    pressure_tactics: Probability
    checkpoint_revision: Version
    question_set_version: Version
    model_adapter_version: Version
    input_complete: bool
    input_coverage: Probability
    warnings: Warnings = Field(default_factory=list)


class IndicatorResult(Contract):
    indicator: Literal["credential_theft", "impersonation", "payment_fraud", "pressure_tactics"]
    estimate: Probability
    description: ShortText


class Timings(Contract):
    retrieval_ms: Annotated[float, Field(ge=0, allow_inf_nan=False)] = 0
    extraction_ms: Annotated[float, Field(ge=0, allow_inf_nan=False)] = 0
    inference_ms: Annotated[float, Field(ge=0, allow_inf_nan=False)] = 0
    total_ms: Annotated[float, Field(ge=0, allow_inf_nan=False)] = 0


class RuntimeMetrics(Contract):
    model_load_ms: Annotated[float, Field(ge=0, allow_inf_nan=False)] | None = None
    model_tensor_bytes: Annotated[int, Field(ge=0)] | None = None
    process_rss_bytes: Annotated[int, Field(ge=0)] | None = None
    process_peak_rss_bytes: Annotated[int, Field(ge=0)] | None = None
    inference_phase: Literal["first", "warm", "cached", "not_run"] = "not_run"


class ScanResult(Contract):
    scan_id: Version
    source_fingerprint: Fingerprint
    status: Literal["complete", "needs_review", "failed"]
    score: Annotated[int, Field(ge=0, le=100)] | None = None
    score_kind: Literal["uncalibrated_score", "calibrated_probability", "unavailable"]
    risk_label: Literal["low_apparent_risk", "review", "high"] | None = None
    assessment_label: (
        Literal["Experimental assessment", "Needs review", "Assessment failed"] | None
    ) = None
    indicators: Annotated[list[IndicatorResult], Field(max_length=4)] = Field(default_factory=list)
    warnings: Warnings = Field(default_factory=list)
    coverage_statement: ShortText
    critical_content_missing: bool = False
    checkpoint_revision: Version | None = None
    parser_version: Version
    question_set_version: Version | None = None
    model_adapter_version: Version | None = None
    calibration_version: Version | None = None
    threshold_version: Version | None = None
    timings: Timings = Field(default_factory=Timings)
    runtime: RuntimeMetrics = Field(default_factory=RuntimeMetrics)
    is_test_double: bool = False
    assessment: ModelAssessment | None = None

    @model_validator(mode="after")
    def validate_score(self):
        unavailable = self.status == "failed" or self.critical_content_missing
        if unavailable and (self.score is not None or self.risk_label is not None):
            raise ValueError("Failure or critical missing evidence cannot carry a score or label")
        if (self.score is None) != (self.score_kind == "unavailable"):
            raise ValueError("Score and score kind disagree")
        if self.score is None and self.risk_label in {"low_apparent_risk", "high"}:
            raise ValueError("Unavailable scores cannot carry an authoritative risk band")
        if self.score is not None and not all(
            (self.checkpoint_revision, self.question_set_version, self.model_adapter_version)
        ):
            raise ValueError("Scored results require model provenance")
        if self.score_kind == "calibrated_probability" and not self.calibration_version:
            raise ValueError("Calibrated results require a calibration version")
        if self.risk_label in {"low_apparent_risk", "high"} and not self.threshold_version:
            raise ValueError("Risk bands require an evaluated threshold version")
        if self.status == "complete" and (self.score is None or self.critical_content_missing):
            raise ValueError("Complete results require a score and critical evidence")
        return self


class ErrorResponse(Contract):
    code: Annotated[str, Field(min_length=1, max_length=100)]
    message: ShortText
    retryable: bool = False


class Readiness(Contract):
    server_running: bool = True
    model_loaded: bool = False
    status: Literal["setup_required", "ready"] = "setup_required"
    code: Literal[
        "checkpoint_missing",
        "checkpoint_unavailable",
        "adapter_pending",
        "model_error",
        "test_double",
        "ready",
    ]
    message: ShortText
    mode: Literal["production", "development", "test"]
    is_test_double: bool = False
    scans_available: bool = False


class ScanInput(Contract):
    source: Literal["paste", "gmail"] = "paste"
    text: Annotated[str, Field(min_length=1, max_length=200_000)] | None = None
    source_message_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,256}$")] | None = None
    account_scope: Annotated[str, Field(min_length=1, max_length=256)] | None = None

    @model_validator(mode="after")
    def validate_input(self):
        if self.source == "paste":
            if (
                self.text is None
                or self.source_message_id is not None
                or self.account_scope is not None
            ):
                raise ValueError("Paste requires text only")
        elif self.text is not None or self.source_message_id is None or self.account_scope is None:
            raise ValueError("Gmail requires an account-scoped message ID only")
        return self


class PasteInput(Contract):
    text: Annotated[str, Field(min_length=1, max_length=200_000)]


class EmailPreview(Contract):
    evidence: EmailEvidence
    status: Literal["complete", "needs_review", "failed"]
    coverage_statement: ShortText = (
        "Extraction preview only. Model context has not been checked. "
        "Linked websites and attachments were not inspected."
    )


class GmailMessageSummary(Contract):
    id: Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,256}$")]
    sender: ShortText
    subject: ShortText
    date: ShortText


class GmailMessagePage(Contract):
    account_scope: Fingerprint
    messages: Annotated[list[GmailMessageSummary], Field(max_length=10)]
    next_page_token: Annotated[str, Field(max_length=2048)] | None = None
