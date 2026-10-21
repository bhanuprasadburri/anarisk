"""Score an independently collected, explicitly labeled email CSV offline."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.metrics import (average_precision_score, confusion_matrix, f1_score,
                             precision_score, recall_score, roc_auc_score)

from email_model import MAX_RAW_EMAIL_CHARS, FEATURE_SCHEMA, _load_artifact, normalize_email_text


def _validate_label_map(label_map: dict[str, int]) -> None:
    if not isinstance(label_map, dict) or len(label_map) < 2:
        raise ValueError("Label mapping must be an object with at least two raw labels")
    if any(not isinstance(key, str) or not key.strip() for key in label_map):
        raise ValueError("Every raw label mapping key must be a nonempty string")
    if any(type(value) is not int or value not in (0, 1) for value in label_map.values()):
        raise ValueError("Mapped labels must be integer 0 or 1")
    if set(label_map.values()) != {0, 1}:
        raise ValueError("Label mapping must map at least one label to each of 0 and 1")


def _metrics(y_true: list[int], scores: np.ndarray, threshold: float) -> dict[str, Any]:
    predicted = scores >= threshold
    matrix = confusion_matrix(y_true, predicted, labels=[0, 1])
    tn, fp, fn, _tp = (int(value) for value in matrix.ravel())
    both_classes = len(set(y_true)) == 2
    return {
        "rows": len(y_true),
        "precision": float(precision_score(y_true, predicted, zero_division=0)),
        "recall": float(recall_score(y_true, predicted, zero_division=0)),
        "f1": float(f1_score(y_true, predicted, zero_division=0)),
        "confusion_matrix_labels_0_1": matrix.tolist(),
        "false_positive_rate": fp / (fp + tn) if fp + tn else None,
        "false_negatives": fn,
        "average_precision": float(average_precision_score(y_true, scores)) if 1 in y_true else None,
        "roc_auc": float(roc_auc_score(y_true, scores)) if both_classes else None,
    }


def evaluate_dataset(
    dataset_path: Path,
    artifact_path: Path,
    *,
    label_map: dict[str, int],
    target_type: str,
    negative_label_meaning: str,
    positive_label_meaning: str,
    report_path: Path,
    text_column: str = "email_text",
    label_column: str = "label",
    source_column: str | None = None,
) -> dict[str, Any]:
    """Evaluate fixed model/threshold. Any malformed or unlabeled row aborts evaluation."""
    _validate_label_map(label_map)
    if target_type not in {"spam", "phishing", "mixed_spam_phishing"}:
        raise ValueError("target_type must be spam, phishing, or mixed_spam_phishing")
    if not negative_label_meaning.strip() or not positive_label_meaning.strip():
        raise ValueError("Document the meaning of both negative and positive labels")
    if text_column == label_column or (source_column and source_column in {text_column, label_column}):
        raise ValueError("Text, label, and source columns must be distinct")

    dataset_path = dataset_path.resolve()
    artifact_path = artifact_path.resolve()
    report_path = report_path.resolve()
    if report_path in {dataset_path, artifact_path}:
        raise ValueError("Report path must differ from dataset and model artifact")
    if report_path.exists():
        raise FileExistsError(f"Refusing to overwrite evaluation report: {report_path}")
    digest = hashlib.sha256()
    with dataset_path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    dataset_hash = digest.hexdigest()

    csv.field_size_limit(MAX_RAW_EMAIL_CHARS + 1)
    texts: list[str] = []
    labels: list[int] = []
    source_values: list[str] = []
    truncated_count = 0
    with dataset_path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        header = reader.fieldnames
        if not header or len(set(header)) != len(header):
            raise ValueError("CSV must have a unique header row")
        required = {text_column, label_column}
        if source_column:
            required.add(source_column)
        if not required.issubset(header):
            raise ValueError(f"CSV is missing required columns: {sorted(required - set(header))}")

        for row_number, row in enumerate(reader, start=2):
            if None in row or any(row.get(column) is None for column in required):
                raise ValueError(f"Malformed CSV row {row_number}: missing or extra fields")
            raw_text = row[text_column]
            if not isinstance(raw_text, str) or not raw_text.strip() or len(raw_text) > MAX_RAW_EMAIL_CHARS:
                raise ValueError(f"Malformed email text at CSV row {row_number}")
            raw_label = row[label_column].strip()
            if not raw_label:
                raise ValueError(f"Missing label at CSV row {row_number}")
            if raw_label not in label_map:
                raise ValueError(f"Unmapped label at CSV row {row_number}")
            normalized, truncated = normalize_email_text(raw_text)
            if not normalized:
                raise ValueError(f"Email text is empty after preprocessing at CSV row {row_number}")
            texts.append(normalized)
            labels.append(label_map[raw_label])
            truncated_count += int(truncated)
            if source_column:
                source = row[source_column].strip()
                if not source:
                    raise ValueError(f"Missing source value at CSV row {row_number}")
                source_values.append(source)

    if not labels:
        raise ValueError("Evaluation CSV contains no data rows")
    stat = artifact_path.stat()
    bundle = _load_artifact(str(artifact_path), stat.st_mtime_ns, stat.st_size)
    metadata = bundle["metadata"]
    threshold = float(metadata["threshold_selection"]["selected_threshold"])
    scores = np.asarray(bundle["model"].predict_proba(texts)[:, 1], dtype=float)
    if len(scores) != len(labels) or not np.isfinite(scores).all() or ((scores < 0) | (scores > 1)).any():
        raise ValueError("Artifact returned malformed prediction scores")

    report: dict[str, Any] = {
        "evaluation_type": "independent_external_dataset_fixed_model_evaluation",
        "evaluated_at_utc": datetime.now(UTC).isoformat(),
        "dataset_file": dataset_path.name,
        "dataset_sha256": dataset_hash,
        "dataset_rows": len(labels),
        "model_version": metadata["model_version"],
        "model_artifact_sha256": hashlib.sha256(artifact_path.read_bytes()).hexdigest(),
        "feature_schema": FEATURE_SCHEMA,
        "preprocessing_from_artifact_metadata": metadata.get("preprocessing"),
        "target_type": target_type,
        "label_mapping_raw_to_binary": label_map,
        "label_meanings": {"0": negative_label_meaning, "1": positive_label_meaning},
        "decision_threshold_from_saved_validation_metadata": threshold,
        "threshold_tuned_on_evaluation_data": False,
        "model_fitted_on_evaluation_data": False,
        "input_truncated_rows": truncated_count,
        "metrics": _metrics(labels, scores, threshold),
        "source_column": source_column,
        "limitations": [
            "Metrics describe the documented target labels only; spam labels do not establish phishing labels.",
            "This command uses the saved model and threshold unchanged and does not train or tune on evaluation data.",
            "Independent interpretation depends on the evaluator's source, collection-time, and labeling documentation.",
        ],
    }
    if source_column:
        grouped_indices: dict[str, list[int]] = defaultdict(list)
        for index, source in enumerate(source_values):
            source_hash = hashlib.sha256(source.encode("utf-8", "replace")).hexdigest()[:16]
            grouped_indices[source_hash].append(index)
        report["metrics_by_source_hash"] = {
            source_hash: _metrics([labels[i] for i in indices], scores[indices], threshold)
            for source_hash, indices in sorted(grouped_indices.items())
        }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--label-map", required=True, help='JSON object, e.g. "{\"legitimate\":0,\"phishing\":1}"')
    parser.add_argument("--target-type", choices=["spam", "phishing", "mixed_spam_phishing"], required=True)
    parser.add_argument("--negative-label-meaning", required=True)
    parser.add_argument("--positive-label-meaning", required=True)
    parser.add_argument("--text-column", default="email_text")
    parser.add_argument("--label-column", default="label")
    parser.add_argument("--source-column")
    args = parser.parse_args()
    try:
        label_map = json.loads(args.label_map)
        if not isinstance(label_map, dict):
            raise ValueError("--label-map must decode to a JSON object")
        report = evaluate_dataset(
            args.dataset, args.artifact, label_map=label_map, target_type=args.target_type,
            negative_label_meaning=args.negative_label_meaning,
            positive_label_meaning=args.positive_label_meaning, report_path=args.report,
            text_column=args.text_column, label_column=args.label_column, source_column=args.source_column,
        )
    except (json.JSONDecodeError, ValueError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
