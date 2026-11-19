import argparse
import gc
import hashlib
import json
import math
from importlib.metadata import version
from pathlib import Path

from .baseline import offline, rates
from .config import Settings
from .extraction import extract_eml
from .laya_adapter import CoverageError, LayaAdapter, verify_checkpoint
from .model_adapter import AdapterIdentity
from .questions import QUESTION_SET_VERSION
from .supervised_export import read_snapshot, verify_assets
from .supervised_tuning import verified_labels

CALIBRATION_VERSION = "email-temperature-grid-v1"


def transformed(estimate, temperature):
    estimate = min(1 - 1e-12, max(1e-12, estimate))
    logit = math.log(estimate / (1 - estimate)) / temperature
    return 1 / (1 + math.exp(-max(-700, min(700, logit))))


def reliability(pairs):
    bins = []
    for index in range(5):
        selected = [(p, y) for p, y in pairs if min(4, int(p * 5)) == index]
        bins.append(
            {
                "lower": index / 5,
                "upper": (index + 1) / 5,
                "count": len(selected),
                "mean_estimate": sum(p for p, _ in selected) / len(selected) if selected else None,
                "observed_rate": sum(y for _, y in selected) / len(selected) if selected else None,
            }
        )
    return {
        "brier": sum((p - y) ** 2 for p, y in pairs) / len(pairs) if pairs else None,
        "bins": bins,
    }


def fit_temperature(pairs):
    if any(sum(y == label for _, y in pairs) < 2 for label in (0, 1)):
        return None

    def loss(temperature):
        probabilities = [(transformed(p, temperature), y) for p, y in pairs]
        return -sum(
            y * math.log(max(p, 1e-12)) + (1 - y) * math.log(max(1 - p, 1e-12))
            for p, y in probabilities
        ) / len(probabilities)

    candidates = [math.exp(index / 20) for index in range(-46, 47)]
    return min(candidates, key=lambda temperature: (loss(temperature), abs(math.log(temperature))))


def summarize_validation(rows, policy):
    def metrics(name, threshold=0.5):
        return rates(
            [
                {
                    "label": row["label"],
                    "predicted": int(row[name] >= threshold) if row[name] is not None else None,
                }
                for row in rows
            ]
        )

    base = metrics("baseline")
    candidate = metrics("candidate")
    pairs = [(row["candidate"], row["label"]) for row in rows if row["candidate"] is not None]
    temperature = fit_temperature(pairs)
    thresholds = sorted({0.0, 1.0, *(p for p, _ in pairs)})
    budget = base["fp"] + policy["extra_false_alerts"]
    profiles = [
        {"threshold": threshold, "metrics": metrics("candidate", threshold)}
        for threshold in thresholds
    ]
    feasible = [profile for profile in profiles if profile["metrics"]["fp"] <= budget]
    selected = max(
        feasible,
        key=lambda profile: (
            profile["metrics"]["recall"] or 0,
            -profile["metrics"]["fp"],
            profile["threshold"],
        ),
        default=None,
    )
    complete = bool(rows) and base["coverage"] == candidate["coverage"] == 1
    if not rows:
        improved = False
    elif policy["name"] == "fewer_alerts":
        improved = candidate["fp"] < base["fp"] and candidate["recall"] >= base["recall"]
    else:
        improved = candidate["recall"] > base["recall"] and candidate["fp"] <= budget
    calibrated = [(transformed(p, temperature), y) for p, y in pairs] if temperature else []
    return {
        "baseline": base,
        "candidate": candidate,
        "agreed_cutoff": 0.5,
        "complete_validation_coverage": complete,
        "agreed_validation_gate_passed": complete and improved,
        "calibration": {
            "version": CALIBRATION_VERSION,
            "input": "SDK overall_scam noul with inherited upstream temperature configuration",
            "fit_split": "validation",
            "temperature": temperature,
            "fitted": temperature is not None,
            "raw": reliability(pairs),
            "transformed": reliability(calibrated),
            "calibrated_probability_enabled": False,
            "bands_enabled": False,
            "limitation": (
                "Exploratory historical cohort; too few independent positive examples "
                "to establish population reliability."
            ),
        },
        "exploratory_validation_threshold": selected,
        "threshold_version": "email-validation-threshold-v1",
        "threshold_activated": False,
    }


class OfflineCandidate(LayaAdapter):
    def __init__(self, path, expected_hash):
        snapshot = read_snapshot(path / "candidate-manifest.json", 2_000_000)
        if hashlib.sha256(snapshot).hexdigest() != expected_hash:
            raise ValueError("Frozen candidate identity differs")
        self.manifest = json.loads(snapshot)
        if (
            self.manifest.get("format") != "email-candidate-v1"
            or self.manifest.get("context_tokens") != 2048
            or self.manifest.get("head_tokens") != 192
            or self.manifest.get("question_set_version") != QUESTION_SET_VERSION
            or version("laya") != "0.4.15"
        ):
            raise ValueError("Unsupported offline candidate")
        verify_assets(path, self.manifest["files"])
        import torch
        from laya import Agent

        torch.set_num_threads(4)
        self.agent = Agent(
            str(path.resolve()),
            device="cpu",
            compile=False,
            fast=False,
            expected_sha256=self.manifest["files"],
        )
        self.revision = expected_hash
        self.context_limit = 2048
        self.head_limit = 192
        self.last_input_tokens = None
        self.assess_calls = 0

    @property
    def identity(self):
        return AdapterIdentity(
            self.revision, "email-offline-candidate-v1", QUESTION_SET_VERSION, False
        )


def evaluate_validation(
    root, manifest_hash, labels_hash, candidate_path, candidate_hash, base, output
):
    manifest, labels, targets, _ = verified_labels(root, manifest_hash, labels_hash)
    provenance_bytes = read_snapshot(candidate_path / "training-provenance.json", 200_000)
    provenance = json.loads(provenance_bytes)
    if (
        provenance.get("complete") is not True
        or provenance.get("manifest_sha256") != manifest_hash
        or provenance.get("reviewed_labels_sha256") != labels_hash
        or provenance.get("candidate_manifest_sha256") != candidate_hash
    ):
        raise ValueError("Candidate does not belong to these reviewed labels")
    selected = [
        row
        for row in manifest["records"]
        if row["split"] == "validation" and targets[row["id"]] is not None
    ]
    output.mkdir(parents=True, exist_ok=False)
    report = {
        "complete": False,
        "manifest_sha256": manifest_hash,
        "reviewed_labels_sha256": labels_hash,
        "candidate_manifest_sha256": candidate_hash,
        "owner_policy": labels["policy"],
        "selected_split": "validation",
        "final_test_evaluated": False,
        "unknowns_excluded": True,
        "production_activated": False,
    }
    report_path = output / "validation-report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    rows = [
        {"id": row["id"], "content_sha256": row["sha256"], "label": int(targets[row["id"]])}
        for row in selected
    ]
    settings = Settings(_env_file=None, gmail_client_file=None)
    original = verify_checkpoint(base)
    with offline() as attempts:
        for name in ("baseline", "candidate"):
            adapter = (
                LayaAdapter(base)
                if name == "baseline"
                else OfflineCandidate(candidate_path, candidate_hash)
            )
            for index, (record, row) in enumerate(zip(selected, rows, strict=True), 1):
                path = (root / record["path"]).resolve(strict=True)
                path.relative_to(root.resolve(strict=True))
                raw = read_snapshot(path, 1_500_000)
                if (
                    len(raw) != record["bytes"]
                    or hashlib.sha256(raw).hexdigest() != record["sha256"]
                ):
                    raise ValueError("Validation content differs from reviewed bytes")
                evidence = extract_eml(raw, settings)
                try:
                    row[name] = adapter.assess(evidence).overall_scam
                except CoverageError:
                    row[name] = None
                print(f"{name}: validation item {index}/{len(rows)}")
            if name == "candidate":
                verify_assets(candidate_path, adapter.manifest["files"])
            del adapter
            gc.collect()
        if attempts or verify_checkpoint(base) != original:
            raise ValueError("Evaluation attempted network access or changed baseline")
        if (
            hashlib.sha256(
                read_snapshot(candidate_path / "candidate-manifest.json", 2_000_000)
            ).hexdigest()
            != candidate_hash
            or read_snapshot(candidate_path / "training-provenance.json", 200_000)
            != provenance_bytes
        ):
            raise ValueError("Candidate identity or provenance changed during evaluation")
    report.update(
        complete=True,
        rows=rows,
        summary=summarize_validation(rows, labels["policy"]),
        network_attempts=0,
        baseline_unchanged=True,
        source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    )
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description="Fit exploratory calibration on validation only.")
    parser.add_argument("--dataset", type=Path, default=Path("data/specialization"))
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--labels-sha256", required=True)
    parser.add_argument("--candidate", type=Path, default=Path("checkpoints/email-candidate-v1"))
    parser.add_argument("--candidate-sha256", required=True)
    parser.add_argument("--base", type=Path, default=Path("checkpoints/laya-english"))
    parser.add_argument("--output", type=Path, default=Path("data/specialization/calibration-v1"))
    args = parser.parse_args()
    try:
        result = evaluate_validation(
            args.dataset,
            args.manifest_sha256,
            args.labels_sha256,
            args.candidate,
            args.candidate_sha256,
            args.base,
            args.output,
        )
    except OSError, ValueError, RuntimeError, KeyError:
        print("Validation was not completed. Preserve partial evidence and check local setup.")
        raise SystemExit(2) from None
    print(json.dumps(result["summary"]))


if __name__ == "__main__":
    main()
