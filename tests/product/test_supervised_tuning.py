import hashlib
import json
import sys
from types import SimpleNamespace

import pytest
import test_label_review

from bad_email_check import supervised_tuning


@pytest.fixture
def reviewed(tmp_path):
    root, manifest = test_label_review.cohort.__wrapped__(tmp_path)
    labels = {
        "finalized": True,
        "manifest_sha256": hashlib.sha256((root / "manifest.json").read_bytes()).hexdigest(),
        "policy": {
            "name": "recall_no_extra_alerts",
            "extra_false_alerts": 0,
            "evaluation_cutoff": 0.5,
            "agreed_by_owner": True,
        },
        "decisions": {
            row["id"]: {
                "label": "scam" if row["label"] == 0 else "legitimate",
                "reviewed_by_owner": True,
                "content_sha256": row["sha256"],
            }
            for row in manifest["records"]
        },
    }
    return root, manifest, labels


def freeze(root, labels):
    path = root / "reviewed-labels.json"
    path.write_bytes(json.dumps(labels).encode())
    return labels["manifest_sha256"], hashlib.sha256(path.read_bytes()).hexdigest()


def test_owner_labels_override_provider_and_unknowns_stay_unresolved(reviewed):
    root, manifest, labels = reviewed
    unknown = manifest["records"][0]["id"]
    labels["decisions"][unknown]["label"] = "unknown"
    _, _, targets, counts = supervised_tuning.verified_labels(root, *freeze(root, labels))
    assert targets[unknown] is None
    for row in manifest["records"][1:]:
        assert targets[row["id"]] is (row["label"] == 0)
    assert counts["train:unknown"] == 1


@pytest.mark.parametrize("invalid", ["unfinished", "no_agreement", "content_changed", "one_class"])
def test_invalid_review_cannot_start_training(reviewed, invalid):
    root, manifest, labels = reviewed
    if invalid == "unfinished":
        labels["finalized"] = False
    elif invalid == "no_agreement":
        labels["policy"]["agreed_by_owner"] = False
    elif invalid == "content_changed":
        labels["decisions"][manifest["records"][0]["id"]]["content_sha256"] = "0" * 64
    else:
        for decision in labels["decisions"].values():
            decision["label"] = "scam"
    with pytest.raises(ValueError):
        supervised_tuning.verified_labels(root, *freeze(root, labels))


def test_only_known_training_rows_and_full_context_are_used(reviewed):
    root, manifest, labels = reviewed
    labels["decisions"][manifest["records"][0]["id"]]["label"] = "unknown"
    _, _, targets, _ = supervised_tuning.verified_labels(root, *freeze(root, labels))
    encoded = [
        {
            "state_stats": {"truncated": False, "state_tokens_dropped": 0},
            "options": {"options_distinct": 2, "options": 2},
        }
        for _ in range(5)
    ]
    adapter = SimpleNamespace(
        agent=SimpleNamespace(
            _to_internal=lambda question: question, _encode_state=lambda *a, **k: encoded
        )
    )
    rows, ids = supervised_tuning.training_rows(root, manifest, targets, adapter)
    assert len(rows) == len(ids) == 11
    assert all(set(row["expected"]) == {"overall_scam"} for row in rows)
    assert set(ids) == {row["id"] for row in manifest["records"][1:12]}
    encoded[0]["state_stats"]["truncated"] = True
    with pytest.raises(ValueError, match="full input coverage"):
        supervised_tuning.training_rows(root, manifest, targets, adapter)


def test_missing_owner_review_cannot_load_model_or_create_candidate(tmp_path, monkeypatch):
    root, _ = test_label_review.cohort.__wrapped__(tmp_path)
    output = root / "candidate"

    def forbidden(*args, **kwargs):
        pytest.fail("Model loaded without owner-reviewed labels")

    monkeypatch.setattr(supervised_tuning, "LayaAdapter", forbidden)
    with pytest.raises(ValueError, match="Owner-reviewed labels"):
        supervised_tuning.tune(root, "0" * 64, "0" * 64, root / "base", output)
    assert not output.exists()


def test_hash_and_parsing_use_the_same_frozen_snapshots(reviewed, monkeypatch):
    root, manifest, labels = reviewed
    hashes = freeze(root, labels)
    original_read = supervised_tuning.read_snapshot

    def read_then_replace(path, limit):
        snapshot = original_read(path, limit)
        if path.name in {"manifest.json", "reviewed-labels.json"}:
            path.write_bytes(b"{}")
        return snapshot

    monkeypatch.setattr(supervised_tuning, "read_snapshot", read_then_replace)
    result, saved_labels, targets, _ = supervised_tuning.verified_labels(root, *hashes)
    assert result == manifest and saved_labels == labels and len(targets) == 48


@pytest.mark.parametrize("mutation", ["same_size", "larger", "escape"])
def test_changed_training_bytes_fail_before_training_or_candidate_creation(
    reviewed, monkeypatch, mutation
):
    root, manifest, labels = reviewed
    hashes = freeze(root, labels)
    base = root / "baseline"
    base.mkdir()
    output = root / "candidate"
    record = manifest["records"][0]

    def forbidden(*args, **kwargs):
        pytest.fail("Training reached unreviewed bytes")

    class Config:
        def __init__(self, **kwargs):
            pass

        def validate(self):
            pass

    def load_and_mutate(path):
        item = root / record["path"]
        if mutation == "escape":
            record["path"] = "../outside.eml"
            outside = root.parent / "outside.eml"
            outside.write_bytes(b"Unreviewed replacement")
        else:
            original = item.read_bytes()
            item.write_bytes(b"X" * len(original) if mutation == "same_size" else original + b"X")
        return SimpleNamespace(agent=SimpleNamespace(_to_internal=lambda question: question))

    original_verify = supervised_tuning.verified_labels

    def capture_verified(*args):
        result = original_verify(*args)
        result[0]["records"][0] = record
        return result

    monkeypatch.setattr(supervised_tuning, "verified_labels", capture_verified)
    monkeypatch.setattr(supervised_tuning, "verify_checkpoint", lambda path: {"files": {}})
    monkeypatch.setattr(supervised_tuning, "LayaAdapter", load_and_mutate)
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(set_num_threads=lambda count: None))
    monkeypatch.setitem(
        sys.modules,
        "laya",
        SimpleNamespace(train=SimpleNamespace(TrainConfig=Config, items_from_rows=forbidden)),
    )
    with pytest.raises(ValueError):
        supervised_tuning.tune(root, *hashes, base, output)
    assert not output.exists()
