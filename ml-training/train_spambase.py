"""Train an offline UCI Spambase model with feature-grouped holdout evaluation."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

SEED = "anarisk-spambase-v1"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def feature_names(names_file: Path) -> list[str]:
    names = [line.split(":", 1)[0].strip() for line in names_file.read_text(encoding="utf-8", errors="replace").splitlines()
             if ":" in line and not line.lstrip().startswith("|")]
    if len(names) != 57 or len(set(names)) != 57:
        raise ValueError("spambase.names must define exactly 57 ordered features")
    return names


def split_key(row: list[float]) -> str:
    return hashlib.sha256((",".join(format(v, ".12g") for v in row)).encode()).hexdigest()


def metrics(y, scores, threshold):
    import numpy as np
    from sklearn.metrics import (average_precision_score, confusion_matrix, f1_score,
                                 precision_score, recall_score, roc_auc_score)
    predicted = np.asarray(scores) >= threshold
    tn, fp, fn, tp = (int(v) for v in confusion_matrix(y, predicted, labels=[0, 1]).ravel())
    return {"precision": float(precision_score(y, predicted, zero_division=0)),
            "recall": float(recall_score(y, predicted, zero_division=0)),
            "f1": float(f1_score(y, predicted, zero_division=0)),
            "confusion_matrix_labels_0_1": [[tn, fp], [fn, tp]],
            "false_positive_rate": fp / (fp + tn) if tn + fp else None,
            "false_negative_count": fn, "average_precision": float(average_precision_score(y, scores)),
            "roc_auc": float(roc_auc_score(y, scores))}


def train(data_path: Path, names_path: Path, artifact_path: Path, report_path: Path) -> dict:
    import joblib
    import numpy as np
    import sklearn
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    names = feature_names(names_path)
    rows, labels = [], []
    with data_path.open("r", encoding="utf-8-sig", newline="") as stream:
        for line_num, row in enumerate(csv.reader(stream), 1):
            if len(row) != 58:
                raise ValueError(f"Expected 58 values on row {line_num}")
            values = [float(v) for v in row]
            if not all(math.isfinite(v) for v in values) or values[-1] not in (0.0, 1.0):
                raise ValueError(f"Invalid numeric value or label on row {line_num}")
            rows.append(values[:-1]); labels.append(int(values[-1]))
    if len(rows) != 4601 or set(labels) != {0, 1}:
        raise ValueError("Local file does not match the documented 4601-row binary Spambase schema")

    # Exclude feature vectors with contradictory targets; group all other identical
    # vectors together so duplicates cannot leak across the evaluation partitions.
    buckets: dict[str, list[int]] = defaultdict(list)
    group_labels: dict[str, set[int]] = defaultdict(set)
    for i, (row, label) in enumerate(zip(rows, labels)):
        key = split_key(row)
        group_labels[key].add(label); buckets[key].append(i)
    conflicting_groups = {key for key, values in group_labels.items() if len(values) > 1}
    keep = [i for i, row in enumerate(rows) if split_key(row) not in conflicting_groups]
    rows = [rows[i] for i in keep]
    labels = [labels[i] for i in keep]
    buckets = defaultdict(list)
    for i, row in enumerate(rows):
        buckets[split_key(row)].append(i)
    splits = {"train": [], "validation": [], "test": []}
    for key, indices in buckets.items():
        slot = int(hashlib.sha256(f"{SEED}:{key}".encode()).hexdigest()[:8], 16) % 100
        name = "train" if slot < 70 else "validation" if slot < 85 else "test"
        splits[name].extend(indices)
    if any(not idx or len({labels[i] for i in idx}) != 2 for idx in splits.values()):
        raise ValueError("Feature-group split is empty or missing a class")

    model = make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000, class_weight="balanced", random_state=42))
    model.fit([rows[i] for i in splits["train"]], [labels[i] for i in splits["train"]])
    val_y = [labels[i] for i in splits["validation"]]
    val_scores = model.predict_proba([rows[i] for i in splits["validation"]])[:, 1]
    from sklearn.metrics import roc_curve
    fpr, tpr, thresholds = roc_curve(val_y, val_scores)
    eligible = [i for i, rate in enumerate(fpr) if rate <= 0.01 and np.isfinite(thresholds[i])]
    if not eligible:
        raise ValueError("No validation threshold meets FPR <= 1%")
    best = max(eligible, key=lambda i: (tpr[i], thresholds[i]))
    threshold = float(thresholds[best])
    val_metrics = metrics(val_y, val_scores, threshold)
    test_y = [labels[i] for i in splits["test"]]
    test_scores = model.predict_proba([rows[i] for i in splits["test"]])[:, 1]
    data_path, artifact_path, report_path = data_path.resolve(), artifact_path.resolve(), report_path.resolve()
    dataset_hash = sha256(data_path)
    metadata = {"model_name": "AnaRisk UCI Spambase Logistic Regression research baseline",
                "model_version": f"anarisk-spambase-logreg-v1-research-{dataset_hash[:8]}",
                "trained_at_utc": datetime.now(UTC).isoformat(), "feature_schema": "uci-spambase-57-v1",
                "feature_names": names, "label_definition": {"0": "non-spam", "1": "unsolicited commercial spam"},
                "dataset_sha256": dataset_hash, "rows": len(rows), "conflicting_feature_groups_excluded": len(conflicting_groups),
                "conflicting_feature_rows_excluded": sum(len(indices) for key, indices in group_labels.items()
                                                          if key in conflicting_groups),
                "exact_feature_groups": len(buckets),
                "split_counts": {key: {"rows": len(idx), "groups": len({split_key(rows[i]) for i in idx}),
                                        "labels": dict(Counter(str(labels[i]) for i in idx))}
                                 for key, idx in splits.items()},
                "split_method": "deterministic feature-vector SHA-256 group split 70/15/15",
                "selection": "maximum validation recall subject to validation FPR <= 1%",
                "threshold_selection": {"selected_threshold": threshold, "validation_metrics": val_metrics},
                "test_metrics": metrics(test_y, test_scores, threshold),
                "dependencies": {"scikit_learn": sklearn.__version__, "joblib": joblib.__version__, "numpy": np.__version__},
                "limitations": ["This is a spam target, not a phishing target.",
                                "Input requires the original 57 engineered features; raw messages cannot be scored directly.",
                                "Dataset is from 1999 and includes collection-specific indicators.",
                                "Threshold and score are research outputs, not production decisions."]}
    artifact_path.parent.mkdir(parents=True, exist_ok=True); report_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": model, "metadata": metadata}, artifact_path)
    report_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return metadata


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data", type=Path); parser.add_argument("names", type=Path)
    parser.add_argument("artifact", type=Path); parser.add_argument("report", type=Path)
    args = parser.parse_args()
    print(json.dumps(train(args.data, args.names, args.artifact, args.report), indent=2))
