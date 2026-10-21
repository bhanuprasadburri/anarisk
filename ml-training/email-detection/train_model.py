"""Train/evaluate the isolated TF-IDF email-text research baseline."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import joblib
import numpy as np
import sklearn
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (average_precision_score, confusion_matrix, f1_score,
                             precision_score, recall_score, roc_auc_score, roc_curve)
from sklearn.pipeline import make_pipeline

from email_model import FEATURE_SCHEMA, MAX_EMAIL_CHARS
from prepare_dataset import SEED, grouped_split, load_dataset

LABEL_DEFINITIONS = {"0": "legitimate according to the source corpus", "1": "spam_or_phishing according to the source corpus"}
VALIDATION_FPR_TARGET = 0.01


def _metrics(y_true: list[int], scores: np.ndarray, threshold: float) -> dict:
    predicted = scores >= threshold
    cm = confusion_matrix(y_true, predicted, labels=[0, 1])
    tn, fp, fn, _tp = (int(x) for x in cm.ravel())
    return {
        "precision": float(precision_score(y_true, predicted, pos_label=1, zero_division=0)),
        "recall": float(recall_score(y_true, predicted, pos_label=1, zero_division=0)),
        "f1": float(f1_score(y_true, predicted, pos_label=1, zero_division=0)),
        "confusion_matrix_labels_0_1": cm.tolist(),
        "false_positive_rate": fp / (fp + tn) if fp + tn else None,
        "false_negatives": fn,
        "average_precision": float(average_precision_score(y_true, scores)),
        "roc_auc": float(roc_auc_score(y_true, scores)),
    }


def _select_threshold(y_true: list[int], scores: np.ndarray) -> float:
    fpr, tpr, thresholds = roc_curve(y_true, scores)
    eligible = [i for i, rate in enumerate(fpr) if rate <= VALIDATION_FPR_TARGET and np.isfinite(thresholds[i])]
    if not eligible:
        raise ValueError("No finite validation threshold meets the 1% false-positive target")
    best = max(eligible, key=lambda i: (tpr[i], thresholds[i]))
    return float(thresholds[best])


def train(dataset_path: Path, artifact_path: Path | None = None, report_path: Path | None = None) -> dict:
    dataset_path = dataset_path.resolve()
    if not dataset_path.is_file():
        raise FileNotFoundError(dataset_path)
    rows, quality = load_dataset(dataset_path)
    fingerprint = quality["input_sha256"]
    version_suffix = fingerprint[:8]
    workflow_dir = Path(__file__).resolve().parent
    artifact_path = (artifact_path or workflow_dir / f"models/email-tfidf-logreg-v0.1.0-research-{version_suffix}.joblib").resolve()
    report_path = (report_path or workflow_dir / f"reports/email-tfidf-logreg-v0.1.0-research-{version_suffix}-evaluation.json").resolve()
    if artifact_path in (dataset_path, report_path) or report_path == dataset_path:
        raise ValueError("Dataset, model artifact, and report paths must be different")
    if artifact_path.exists():
        raise FileExistsError(f"Refusing to overwrite versioned artifact: {artifact_path}")

    splits = grouped_split(rows, SEED)
    hashes = {name: {row["text_hash"] for row in part} for name, part in splits.items()}
    if any(hashes[a] & hashes[b] for a, b in (("train", "validation"), ("train", "test"), ("validation", "test"))):
        raise ValueError("Normalized duplicate-text group leakage detected")
    for name, part in splits.items():
        if not part or {row["label"] for row in part} != {0, 1}:
            raise ValueError(f"{name} split is empty or missing a label class")

    # The vectorizer is part of the fitted pipeline and sees training text only.
    model = make_pipeline(
        TfidfVectorizer(analyzer="word", ngram_range=(1, 2), min_df=2, max_df=0.99,
                        max_features=120_000, sublinear_tf=True, strip_accents="unicode", dtype=np.float32,
                        token_pattern=r"(?u)\b\w[\w'-]{1,}\b"),
        LogisticRegression(max_iter=1000, class_weight="balanced", solver="liblinear", random_state=SEED),
    )
    model.fit([row["text"] for row in splits["train"]], [row["label"] for row in splits["train"]])
    validation_rows = splits["validation"]
    validation_scores = model.predict_proba([row["text"] for row in validation_rows])[:, 1]
    threshold = _select_threshold([row["label"] for row in validation_rows], validation_scores)
    validation_metrics = _metrics([row["label"] for row in validation_rows], validation_scores, threshold)
    # Held-out test is scored after model and threshold selection; no test statistic affects either.
    test_rows = splits["test"]
    test_scores = model.predict_proba([row["text"] for row in test_rows])[:, 1]
    test_metrics = _metrics([row["label"] for row in test_rows], test_scores, threshold)

    report = {
        "model_name": "AnaRisk email text TF-IDF Logistic Regression research baseline",
        "model_version": f"anarisk-email-tfidf-logreg-0.1.0-research-{version_suffix}",
        "trained_at_utc": datetime.now(UTC).isoformat(),
        "dataset_file": dataset_path.name,
        "dataset_sha256": fingerprint,
        "dataset_prepared_sha256": quality["prepared_sha256"],
        "dataset_rows": quality["prepared_rows"],
        "dataset_quality": quality,
        "source": {
            "dataset_card": "https://www.kaggle.com/datasets/naserabdullahalam/phishing-email-dataset",
            "dataset_version_in_local_copy": None,
            "local_copy_provenance_verified": False,
            "reported_license": "CC BY-SA 4.0",
            "rights_limitation": "The local copy is not pinned to a source version/checksum; constituent corpora may have separate terms. Do not redistribute the artifact until rights and privacy review is complete.",
        },
        "label_definitions": LABEL_DEFINITIONS,
        "scope": "Text-only classification of the source dataset's combined spam/phishing positive class; not phishing-specific assurance.",
        "seed": SEED,
        "feature_schema": FEATURE_SCHEMA,
        "preprocessing": {
            "unicode_normalization": "NFKC", "email_address_masking": True, "url_masking": True,
            "ipv4_masking": True, "max_email_characters": MAX_EMAIL_CHARS,
            "fit_scope": "TF-IDF vocabulary and IDF are fit on training split only",
        },
        "features": {"type": "word TF-IDF", "ngram_range": [1, 2], "min_df": 2,
                     "max_df": 0.99, "max_features": 120000, "sublinear_tf": True,
                     "strip_accents": "unicode"},
        "classifier": {"type": "LogisticRegression", "max_iter": 1000, "class_weight": "balanced",
                       "solver": "liblinear", "random_state": SEED},
        "dependencies": {"scikit_learn": sklearn.__version__, "joblib": joblib.__version__, "numpy": np.__version__},
        "split_method": "Deterministic SHA-256 assignment by normalized full-message hash: 70% train, 15% validation, 15% test; exact duplicate messages are deduplicated and kept in one group.",
        "split": {name: {"rows": len(part), "label_counts": dict(Counter(str(row["label"]) for row in part)),
                         "normalized_text_groups": len(hashes[name])} for name, part in splits.items()},
        "threshold_selection": {"method": "maximum validation recall subject to validation false-positive rate <= 1%",
                                "validation_fpr_target": VALIDATION_FPR_TARGET,
                                "selected_threshold": threshold,
                                "validation_metrics_at_threshold": validation_metrics},
        "test_metrics_at_selected_threshold": test_metrics,
        "score_is_calibrated_probability": False,
        "limitations": [
            "The source combines spam and phishing examples; spam detection does not establish phishing detection.",
            "No sender, campaign, thread, source identifier, or dedicated timestamp columns are available; related and near-duplicate messages may cross splits.",
            "No temporal holdout is possible from structured date fields.",
            "Labels, local provenance, constituent-source rights, and personal-data handling are not independently verified.",
            "This offline artifact is research-only and is not integrated with AnaRisk or production decisions.",
        ],
    }
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": model, "metadata": report}, artifact_path)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    report["artifact_file"] = artifact_path.name
    report["report_file"] = report_path.name
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--artifact", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    print(json.dumps(train(args.dataset, args.artifact, args.report), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
