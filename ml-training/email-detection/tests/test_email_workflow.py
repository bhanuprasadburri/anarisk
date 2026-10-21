from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import joblib
import pytest
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline

WORKFLOW_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKFLOW_DIR))

from email_model import FEATURE_SCHEMA, _load_artifact, normalize_email_text, predict_email  # noqa: E402
from prepare_dataset import grouped_split, load_dataset  # noqa: E402
from evaluate_external import _metrics, evaluate_dataset  # noqa: E402


def test_preprocessing_masks_addresses_links_and_limits_length():
    normalized, truncated = normalize_email_text(
        "Contact Alice@example.test at https://example.test/login from 192.0.2.1"
    )
    assert "Alice@example.test" not in normalized
    assert "https://example.test" not in normalized
    assert "192.0.2.1" not in normalized
    assert "emailaddress" in normalized and "urladdress" in normalized and "ipaddress" in normalized
    assert truncated is False

    clipped, truncated = normalize_email_text("x " * 110_000)
    assert len(clipped) == 200_000
    assert truncated is True


def test_preparation_deduplicates_exact_normalized_text_and_excludes_conflicting_labels(tmp_path):
    source = tmp_path / "mail.csv"
    rows = [
        ("Team update", "0"), ("  TEAM   UPDATE  ", "0"),
        ("Urgent account notice", "1"), ("Shared content", "0"),
        (" shared   CONTENT ", "1"), ("Ordinary note", "0"),
        ("Credential request", "1"),
    ]
    with source.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["text_combined", "label"])
        writer.writerows(rows)

    prepared, report = load_dataset(source, minimum_rows=0)

    assert len(prepared) == 4
    assert report["duplicate_normalized_text_rows_removed"] == 2
    assert report["conflicting_duplicate_text_groups_excluded"] == 1
    assert set(row["label"] for row in prepared) == {0, 1}
    assert all("shared content" != " ".join(row["text"].casefold().split()) for row in prepared)


def test_grouped_split_is_deterministic_and_has_no_message_hash_overlap():
    rows = [
        {"text": f"message {i}", "text_hash": f"hash-{i}", "label": i % 2}
        for i in range(300)
    ]
    first = grouped_split(rows, seed=17)
    second = grouped_split(rows, seed=17)
    assert first == second
    groups = {name: {row["text_hash"] for row in part} for name, part in first.items()}
    assert groups["train"].isdisjoint(groups["validation"])
    assert groups["train"].isdisjoint(groups["test"])
    assert groups["validation"].isdisjoint(groups["test"])


def test_inference_rejects_malformed_input_without_loading_artifact(tmp_path, monkeypatch):
    monkeypatch.setattr("email_model._load_artifact", lambda *_: (_ for _ in ()).throw(AssertionError()))
    artifact = tmp_path / "missing.joblib"
    assert predict_email(None, artifact)["status"] == "invalid_input"
    assert predict_email("   ", artifact)["status"] == "invalid_input"
    assert predict_email("x" * 5_000_001, artifact)["status"] == "invalid_input"
    assert predict_email("valid email body", artifact)["status"] == "unavailable"


def test_artifact_loading_and_prediction_use_saved_schema_and_threshold(tmp_path):
    artifact = tmp_path / "email.joblib"
    model = make_pipeline(TfidfVectorizer(), LogisticRegression(random_state=1))
    model.fit(["normal project update", "credential phishing alert"], [0, 1])
    metadata = {
        "feature_schema": FEATURE_SCHEMA,
        "model_version": "test-email-v1",
        "threshold_selection": {"selected_threshold": 0.5},
    }
    joblib.dump({"model": model, "metadata": metadata}, artifact)
    stat = artifact.stat()
    loaded = _load_artifact(str(artifact.resolve()), stat.st_mtime_ns, stat.st_size)
    assert loaded["metadata"]["feature_schema"] == FEATURE_SCHEMA
    prediction = predict_email("credential phishing alert", artifact)
    assert prediction["status"] == "scored"
    assert prediction["model_version"] == "test-email-v1"
    assert prediction["score_is_calibrated_probability"] is False


def test_artifact_loading_rejects_wrong_schema(tmp_path):
    artifact = tmp_path / "wrong-schema.joblib"
    joblib.dump({"model": object(), "metadata": {"feature_schema": "url-v1"}}, artifact)
    stat = artifact.stat()
    with pytest.raises(ValueError):
        _load_artifact(str(artifact.resolve()), stat.st_mtime_ns, stat.st_size)


def test_dataset_audit_report_contains_no_email_contents(tmp_path):
    from audit_dataset import audit

    source = tmp_path / "tiny.csv"
    with source.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["text_combined", "label"])
        writer.writerow(["sensitive message text", "0"])
        writer.writerow(["another private email", "1"])
    report_path = tmp_path / "audit.json"

    audit(source, report_path)

    serialized = report_path.read_text(encoding="utf-8")
    assert "sensitive message text" not in serialized
    assert "another private email" not in serialized
    assert json.loads(serialized)["message_contents_written_to_report"] is False


def _external_eval_artifact(path):
    model = make_pipeline(TfidfVectorizer(), LogisticRegression(random_state=1))
    model.fit(["routine agenda notes", "verify account credentials immediately"], [0, 1])
    metadata = {
        "feature_schema": FEATURE_SCHEMA,
        "model_version": "test-email-v1",
        "threshold_selection": {"selected_threshold": 0.5},
    }
    joblib.dump({"model": model, "metadata": metadata}, path)


def _write_external_csv(path, rows, header=("email_text", "label")):
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(header)
        writer.writerows(rows)


def _evaluate(path, artifact, report, **kwargs):
    return evaluate_dataset(
        path, artifact, label_map={"legit": 0, "phish": 1}, target_type="phishing",
        negative_label_meaning="Benign labeled message", positive_label_meaning="Confirmed phishing",
        report_path=report, **kwargs,
    )


def test_external_evaluator_rejects_invalid_schema_and_missing_labels(tmp_path):
    artifact = tmp_path / "model.joblib"
    _external_eval_artifact(artifact)
    invalid_schema = tmp_path / "bad-schema.csv"
    _write_external_csv(invalid_schema, [("ordinary", "legit")], header=("body", "class"))
    with pytest.raises(ValueError, match="missing required columns"):
        _evaluate(invalid_schema, artifact, tmp_path / "one.json")

    missing_label = tmp_path / "missing-label.csv"
    _write_external_csv(missing_label, [("ordinary", "")])
    with pytest.raises(ValueError, match="Missing label"):
        _evaluate(missing_label, artifact, tmp_path / "two.json")


def test_external_evaluator_rejects_unknown_labels_and_malformed_text(tmp_path):
    artifact = tmp_path / "model.joblib"
    _external_eval_artifact(artifact)
    unknown = tmp_path / "unknown-label.csv"
    _write_external_csv(unknown, [("ordinary", "spam")])
    with pytest.raises(ValueError, match="Unmapped label"):
        _evaluate(unknown, artifact, tmp_path / "unknown.json")

    malformed = tmp_path / "malformed.csv"
    _write_external_csv(malformed, [("   ", "legit")])
    with pytest.raises(ValueError, match="Malformed email text"):
        _evaluate(malformed, artifact, tmp_path / "malformed.json")


def test_external_evaluator_uses_shared_preprocessing_and_saved_threshold(tmp_path):
    artifact = tmp_path / "model.joblib"
    _external_eval_artifact(artifact)
    data = tmp_path / "external.csv"
    rows = [
        ("Please see https://example.test/info", "legit", "source-a"),
        ("Verify account credentials immediately", "phish", "source-b"),
    ]
    _write_external_csv(data, rows, header=("email_text", "label", "origin"))
    report = _evaluate(data, artifact, tmp_path / "evaluation.json", source_column="origin")

    bundle = joblib.load(artifact)
    normalized = [normalize_email_text(row[0])[0] for row in rows]
    expected_scores = bundle["model"].predict_proba(normalized)[:, 1]
    assert report["metrics"] == _metrics([0, 1], expected_scores, 0.5)
    assert report["decision_threshold_from_saved_validation_metadata"] == 0.5
    assert report["threshold_tuned_on_evaluation_data"] is False
    assert report["model_fitted_on_evaluation_data"] is False
    assert len(report["metrics_by_source_hash"]) == 2


def test_external_metrics_report_expected_confusion_and_single_class_auc(tmp_path):
    metrics = _metrics([0, 0, 1, 1], __import__("numpy").array([0.1, 0.8, 0.4, 0.9]), 0.5)
    assert metrics["confusion_matrix_labels_0_1"] == [[1, 1], [1, 1]]
    assert metrics["false_positive_rate"] == 0.5
    assert metrics["false_negatives"] == 1
    assert metrics["precision"] == 0.5
    assert metrics["recall"] == 0.5
    assert metrics["f1"] == 0.5
    single_class = _metrics([0, 0], __import__("numpy").array([0.1, 0.2]), 0.5)
    assert single_class["average_precision"] is None
    assert single_class["roc_auc"] is None
