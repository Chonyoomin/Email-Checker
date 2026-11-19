import hashlib
import json

import pytest

from bad_email_check.baseline import (
    checked_manifest,
    percentile,
    rates,
    summarize,
    uncertainty,
    wilson,
)
from bad_email_check.baseline_report import percentage, render


def test_abstention_never_becomes_a_negative_prediction_or_drops_from_recall():
    rows = [
        {"label": label, "predicted": predicted}
        for label, predicted in ((1, 1), (1, 0), (1, None), (0, 1), (0, 0), (0, None))
    ]
    result = rates(rows)
    assert (result["tp"], result["fn"], result["fp"], result["tn"]) == (1, 1, 1, 1)
    assert result["abstained_positive"] == result["abstained_negative"] == 1
    assert result["recall"] == result["false_positive_rate"] == 1 / 3
    assert result["precision"] == 0.5 and result["coverage"] == 2 / 3
    assert rates([])["precision"] is None


def test_percentiles_interpolate_and_wilson_keeps_boundary_uncertainty():
    assert percentile([40, 10, 20, 30], 0.5) == 25
    assert percentile([10, 20, 30, 40], 0.95) == pytest.approx(38.5)
    assert percentile([], 0.5) is None
    assert wilson(0, 12)[1] > 0 and wilson(12, 12)[0] < 1
    assert wilson(0, 0) is None


def test_uncertainty_resamples_groups_and_is_reproducible():
    rows = [
        {"group_id": group, "label": label, "predicted": predicted}
        for group, label, predicted in (
            ("one", 1, 1),
            ("one", 1, None),
            ("two", 0, 1),
            ("three", 0, 0),
        )
    ]
    result = uncertainty(rows, 100)
    assert result["groups"] == 3
    assert result == uncertainty(rows, 100)
    assert result["cluster_bootstrap"]["recall"]["valid_repetitions"] <= 100
    assert all(0 <= value <= 1 for value in result["cluster_bootstrap"]["coverage"]["interval"])


def test_frozen_manifest_hash_is_checked_before_loading_data(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"invalid": "No records must be loaded"}))
    with pytest.raises(ValueError, match="Frozen evaluation manifest hash"):
        checked_manifest(tmp_path, hashlib.sha256(b"different").hexdigest())


def test_report_separates_safety_cases_and_does_not_render_extra_content():
    rows = []
    for index, (source, label, prediction) in enumerate(
        (
            ("public", 1, 1),
            ("public", 1, 0),
            ("public", 0, 0),
            ("authored-safety-fixture", 0, 1),
            ("authored-safety-fixture", 1, 0),
        )
    ):
        rows.append(
            {
                "id": str(index),
                "group_id": str(index),
                "source": source,
                "label": label,
                "predicted": prediction,
                "status": "complete",
                "tags": [str(index)],
                "timings": {"inference_ms": 4000, "total_ms": 4001, "extraction_ms": 1},
                "runtime": {
                    "inference_phase": "first" if index == 0 else "warm",
                    "process_peak_rss_bytes": 100,
                    "model_tensor_bytes": 80,
                },
                "body": "DO_NOT_RENDER_EMAIL_CONTENT",
            }
        )
    summary = summarize(rows)
    assert summary["public"]["metrics"]["precision"] == 1
    assert summary["synthetic_safety"]["metrics"]["fp"] == 1
    report = {
        "complete": True,
        "summary": summary,
        "records": rows,
        "manifest_sha256": "a" * 64,
        "threshold": 0.5,
        "prediction_calls": 5,
        "network_attempts": 0,
        "model_identity": {
            "checkpoint_revision": "fixture",
            "adapter_version": "fixture",
            "question_set_version": "fixture",
        },
        "parser_version": "fixture",
        "context_tokens": 2048,
        "head_tokens": 192,
        "model_load_ms": 1000,
        "hardware": {
            "cpu": "fixture",
            "logical_cpus": 4,
            "os": "fixture",
            "os_release": "fixture",
            "architecture": "fixture",
            "python": "3.14",
            "torch": "fixture",
            "torch_threads": 4,
            "physical_ram_bytes": 1000,
        },
    }
    text = render(report)
    assert "DO_NOT_RENDER_EMAIL_CONTENT" not in text
    assert "NOT met" in text and "NOT cluster-correct" in text
    assert percentage(0) == "0.0%" and percentage(None) == "undefined"
    report["complete"] = False
    with pytest.raises(ValueError, match="partial run"):
        render(report)
