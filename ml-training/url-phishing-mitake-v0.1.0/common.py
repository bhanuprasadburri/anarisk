from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from pathlib import Path
from urllib.parse import urlsplit

import tldextract

from app.services.url_model_features import normalize_url

SEED = 20261021
VALIDATION_FPR_TARGET = 0.01
EXPERIMENT_VERSION = "v0.1.0-research"
LABEL_MAP = {"0": 0, "1": 1}  # Confirmed by the dataset owner for this experiment.
SOURCE_URL = "https://huggingface.co/datasets/Mitake/PhishingURLsANDBenignURLs"
MODEL_FEATURE_SCHEMA = "char-tfidf-url-v1"

# An empty URL list disables network fetching; tldextract uses its packaged PSL snapshot.
_extract_psl = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def domain_group(url: str) -> str:
    """Return PSL registrable domain; use exact host for IP/unknown suffix."""
    host = (urlsplit(url).hostname or "").lower().rstrip(".")
    if not host:
        return ""
    result = _extract_psl(host)
    return result.top_domain_under_public_suffix or host


def split_name(group_hash: str, seed: int = SEED) -> str:
    bucket = int.from_bytes(hashlib.sha256(f"{seed}:{group_hash}".encode()).digest()[:8], "big") % 100
    return "train" if bucket < 70 else "validation" if bucket < 85 else "test"


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def metric_summary(y_true: Iterable[int], scores: Iterable[float], threshold: float) -> dict:
    import numpy as np
    from sklearn.metrics import (average_precision_score, balanced_accuracy_score,
                                 confusion_matrix, f1_score, precision_score,
                                 recall_score, roc_auc_score)

    truth = np.asarray(list(y_true), dtype=np.int8)
    score = np.asarray(list(scores), dtype=np.float64)
    pred = score >= threshold
    tn, fp, fn, tp = (int(x) for x in confusion_matrix(truth, pred, labels=[0, 1]).ravel())
    specificity = tn / (tn + fp) if tn + fp else None
    return {
        "threshold": float(threshold),
        "precision_phishing": float(precision_score(truth, pred, pos_label=1, zero_division=0)),
        "recall_phishing": float(recall_score(truth, pred, pos_label=1, zero_division=0)),
        "f1_phishing": float(f1_score(truth, pred, pos_label=1, zero_division=0)),
        "specificity_benign": specificity,
        "balanced_accuracy": float(balanced_accuracy_score(truth, pred)),
        "precision_by_class_0_1": [
            float(precision_score(truth, pred, pos_label=label, zero_division=0)) for label in (0, 1)
        ],
        "recall_by_class_0_1": [
            float(recall_score(truth, pred, pos_label=label, zero_division=0)) for label in (0, 1)
        ],
        "confusion_matrix_true_rows_0_1_predicted_columns_0_1": [[tn, fp], [fn, tp]],
        "false_positive_rate": fp / (fp + tn) if fp + tn else None,
        "false_negative_rate": fn / (fn + tp) if fn + tp else None,
        "false_positive_count": fp,
        "false_negative_count": fn,
        "average_precision_pr_auc": float(average_precision_score(truth, score)),
        "roc_auc": float(roc_auc_score(truth, score)),
    }


def select_threshold(y_true, scores, fpr_target: float = VALIDATION_FPR_TARGET) -> tuple[float, dict]:
    import numpy as np
    from sklearn.metrics import roc_curve

    fpr, tpr, thresholds = roc_curve(y_true, scores)
    candidates = [i for i, value in enumerate(fpr) if value <= fpr_target and np.isfinite(thresholds[i])]
    if not candidates:
        raise ValueError("No finite validation threshold satisfies the false-positive-rate constraint")
    index = max(candidates, key=lambda i: (tpr[i], thresholds[i]))
    return float(thresholds[index]), {
        "method": "maximum validation recall subject to validation FPR <= configured target",
        "validation_fpr_target": fpr_target,
        "validation_fpr_at_selected_threshold": float(fpr[index]),
        "validation_recall_at_selected_threshold": float(tpr[index]),
    }


