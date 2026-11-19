import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from bad_email_check.label_review import create_review_app
from bad_email_check.specialization_data import BASELINE_MANIFEST_SHA256, validate

HEADERS = {"X-Email-Checker-Request": "1"}


@pytest.fixture
def cohort(tmp_path):
    rows = []
    for index in range(48):
        raw = (
            "From: synthetic@example.org\nSubject: Literal <img onerror=alert(1)>\n\n"
            f"Synthetic body {index}"
        ).encode()
        path = f"item-{index}.eml"
        (tmp_path / path).write_bytes(raw)
        rows.append(
            {
                "id": hashlib.sha256(str(index).encode()).hexdigest(),
                "split": "train" if index < 12 else "validation" if index < 24 else "final_test",
                "source": "hidden-source",
                "label": index % 2,
                "source_row": index,
                "group_id": str(index),
                "path": path,
                "bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
    manifest = {
        "dataset_version": "email-specialization-v1",
        "baseline_manifest_sha256": BASELINE_MANIFEST_SHA256,
        "excluded_baseline_ids": [],
        "excluded_baseline_groups": [],
        "records": rows,
    }
    (tmp_path / "manifest.json").write_bytes(json.dumps(manifest).encode())
    return tmp_path, manifest


def test_review_is_blinded_and_never_saves_content(cohort):
    root, manifest = cohort
    with TestClient(create_review_app(root), base_url="http://127.0.0.1:8010") as client:
        item = client.get("/api/review/item/0").json()
        assert item["subject"] == "Literal <img onerror=alert(1)>"
        assert set(item).isdisjoint({"label", "source", "split", "source_row", "path", "score"})
        assert item["previous_label"] is None
        response = client.post(
            "/api/review/decision",
            json={"item_id": item["id"], "label": "unknown", "reviewed_by_owner": True},
            headers=HEADERS,
        )
        assert response.status_code == 200 and response.json()["reviewed"] == 1
    saved = (root / "reviewed-labels.json").read_text()
    assert "Synthetic body" not in saved and "synthetic@example.org" not in saved
    assert json.loads(saved)["decisions"][manifest["records"][0]["id"]]["label"] == "unknown"
    with TestClient(create_review_app(root), base_url="http://127.0.0.1:8010") as client:
        assert client.get("/api/review/item/0").json()["previous_label"] == "unknown"


def test_finalize_requires_all_reviews_and_explicit_agreement_then_freezes(cohort):
    root, manifest = cohort
    with TestClient(create_review_app(root), base_url="http://127.0.0.1:8010") as client:
        payload = {"policy": "recall_no_extra_alerts", "agree": True}
        assert client.post("/api/review/finalize", json=payload, headers=HEADERS).status_code == 409
        for row in manifest["records"]:
            assert (
                client.post(
                    "/api/review/decision",
                    json={"item_id": row["id"], "label": "unknown", "reviewed_by_owner": True},
                    headers=HEADERS,
                ).status_code
                == 200
            )
        assert (
            client.post(
                "/api/review/finalize", json={**payload, "agree": False}, headers=HEADERS
            ).status_code
            == 422
        )
        response = client.post("/api/review/finalize", json=payload, headers=HEADERS)
        assert response.json()["finalized"] and response.json()["policy"]["agreed_by_owner"]
        assert (
            client.post(
                "/api/review/decision",
                json={"item_id": row["id"], "label": "scam", "reviewed_by_owner": True},
                headers=HEADERS,
            ).status_code
            == 409
        )


def test_failed_save_does_not_change_in_memory_review_state(cohort, monkeypatch):
    root, manifest = cohort
    app = create_review_app(root)
    original = type(root).write_bytes

    def fail(path, data):
        if path.name == "reviewed-labels.tmp":
            raise OSError("Synthetic private filesystem detail")
        return original(path, data)

    with TestClient(app, base_url="http://127.0.0.1:8010") as client:
        monkeypatch.setattr(type(root), "write_bytes", fail)
        response = client.post(
            "/api/review/decision",
            json={
                "item_id": manifest["records"][0]["id"],
                "label": "scam",
                "reviewed_by_owner": True,
            },
            headers=HEADERS,
        )
        assert response.status_code == 503 and "private filesystem" not in response.text
        assert client.get("/api/review/status").json()["reviewed"] == 0


def test_attestation_and_local_origin_are_required(cohort):
    root, manifest = cohort
    with TestClient(create_review_app(root), base_url="http://127.0.0.1:8010") as client:
        payload = {
            "item_id": manifest["records"][0]["id"],
            "label": "legitimate",
            "reviewed_by_owner": 1,
        }
        assert client.post("/api/review/decision", json=payload, headers=HEADERS).status_code == 422
        assert (
            client.post(
                "/api/review/decision",
                json={**payload, "reviewed_by_owner": True},
                headers={"Origin": "https://attacker.example"},
            ).status_code
            == 403
        )


def test_fresh_final_test_rejects_prior_baseline_group(cohort):
    root, manifest = cohort
    manifest["excluded_baseline_groups"] = [manifest["records"][-1]["group_id"]]
    (root / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="Final test overlaps"):
        validate(root)


def test_p7_2_f1_only_one_writer_and_stale_app_cannot_erase_frozen_review(cohort):
    root, manifest = cohort
    first_app = create_review_app(root)
    stale_app = create_review_app(root)
    with TestClient(first_app, base_url="http://127.0.0.1:8010") as first:
        with pytest.raises(ValueError, match="Another label-review writer"):
            with TestClient(stale_app, base_url="http://127.0.0.1:8010"):
                pass
        for row in manifest["records"]:
            first.post(
                "/api/review/decision",
                json={"item_id": row["id"], "label": "unknown", "reviewed_by_owner": True},
                headers=HEADERS,
            )
        assert (
            first.post(
                "/api/review/finalize",
                json={"policy": "recall_no_extra_alerts", "agree": True},
                headers=HEADERS,
            ).status_code
            == 200
        )
        frozen = (root / "reviewed-labels.json").read_bytes()
    with TestClient(stale_app, base_url="http://127.0.0.1:8010") as stale:
        response = stale.post(
            "/api/review/decision",
            json={"item_id": row["id"], "label": "scam", "reviewed_by_owner": True},
            headers=HEADERS,
        )
        assert response.status_code == 409
        assert stale.get("/api/review/status").json()["reviewed"] == 48
    assert (root / "reviewed-labels.json").read_bytes() == frozen
