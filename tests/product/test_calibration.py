import hashlib
import json
from types import SimpleNamespace

import test_supervised_tuning

from bad_email_check import calibration


def test_calibration_uses_validation_labels_and_keeps_probability_and_bands_disabled():
    pairs = [(0.95, 1), (0.9, 0), (0.85, 1), (0.8, 0)]
    temperature = calibration.fit_temperature(pairs)
    assert temperature is not None and temperature > 1
    raw = calibration.reliability(pairs)
    calibrated = calibration.reliability(
        [(calibration.transformed(p, temperature), y) for p, y in pairs]
    )
    assert calibrated["brier"] < raw["brier"]
    assert sum(bucket["count"] for bucket in calibrated["bins"]) == 4
    assert calibration.fit_temperature([(0.2, 0), (0.8, 1)]) is None
    assert 0 < calibration.transformed(0, 1) < 1
    assert 0 < calibration.transformed(1, 1) < 1


def test_agreed_gate_uses_original_cutoff_and_all_validation_coverage():
    rows = [
        {"label": 1, "baseline": 0.1, "candidate": 0.8},
        {"label": 1, "baseline": 0.1, "candidate": 0.8},
        {"label": 0, "baseline": 0.1, "candidate": 0.2},
        {"label": 0, "baseline": 0.1, "candidate": 0.2},
    ]
    policy = {"name": "recall_no_extra_alerts", "extra_false_alerts": 0}
    summary = calibration.summarize_validation(rows, policy)
    assert summary["agreed_validation_gate_passed"] is True
    assert summary["calibration"]["fitted"] is True
    assert summary["calibration"]["calibrated_probability_enabled"] is False
    assert summary["calibration"]["bands_enabled"] is False
    assert summary["threshold_activated"] is False
    rows[0]["candidate"] = None
    assert calibration.summarize_validation(rows, policy)["agreed_validation_gate_passed"] is False
    rows[0]["candidate"] = 0.4
    rows[1]["candidate"] = 0.4
    summary = calibration.summarize_validation(rows, policy)
    assert summary["agreed_validation_gate_passed"] is False
    assert summary["exploratory_validation_threshold"]["metrics"]["recall"] == 1
    assert calibration.summarize_validation([], policy)["agreed_validation_gate_passed"] is False


def test_exploratory_threshold_respects_owner_false_alert_budget():
    rows = [
        {"label": 1, "baseline": 0.2, "candidate": 0.3},
        {"label": 1, "baseline": 0.2, "candidate": 0.6},
        {"label": 0, "baseline": 0.2, "candidate": 0.4},
        {"label": 0, "baseline": 0.2, "candidate": 0.1},
    ]
    strict = calibration.summarize_validation(
        rows, {"name": "recall_no_extra_alerts", "extra_false_alerts": 0}
    )
    relaxed = calibration.summarize_validation(
        rows, {"name": "recall_with_alert_budget", "extra_false_alerts": 1}
    )
    assert strict["exploratory_validation_threshold"]["metrics"]["recall"] == 0.5
    assert relaxed["exploratory_validation_threshold"]["metrics"]["recall"] == 1


def test_validation_execution_never_trains_or_predicts_on_final_or_unknown_examples(
    tmp_path, monkeypatch
):
    root, manifest, labels = test_supervised_tuning.reviewed.__wrapped__(tmp_path)
    labels["decisions"][manifest["records"][12]["id"]]["label"] = "unknown"
    manifest_hash, labels_hash = test_supervised_tuning.freeze(root, labels)
    candidate = root / "candidate"
    candidate.mkdir()
    (candidate / "candidate-manifest.json").write_text('{"synthetic": true}')
    candidate_hash = hashlib.sha256(
        (candidate / "candidate-manifest.json").read_bytes()
    ).hexdigest()
    (candidate / "training-provenance.json").write_text(
        json.dumps(
            {
                "complete": True,
                "manifest_sha256": manifest_hash,
                "reviewed_labels_sha256": labels_hash,
                "candidate_manifest_sha256": candidate_hash,
            }
        )
    )
    consumed = []

    class Baseline:
        def __init__(self, *args):
            self.manifest = {"files": {}}

        def assess(self, evidence):
            index = int(evidence.body_text.rsplit(" ", 1)[-1])
            consumed.append(index)
            return SimpleNamespace(overall_scam=0.1)

    class Candidate(Baseline):
        def assess(self, evidence):
            index = int(evidence.body_text.rsplit(" ", 1)[-1])
            consumed.append(index)
            return SimpleNamespace(overall_scam=0.8 if index % 2 == 0 else 0.1)

    monkeypatch.setattr(calibration, "LayaAdapter", Baseline)
    monkeypatch.setattr(calibration, "OfflineCandidate", Candidate)
    monkeypatch.setattr(calibration, "verify_checkpoint", lambda path: {"files": {}})
    report = calibration.evaluate_validation(
        root, manifest_hash, labels_hash, candidate, candidate_hash, root / "base", root / "output"
    )
    assert consumed == list(range(13, 24)) * 2
    assert report["complete"] and report["final_test_evaluated"] is False
    assert report["summary"]["agreed_validation_gate_passed"] is True
