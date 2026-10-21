from __future__ import annotations

import csv
import hashlib
import json

import pytest

from scripts.ml.url_dataset import prepare
from scripts.ml.prepare_local_dataset import prepare as prepare_local
from scripts.ml.train_local_url_model import _domain_split, train
from scripts.ml.prepare_parquet_url_dataset import prepare as prepare_parquet_pair
from app.services.url_model_features import group_key
from app.services.url_model import predict_url


REVISION = "a" * 40


def _write_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=["url", "label", "date"])
        writer.writeheader()
        writer.writerows(rows)


def test_prepare_maps_only_documented_labels_and_preserves_source(tmp_path):
    source = tmp_path / "source.csv"
    output = tmp_path / "prepared.csv"
    _write_csv(source, [
        {"url": "https://bad.example/login", "label": "phish", "date": "2026-01-01"},
        {"url": "https://good.example/", "label": "benign", "date": "2026-01-02"},
        {"url": "https://unknown.example/", "label": "unknown", "date": "2026-01-03"},
    ])
    original = source.read_bytes()

    report = prepare(source, output, "train", REVISION, None)

    with output.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    assert [(row["url"], row["label"]) for row in rows] == [
        ("https://bad.example/login", "1"),
        ("https://good.example/", "0"),
    ]
    assert rows[0]["source_split"] == "train"
    assert report["unknown_label_rows"] == 1
    assert report["rows_by_label"] == {"phish": 1, "benign": 1}
    assert source.read_bytes() == original
    assert report["input_sha256"] == hashlib.sha256(original).hexdigest()
    manifest = json.loads(output.with_suffix(".csv.manifest.json").read_text(encoding="utf-8"))
    assert manifest["output_sha256"] == report["output_sha256"]


def test_prepare_excludes_invalid_urls_and_exact_normalized_duplicates(tmp_path):
    source = tmp_path / "source.csv"
    output = tmp_path / "prepared.csv"
    _write_csv(source, [
        {"url": "HTTPS://Example.com/path#one", "label": "phish", "date": ""},
        {"url": "https://example.com/path#two", "label": "benign", "date": ""},
        {"url": "javascript:alert(1)", "label": "phish", "date": ""},
        {"url": "not a url\nhttps://example.com", "label": "benign", "date": ""},
    ])

    report = prepare(source, output, "train", REVISION, None)

    assert report["rows_written"] == 1
    assert report["duplicate_normalized_url_rows"] == 1
    assert report["invalid_rows"] == 2
    with output.open(newline="", encoding="utf-8") as stream:
        row = next(csv.DictReader(stream))
    assert row["url"] == "https://example.com/path"
    assert row["label"] == "1"  # first observed label is retained; conflict is surfaced as duplicate


def test_prepare_rejects_missing_input_same_input_output_and_unpinned_source(tmp_path):
    source = tmp_path / "source.csv"
    _write_csv(source, [{"url": "https://example.com", "label": "benign", "date": ""}])

    with pytest.raises(FileNotFoundError):
        prepare(tmp_path / "missing.csv", tmp_path / "out.csv", "train", REVISION, None)
    with pytest.raises(ValueError, match="different files"):
        prepare(source, source, "train", REVISION, None)
    with pytest.raises(ValueError, match="40-character"):
        prepare(source, tmp_path / "out.csv", "train", "unknown", None)


def test_local_dataset_preparation_preserves_categories_and_drops_conflicts(tmp_path):
    source = tmp_path / "local.csv"
    output = tmp_path / "prepared.csv"
    report_path = tmp_path / "quality.json"
    with source.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=["url", "type", "date"])
        writer.writeheader()
        writer.writerows([
        {"url": "https://phish.example/login", "type": "phishing", "date": ""},
        {"url": "https://bad.example/payload", "type": "malware", "date": ""},
        {"url": "https://safe.example/", "type": "benign", "date": ""},
        {"url": "https://example.test/path#first", "type": "defacement", "date": ""},
        {"url": "https://example.test/path#other", "type": "benign", "date": ""},
        {"url": "javascript:alert(1)", "type": "phishing", "date": ""},
        {"url": "https://ignored.example/", "type": "unknown", "date": ""},
        ])
    original = source.read_bytes()

    report = prepare_local(source, output, report_path)

    with output.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    assert {row["source_category"] for row in rows} == {"phishing", "malware", "benign"}
    assert {row["label"] for row in rows} == {"0", "1"}
    assert all((row["label"] == "0") == (row["source_category"] == "benign") for row in rows)
    assert report["source_category_counts"] == {"phishing": 2, "malware": 1, "benign": 2, "defacement": 1}
    assert report["conflicting_normalized_urls_excluded"] == 1
    assert report["malformed_url_rows"] == 1
    assert report["unknown_label_rows"] == 1
    assert report["dates_available"] is False
    assert source.read_bytes() == original


def test_local_model_split_keeps_registrable_domains_disjoint_and_is_repeatable():
    rows = [{"url": f"https://host-{i}.site-{i}.com/{i}", "label": i % 2,
             "category": "benign" if i % 2 == 0 else "phishing"} for i in range(1200)]
    first = _domain_split(rows, seed=91)
    second = _domain_split(rows, seed=91)
    assert first == second
    domains = {name: {group_key(row["url"]) for row in split} for name, split in first.items()}
    assert domains["train"].isdisjoint(domains["validation"])
    assert domains["train"].isdisjoint(domains["test"])
    assert domains["validation"].isdisjoint(domains["test"])
    assert sum(map(len, first.values())) == len(rows)


def test_small_training_run_writes_loadable_artifact_and_report(tmp_path):
    prepared = tmp_path / "prepared.csv"
    with prepared.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=["url", "label", "source_category", "original_label"])
        writer.writeheader()
        for i in range(800):
            malicious = i % 2 == 1
            host = f"sample-{i}.test{i}.com"
            path = "/secure/login/verify" if malicious else "/about/contact"
            writer.writerow({"url": f"https://{host}{path}?item={i}", "label": int(malicious),
                             "source_category": "phishing" if malicious else "benign",
                             "original_label": "phishing" if malicious else "benign"})
    artifact = tmp_path / "model.joblib"
    report = tmp_path / "evaluation.json"

    evaluation = train(prepared, artifact, report)
    prediction = predict_url("https://brand-new-domain.example/login", artifact)

    assert evaluation["split"]["test"]["rows"] > 0
    assert evaluation["test_metrics_at_selected_threshold"]["roc_auc"] >= 0.5
    assert artifact.is_file() and report.is_file()
    assert prediction["status"] == "scored"
    assert prediction["model_version"] == evaluation["model_version"]
    assert prediction["score_is_calibrated_probability"] is False


def test_parquet_pair_preserves_sources_maps_labels_and_reassigns_overlapping_domains(tmp_path):
    pa = pytest.importorskip("pyarrow")
    pq = pytest.importorskip("pyarrow.parquet")
    data_dir = tmp_path / "source"
    data_dir.mkdir()
    pq.write_table(pa.table({
        "url": ["https://shared.example/login", "https://duplicate.example/a#first",
                "https://same.example/path#first",
                "javascript:alert(1)"],
        "status": ["phishing", "legitimate", "legitimate", "phishing"],
        "web_traffic": [100, 200, 300, 350],
    }), data_dir / "Training.parquet")
    pq.write_table(pa.table({
        "url": ["https://shared.example/about", "https://duplicate.example/a#second",
                "https://duplicate.example/a#third", "https://same.example/path#second"],
        "status": ["legitimate", "legitimate", "phishing", "legitimate"],
        "web_traffic": [400, 500, 600, 700],
    }), data_dir / "Testing.parquet")

    output, report_path = tmp_path / "prepared.csv", tmp_path / "quality.json"
    report = prepare_parquet_pair(data_dir, output, report_path)

    with output.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    assert report["source_files"]["Training.parquet"]["rows"] == 4
    assert report["source_files"]["Testing.parquet"]["rows"] == 4
    assert report["normalized_duplicate_rows_removed"] == 3
    assert report["conflicting_normalized_urls_excluded"] == 1
    assert report["original_split_registrable_domain_overlap"] == 3
    assert report["original_splits_repartitioned"] is True
    assert report["ignored_non_url_columns"] == ["web_traffic"]
    assert any(row["source_files"] == "Training.parquet;Testing.parquet" for row in rows)
    assert all(row["label"] == ("1" if row["original_label"] == "phishing" else "0") for row in rows)
