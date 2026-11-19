import argparse
import copy
import hashlib
import json
import math
import shutil
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from .baseline import offline
from .config import Settings
from .extraction import extract_eml
from .label_review import Finalize
from .laya_adapter import ADAPTER_VERSION, CHECKPOINT_REVISION, LayaAdapter, verify_checkpoint
from .questions import QUESTION_SET_VERSION, email_questions, evidence_state
from .specialization_data import validate
from .supervised_export import normalize_tokenizer, read_snapshot


def verified_labels(root, manifest_hash, labels_hash):
    manifest_path = root / "manifest.json"
    labels_path = root / "reviewed-labels.json"
    if not labels_path.is_file():
        raise ValueError("Owner-reviewed labels are required before training")
    manifest_bytes = read_snapshot(manifest_path, 2_000_000)
    labels_bytes = read_snapshot(labels_path, 200_000)
    if hashlib.sha256(manifest_bytes).hexdigest() != manifest_hash:
        raise ValueError("Specialization manifest hash mismatch")
    if hashlib.sha256(labels_bytes).hexdigest() != labels_hash:
        raise ValueError("Reviewed-label snapshot hash mismatch")
    manifest = validate(root, json.loads(manifest_bytes))
    labels = json.loads(labels_bytes)
    if labels.get("finalized") is not True or labels.get("manifest_sha256") != manifest_hash:
        raise ValueError("Owner label review must be finalized for this cohort")
    policy = labels.get("policy") or {}
    Finalize.model_validate(
        {
            "policy": policy.get("name"),
            "extra_false_alerts": policy.get("extra_false_alerts"),
            "agree": policy.get("agreed_by_owner"),
        }
    )
    if policy.get("evaluation_cutoff") != 0.5 or (
        policy["name"] != "recall_with_alert_budget" and policy["extra_false_alerts"] != 0
    ):
        raise ValueError("Validation policy differs from owner agreement")
    if set(labels["decisions"]) != {row["id"] for row in manifest["records"]}:
        raise ValueError("Every review item needs an explicit owner decision")
    targets = {}
    counts = Counter()
    for row in manifest["records"]:
        decision = labels["decisions"][row["id"]]
        if (
            decision.get("reviewed_by_owner") is not True
            or decision.get("content_sha256") != row["sha256"]
            or decision.get("label") not in {"scam", "legitimate", "unknown"}
        ):
            raise ValueError("Owner decision is invalid or belongs to changed content")
        target = {"scam": True, "legitimate": False, "unknown": None}[decision["label"]]
        targets[row["id"]] = target
        counts[(row["split"], "unknown" if target is None else str(int(target)))] += 1
    for split in ("train", "validation", "final_test"):
        if any(counts[(split, label)] < 2 for label in ("0", "1")):
            raise ValueError("More known owner-reviewed examples of both classes are required")
    return (
        manifest,
        labels,
        targets,
        {split + ":" + label: count for (split, label), count in counts.items()},
    )


def training_rows(root, manifest, targets, adapter):
    rows = []
    trained_ids = []
    settings = Settings(_env_file=None, gmail_client_file=None)
    questions = email_questions()
    internal = {name: adapter.agent._to_internal(question) for name, question in questions.items()}
    for record in manifest["records"]:
        if record["split"] != "train" or targets[record["id"]] is None:
            continue
        path = (root / record["path"]).resolve(strict=True)
        path.relative_to(root.resolve(strict=True))
        raw = read_snapshot(path, 1_500_000)
        if len(raw) != record["bytes"] or hashlib.sha256(raw).hexdigest() != record["sha256"]:
            raise ValueError("Training content differs from the reviewed snapshot")
        evidence = extract_eml(raw, settings)
        if (
            evidence.extraction_status != "complete"
            or evidence.truncated
            or evidence.context_limit_exceeded
        ):
            raise ValueError("A known training example has incomplete extraction")
        state = evidence_state(evidence)
        encoded = adapter.agent._encode_state(
            state, list(questions), internal, max_len=2048, head_max_len=192
        )
        if len(encoded) != 5 or any(
            item["state_stats"]["truncated"]
            or item["state_stats"]["state_tokens_dropped"]
            or item["options"]["options_distinct"] != item["options"]["options"]
            for item in encoded
        ):
            raise ValueError("A known training example exceeds full input coverage")
        rows.append(
            {
                "state": state,
                "questions": questions,
                "expected": {"overall_scam": targets[record["id"]]},
            }
        )
        trained_ids.append(record["id"])
    return rows, trained_ids


def tune(root, manifest_hash, labels_hash, base, output):
    manifest, labels, targets, counts = verified_labels(root, manifest_hash, labels_hash)
    base = base.resolve(strict=True)
    output = output.resolve()
    if output == base or output in base.parents or base in output.parents or output.exists():
        raise ValueError("Candidate output must be new and separate from the baseline")
    original = verify_checkpoint(base)
    import torch
    from laya import train

    torch.set_num_threads(4)
    config = train.TrainConfig(
        loss="soft-ce",
        epochs=16,
        micro_batch=1,
        grad_accum=2,
        freeze_encoder=True,
        amp=False,
        gradient_checkpointing=False,
        max_len=2048,
        head_max_len=192,
        seed=20261029,
        head_lr=1e-4,
        log_every=0,
    )
    config.validate()
    started = time.monotonic()
    with offline() as attempts:
        adapter = LayaAdapter(base)
        rows, identifiers = training_rows(root, manifest, targets, adapter)
        items, skipped = train.items_from_rows(adapter.agent.tok, rows, 2048, 192)
        if len(items) != len(rows) or skipped:
            raise ValueError("Training tool omitted or changed known-label examples")
        output.mkdir(parents=True, exist_ok=False)
        provenance = {
            "complete": False,
            "parent_revision": CHECKPOINT_REVISION,
            "parent_artifact_hashes": original["files"],
            "parent_adapter_version": ADAPTER_VERSION,
            "question_set_version": QUESTION_SET_VERSION,
            "manifest_sha256": manifest_hash,
            "reviewed_labels_sha256": labels_hash,
            "owner_policy": labels["policy"],
            "label_counts": counts,
            "trained_ids": identifiers,
            "unknown_excluded": True,
            "trained_question": "overall_scam",
            "config": asdict(config),
            "device": "cpu",
            "parallel_options": adapter.agent.parallel_options,
            "training_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        }
        path = output / "training-provenance.json"
        path.write_bytes(json.dumps(provenance, indent=2).encode())
        history = train.train_model(
            adapter.agent.model,
            adapter.agent.tok,
            items,
            config,
            torch.device("cpu"),
            2048,
            192,
            parallel=adapter.agent.parallel_options,
        )
        if len(history) != config.epochs or not all(math.isfinite(value) for value in history):
            raise ValueError("Supervised run did not finish with finite losses")
        checkpoint_config = copy.deepcopy(adapter.agent.cfg)
        checkpoint_config.update(max_len=2048, head_max_len=192)
        train.save_checkpoint(
            adapter.agent.model, adapter.agent.tok, checkpoint_config, str(output)
        )
        provenance["tokenizer_normalization"] = normalize_tokenizer(output)
        shutil.copyfile(base / "README.md", output / "README.md")
        assets = {
            str(item.relative_to(output)).replace("\\", "/"): hashlib.sha256(
                item.read_bytes()
            ).hexdigest()
            for item in output.rglob("*")
            if item.is_file() and item != path
        }
        candidate = {
            "format": "email-candidate-v1",
            "parent_revision": CHECKPOINT_REVISION,
            "question_set_version": QUESTION_SET_VERSION,
            "context_tokens": 2048,
            "head_tokens": 192,
            "files": assets,
            "activation_approved": False,
            "calibration_approved": False,
        }
        (output / "candidate-manifest.json").write_bytes(json.dumps(candidate, indent=2).encode())
        if verify_checkpoint(base) != original or attempts:
            raise ValueError("Baseline changed or training attempted network access")
        provenance.update(
            complete=True,
            loss_history=history,
            elapsed_seconds=time.monotonic() - started,
            network_attempts=len(attempts),
            candidate_manifest_sha256=hashlib.sha256(
                (output / "candidate-manifest.json").read_bytes()
            ).hexdigest(),
            baseline_unchanged=True,
            calibrated_probability_enabled=False,
            production_activated=False,
        )
        path.write_bytes(json.dumps(provenance, indent=2).encode())
    return provenance


def main():
    parser = argparse.ArgumentParser(
        description="Run one isolated supervised candidate from frozen owner labels."
    )
    parser.add_argument("--dataset", type=Path, default=Path("data/specialization"))
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--labels-sha256", required=True)
    parser.add_argument("--base", type=Path, default=Path("checkpoints/laya-english"))
    parser.add_argument("--output", type=Path, default=Path("checkpoints/email-candidate-v1"))
    args = parser.parse_args()
    try:
        result = tune(
            args.dataset, args.manifest_sha256, args.labels_sha256, args.base, args.output
        )
    except OSError, ValueError, RuntimeError, KeyError:
        print(
            "Supervised candidate was not completed. Verify frozen labels, policy and local setup."
        )
        raise SystemExit(2) from None
    print(
        json.dumps(
            {
                "complete": result["complete"],
                "training_items": len(result["trained_ids"]),
                "production_activated": False,
            }
        )
    )


if __name__ == "__main__":
    main()
