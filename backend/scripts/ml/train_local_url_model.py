"""Train and evaluate the local dataset with domain-grouped character TF-IDF."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

from app.services.url_model_features import group_key

SEED = 20261021
FEATURE_SCHEMA = "char-tfidf-url-v1"
TARGET_VALIDATION_FPR = 0.01


def _checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _domain_split(rows: list[dict], seed: int = SEED) -> dict[str, list[dict]]:
    domains: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        domain = group_key(row["url"])
        if not domain:
            raise ValueError("A prepared URL has no usable domain grouping key")
        domains[domain].append(row)
    result = {"train": [], "validation": [], "test": []}
    for domain, items in domains.items():
        bucket = int.from_bytes(hashlib.sha256(f"{seed}:{domain}".encode()).digest()[:8], "big") % 100
        name = "train" if bucket < 70 else "validation" if bucket < 85 else "test"
        result[name].extend(items)
    return result


def _metrics(y_true, scores, threshold: float, metrics):
    import numpy as np
    from sklearn.metrics import (average_precision_score, confusion_matrix, f1_score,
                                 precision_score, recall_score, roc_auc_score)

    predictions = np.asarray(scores) >= threshold
    cm = confusion_matrix(y_true, predictions, labels=[0, 1])
    tn, fp, fn, tp = (int(v) for v in cm.ravel())
    return {
        "precision_by_class_0_1": [float(precision_score(y_true, predictions, pos_label=c, zero_division=0)) for c in (0, 1)],
        "recall_by_class_0_1": [float(recall_score(y_true, predictions, pos_label=c, zero_division=0)) for c in (0, 1)],
        "f1": float(f1_score(y_true, predictions, zero_division=0)),
        "confusion_matrix_labels_0_1": cm.tolist(),
        "false_positive_rate": fp / (fp + tn) if fp + tn else None,
        "false_negative_count": fn,
        "average_precision": float(average_precision_score(y_true, scores)),
        "roc_auc": float(roc_auc_score(y_true, scores)),
    }


def train(prepared_path: Path, artifact_path: Path, report_path: Path) -> dict:
    try:
        import joblib
        import numpy as np
        import sklearn
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.linear_model import LogisticRegression
        from sklearn.metrics import roc_curve
        from sklearn.pipeline import make_pipeline
    except ImportError as exc:
        raise RuntimeError("Install backend/requirements-ml.txt in a supported Python environment") from exc

    prepared_path = prepared_path.resolve()
    artifact_path = artifact_path.resolve()
    report_path = report_path.resolve()
    if not prepared_path.is_file():
        raise FileNotFoundError(prepared_path)
    if prepared_path in (artifact_path, report_path) or artifact_path == report_path:
        raise ValueError("Dataset, artifact, and report must be separate files")

    rows = []
    with prepared_path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {"url", "label", "source_category"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError(f"Prepared CSV must contain: {', '.join(sorted(required))}")
        for row in reader:
            if row["label"] not in {"0", "1"}:
                raise ValueError("Prepared CSV contains a label outside the documented binary target")
            rows.append({"url": row["url"], "label": int(row["label"]), "category": row["source_category"]})
    if len(rows) < 100 or len({row["label"] for row in rows}) != 2:
        raise ValueError("At least 100 rows and both binary classes are required")
    dataset_fingerprint = _checksum(prepared_path)
    category_by_label = {
        label: sorted({row["category"] for row in rows if row["label"] == label})
        for label in (0, 1)
    }
    model_version = f"anarisk-url-char-tfidf-0.1.0-research-{dataset_fingerprint[:8]}"

    splits = _domain_split(rows)
    split_domains = {name: {group_key(row["url"]) for row in items} for name, items in splits.items()}
    if any(not items or len({row["label"] for row in items}) != 2 for items in splits.values()):
        raise ValueError("A domain split is empty or lacks one class; gather more independently labeled domains")
    if (split_domains["train"] & split_domains["validation"] or split_domains["train"] & split_domains["test"]
            or split_domains["validation"] & split_domains["test"]):
        raise ValueError("Registrable-domain leakage detected across splits")

    model = make_pipeline(
        TfidfVectorizer(analyzer="char", ngram_range=(3, 5), min_df=2, max_features=300_000,
                        sublinear_tf=True, dtype=np.float32),
        LogisticRegression(max_iter=1000, class_weight="balanced", random_state=SEED, solver="liblinear"),
    )
    model.fit([r["url"] for r in splits["train"]], [r["label"] for r in splits["train"]])
    validation_scores = model.predict_proba([r["url"] for r in splits["validation"]])[:, 1]
    fpr, tpr, thresholds = roc_curve([r["label"] for r in splits["validation"]], validation_scores)
    eligible = [i for i, rate in enumerate(fpr) if rate <= TARGET_VALIDATION_FPR and np.isfinite(thresholds[i])]
    if not eligible:
        raise ValueError("Could not select a finite threshold at the validation false-positive target")
    best = max(eligible, key=lambda i: (tpr[i], thresholds[i]))
    threshold = float(thresholds[best])
    test_scores = model.predict_proba([r["url"] for r in splits["test"]])[:, 1]
    test_metrics = _metrics([r["label"] for r in splits["test"]], test_scores, threshold, None)

    split_report = {}
    for name, items in splits.items():
        split_report[name] = {
            "rows": len(items), "binary_label_counts": dict(Counter(str(r["label"]) for r in items)),
            "source_category_counts": dict(Counter(r["category"] for r in items)),
            "registrable_domain_groups": len(split_domains[name]),
        }
    report = {
        "model_name": "AnaRisk malicious URL character TF-IDF baseline",
        "model_version": model_version, "trained_at_utc": datetime.now(UTC).isoformat(),
        "dataset_file": prepared_path.name, "dataset_sha256": dataset_fingerprint,
        "dataset_rows": len(rows),
        "label_definitions": {str(label): categories[0] if len(categories) == 1 else categories
                              for label, categories in category_by_label.items()},
        "source_categories_preserved": True, "seed": SEED,
        "feature_schema": FEATURE_SCHEMA,
        "features": {"type": "character TF-IDF", "analyzer": "char", "ngram_range": [3, 5],
                     "min_df": 2, "max_features": 300000, "sublinear_tf": True},
        "classifier": {"type": "LogisticRegression", "max_iter": 1000, "class_weight": "balanced", "solver": "liblinear"},
        "dependencies": {"scikit_learn": sklearn.__version__, "joblib": joblib.__version__, "numpy": np.__version__},
        "split_method": "Deterministic SHA-256 registrable-domain group assignment: 70% train, 15% validation, 15% test by group hash; test held out until final evaluation.",
        "split": split_report,
        "threshold_selection": {"method": "maximum validation recall subject to the stated validation false-positive-rate target",
                                "target_validation_false_positive_rate": TARGET_VALIDATION_FPR,
                                "selected_threshold": threshold, "validation_metrics_at_threshold": _metrics(
                                    [r["label"] for r in splits["validation"]], validation_scores, threshold, None)},
        "test_metrics_at_selected_threshold": test_metrics,
        "score_is_calibrated_probability": False,
        "limitations": ["No timestamps are present, so temporal evaluation is unavailable.",
                        "Labels and license/provenance were not independently verified.",
                        "The registrable-domain helper uses a limited suffix list."]
                       + ([f"Binary prediction does not distinguish {', '.join(category_by_label[1])}."]
                          if len(category_by_label[1]) > 1 else [])
                       + ["This is an offline research baseline, not a production verdict."],
    }
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": model, "metadata": report}, artifact_path)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prepared", type=Path)
    parser.add_argument("--artifact", type=Path, default=Path("var/models/url-char-tfidf-v0.1.0-research.joblib"))
    parser.add_argument("--report", type=Path, default=Path("var/reports/url-char-tfidf-evaluation.json"))
    args = parser.parse_args()
    try:
        print(json.dumps(train(args.prepared, args.artifact, args.report), indent=2))
    except (OSError, ValueError, RuntimeError, csv.Error) as exc:
        print(f"training failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
