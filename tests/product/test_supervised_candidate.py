import hashlib
import json
import math
import os
from pathlib import Path

import pytest

from bad_email_check.baseline import offline
from bad_email_check.config import Settings
from bad_email_check.extraction import extract_paste
from bad_email_check.laya_adapter import CHECKPOINT_REVISION, verify_checkpoint
from bad_email_check.questions import QUESTION_SET_VERSION, email_questions, evidence_state
from bad_email_check.supervised_export import verify_assets

pytestmark = pytest.mark.real_model


def test_exported_supervised_candidate_reloads_offline_without_activation(record_property):
    configured = os.environ.get("EMAIL_CHECK_CANDIDATE_PATH")
    if not configured:
        pytest.skip("Set EMAIL_CHECK_CANDIDATE_PATH to the completed isolated candidate")
    root = Path(configured).resolve(strict=True)
    candidate = json.loads((root / "candidate-manifest.json").read_bytes())
    provenance = json.loads((root / "training-provenance.json").read_bytes())
    assert candidate["format"] == "email-candidate-v1"
    assert candidate["activation_approved"] is candidate["calibration_approved"] is False
    assert candidate["question_set_version"] == QUESTION_SET_VERSION
    assert provenance["complete"] is True and provenance["production_activated"] is False
    assert provenance["parent_revision"] == CHECKPOINT_REVISION
    assert provenance["unknown_excluded"] is True
    assert provenance["config"]["loss"] == "soft-ce"
    assert len(provenance["loss_history"]) == provenance["config"]["epochs"]
    assert all(math.isfinite(loss) for loss in provenance["loss_history"])
    assert (
        provenance["candidate_manifest_sha256"]
        == hashlib.sha256((root / "candidate-manifest.json").read_bytes()).hexdigest()
    )
    for relative, expected in candidate["files"].items():
        path = (root / relative).resolve(strict=True)
        path.relative_to(root)
        with path.open("rb") as handle:
            assert hashlib.file_digest(handle, "sha256").hexdigest() == expected
    base = Path("checkpoints/laya-english")
    original = verify_checkpoint(base)
    assert original["files"] == provenance["parent_artifact_hashes"]
    import torch
    from laya import Agent

    torch.set_num_threads(4)

    evidence = extract_paste(
        "From: synthetic@example.org\nSubject: Export check\n\nMeeting tomorrow at noon.",
        Settings(_env_file=None, gmail_client_file=None),
    )
    with offline() as attempts:
        agent = Agent(
            str(root), device="cpu", compile=False, fast=False, expected_sha256=candidate["files"]
        )
        answer = agent.predict(
            evidence_state(evidence), email_questions(), max_len=2048, head_max_len=192
        )
    assert not attempts
    assert answer["usage"]["truncated"] is False
    assert set(answer["answers"]) == set(email_questions())
    assert all(0 <= value["noul"] <= 1 for value in answer["answers"].values())
    verify_assets(root, candidate["files"])
    assert json.loads((root / "candidate-manifest.json").read_bytes()) == candidate
    assert json.loads((root / "training-provenance.json").read_bytes()) == provenance
    assert verify_checkpoint(base) == original
    record_property(
        "candidate_reload",
        {
            "candidate_manifest_sha256": provenance["candidate_manifest_sha256"],
            "five_answers_valid": True,
            "network_attempts": 0,
            "baseline_unchanged": True,
            "production_activated": False,
        },
    )
