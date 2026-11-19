import copy
import hashlib
import json
from urllib.parse import urlsplit

import pytest

from bad_email_check import evaluation_dataset as dataset


def test_related_templates_senders_and_threads_share_transitive_split():
    rows = [
        {"id": "a", "body": "Invoice 123 at https://one.example/a", "sender": "one@example.org"},
        {"id": "b", "body": "Invoice 456 at https://two.example/b", "sender": "two@example.org"},
        {
            "id": "c",
            "body": "Different billing discussion",
            "sender": "two@example.org",
            "subject": "Re: Your account update",
        },
        {
            "id": "d",
            "body": "Different security discussion",
            "sender": "three@example.org",
            "subject": "Your account update",
        },
    ]
    result = dataset.grouped_splits(copy.deepcopy(rows))
    assert len({row["group_id"] for row in result}) == 1
    assert len({row["split"] for row in result}) == 1
    assert result == dataset.grouped_splits(copy.deepcopy(rows))


def test_redaction_preserves_valid_reserved_url_destinations():
    text = (
        "Contact person@private.invalid at https://one.invalid/123?token=456 "
        "or https://two.invalid/789. Account 123456."
    )
    result = dataset.redact(text)
    assert "person@private.invalid" not in result and "123456" not in result
    urls = dataset.URL.findall(result)
    assert len(urls) == 2
    hosts = [urlsplit(url).hostname for url in urls]
    assert all(host.endswith(".example") for host in hosts) and hosts[0] != hosts[1]


def test_manifest_hash_path_and_group_integrity(tmp_path):
    record = {
        "id": "one",
        "path": "one.eml",
        "label": 0,
        "split": "train",
        "group_id": "group",
        "bytes": 3,
        "sha256": hashlib.sha256(b"one").hexdigest(),
    }
    (tmp_path / "one.eml").write_bytes(b"one")
    manifest = {"dataset_version": "email-baseline-v1", "records": [record]}
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    assert dataset.validate_dataset(tmp_path) == manifest
    (tmp_path / "one.eml").write_bytes(b"bad")
    with pytest.raises(ValueError, match="checksum"):
        dataset.validate_dataset(tmp_path)
    (tmp_path / "one.eml").write_bytes(b"one")
    (tmp_path / "two.eml").write_bytes(b"two")
    manifest["records"].append(
        {
            **record,
            "id": "two",
            "path": "two.eml",
            "split": "test",
            "sha256": hashlib.sha256(b"two").hexdigest(),
        }
    )
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="leakage"):
        dataset.validate_dataset(tmp_path)
    manifest["records"] = [{**record, "path": "../outside.eml"}]
    (tmp_path.parent / "outside.eml").write_bytes(b"one")
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        dataset.validate_dataset(tmp_path)


def test_existing_source_is_not_overwritten_or_deleted(tmp_path, monkeypatch):
    path = tmp_path / "source.csv"
    path.write_bytes(b"original")
    monkeypatch.setattr(dataset, "SOURCES", {"source.csv": {"size": 8, "sha256": "invalid"}})
    with pytest.raises(ValueError, match="Existing public source"):
        dataset.download_sources(tmp_path)
    assert path.read_bytes() == b"original"


def test_balanced_builder_is_deterministic_and_keeps_content_out_of_manifest(tmp_path, monkeypatch):
    rows = []
    for split, limit in (("train", 6), ("validation", 6), ("test", 12)):
        for label in (0, 1):
            for index in range(limit):
                identity = dataset.digest(f"{split}:{label}:{index}")
                rows.append(
                    {
                        "id": identity,
                        "source": "synthetic-public-proxy",
                        "source_row": index,
                        "label": label,
                        "body": "PRIVATE_SOURCE_BODY "
                        + split
                        + (" scam " if label else " legitimate ")
                        + chr(97 + index) * 5,
                        "subject": "Example",
                        "sender": "unused@example.org",
                        "group_id": identity,
                        "split": split,
                    }
                )
    monkeypatch.setattr(dataset, "public_records", lambda _: copy.deepcopy(rows))
    one, two = tmp_path / "one", tmp_path / "two"
    manifest = dataset.build_dataset(tmp_path, one)
    dataset.build_dataset(tmp_path, two)
    assert dataset.validate_dataset(one) == manifest
    assert len(manifest["records"]) == 58
    assert (one / "manifest.json").read_bytes() == (two / "manifest.json").read_bytes()
    assert b"PRIVATE_SOURCE_BODY" not in (one / "manifest.json").read_bytes()
