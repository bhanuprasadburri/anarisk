from __future__ import annotations

import csv
import sys
from pathlib import Path

import joblib
import pytest

from common import LABEL_MAP, digest, domain_group, metric_summary, select_threshold, split_name
from predict import predict
from prepare import _scan


class _StubModel:
    def predict_proba(self, rows):
        assert rows == ["https://example.com/a"]
        return [[0.8, 0.2]]


def test_confirmed_label_mapping_is_explicit():
    assert LABEL_MAP == {"0": 0, "1": 1}


def test_psl_groups_subdomains_under_same_registrable_domain():
    assert domain_group("https://a.example.co.uk/x") == domain_group("https://b.example.co.uk/y")
    assert domain_group("https://a.example.co.uk") != domain_group("https://a.other.co.uk")


def test_split_assignment_is_deterministic_and_domain_separated():
    domain_hashes = [digest(f"host{i}.example{i}.com") for i in range(300)]
    assignments = {key: split_name(key) for key in domain_hashes}
    assert assignments == {key: split_name(key) for key in domain_hashes}
    buckets = {name: {key for key, assigned in assignments.items() if assigned == name}
               for name in ("train", "validation", "test")}
    assert not buckets["train"] & buckets["validation"]
    assert not buckets["train"] & buckets["test"]
    assert not buckets["validation"] & buckets["test"]


def test_preparation_maps_labels_and_excludes_conflicts_without_url_leakage(tmp_path):
    source = tmp_path / "source.csv"
    output = tmp_path / "prepared.csv"
    rows = [
        {"url": "www.one-example.com/a", "label": "0"},
        {"url": "https://www.one-example.com/a", "label": "0"},
        {"url": "https://www.one-example.com/b", "label": "1"},
        {"url": "https://conflict-example.net/x", "label": "0"},
        {"url": "https://conflict-example.net/x", "label": "1"},
        {"url": "http://[::1", "label": "0"},
        {"url": "https://unknown-example.org", "label": "other"},
        {"url": "", "label": "1"},
    ]
    with source.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["url", "label"])
        writer.writeheader()
        writer.writerows(rows)

    report = _scan(source, "url", "label", output_path=output)
    assert report["input_rows"] == len(rows)
    assert report["normalized_conflicting_url_keys"] == 1
    assert report["unknown_label_rows"] == 1
    assert report["missing_url_rows"] == 1
    assert report["malformed_or_unsupported_url_rows"] == 1
    assert "conflict-example" not in (output.with_name("data-quality.json").read_text(encoding="utf-8"))
    with output.open("r", encoding="utf-8", newline="") as stream:
        prepared = list(csv.DictReader(stream))
    assert {int(row["label"]) for row in prepared} == {0, 1}
    assert len(prepared) == 2
    assert all("raw_url" not in row for row in prepared)


def test_threshold_is_selected_from_validation_only_and_respects_fpr():
    threshold, detail = select_threshold([0, 0, 1, 1], [0.05, 0.2, 0.3, 0.9], 0.01)
    assert threshold == pytest.approx(0.3)
    assert detail["validation_fpr_at_selected_threshold"] <= 0.01
    assert metric_summary([0, 0, 1, 1], [0.05, 0.2, 0.3, 0.9], threshold)[
        "confusion_matrix_true_rows_0_1_predicted_columns_0_1"
    ] == [[2, 0], [0, 2]]


def test_inference_rejects_empty_malformed_and_oversized_inputs(tmp_path):
    for value in ("", "https://", "x" * 25_001):
        with pytest.raises(ValueError):
            predict(value, tmp_path / "missing.joblib")


def test_inference_loads_research_artifact_and_emits_only_prediction_metadata(tmp_path):
    artifact = tmp_path / "model.joblib"
    joblib.dump({"model": _StubModel(), "metadata": {
        "feature_schema": "char-tfidf-url-v1",
        "model_version": "test-research-v1",
        "threshold_selection": {"selected_threshold": 0.5},
    }}, artifact)
    result = predict("HTTPS://Example.com/a#fragment", artifact)
    assert result == {
        "model_version": "test-research-v1",
        "score": 0.2,
        "score_is_calibrated_probability": False,
        "threshold": 0.5,
        "prediction": "benign",
    }

