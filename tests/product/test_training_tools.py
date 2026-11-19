import hashlib
import math
import os
import socket
from pathlib import Path

import pytest

from bad_email_check.config import Settings
from bad_email_check.extraction import extract_paste
from bad_email_check.laya_adapter import verify_checkpoint
from bad_email_check.questions import email_questions, evidence_state


@pytest.mark.real_model
def test_pinned_supervised_head_training_export_and_reload(tmp_path, monkeypatch, record_property):
    if os.environ.get("EMAIL_CHECK_RUN_REAL_MODEL") != "1":
        pytest.skip("Explicit real-model run required")
    import gc

    import torch
    from laya import Agent, train

    torch.set_num_threads(4)
    attempts = []

    def denied(*args, **kwargs):
        attempts.append(True)
        raise AssertionError("Training tool verification attempted network access")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")
    monkeypatch.setenv("HF_HUB_DISABLE_TELEMETRY", "1")
    base = Path("checkpoints/laya-english")
    original = verify_checkpoint(base)
    model, tokenizer, cfg = train.load_checkpoint(str(base.resolve()))
    rows = []
    for body, label in (
        ("Meeting tomorrow at noon.", False),
        ("Send your password and login code to the stranger.", True),
        ("Unresolved example.", None),
    ):
        evidence = extract_paste(
            "From: synthetic@example.org\nSubject: Tool test\n\n" + body, Settings(_env_file=None)
        )
        rows.append(
            {
                "state": evidence_state(evidence),
                "questions": email_questions(),
                "expected": {"overall_scam": label},
            }
        )
    items, skipped = train.items_from_rows(tokenizer, rows, 2048, 192)
    assert len(items) == 2 and not skipped
    assert [item["target"] for item in items] == [[1.0, 0.0], [0.0, 1.0]]
    assert all(item["qtype"] == items[0]["qtype"] for item in items)
    monkeypatch.setattr(
        train, "rlcd_loss", lambda *a, **k: pytest.fail("RLCD is not supervised CE")
    )
    before = model.scorer[-1].weight.detach().clone()
    config = train.TrainConfig(
        loss="soft-ce",
        epochs=1,
        micro_batch=1,
        grad_accum=2,
        freeze_encoder=True,
        amp=False,
        gradient_checkpointing=False,
        log_every=0,
        max_len=2048,
        head_max_len=192,
        seed=20261029,
    )
    config.validate()
    history = train.train_model(model, tokenizer, items, config, torch.device("cpu"), 2048, 192)
    assert len(history) == 1 and math.isfinite(history[0])
    assert not torch.equal(before, model.scorer[-1].weight.detach())
    assert all(
        not parameter.requires_grad and parameter.grad is None
        for parameter in model.encoder.parameters()
    )
    output = tmp_path / "synthetic-tool-spike"
    train.save_checkpoint(model, tokenizer, dict(cfg, max_len=2048, head_max_len=192), str(output))
    files = {
        str(path.relative_to(output)).replace("\\", "/"): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in output.rglob("*")
        if path.is_file()
    }
    del model, tokenizer, items
    gc.collect()
    agent = Agent(
        str(output.resolve()), device="cpu", compile=False, fast=False, expected_sha256=files
    )
    questions = {"overall_scam": email_questions()["overall_scam"]}
    answer = agent.predict(rows[0]["state"], questions, max_len=2048, head_max_len=192)
    assert 0 <= answer["answers"]["overall_scam"]["noul"] <= 1
    assert answer["usage"]["truncated"] is False
    assert verify_checkpoint(base) == original
    assert not attempts
    record_property(
        "training_tool_spike",
        {
            "objective": "soft-ce",
            "device": "cpu",
            "freeze_encoder": True,
            "training_items": 2,
            "unknown_items_excluded": 1,
            "optimizer_updates": train.optimizer_updates(2, 1, 2, 1),
            "finite_loss": history[0],
            "head_changed": True,
            "export_reloaded": True,
            "base_unchanged": True,
            "network_attempts": len(attempts),
            "export_files": files,
        },
    )
