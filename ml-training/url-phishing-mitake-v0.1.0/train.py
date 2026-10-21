from __future__ import annotations

import argparse
import csv
import json
import platform
import sys
import time
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

import joblib
import numpy as np
import sklearn
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.naive_bayes import MultinomialNB
from sklearn.pipeline import Pipeline
from sklearn.metrics import average_precision_score

from common import (EXPERIMENT_VERSION, LABEL_MAP, MODEL_FEATURE_SCHEMA, SEED,
                    VALIDATION_FPR_TARGET, metric_summary, select_threshold,
                    sha256_file, split_name, write_json)


def _peak_rss_mb() -> float | None:
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]

        value = Counters()
        value.cb = ctypes.sizeof(value)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        handle = kernel32.GetCurrentProcess()
        if psapi.GetProcessMemoryInfo(handle, ctypes.byref(value), value.cb):
            return round(value.PeakWorkingSetSize / (1024 * 1024), 2)
        return None
    try:
        import resource
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return round(peak / (1024 if sys.platform != "darwin" else 1024 * 1024), 2)
    except (ImportError, AttributeError):
        return None


def _load(path: Path) -> list[dict]:
    records = []
    with path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or not {"url", "label", "domain_group_hash"}.issubset(reader.fieldnames):
            raise ValueError("Prepared data schema must be url,label,domain_group_hash")
        for row in reader:
            if row["label"] not in {"0", "1"} or not row["url"] or not row["domain_group_hash"]:
                raise ValueError("Prepared data contains an invalid row")
            records.append({"url": row["url"], "label": int(row["label"]),
                            "domain_group_hash": row["domain_group_hash"]})
    if len(records) < 100 or {r["label"] for r in records} != {0, 1}:
        raise ValueError("At least 100 prepared rows and both classes are required")
    return records


def train(prepared: Path, artifact: Path, report_path: Path) -> dict:
    prepared = prepared.resolve()
    artifact = artifact.resolve()
    report_path = report_path.resolve()
    if artifact in {prepared, report_path} or prepared == report_path or artifact == report_path:
        raise ValueError("Dataset, model, and report paths must be different")
    records = _load(prepared)
    by_split: dict[str, list[dict]] = defaultdict(list)
    groups: dict[str, set[str]] = {name: set() for name in ("train", "validation", "test")}
    for record in records:
        name = split_name(record["domain_group_hash"])
        by_split[name].append(record)
        groups[name].add(record["domain_group_hash"])
    if any(groups[a] & groups[b] for a, b in (("train", "validation"), ("train", "test"), ("validation", "test"))):
        raise ValueError("Registrable-domain overlap detected between partitions")
    for name in ("train", "validation", "test"):
        if not by_split[name] or {r["label"] for r in by_split[name]} != {0, 1}:
            raise ValueError(f"{name} partition is empty or missing a class")

    started = time.perf_counter()
    vectorizer = TfidfVectorizer(analyzer="char", ngram_range=(3, 5), min_df=2,
                                 max_features=300_000, sublinear_tf=True, dtype=np.float32)
    train_rows, val_rows = (by_split[k] for k in ("train", "validation"))
    x_train = vectorizer.fit_transform([r["url"] for r in train_rows])
    x_validation = vectorizer.transform([r["url"] for r in val_rows])
    y_train = np.asarray([r["label"] for r in train_rows], dtype=np.int8)
    y_validation = np.asarray([r["label"] for r in val_rows], dtype=np.int8)

    candidates = {
        "logistic_regression": LogisticRegression(max_iter=1000, class_weight="balanced",
                                                   random_state=SEED, solver="liblinear"),
        "multinomial_nb": MultinomialNB(alpha=0.1),
    }
    validation_results = {}
    for name, estimator in candidates.items():
        estimator.fit(x_train, y_train)
        scores = estimator.predict_proba(x_validation)[:, 1]
        threshold, method = select_threshold(y_validation, scores)
        validation_results[name] = {
            "threshold_selection": method,
            "metrics": metric_summary(y_validation, scores, threshold),
            "average_precision": float(average_precision_score(y_validation, scores)),
        }
        validation_results[name]["threshold_selection"]["selected_threshold"] = threshold

    # Predeclared selection: highest validation phishing recall under the FPR limit,
    # then highest validation AP; exact ties favor the established Logistic Regression baseline.
    selected_name = max(
        candidates,
        key=lambda name: (
            validation_results[name]["metrics"]["recall_phishing"],
            validation_results[name]["average_precision"],
            name == "logistic_regression",
        ),
    )
    selected = candidates[selected_name]
    threshold = validation_results[selected_name]["threshold_selection"]["selected_threshold"]
    model = Pipeline([("tfidf", vectorizer), ("classifier", selected)])
    training_seconds = round(time.perf_counter() - started, 3)
    split_summary = {}
    for name, rows in by_split.items():
        split_summary[name] = {
            "rows": len(rows),
            "label_counts": {str(k): v for k, v in sorted(Counter(r["label"] for r in rows).items())},
            "phishing_prevalence": sum(r["label"] == 1 for r in rows) / len(rows),
            "unique_registrable_domains": len(groups[name]),
        }
    metadata = {
        "model_name": "AnaRisk URL phishing character TF-IDF research model",
        "model_version": f"anarisk-url-phish-mitake-{EXPERIMENT_VERSION}-{sha256_file(prepared)[:8]}",
        "experiment_version": EXPERIMENT_VERSION,
        "trained_at_utc": datetime.now(UTC).isoformat(),
        "dataset_id": "Mitake/PhishingURLsANDBenignURLs",
        "dataset_sha256": sha256_file(prepared),
        "source_dataset_sha256": json.loads((prepared.parent / "data-quality.json").read_text(encoding="utf-8"))["source_sha256"],
        "dataset_rows": len(records),
        "label_definitions": {"0": "benign", "1": "phishing"},
        "label_mapping_basis": "User-confirmed; the source card does not document the integer semantics.",
        "seed": SEED,
        "feature_schema": MODEL_FEATURE_SCHEMA,
        "features": {"type": "character TF-IDF", "analyzer": "char", "ngram_range": [3, 5],
                     "min_df": 2, "max_features": 300000, "sublinear_tf": True, "dtype": "float32"},
        "preprocessing": "AnaRisk url_model_features.normalize_url; applied before vectorization at preparation and inference.",
        "split_method": "Hash registrable-domain group assignment using tldextract bundled Public Suffix List snapshot: 70/15/15 by domain hash; seed controls the assignment.",
        "split": split_summary,
        "threshold_selection": {**validation_results[selected_name]["threshold_selection"],
                                "validation_metrics": validation_results[selected_name]["metrics"]},
        "model_selection": {
            "rule": "Highest validation phishing recall under validation FPR <= 1%; then validation AP; exact ties favor Logistic Regression.",
            "selected": selected_name,
            "validation_comparison": validation_results,
        },
        "classifier": {"type": selected_name, **(
            {"max_iter": 1000, "class_weight": "balanced", "solver": "liblinear", "random_state": SEED}
            if selected_name == "logistic_regression" else {"alpha": 0.1}
        )},
        "dependencies": {"python": platform.python_version(), "scikit_learn": sklearn.__version__,
                         "joblib": joblib.__version__, "numpy": np.__version__,
                         "tldextract": __import__("tldextract").__version__},
        "training_duration_seconds": training_seconds,
        "peak_process_working_set_mb": _peak_rss_mb(),
        "research_only": True,
        "production_integration": False,
        "limitations": [
            "Source card has no explanatory README; label meanings were supplied by the user.",
            "The local CSV is not byte-verified against an immutable source revision.",
            "Candidate data has substantial overlap with the legacy dataset; test results are not an independent source benchmark.",
            "No timestamps, source IDs, or label verification history are present.",
            "The dataset card declares CC BY-SA 4.0; upstream rights and model-weight share-alike treatment are not legally reviewed.",
            "Model is private research output only; no redistribution, deployment, or staging use is authorized.",
        ],
    }
    artifact.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": model, "metadata": metadata}, artifact, compress=3)
    artifact_checksum = sha256_file(artifact)
    artifact.with_suffix(artifact.suffix + ".sha256").write_text(
        f"{artifact_checksum}  {artifact.name}\n", encoding="ascii"
    )
    training_report = {**metadata, "artifact_file": artifact.name,
                       "artifact_sha256": artifact_checksum, "artifact_bytes": artifact.stat().st_size}
    write_json(report_path, training_report)
    return training_report


def main() -> int:
    parser = argparse.ArgumentParser(description="Train URL-only research models; never connects to production")
    parser.add_argument("prepared", type=Path)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(train(args.prepared, args.artifact, args.report), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
