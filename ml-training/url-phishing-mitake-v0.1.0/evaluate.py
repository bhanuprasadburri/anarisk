from __future__ import annotations

import argparse
import csv
import json
import hashlib
import time
from collections import Counter, defaultdict
from pathlib import Path

import joblib
import numpy as np

from common import metric_summary, sha256_file, split_name, write_json
from train import _peak_rss_mb


def evaluate(prepared: Path, artifact: Path, report_path: Path) -> dict:
    prepared, artifact, report_path = prepared.resolve(), artifact.resolve(), report_path.resolve()
    if not prepared.is_file() or not artifact.is_file():
        raise FileNotFoundError("Prepared dataset and trained artifact must both exist")
    bundle = joblib.load(artifact)
    if not isinstance(bundle, dict) or not isinstance(bundle.get("metadata"), dict):
        raise ValueError("Invalid model artifact")
    metadata = bundle["metadata"]
    if metadata.get("feature_schema") != "char-tfidf-url-v1":
        raise ValueError("Unsupported model feature schema")
    data_hash = sha256_file(prepared)
    if data_hash != metadata.get("dataset_sha256"):
        raise ValueError("Prepared dataset checksum differs from the training artifact")
    audit_path = prepared.parent / "data-quality.json"
    audit = json.loads(audit_path.read_text(encoding="utf-8")) if audit_path.is_file() else {}
    overlap = audit.get("reference_overlap") or {}
    rows = []
    with prepared.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or not {"url", "label", "domain_group_hash"}.issubset(reader.fieldnames):
            raise ValueError("Prepared data schema mismatch")
        for row in reader:
            if row["label"] not in {"0", "1"}:
                raise ValueError("Prepared data has an invalid label")
            rows.append({"url": row["url"], "label": int(row["label"]),
                         "domain_group_hash": row["domain_group_hash"]})
    groups: dict[str, set[str]] = {name: set() for name in ("train", "validation", "test")}
    split_rows = defaultdict(list)
    url_hashes = defaultdict(set)
    for row in rows:
        name = split_name(row["domain_group_hash"])
        groups[name].add(row["domain_group_hash"])
        split_rows[name].append(row)
        url_hashes[name].add(hashlib.sha256(row["url"].encode()).digest())
    group_overlaps = {
        f"{a}_{b}": len(groups[a] & groups[b])
        for a, b in (("train", "validation"), ("train", "test"), ("validation", "test"))
    }
    url_overlaps = {
        f"{a}_{b}": len(url_hashes[a] & url_hashes[b])
        for a, b in (("train", "validation"), ("train", "test"), ("validation", "test"))
    }
    if any(group_overlaps.values()) or any(url_overlaps.values()):
        raise ValueError("Domain or normalized URL overlap found across partitions")
    test = split_rows["test"]
    if not test or {row["label"] for row in test} != {0, 1}:
        raise ValueError("Test partition is empty or missing a class")
    start = time.perf_counter()
    scores = bundle["model"].predict_proba([row["url"] for row in test])[:, 1]
    test_seconds = time.perf_counter() - start
    threshold = float(metadata["threshold_selection"]["selected_threshold"])
    labels = [row["label"] for row in test]
    split_summary = {}
    for name, records in split_rows.items():
        split_summary[name] = {
            "rows": len(records),
            "label_counts": {str(k): v for k, v in sorted(Counter(r["label"] for r in records).items())},
            "phishing_prevalence": sum(r["label"] == 1 for r in records) / len(records),
            "unique_registrable_domains": len(groups[name]),
        }
    result = {
        "evaluation_type": "held-out domain-separated test from this dataset; not an independent source evaluation",
        "model_version": metadata["model_version"],
        "artifact_sha256": sha256_file(artifact),
        "prepared_dataset_sha256": data_hash,
        "threshold_from_training_validation_only": threshold,
        "threshold_reselected_on_test": False,
        "metrics": metric_summary(labels, scores, threshold),
        "partitions": split_summary,
        "overlap_validation": {"registrable_domain_intersections": group_overlaps,
                               "normalized_url_hash_intersections": url_overlaps,
                               "passed": True},
        "performance": {
            "test_batch_inference_seconds": round(test_seconds, 4),
            "test_rows_per_second": round(len(test) / test_seconds, 2) if test_seconds else None,
            "artifact_bytes": artifact.stat().st_size,
            "process_peak_working_set_mb": _peak_rss_mb(),
        },
        "legacy_baseline_comparison": {
            "valid_same_test_comparison": False,
            "shared_normalized_url_hashes": overlap.get("shared_normalized_url_hashes"),
            "shared_registrable_domain_hashes": overlap.get("shared_registrable_domain_hashes"),
            "reason": "The legacy source overlaps this candidate, so test observations may have appeared in legacy training. Its training label also combines phishing, malware, and defacement.",
            "legacy_historical_metrics_are_incomparable": True,
        },
        "limitations": metadata["limitations"],
    }
    write_json(report_path, result)
    m = result["metrics"]
    model_card = f"""# {metadata['model_name']}\n\n## Intended use\n\nPrivate offline anti-phishing research only. This model is not a production verdict, is not connected to AnaRisk findings or risk scoring, and is not approved for staging or deployment. Do not redistribute the dataset or model artifact.\n\n## Dataset and labels\n\n- Source listing: https://huggingface.co/datasets/Mitake/PhishingURLsANDBenignURLs\n- Local raw dataset SHA-256: `{metadata['source_dataset_sha256']}`\n- Prepared dataset SHA-256: `{data_hash}`\n- Label mapping: `0 = benign`, `1 = phishing` (user-confirmed; publisher README/card does not explain it).\n- Declared dataset license: CC BY-SA 4.0. Source lineage and upstream rights have not been independently verified; no conclusion is made about model-weight share-alike treatment.\n- Attribution: Mitake, PhishingURLsANDBenignURLs, CC BY-SA 4.0, https://huggingface.co/datasets/Mitake/PhishingURLsANDBenignURLs. Changes: URL normalization, conflict/duplicate handling, and domain-separated splits.\n\n## Evaluation\n\n- Model version: `{metadata['model_version']}`\n- Selected estimator: `{metadata['classifier']['type']}`\n- Validation-selected threshold: `{threshold}` (validation FPR target <= 1%; no test tuning).\n- Test rows: {len(test)}; phishing prevalence: {split_summary['test']['phishing_prevalence']:.4f}.\n- Precision: {m['precision_phishing']:.4f}; recall: {m['recall_phishing']:.4f}; F1: {m['f1_phishing']:.4f}; specificity: {m['specificity_benign']:.4f}; balanced accuracy: {m['balanced_accuracy']:.4f}.\n- Average precision: {m['average_precision_pr_auc']:.4f}; ROC-AUC: {m['roc_auc']:.4f}.\n- FPR: {m['false_positive_rate']:.4f}; FNR: {m['false_negative_rate']:.4f}; FP: {m['false_positive_count']}; FN: {m['false_negative_count']}.\n- Confusion matrix, true rows `[benign, phishing]`, predicted columns `[benign, phishing]`: `{m['confusion_matrix_true_rows_0_1_predicted_columns_0_1']}`.\n- Domain/normalized URL disjointness: `{result['overlap_validation']['passed']}`.\n\n## Limitations\n\n- The candidate data shares {overlap.get('shared_normalized_url_hashes', 'an unknown number of')} normalized URL hashes and {overlap.get('shared_registrable_domain_hashes', 'an unknown number of')} registrable-domain hashes with the legacy source dataset; this is not an independent source-level benchmark, and a clean same-test baseline comparison is invalid.\n- No reliable timestamps, source IDs, or label verification history are available.\n- Dataset source revision and local byte identity are not verified.\n- Metrics reflect this dataset's labels and class prevalence, not current real-world traffic.\n- No claims of production generalization or deployment readiness are made.\n"""
    report_path.with_name("model-card.md").write_text(model_card, encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate saved model on untouched test partition")
    parser.add_argument("prepared", type=Path)
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(evaluate(args.prepared, args.artifact, args.report), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
