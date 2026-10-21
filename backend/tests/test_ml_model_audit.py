from __future__ import annotations

import json

from scripts.ml.audit_and_compare_url_model import _error_analysis


def test_error_report_aggregates_errors_without_exposing_urls():
    rows = [
        {"url": "https://a.example/login?x=%2F", "label": 1, "category": "phishing"},
        {"url": "http://b.example/page", "label": 1, "category": "malware"},
        {"url": "https://c.example/about", "label": 0, "category": "benign"},
        {"url": "http://d.example/a/b/c", "label": 0, "category": "benign"},
    ]

    report = _error_analysis(rows, [0.2, 0.8, 0.9, 0.1], 0.5)

    assert report["false_negative_count"] == 1
    assert report["false_positive_count"] == 1
    assert report["false_negatives_by_source_category"]["phishing"]["false_negatives"] == 1
    assert report["false_positives_by_source_category"] == {"benign": 1}
    assert report["aggregate_url_characteristics_by_true_class_and_error_status"]["malicious"]["error_rows"] == 1
    serialized = json.dumps(report)
    assert "a.example" not in serialized
    assert "login?x" not in serialized
    assert "b.example" not in serialized
