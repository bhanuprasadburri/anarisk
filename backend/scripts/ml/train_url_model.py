"""Train/evaluate a small URL-only phishing baseline for offline research.

This tool intentionally does not integrate the artifact into production scoring. It groups
by hostname before splitting to reduce near-duplicate/domain leakage, reserves test groups,
and reports ranking/classification metrics. Probability outputs are not calibrated.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from scripts.ml.url_dataset import SOURCE, SOURCE_URL

SEED = 20261020
FEATURE_VERSION = "url-lexical-v1"


FEATURE_NAMES = ("url_length", "host_length", "path_length", "query_length", "subdomain_count", "label_count",
                 "has_ip_host", "has_punycode", "https", "at_count", "hyphen_count", "digit_ratio",
                 "dot_count", "encoded_count", "suspicious_token_count")


def features(url: str) -> tuple[float, ...]:
    p = urlsplit(url)
    host = p.hostname or ""
    labels = [x for x in host.split(".") if x]
    text = f"{host}{p.path}?{p.query}"
    lowered = text.lower()
    return (
        min(len(url), 5000) / 5000,
        min(len(host), 253) / 253,
        min(len(p.path), 2000) / 2000,
        min(len(p.query), 2000) / 2000,
        min(max(0, len(labels) - 2), 10) / 10,
        min(len(labels), 15) / 15,
        float(all(c.isdigit() or c == "." for c in host) and bool(host)),
        float("xn--" in host),
        float(p.scheme == "https"),
        min(url.count("@"), 5) / 5,
        min(host.count("-"), 20) / 20,
        sum(c.isdigit() for c in host) / max(1, len(host)),
        min(host.count("."), 10) / 10,
        min(lowered.count("%"), 20) / 20,
        min(sum(lowered.count(t) for t in ("login", "verify", "secure", "account", "update", "password", "signin")), 10) / 10,
    )


def group_key(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().rstrip(".")


def grouped_split(rows: list[dict], seed: int = SEED) -> dict[str, list[dict]]:
    """Assign whole hosts to a deterministic approximate 70/15/15 split."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        key = group_key(row["url"])
        if key:
            groups[key].append(row)
    # A source release's official test set is kept intact; only source-train is split here.
    assignments = {"train": [], "validation": []}
    ordered = sorted(groups, key=lambda h: hashlib.sha256(f"split:{seed}:{h}".encode()).digest())
    totals = Counter(r["label"] for group in groups.values() for r in group)
    target_train = {label: count * 0.82 for label, count in totals.items()}
    current_train = Counter()
    for host in ordered:
        group = groups[host]
        group_counts = Counter(r["label"] for r in group)
        # Put each whole host in whichever partition most needs its class counts.
        train_need = sum(max(0, target_train.get(label, 0) - current_train[label]) for label in group_counts)
        val_need = sum(max(0, (totals[label] - target_train.get(label, 0)) - (totals[label] - current_train[label] - group_counts[label])) for label in group_counts)
        bucket = "train" if train_need >= val_need else "validation"
        assignments[bucket].extend(group)
        if bucket == "train":
            current_train.update(group_counts)
    return assignments


def run(train_path: Path, test_path: Path, artifact_path: Path, report_path: Path) -> dict:
    try:
        from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
        from sklearn.linear_model import LogisticRegression
        from sklearn.metrics import (average_precision_score, confusion_matrix, f1_score,
                                     precision_score, recall_score, roc_auc_score)
        from sklearn.utils.class_weight import compute_sample_weight
        import joblib
    except ImportError as exc:
        raise RuntimeError("Install backend/requirements-ml.txt before training") from exc

    def load_rows(path: Path) -> list[dict]:
        with path.open("r", encoding="utf-8", newline="") as f:
            return [{"url": r["url"], "label": int(r["label"]), "date": r.get("date", "")} for r in csv.DictReader(f)
                    if r.get("url") and r.get("label") in {"0", "1"}]
    rows = load_rows(train_path)
    test_rows = load_rows(test_path)
    if len(rows) < 100 or len(test_rows) < 100:
        raise ValueError("At least 100 valid examples are required for research evaluation")
    split = grouped_split(rows)
    split["test"] = test_rows
    for name in ("train", "validation", "test"):
        if not split[name] or len({r["label"] for r in split[name]}) < 2:
            raise ValueError(f"{name} split is empty or lacks one class; collect more diverse labeled domains")
    X = {k: [features(r["url"]) for r in v] for k, v in split.items()}
    y = {k: [r["label"] for r in v] for k, v in split.items()}
    train_hosts = {group_key(r["url"]) for r in split["train"]}
    val_hosts = {group_key(r["url"]) for r in split["validation"]}
    test_hosts = {group_key(r["url"]) for r in split["test"]}
    overlap = (train_hosts & val_hosts) | (train_hosts & test_hosts) | (val_hosts & test_hosts)
    if overlap:
        raise ValueError(f"Domain leakage detected: {len(overlap)} hostnames occur in multiple splits")
    # Candidate selection uses validation only; final metrics use held-out test once.
    candidates = {
        "logistic_regression": LogisticRegression(max_iter=1000, class_weight="balanced", random_state=SEED),
        "random_forest": RandomForestClassifier(n_estimators=200, min_samples_leaf=2, class_weight="balanced_subsample", n_jobs=-1, random_state=SEED),
        "hist_gradient_boosting": HistGradientBoostingClassifier(max_iter=150, learning_rate=0.08, l2_regularization=1.0, random_state=SEED),
    }
    trained = {}
    selection = []
    for name, model in candidates.items():
        weights = compute_sample_weight(class_weight="balanced", y=y["train"])
        try:
            model.fit(X["train"], y["train"], sample_weight=weights)
        except TypeError:
            model.fit(X["train"], y["train"])
        score = model.predict_proba(X["validation"])[:, 1]
        ap = float(average_precision_score(y["validation"], score))
        selection.append({"model": name, "validation_pr_auc": ap})
        trained[name] = model
    chosen = max(selection, key=lambda r: r["validation_pr_auc"])["model"]
    model = trained[chosen]
    test_scores = model.predict_proba(X["test"])[:, 1]
    # Threshold is selected on the validation set for F1, never on the test set.
    val_scores = model.predict_proba(X["validation"])[:, 1]
    thresholds = [i / 100 for i in range(5, 96, 5)]
    threshold = max(thresholds, key=lambda t: f1_score(y["validation"], val_scores >= t, zero_division=0))
    pred = test_scores >= threshold
    cm = confusion_matrix(y["test"], pred, labels=[0, 1]).tolist()
    host_overlaps = {name: {group_key(r["url"]) for r in split[name]} for name in split}
    assert not (host_overlaps["train"] & host_overlaps["validation"] or host_overlaps["train"] & host_overlaps["test"] or host_overlaps["validation"] & host_overlaps["test"])
    dates = [r["date"] for r in rows + test_rows if r["date"]]
    report = {
        "model_name": "anarisk-url-phishing-baseline", "model_version": "0.1.0-research",
        "trained_at_utc": datetime.now(UTC).isoformat(), "seed": SEED, "dataset_source": SOURCE,
        "dataset_source_url": SOURCE_URL, "train_manifest": train_path.with_suffix(train_path.suffix + ".manifest.json").name,
        "official_test_manifest": test_path.with_suffix(test_path.suffix + ".manifest.json").name,
        "feature_schema": FEATURE_VERSION, "selected_candidate_by_validation_pr_auc": chosen,
        "candidate_validation_results": selection, "split": {k: {"rows": len(v), "label_counts": dict(Counter(str(x) for x in y[k])), "unique_hosts": len(host_overlaps[k])} for k, v in split.items()},
        "test_metrics": {"precision": float(precision_score(y["test"], pred, zero_division=0)), "recall": float(recall_score(y["test"], pred, zero_division=0)),
                         "f1": float(f1_score(y["test"], pred, zero_division=0)), "pr_auc": float(average_precision_score(y["test"], test_scores)),
                         "roc_auc": float(roc_auc_score(y["test"], test_scores)), "confusion_matrix_labels_0_1": cm,
                         "false_positives": cm[0][1], "false_negatives": cm[1][0]},
        "threshold_selected_on_validation": threshold, "date_range": [min(dates), max(dates)] if dates else None,
        "calibration": "not calibrated; model scores are not probabilities of real-world harm",
        "scope": "URL lexical features only; no webpage content, live feed, domain age or DNS features",
        "intended_use": "offline anti-phishing research; not production-ready and not integrated with AnaRisk risk scoring",
        "known_limitations": ["dataset may contain stale/noisy labels", "domain-held-out split is not temporal validation", "distribution shift and class imbalance", "domain overlap assertion prevents exact hostname leakage but not shared campaigns/infrastructure"],
    }
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": model, "metadata": report}, artifact_path)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("train", type=Path, help="Prepared official train split")
    ap.add_argument("test", type=Path, help="Prepared official held-out test split")
    ap.add_argument("--artifact", type=Path, default=Path("var/models/url-phishing.joblib"))
    ap.add_argument("--report", type=Path, default=Path("var/reports/url-phishing-evaluation.json"))
    a = ap.parse_args()
    try:
        print(json.dumps(run(a.train, a.test, a.artifact, a.report), indent=2))
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        print(f"training/evaluation failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
