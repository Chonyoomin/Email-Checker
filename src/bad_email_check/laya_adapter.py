import hashlib
import json
import os
from importlib.metadata import version
from pathlib import Path

from .contracts import ModelAssessment
from .model_adapter import AdapterIdentity
from .questions import QUESTION_SET_VERSION, email_questions, evidence_state

CHECKPOINT_ID = "convaiinnovations/laya"
CHECKPOINT_REVISION = "55cf4c4ebb4ebe31b2550e8bdf3bd21b99753851"
ADAPTER_VERSION = "laya-adapter-v2-context2048"
CONTEXT_LIMIT = 2048
REQUIRED_FILES = {
    "rl_agent_config.json",
    "model.safetensors",
    "tokenizer/tokenizer.json",
    "tokenizer/tokenizer_config.json",
    "encoder/config.json",
}


class CoverageError(Exception):
    pass


def verify_checkpoint(path: Path) -> dict:
    root = path.resolve(strict=True)
    manifest = json.loads(
        Path(__file__).with_name("laya_checkpoint.json").read_text(encoding="utf-8")
    )
    if manifest["repo"] != CHECKPOINT_ID or manifest["revision"] != CHECKPOINT_REVISION:
        raise ValueError("Checkpoint identity is not the reviewed artifact")
    files = manifest["files"]
    if not REQUIRED_FILES.issubset(files):
        raise ValueError("Checkpoint is incomplete")
    for relative, expected in files.items():
        target = (root / relative).resolve(strict=True)
        target.relative_to(root)
        if not target.is_file():
            raise ValueError("Checkpoint artifact is not a file")
        with target.open("rb") as handle:
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
        if digest != expected:
            raise ValueError("Checkpoint digest mismatch")
    return manifest


class LayaAdapter:
    def __init__(self, checkpoint_path: Path):
        manifest = verify_checkpoint(checkpoint_path)
        if version("laya") != "0.4.15":
            raise ValueError("Adapter requires the reviewed LAYA release")
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
        os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"
        import torch
        from laya import Agent

        torch.set_num_threads(min(4, os.cpu_count() or 1))
        self.agent = Agent(
            str(checkpoint_path.resolve()),
            device="cpu",
            compile=False,
            fast=False,
            expected_sha256=manifest["files"],
        )
        self.context_limit = CONTEXT_LIMIT
        self.head_limit = int(self.agent.cfg["head_max_len"])
        self.last_input_tokens = None
        self.assess_calls = 0
        self.model_tensor_bytes = sum(
            tensor.numel() * tensor.element_size()
            for tensor in (*self.agent.model.parameters(), *self.agent.model.buffers())
        )

    @property
    def identity(self) -> AdapterIdentity:
        return AdapterIdentity(CHECKPOINT_REVISION, ADAPTER_VERSION, QUESTION_SET_VERSION, False)

    def assess(self, evidence) -> ModelAssessment:
        if (
            evidence.extraction_status != "complete"
            or evidence.truncated
            or evidence.context_limit_exceeded
        ):
            raise CoverageError
        state = evidence_state(evidence)
        questions = email_questions()
        internal = {name: self.agent._to_internal(question) for name, question in questions.items()}
        items = self.agent._encode_state(
            state,
            list(questions),
            internal,
            max_len=self.context_limit,
            head_max_len=self.head_limit,
        )
        if len(items) != len(questions) or any(
            item["state_stats"]["truncated"]
            or item["state_stats"]["state_tokens_dropped"] != 0
            or item["options"]["options_distinct"] != item["options"]["options"]
            for item in items
        ):
            raise CoverageError
        self.last_input_tokens = max(len(item["ids"]) for item in items)
        raw = self.agent.predict(
            state, questions, max_len=self.context_limit, head_max_len=self.head_limit
        )
        self.assess_calls += 1
        usage = raw["usage"]
        if usage.get("truncated") is not False or usage.get("state_tokens_dropped") != 0:
            raise CoverageError
        answers = raw["answers"]
        if set(answers) != set(questions):
            raise ValueError("Assessment answers do not match the question set")
        values = {name: answers[name]["noul"] for name in questions}
        return ModelAssessment(
            **values,
            checkpoint_revision=self.identity.checkpoint_revision,
            question_set_version=QUESTION_SET_VERSION,
            model_adapter_version=ADAPTER_VERSION,
            input_complete=True,
            input_coverage=1.0,
        )
