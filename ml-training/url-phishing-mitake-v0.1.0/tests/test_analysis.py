from __future__ import annotations

import json
import csv
import hashlib
import sys
from pathlib import Path

import numpy as np
import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

from analyze_errors import (_feature_error_rates, _summarize_split, cluster_bootstrap,
                            exact_binomial_interval, metric_values, safe_features)
from benchmark_inference import benchmark, process_memory_mb
from common import split_name


def test_confusion_matrix_order_and_rate_denominators_are_explicit():
    result = metric_values(np.array([8, 2, 3, 7]))
    assert result["confusion_matrix_true_rows_benign_phishing_predicted_columns_benign_phishing"] == [[8, 2], [3, 7]]
    assert result["false_positive_denominator_benign"] == 10
    assert result["false_negative_denominator_phishing"] == 10
    assert result["false_positive_rate"] == 0.2
    assert result["false_negative_rate"] == 0.3
    assert result["specificity_denominator_benign"] == 10
    assert result["recall_denominator_phishing"] == 10
    assert result["f1_denominator"] == 19


def test_exact_binomial_interval_handles_empty_and_boundary_counts():
    assert exact_binomial_interval(0, 0) is None
    lower, upper = exact_binomial_interval(0, 10)
    assert lower == 0 and 0 < upper < 1


def test_feature_groups_are_aggregate_only_and_zero_class_denominator_is_null():
    raw_url = "https://private-host.example/path?secret=value#fragment"
    rows = [{"url": raw_url}]
    output = _feature_error_rates(rows, np.array([0.1]), np.array([1]), np.array([True]), {})
    serialized = json.dumps(output)
    assert "private-host" not in serialized and "secret=value" not in serialized
    group = output["query_string"]["yes"]
    assert group["support"] == 1
    assert group["phishing_support"] == 1
    assert group["benign_support"] == 0
    assert group["false_positive_rate"] is None
    assert group["false_negative_count"] == 0
    assert output["fragment"]["unavailable_after_normalization"]["support"] == 1
    assert _feature_error_rates([], np.array([]), np.array([]), np.array([]), {}) == {}


def test_safe_features_use_coarse_values_only_and_mark_fragment_unavailable():
    features = safe_features("http://192.0.2.9:8080/a/b?x=1", {})
    assert features["ip_literal_host"] == "yes"
    assert features["non_default_port"] == "yes"
    assert features["query_string"] == "yes"
    assert features["fragment"] == "unavailable_after_normalization"
    assert features["training_domain_frequency"] == "unseen_in_training"
    assert "192.0.2.9" not in json.dumps(features)


def test_domain_cluster_bootstrap_is_deterministic_and_resamples_group_counts():
    domains = np.array([[10, 0, 0, 0], [0, 10, 0, 0], [0, 0, 10, 0], [0, 0, 0, 10]])
    first = cluster_bootstrap(domains, seed=77, replicates=250)
    second = cluster_bootstrap(domains, seed=77, replicates=250)
    assert first == second
    assert first["false_positive_rate"] is not None
    # Cluster resampling yields variation because complete all-benign/all-phishing domains move together.
    assert first["false_positive_rate"][0] < first["false_positive_rate"][1]


def test_summary_uses_the_supplied_fixed_threshold_without_optimization():
    rows = [
        {"url": "https://one.example/a", "label": 0, "domain": "d1"},
        {"url": "https://two.example/b", "label": 1, "domain": "d2"},
    ]
    summary = _summarize_split(rows, np.array([0.7, 0.8]), 0.75, {}, seed=1, replicates=100)
    assert summary["threshold_fixed_from_training_validation"] == 0.75
    assert summary["confusion_matrix_true_rows_benign_phishing_predicted_columns_benign_phishing"] == [[1, 0], [0, 1]]
    assert summary["false_positive_count"] == 0


def test_memory_measurement_reports_process_scope_or_explicit_unsupported(monkeypatch):
    monkeypatch.setattr(sys, "platform", "plan9")
    result = process_memory_mb()
    assert result["current_working_set_mb"] is None
    assert result["peak_working_set_mb"] is None
    assert "unsupported" in result["method"]


def test_benchmark_loads_and_measures_a_fresh_worker_process(tmp_path):
    prepared = tmp_path / "prepared.csv"
    rows = []
    for i in range(20):
        url = f"https://host{i}.example/path{i}"
        group_hash = hashlib.sha256(f"group-{i}".encode()).hexdigest()
        if split_name(group_hash) == "test":
            rows.append({"url": url, "label": str(i % 2), "domain_group_hash": group_hash})
    with prepared.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["url", "label", "domain_group_hash"])
        writer.writeheader()
        writer.writerows(rows)
    model = Pipeline([
        ("tfidf", TfidfVectorizer(analyzer="char", ngram_range=(2, 3))),
        ("classifier", LogisticRegression()),
    ]).fit([f"https://train{i}.example/path{i}" for i in range(6)], [0, 1, 0, 1, 0, 1])
    artifact = tmp_path / "tiny.joblib"
    joblib.dump({"model": model, "metadata": {
        "feature_schema": "char-tfidf-url-v1", "model_version": "test-v1",
        "threshold_selection": {"selected_threshold": 0.5},
    }}, artifact)
    output = tmp_path / "latency.json"

    result = benchmark(prepared, artifact, output, sample_count=3)

    assert result["worker_exit_code"] == 0
    assert result["warm_single_url_latency_seconds"]["sample_count"] == min(3, len(rows))
    assert result["memory"]["baseline_before_model_load"]["method"]
    assert output.is_file() and output.with_suffix(".md").is_file()
    serialized = output.read_text(encoding="utf-8")
    assert "host" not in serialized
