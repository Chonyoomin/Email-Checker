import hashlib
import json

import pytest

from bad_email_check.supervised_export import (
    TOKENIZER_CONFIG,
    digest,
    normalize_tokenizer,
    repair_export,
    verify_assets,
)


@pytest.fixture
def exported(tmp_path):
    root = tmp_path / "candidate"
    (root / "tokenizer").mkdir(parents=True)
    (root / TOKENIZER_CONFIG).write_text(
        json.dumps(
            {"tokenizer_class": "TokenizersBackend", "backend": "synthetic", "is_local": True}
        )
    )
    (root / "model.safetensors").write_bytes(b"synthetic weights")
    manifest = {
        "format": "email-candidate-v1",
        "activation_approved": False,
        "calibration_approved": False,
        "files": {name: digest(root / name) for name in [TOKENIZER_CONFIG, "model.safetensors"]},
    }
    (root / "candidate-manifest.json").write_text(json.dumps(manifest))
    frozen_hash = digest(root / "candidate-manifest.json")
    (root / "training-provenance.json").write_text(
        json.dumps(
            {
                "complete": True,
                "candidate_manifest_sha256": frozen_hash,
                "production_activated": False,
            }
        )
    )
    return root, manifest, frozen_hash


def test_export_normalization_is_idempotent_and_ready_before_hash_freeze(exported):
    root, _, _ = exported
    config_path = root / TOKENIZER_CONFIG
    config = json.loads(config_path.read_bytes())
    config["extra_special_tokens"] = ["<synthetic>"]
    config_path.write_text(json.dumps(config))
    first = normalize_tokenizer(root)
    assert first["changed"] and first["before_sha256"] != first["after_sha256"]
    config = json.loads(config_path.read_bytes())
    assert config["tokenizer_class"] == "PreTrainedTokenizerFast"
    assert "backend" not in config and "is_local" not in config
    assert config["extra_special_tokens"] == {"extra_0": "<synthetic>"}
    second = normalize_tokenizer(root)
    assert not second["changed"] and second["after_sha256"] == first["after_sha256"]


def test_repair_preserves_original_identity_and_weights_without_retraining(exported):
    root, manifest, original_hash = exported
    original = (root / "candidate-manifest.json").read_bytes()
    normalize_tokenizer(root)
    repaired = repair_export(root, original_hash, digest(root / TOKENIZER_CONFIG))
    updated = json.loads((root / "candidate-manifest.json").read_bytes())
    assert updated["files"]["model.safetensors"] == manifest["files"]["model.safetensors"]
    assert updated["supersedes_manifest_sha256"] == original_hash
    assert repaired["retrained"] is False and repaired["weights_unchanged"] is True
    assert repaired["candidate_manifest_sha256"] == digest(root / "candidate-manifest.json")
    assert (
        root.parent / f"candidate-export-history/{original_hash}-candidate-manifest.json"
    ).read_bytes() == original
    verify_assets(root, updated["files"])
    provenance = json.loads((root / "training-provenance.json").read_bytes())
    assert provenance["export_repairs"][0]["original_manifest_sha256"] == original_hash


@pytest.mark.parametrize("change", ["weights", "tokenizer", "identity"])
def test_repair_refuses_unreviewed_asset_or_identity_changes(exported, change):
    root, _, original_hash = exported
    normalize_tokenizer(root)
    accepted = digest(root / TOKENIZER_CONFIG)
    if change == "weights":
        (root / "model.safetensors").write_bytes(b"unreviewed weights")
    if change == "tokenizer":
        accepted = hashlib.sha256(b"wrong tokenizer").hexdigest()
    if change == "identity":
        original_hash = "0" * 64
    with pytest.raises(ValueError):
        repair_export(root, original_hash, accepted)
    assert not (root.parent / "candidate-export-history").exists()
