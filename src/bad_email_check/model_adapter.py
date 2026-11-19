from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from .config import Settings
from .contracts import EmailEvidence, ModelAssessment
from .questions import QUESTION_SET_VERSION


@dataclass(frozen=True)
class AdapterIdentity:
    checkpoint_revision: str
    adapter_version: str
    question_set_version: str
    is_test_double: bool


@runtime_checkable
class ModelAdapter(Protocol):
    @property
    def identity(self) -> AdapterIdentity: ...

    def assess(self, evidence: EmailEvidence) -> ModelAssessment: ...


class TestDoubleAdapter:
    def __init__(self, settings: Settings):
        if settings.mode not in {"development", "test"}:
            raise ValueError("Test double requires explicit development or test mode")
        self._mode = settings.mode

    @property
    def identity(self) -> AdapterIdentity:
        return AdapterIdentity(
            checkpoint_revision="test-double-v1",
            adapter_version="test-double-v1",
            question_set_version=QUESTION_SET_VERSION,
            is_test_double=True,
        )

    def assess(self, evidence: EmailEvidence) -> ModelAssessment:
        if evidence.extraction_status != "complete" or evidence.truncated:
            raise ValueError("Incomplete evidence cannot receive a test assessment")
        return ModelAssessment(
            overall_scam=0.5,
            credential_theft=0.5,
            impersonation=0.5,
            payment_fraud=0.5,
            pressure_tactics=0.5,
            checkpoint_revision=self.identity.checkpoint_revision,
            model_adapter_version=self.identity.adapter_version,
            question_set_version=self.identity.question_set_version,
            input_complete=False,
            input_coverage=0.0,
            warnings=[
                "TEST DOUBLE: fixed fixture values; not real model inference or risk evidence."
            ],
        )
