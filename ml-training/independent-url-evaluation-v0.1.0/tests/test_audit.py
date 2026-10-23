from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import audit


def test_timestamp_does_not_infer_missing_values():
    assert audit.parse_timestamp("") is None
    assert audit.parse_timestamp("not a date") is None
    assert audit.parse_timestamp("2024-01-02T03:04:05Z") == "2024-01-02T03:04:05+00:00"


def test_timestamp_columns_keep_event_and_scrape_ranges_separate():
    headers = ["url", "label", "event", "scraped"]
    rows = [{"url": "https://one.example/", "label": "p", "event": "2024-01-01", "scraped": "2024-02-01"},
            {"url": "https://two.example/", "label": "b", "event": "", "scraped": "2024-03-01"}]
    report, _ = audit.audit_table("dates", headers, rows, "url", "label", {"b": 0, "p": 1},
                                  timestamp_col=["event", "scraped"])
    assert report["timestamp_parse_counts"]["event"] == {"parsed": 1, "missing_or_invalid": 1}
    assert report["timestamp_ranges"]["event"] == ["2024-01-01T00:00:00", "2024-01-01T00:00:00"]
    assert report["timestamp_ranges"]["scraped"] == ["2024-02-01T00:00:00", "2024-03-01T00:00:00"]


def test_label_mapping_schema_duplicate_and_conflicts():
    headers = ["url", "label"]
    rows = [
        {"url": "https://example.com/a", "label": "phishing"},
        {"url": "https://example.com/a", "label": "benign"},
        {"url": "https://other.example/b", "label": "unknown"},
    ]
    report, details = audit.audit_table("toy", headers, rows, "url", "label", {"benign": 0, "phishing": 1})
    assert report["rows"] == 3
    assert report["normalized_url_duplicates_beyond_first"] == 1
    assert report["normalized_urls_with_conflicting_labels"] == 1
    assert report["invalid_or_ambiguous_label_rows"] == 1
    assert all("url" not in item for item in details["urls"])


def test_schema_rejects_missing_required_fields():
    report, _ = audit.audit_table("bad", ["href"], iter(()), "url", "label", {"0": 0})
    assert report["schema_valid"] is False
    assert set(report["missing_required_columns"]) == {"url", "label"}


def test_malformed_or_unsupported_url_is_counted_without_echoing_value():
    headers = ["url", "label"]
    rows = [{"url": "javascript:alert(1)", "label": "p"},
            {"url": "", "label": "p"}]
    report, _ = audit.audit_table("malformed", headers, rows, "url", "label", {"p": 1})
    assert report["invalid_or_unsupported_url_rows"] == 2
    assert "javascript:alert" not in json.dumps(report)


def test_compare_counts_url_and_domain_overlap_without_values():
    key = hashlib.sha256(b"url").hexdigest()
    a = {"urls": {key}, "domains": {"domainhash"}, "labels": {key: 1}}
    b = {"urls": {key}, "domains": {"domainhash", "another"}, "labels": {key: 0}}
    result = audit.compare(a, b)
    assert result["normalized_url_overlap"] == 1
    assert result["registrable_domain_overlap"] == 1
    assert result["conflicting_labels_on_overlapping_urls"] == 1
    assert key not in json.dumps(result)


def test_archive_rejects_path_traversal(tmp_path: Path):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("../outside.csv", "x,y\n1,2\n")
    with pytest.raises(ValueError, match="unsafe archive path"):
        audit.inspect_zip(archive)


def test_archive_manifest_verification_and_size(tmp_path: Path):
    archive = tmp_path / "safe.zip"
    data = b"a,b\n1,2\n"
    manifest = f"{hashlib.sha256(data).hexdigest()}  data.csv  ({len(data)} bytes)\n"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("data.csv", data)
        z.writestr("MANIFEST.txt", manifest)
    selected, meta = audit.inspect_zip(archive)
    assert selected["data.csv"] == data
    assert meta["all_manifest_checks_match"] is True


def test_normalizer_and_domain_group_are_deterministic():
    first = audit.normalize_url("HTTPS://Example.COM/path?q=1")
    second = audit.normalize_url("https://example.com/path?q=1")
    assert first == second
    assert audit.domain_group(first) == "example.com"


def test_partition_isolation_rejects_url_or_domain_leakage():
    good = {"train": [{"url_hash": "u1", "domain_hash": "d1"}],
            "validation": [{"url_hash": "u2", "domain_hash": "d2"}],
            "test": [{"url_hash": "u3", "domain_hash": "d3"}]}
    audit.validate_partition_isolation(good)
    bad = {**good, "test": [{"url_hash": "u3", "domain_hash": "d2"}]}
    with pytest.raises(ValueError, match="domain crosses"):
        audit.validate_partition_isolation(bad)


def test_manifest_payload_is_deterministic():
    candidates = {"one": {"sha256": "abc"}}
    records = {"one": {"version": "1"}}
    a = audit.deterministic_manifest(candidates, {"one": "local"}, "blocked", records)
    b = audit.deterministic_manifest(candidates, {"one": "local"}, "blocked", records)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_report_generator_does_not_serialize_raw_candidate_values(tmp_path: Path):
    csv_path = tmp_path / "toy.csv"
    csv_path.write_text("url,label\nhttps://private.example/secret?q=token,phishing\n", encoding="utf-8")
    headers, rows = audit.read_rows(path=csv_path)
    summary, _ = audit.audit_table("toy", headers, rows, "url", "label", {"phishing": 1})
    serialized = json.dumps(summary)
    assert "private.example" not in serialized
    assert "secret" not in serialized
    assert "token" not in serialized
