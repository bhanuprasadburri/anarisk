"""Reproduce the saved URL-model evaluation, report aggregate errors, and compare a fixed NB baseline.

This audit never writes URL strings or hostnames to its reports. The saved test split is
reconstructed from the original deterministic domain assignment; thresholds are selected
using validation data only. Both models use the same split and URL text.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import ipaddress
import json
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from app.services.url_model_features import group_key
from scripts.ml.train_local_url_model import (
    SEED, TARGET_VALIDATION_FPR, _domain_split, _metrics,
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _choose_threshold(y_true, scores):
    import numpy as np
    from sklearn.metrics import roc_curve

    fpr, tpr, thresholds = roc_curve(y_true, scores)
    eligible = [i for i, rate in enumerate(fpr) if rate <= TARGET_VALIDATION_FPR and np.isfinite(thresholds[i])]
    if not eligible:
        raise ValueError("No finite validation threshold meets the configured false-positive-rate target")
    best = max(eligible, key=lambda i: (tpr[i], thresholds[i]))
    return float(thresholds[best])


def _shape(url: str) -> dict[str, str | bool]:
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    try:
        ipaddress.ip_address(host)
        ip_host = True
    except ValueError:
        ip_host = False
    length = len(url)
    path_depth = len([part for part in parsed.path.split("/") if part])
    return {
        "url_length": "<=50" if length <= 50 else "51-100" if length <= 100 else "101-200" if length <= 200 else ">200",
        "scheme_https": parsed.scheme.lower() == "https",
        "ip_host": ip_host,
        "punycode_host": "xn--" in host.lower(),
        "host_has_digits": any(c.isdigit() for c in host),
        "host_has_hyphen": "-" in host,
        "has_query": bool(parsed.query),
        "has_at_sign": "@" in url,
        "has_percent_encoding": "%" in url,
        "path_depth": "0" if path_depth == 0 else "1" if path_depth == 1 else "2-4" if path_depth <= 4 else "5+",
    }


def _error_analysis(test_rows: list[dict], scores, threshold: float) -> dict:
    import numpy as np

    predictions = np.asarray(scores) >= threshold
    by_category: dict[str, dict[str, int]] = defaultdict(lambda: {"rows": 0, "false_negatives": 0})
    false_positives_by_category: Counter[str] = Counter()
    class_outcomes: dict[str, Counter[str]] = defaultdict(Counter)
    groups: dict[str, dict[str, dict[str, int]]] = defaultdict(
        lambda: {"errors": defaultdict(int), "correct": defaultdict(int)}
    )
    for row, predicted in zip(test_rows, predictions, strict=True):
        truth = bool(row["label"])
        if truth:
            counts = by_category[row["category"]]
            counts["rows"] += 1
            counts["false_negatives"] += int(not predicted)
        elif predicted:
            false_positives_by_category[row["category"]] += 1
        error_name = "false_negative" if truth and not predicted else "false_positive" if predicted and not truth else None
        outcome = "errors" if error_name else "correct"
        class_name = "malicious" if truth else "benign"
        class_outcomes[class_name][outcome] += 1
        for feature, value in _shape(row["url"]).items():
            groups[class_name][outcome][f"{feature}={value}"] += 1

    comparison = {}
    for class_name, outcome_groups in groups.items():
        error_count = sum(outcome_groups["errors"].values())
        correct_count = sum(outcome_groups["correct"].values())
        # Each row contributes once per feature family; report prevalence within its true class.
        comparison[class_name] = {
            "error_rows": class_outcomes[class_name]["errors"],
            "correct_rows": class_outcomes[class_name]["correct"],
            "feature_prevalence": {},
        }
        for key in sorted(set(outcome_groups["errors"]) | set(outcome_groups["correct"])):
            comparison[class_name]["feature_prevalence"][key] = {
                "error_count": outcome_groups["errors"].get(key, 0),
                "error_rate_within_group": (
                    outcome_groups["errors"].get(key, 0)
                    / (outcome_groups["errors"].get(key, 0) + outcome_groups["correct"].get(key, 0))
                ),
                "correct_count": outcome_groups["correct"].get(key, 0),
            }

    # Dataset labels define the error cohorts; all feature counts remain aggregate-only.
    return {
        "test_rows": len(test_rows),
        "false_positive_count": int(sum(not bool(r["label"]) and p for r, p in zip(test_rows, predictions, strict=True))),
        "false_negative_count": int(sum(bool(r["label"]) and not p for r, p in zip(test_rows, predictions, strict=True))),
        "false_positives_by_source_category": dict(sorted(false_positives_by_category.items())),
        "false_negatives_by_source_category": {
            category: {**counts, "false_negative_rate": counts["false_negatives"] / counts["rows"] if counts["rows"] else None}
            for category, counts in sorted(by_category.items())
        },
        "aggregate_url_characteristics_by_true_class_and_error_status": comparison,
        "privacy": "No URL, hostname, registrable domain, or row-level identifier is included.",
        "caveat": "These are source-label errors on a domain-held-out split; unknown label accuracy and time-based freshness cannot be inferred.",
    }


def run(dataset_path: Path, cleaned_path: Path, artifact_path: Path, evaluation_path: Path,
        quality_path: Path, error_report_path: Path, comparison_path: Path,
        candidate_artifact_path: Path) -> dict:
    import joblib
    import numpy as np
    import sklearn
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.naive_bayes import MultinomialNB
    from sklearn.pipeline import make_pipeline

    paths = [p.resolve() for p in (dataset_path, cleaned_path, artifact_path, evaluation_path, quality_path,
                                   error_report_path, comparison_path, candidate_artifact_path)]
    dataset_path, cleaned_path, artifact_path, evaluation_path, quality_path, error_report_path, comparison_path, candidate_artifact_path = paths
    if len(set(paths)) != len(paths):
        raise ValueError("All input and output paths must be distinct")
    for path in (dataset_path, cleaned_path, artifact_path, evaluation_path, quality_path):
        if not path.is_file():
            raise FileNotFoundError(path)

    original_report = json.loads(evaluation_path.read_text(encoding="utf-8"))
    quality_report = json.loads(quality_path.read_text(encoding="utf-8"))
    if _sha256(dataset_path) != quality_report.get("input_sha256"):
        raise ValueError("Original CSV checksum differs from the prepared data-quality report")
    if _sha256(cleaned_path) != original_report.get("dataset_sha256"):
        raise ValueError("Cleaned CSV checksum differs from the saved evaluation report")

    rows = []
    with cleaned_path.open("r", encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            rows.append({"url": row["url"], "label": int(row["label"]), "category": row["source_category"]})
    if len({row["url"] for row in rows}) != len(rows):
        raise ValueError("Cleaned dataset contains duplicate normalized URLs")
    splits = _domain_split(rows, SEED)
    domains = {name: {group_key(row["url"]) for row in part} for name, part in splits.items()}
    if any(domains[a] & domains[b] for a, b in (("train", "validation"), ("train", "test"), ("validation", "test"))):
        raise ValueError("Domain group overlap detected")

    bundle = joblib.load(artifact_path)
    saved_metadata = bundle.get("metadata")
    if not isinstance(saved_metadata, dict) or saved_metadata.get("dataset_sha256") != _sha256(cleaned_path):
        raise ValueError("Saved model metadata does not match the cleaned dataset")
    saved_model = bundle["model"]
    threshold = float(saved_metadata["threshold_selection"]["selected_threshold"])
    y_validation = [r["label"] for r in splits["validation"]]
    y_test = [r["label"] for r in splits["test"]]
    baseline_validation_scores = saved_model.predict_proba([r["url"] for r in splits["validation"]])[:, 1]
    baseline_test_scores = saved_model.predict_proba([r["url"] for r in splits["test"]])[:, 1]
    baseline_validation = _metrics(y_validation, baseline_validation_scores, threshold, None)
    baseline_test = _metrics(y_test, baseline_test_scores, threshold, None)
    _assert_metrics(baseline_validation, saved_metadata["threshold_selection"]["validation_metrics_at_threshold"], "validation")
    _assert_metrics(baseline_test, saved_metadata["test_metrics_at_selected_threshold"], "test")

    # Predeclared alternative: the same train-only character TF-IDF pipeline with MultinomialNB.
    # Model selection uses validation AP only; held-out test scores are generated after that rule.
    candidate = make_pipeline(
        TfidfVectorizer(analyzer="char", ngram_range=(3, 5), min_df=2, max_features=300_000,
                        sublinear_tf=True, dtype=np.float32),
        MultinomialNB(alpha=0.1),
    )
    candidate.fit([r["url"] for r in splits["train"]], [r["label"] for r in splits["train"]])
    candidate_validation_scores = candidate.predict_proba([r["url"] for r in splits["validation"]])[:, 1]
    candidate_threshold = _choose_threshold(y_validation, candidate_validation_scores)
    candidate_validation = _metrics(y_validation, candidate_validation_scores, candidate_threshold, None)
    baseline_validation_ap = baseline_validation["average_precision"]
    selected_candidate = (
        candidate_validation["average_precision"] >= baseline_validation_ap + 0.005
        and candidate_validation["recall_by_class_0_1"][1] >= baseline_validation["recall_by_class_0_1"][1] - 0.01
    )
    # This is final held-out evaluation only. Neither threshold nor candidate selection depends on these results.
    candidate_test_scores = candidate.predict_proba([r["url"] for r in splits["test"]])[:, 1]
    candidate_test = _metrics(y_test, candidate_test_scores, candidate_threshold, None)

    if selected_candidate:
        fingerprint = _sha256(cleaned_path)
        candidate_metadata = {
            "model_name": "AnaRisk character TF-IDF Multinomial Naive Bayes research candidate",
            "model_version": f"anarisk-url-char-tfidf-mnb-0.1.1-research-{fingerprint[:8]}",
            "trained_at_utc": datetime.now(UTC).isoformat(), "dataset_file": cleaned_path.name,
            "dataset_sha256": fingerprint, "dataset_rows": len(rows),
            "label_definitions": saved_metadata["label_definitions"], "source_categories_preserved": True,
            "seed": SEED, "feature_schema": "char-tfidf-url-v1",
            "features": saved_metadata["features"], "classifier": {"type": "MultinomialNB", "alpha": 0.1},
            "dependencies": {"scikit_learn": sklearn.__version__, "joblib": joblib.__version__, "numpy": np.__version__},
            "split_method": saved_metadata["split_method"], "split": saved_metadata["split"],
            "threshold_selection": {"method": "maximum validation recall subject to validation FPR <= 1%",
                                    "target_validation_false_positive_rate": TARGET_VALIDATION_FPR,
                                    "selected_threshold": candidate_threshold,
                                    "validation_metrics_at_threshold": candidate_validation},
            "test_metrics_at_selected_threshold": candidate_test,
            "score_is_calibrated_probability": False,
            "limitations": saved_metadata["limitations"] + ["Candidate selected against validation metrics; a recent independent dataset is still required."],
        }
        candidate_artifact_path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({"model": candidate, "metadata": candidate_metadata}, candidate_artifact_path)

    comparison = {
        "created_at_utc": datetime.now(UTC).isoformat(),
        "baseline_artifact": artifact_path.name, "dataset_sha256": _sha256(cleaned_path),
        "split_method": saved_metadata["split_method"],
        "domain_groups_disjoint": True,
        "reproduced_saved_report": True,
        "test_used_for_model_or_threshold_selection": False,
        "data_quality_and_rights": {
            key: quality_report.get(key) for key in (
                "input_sha256", "input_rows", "source_category_counts", "clean_rows",
                "duplicate_normalized_url_rows", "conflicting_normalized_urls_excluded",
                "registrable_domains_with_multiple_source_categories", "dates_available", "source_url", "license",
            )
        },
        "rights_assessment": "The local report records no license. Public availability/source matching does not establish permission to redistribute the CSV or derived artifact.",
        "selection_rule": "Select MultinomialNB only if validation average precision improves by at least 0.005 and validation malicious recall at the validation-selected <=1% FPR threshold is no more than 0.01 lower.",
        "selected_thresholds": {"baseline_logistic_regression": threshold,
                                "candidate_multinomial_nb": candidate_threshold},
        "validation": {"baseline_logistic_regression": baseline_validation,
                       "candidate_multinomial_nb": candidate_validation},
        "held_out_test": {"baseline_logistic_regression": baseline_test,
                          "candidate_multinomial_nb": candidate_test},
        "candidate_selected_on_validation": selected_candidate,
        "candidate_artifact": candidate_artifact_path.name if selected_candidate else None,
        "current_model_version": saved_metadata.get("model_version"),
        "notes": ["The test split was evaluated once for each predeclared model and was not used to choose the candidate or threshold.",
                  "This internal test set contains no reliable timestamps and cannot establish present-day performance.",
                  "Data provenance and usage rights remain unverified; artifacts are research-only."],
    }
    errors = _error_analysis(splits["test"], baseline_test_scores, threshold)
    errors.update({"created_at_utc": datetime.now(UTC).isoformat(), "model_version": saved_metadata.get("model_version"),
                   "dataset_sha256": _sha256(cleaned_path), "threshold_from_validation": threshold,
                   "threshold_selection_method": "maximum validation recall subject to validation FPR <= 1%"})
    error_report_path.parent.mkdir(parents=True, exist_ok=True)
    comparison_path.parent.mkdir(parents=True, exist_ok=True)
    error_report_path.write_text(json.dumps(errors, indent=2) + "\n", encoding="utf-8")
    comparison_path.write_text(json.dumps(comparison, indent=2) + "\n", encoding="utf-8")
    return {"comparison": comparison, "error_analysis": errors}


def _assert_metrics(actual: dict, expected: dict, split: str) -> None:
    for key in ("precision_by_class_0_1", "recall_by_class_0_1", "f1", "false_positive_rate",
                "false_negative_count", "average_precision", "roc_auc", "confusion_matrix_labels_0_1"):
        if key not in expected:
            raise ValueError(f"Saved {split} report is missing {key}")
        a, b = actual[key], expected[key]
        if isinstance(a, list):
            if json.dumps(a) != json.dumps(b):
                raise ValueError(f"Recomputed {split} metric {key} does not match the saved report")
        elif isinstance(a, int):
            if a != b:
                raise ValueError(f"Recomputed {split} metric {key} does not match the saved report")
        elif abs(a - b) > 1e-10:
            raise ValueError(f"Recomputed {split} metric {key} does not match the saved report")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("cleaned", type=Path)
    parser.add_argument("artifact", type=Path)
    parser.add_argument("evaluation", type=Path)
    parser.add_argument("quality", type=Path)
    parser.add_argument("error_report", type=Path)
    parser.add_argument("comparison_report", type=Path)
    parser.add_argument("candidate_artifact", type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(run(args.dataset, args.cleaned, args.artifact, args.evaluation, args.quality,
                             args.error_report, args.comparison_report, args.candidate_artifact), indent=2))
    except (OSError, ValueError, KeyError, csv.Error) as exc:
        print(f"model audit failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
