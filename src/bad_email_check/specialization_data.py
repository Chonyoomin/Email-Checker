import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from .evaluation_dataset import (
    SOURCES,
    digest,
    download_sources,
    public_records,
    redact,
    validate_dataset,
)

BASELINE_MANIFEST_SHA256 = "57cec9d3a8c96774e60de3aab0c782109a60f6d3f51f64d12faa203ff1db7642"


def prepare(baseline_root, sources, output):
    if (output / "manifest.json").exists():
        raise ValueError("Choose a new specialization directory; existing review data is preserved")
    if (
        hashlib.sha256((baseline_root / "manifest.json").read_bytes()).hexdigest()
        != BASELINE_MANIFEST_SHA256
    ):
        raise ValueError("Baseline manifest differs from the approved frozen set")
    baseline = validate_dataset(baseline_root)
    existing_groups = {row["group_id"] for row in baseline["records"]}
    selected = []
    for row in baseline["records"]:
        if row["split"] in {"train", "validation"}:
            selected.append((dict(row), (baseline_root / row["path"]).read_bytes()))
    counts = Counter()
    fresh_groups = set()
    for row in sorted(public_records(sources), key=lambda item: item["id"]):
        if (
            row["split"] != "test"
            or row["group_id"] in existing_groups
            or row["group_id"] in fresh_groups
        ):
            continue
        if counts[row["label"]] >= 12:
            continue
        fresh_groups.add(row["group_id"])
        counts[row["label"]] += 1
        raw = (
            "From: corpus@example.org\nSubject: "
            + redact(row["subject"]).replace("\r", " ").replace("\n", " ")
            + "\nContent-Type: text/plain; charset=utf-8\n\n"
            + redact(row["body"])
        ).encode()
        selected.append(
            (
                {key: row[key] for key in ("id", "source", "source_row", "label", "group_id")}
                | {"split": "final_test", "tags": ["public_corpus"]},
                raw,
            )
        )
    if counts != {0: 12, 1: 12}:
        raise ValueError("Insufficient fresh independent public groups")
    output.mkdir(parents=True, exist_ok=True)
    (output / "records").mkdir()
    records = []
    for row, raw in selected:
        relative = "records/" + row["id"] + ".eml"
        (output / relative).write_bytes(raw)
        records.append(
            {**row, "path": relative, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
        )
    records.sort(key=lambda row: digest("blind-review:" + row["id"]))
    manifest = {
        "dataset_version": "email-specialization-v1",
        "baseline_manifest_sha256": BASELINE_MANIFEST_SHA256,
        "excluded_baseline_ids": sorted(row["id"] for row in baseline["records"]),
        "excluded_baseline_groups": sorted(existing_groups),
        "source_record": baseline["source_record"],
        "sources": SOURCES,
        "records": records,
        "label_policy": (
            "Provider labels are hidden suggestions only; training requires separate "
            "owner-reviewed decisions. Unknown labels remain unresolved."
        ),
    }
    (output / "manifest.json").write_bytes(json.dumps(manifest, indent=2).encode())
    return manifest


def validate(root, manifest=None):
    if manifest is None:
        with (root / "manifest.json").open("rb") as handle:
            snapshot = handle.read(2_000_001)
        if len(snapshot) > 2_000_000:
            raise ValueError("Specialization manifest exceeds size limit")
        manifest = json.loads(snapshot)
    if (
        manifest["dataset_version"] != "email-specialization-v1"
        or len(manifest["records"]) != 48
        or manifest["baseline_manifest_sha256"] != BASELINE_MANIFEST_SHA256
    ):
        raise ValueError("Unsupported specialization cohort")
    groups = {}
    hashes = {}
    ids = set()
    counts = Counter(row["split"] for row in manifest["records"])
    if counts != {"train": 12, "validation": 12, "final_test": 24}:
        raise ValueError("Invalid specialization split counts")
    for row in manifest["records"]:
        if row["split"] not in {"train", "validation", "final_test"} or row["id"] in ids:
            raise ValueError("Invalid specialization split or duplicate ID")
        ids.add(row["id"])
        if row["split"] == "final_test" and (
            row["id"] in manifest["excluded_baseline_ids"]
            or row["group_id"] in manifest["excluded_baseline_groups"]
        ):
            raise ValueError("Final test overlaps the published baseline cohort")
        path = (root / row["path"]).resolve(strict=True)
        path.relative_to(root.resolve())
        if not 0 <= row["bytes"] <= 1_500_000 or path.stat().st_size != row["bytes"]:
            raise ValueError("Invalid specialization record size")
        if hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]:
            raise ValueError("Specialization content checksum mismatch")
        for identity, mapping in ((row["group_id"], groups), (row["sha256"], hashes)):
            if identity in mapping and mapping[identity] != row["split"]:
                raise ValueError("Specialization split leakage")
            mapping[identity] = row["split"]
    return manifest


def main():
    parser = argparse.ArgumentParser(
        description="Prepare a blinded human-review cohort, without training."
    )
    parser.add_argument("--baseline", type=Path, default=Path("data/evaluation"))
    parser.add_argument("--sources", type=Path, default=Path("data/evaluation-sources"))
    parser.add_argument("--output", type=Path, default=Path("data/specialization"))
    parser.add_argument("--download", action="store_true")
    args = parser.parse_args()
    created = download_sources(args.sources) if args.download else []
    try:
        manifest = prepare(args.baseline, args.sources, args.output)
        validate(args.output)
    finally:
        for path in created:
            path.unlink()
    print(
        json.dumps(
            {
                "records": len(manifest["records"]),
                "splits": dict(Counter(row["split"] for row in manifest["records"])),
                "human_review_required": True,
            }
        )
    )


if __name__ == "__main__":
    main()
