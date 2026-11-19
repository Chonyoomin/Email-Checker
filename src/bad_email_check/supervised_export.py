import argparse
import hashlib
import json
from pathlib import Path

TOKENIZER_CONFIG = "tokenizer/tokenizer_config.json"


def read_snapshot(path, limit):
    with path.open("rb") as handle:
        snapshot = handle.read(limit + 1)
    if len(snapshot) > limit:
        raise ValueError("Reviewed input exceeds size limit")
    return snapshot


def digest(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def normalize_tokenizer(root):
    path = (root / TOKENIZER_CONFIG).resolve(strict=True)
    path.relative_to(root.resolve(strict=True))
    before = read_snapshot(path, 2_000_000)
    config = json.loads(before)
    changed = False
    if config.get("tokenizer_class") in {None, "TokenizersBackend"}:
        config["tokenizer_class"] = "PreTrainedTokenizerFast"
        config.pop("backend", None)
        config.pop("is_local", None)
        changed = True
    if isinstance(config.get("extra_special_tokens"), list):
        config["extra_special_tokens"] = {
            f"extra_{index}": value for index, value in enumerate(config["extra_special_tokens"])
        }
        changed = True
    if changed:
        temporary = path.with_suffix(".normalizing.tmp")
        temporary.write_bytes(json.dumps(config, indent=2).encode("utf-8"))
        temporary.replace(path)
    return {
        "recipe": "laya-0.4.15-tokenizer-v1",
        "changed": changed,
        "before_sha256": hashlib.sha256(before).hexdigest(),
        "after_sha256": digest(path),
    }


def verify_assets(root, files):
    for relative, expected in files.items():
        path = (root / relative).resolve(strict=True)
        path.relative_to(root.resolve(strict=True))
        if digest(path) != expected:
            raise ValueError("Candidate artifact checksum mismatch")


def repair_export(root, manifest_hash, tokenizer_hash):
    root = root.resolve(strict=True)
    manifest_path = root / "candidate-manifest.json"
    provenance_path = root / "training-provenance.json"
    original = read_snapshot(manifest_path, 2_000_000)
    previous = read_snapshot(provenance_path, 200_000)
    if hashlib.sha256(original).hexdigest() != manifest_hash:
        raise ValueError("Original candidate identity differs")
    manifest = json.loads(original)
    provenance = json.loads(previous)
    if (
        manifest.get("format") != "email-candidate-v1"
        or manifest.get("activation_approved") is not False
        or manifest.get("calibration_approved") is not False
        or provenance.get("complete") is not True
        or provenance.get("candidate_manifest_sha256") != manifest_hash
        or provenance.get("production_activated") is not False
    ):
        raise ValueError("Only a completed inactive candidate can be repaired")
    original_tokenizer_hash = manifest["files"][TOKENIZER_CONFIG]
    accepted = dict(manifest["files"], **{TOKENIZER_CONFIG: tokenizer_hash})
    verify_assets(root, accepted)
    normalized = normalize_tokenizer(root)
    if normalized["after_sha256"] != tokenizer_hash:
        raise ValueError("Accepted tokenizer metadata was not normalized")
    history = root.parent / f"{root.name}-export-history"
    history.mkdir(exist_ok=True)
    for name, content in (
        ("candidate-manifest.json", original),
        ("training-provenance.json", previous),
    ):
        target = history / f"{manifest_hash}-{name}"
        if target.exists():
            if target.read_bytes() != content:
                raise ValueError("Original export history differs")
        else:
            with target.open("xb") as handle:
                handle.write(content)
    manifest["files"] = accepted
    manifest["supersedes_manifest_sha256"] = manifest_hash
    repaired = json.dumps(manifest, indent=2).encode()
    repaired_hash = hashlib.sha256(repaired).hexdigest()
    provenance.setdefault("export_repairs", []).append(
        {
            "recipe": normalized["recipe"],
            "original_manifest_sha256": manifest_hash,
            "repaired_manifest_sha256": repaired_hash,
            "original_tokenizer_sha256": original_tokenizer_hash,
            "normalized_tokenizer_sha256": tokenizer_hash,
            "weights_unchanged": True,
            "retrained": False,
            "repair_source_sha256": digest(Path(__file__)),
        }
    )
    provenance["candidate_manifest_sha256"] = repaired_hash
    for path, content in (
        (manifest_path, repaired),
        (provenance_path, json.dumps(provenance, indent=2).encode()),
    ):
        temporary = path.with_suffix(".repair.tmp")
        temporary.write_bytes(content)
        temporary.replace(path)
    verify_assets(root, accepted)
    return {
        "candidate_manifest_sha256": repaired_hash,
        "weights_unchanged": True,
        "retrained": False,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Repair only a reviewed tokenizer export mismatch."
    )
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--tokenizer-sha256", required=True)
    args = parser.parse_args()
    try:
        result = repair_export(args.checkpoint, args.manifest_sha256, args.tokenizer_sha256)
    except OSError, ValueError, KeyError:
        print("Export repair failed. Preserve the original artifacts for review.")
        raise SystemExit(2) from None
    print(json.dumps(result))


if __name__ == "__main__":
    main()
