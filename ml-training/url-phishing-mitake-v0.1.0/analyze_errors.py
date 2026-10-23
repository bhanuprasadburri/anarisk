from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import platform
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit
import ipaddress

import joblib
import numpy as np
import sklearn
from scipy.stats import beta
from sklearn.metrics import (average_precision_score, confusion_matrix, f1_score,
                             precision_score, recall_score, roc_auc_score)

from common import MODEL_FEATURE_SCHEMA, domain_group, sha256_file
from app.services.url_model_features import normalize_url


def exact_binomial_interval(successes: int, total: int, alpha: float = 0.05) -> list[float] | None:
    if total <= 0:
        return None
    lower = 0.0 if successes == 0 else float(beta.ppf(alpha / 2, successes, total - successes + 1))
    upper = 1.0 if successes == total else float(beta.ppf(1 - alpha / 2, successes + 1, total - successes))
    return [lower, upper]


def metric_values(counts: np.ndarray) -> dict:
    tn, fp, fn, tp = (int(v) for v in counts)
    total = tn + fp + fn + tp
    return {
        "sample_count": total,
        "class_counts": {"benign_0": tn + fp, "phishing_1": fn + tp},
        "phishing_prevalence": (fn + tp) / total if total else None,
        "confusion_matrix_true_rows_benign_phishing_predicted_columns_benign_phishing": [[tn, fp], [fn, tp]],
        "false_positive_count": fp,
        "false_positive_denominator_benign": tn + fp,
        "false_positive_rate": fp / (tn + fp) if tn + fp else None,
        "false_negative_count": fn,
        "false_negative_denominator_phishing": fn + tp,
        "false_negative_rate": fn / (fn + tp) if fn + tp else None,
        "precision_phishing": tp / (tp + fp) if tp + fp else 0.0,
        "precision_denominator_predicted_phishing": tp + fp,
        "recall_phishing": tp / (tp + fn) if tp + fn else None,
        "recall_denominator_phishing": fn + tp,
        "specificity_benign": tn / (tn + fp) if tn + fp else None,
        "specificity_denominator_benign": tn + fp,
        "f1_phishing": 2 * tp / (2 * tp + fp + fn) if (2 * tp + fp + fn) else 0.0,
        "f1_denominator": 2 * tp + fp + fn,
    }


def exact_intervals(metrics: dict) -> dict:
    definitions = {
        "false_positive_rate": (metrics["false_positive_count"], metrics["false_positive_denominator_benign"]),
        "false_negative_rate": (metrics["false_negative_count"], metrics["false_negative_denominator_phishing"]),
        "precision_phishing": (metrics["confusion_matrix_true_rows_benign_phishing_predicted_columns_benign_phishing"][1][1], metrics["precision_denominator_predicted_phishing"]),
        "recall_phishing": (metrics["confusion_matrix_true_rows_benign_phishing_predicted_columns_benign_phishing"][1][1], metrics["false_negative_denominator_phishing"]),
    }
    return {name: {"method": "95% Clopper-Pearson exact binomial", "interval": exact_binomial_interval(*values)}
            for name, values in definitions.items()}


def cluster_bootstrap(counts_by_domain: np.ndarray, *, seed: int, replicates: int) -> dict:
    """Resample whole domains; counts columns are TN, FP, FN, TP."""
    if counts_by_domain.ndim != 2 or counts_by_domain.shape[1] != 4 or not len(counts_by_domain):
        return {name: None for name in ("false_positive_rate", "false_negative_rate", "precision_phishing", "recall_phishing", "f1_phishing")}
    rng = np.random.default_rng(seed)
    n = len(counts_by_domain)
    values: dict[str, list[float]] = defaultdict(list)
    names = ("false_positive_rate", "false_negative_rate", "precision_phishing", "recall_phishing", "f1_phishing")
    for _ in range(replicates):
        sample = counts_by_domain[rng.integers(0, n, size=n)].sum(axis=0)
        metrics = metric_values(sample)
        for name in names:
            value = metrics[name]
            if value is not None:
                values[name].append(float(value))
    return {name: [float(v) for v in np.quantile(values[name], [0.025, 0.975])]
            if len(values[name]) >= max(20, replicates // 2) else None
            for name in ("false_positive_rate", "false_negative_rate", "precision_phishing", "recall_phishing", "f1_phishing")}


def _bands(value: int, cuts: tuple[int, ...]) -> str:
    if value < cuts[0]:
        return f"0-{cuts[0]-1}"
    for low, high in zip(cuts, cuts[1:]):
        if low <= value < high:
            return f"{low}-{high-1}"
    return f"{cuts[-1]}+"


def safe_features(url: str, training_domain_frequency: dict[str, int]) -> dict[str, str]:
    """Extract local-only coarse groups; never return URL or host values."""
    normalized = normalize_url(url)
    if not normalized:
        raise ValueError("Prepared URL failed the shared inference normalizer")
    parsed = urlsplit(normalized)
    host = parsed.hostname or ""
    try:
        ipaddress.ip_address(host)
        ip_literal = "yes"
    except ValueError:
        ip_literal = "no" if host else "unavailable"
    try:
        port = parsed.port
        nondefault = "yes" if port is not None and port != {"http": 80, "https": 443}.get(parsed.scheme.lower()) else "no"
    except ValueError:
        nondefault = "unavailable"
    group = domain_group(normalized)
    frequency = training_domain_frequency.get(hashlib.sha256(group.encode()).hexdigest()) if group else None
    path_segments = len([part for part in parsed.path.split("/") if part])
    return {
        "url_length": _bands(len(normalized), (51, 101, 201)),
        "digit_count": _bands(sum(ch.isdigit() for ch in normalized), (1, 4, 8)),
        "hyphen_count": _bands(normalized.count("-"), (1, 4, 8)),
        "dot_count": _bands(normalized.count("."), (2, 4, 8)),
        "path_segments": _bands(path_segments, (1, 3, 6)),
        "ip_literal_host": ip_literal,
        "non_default_port": nondefault,
        "query_string": "yes" if parsed.query else "no",
        # The shared inference normalizer strips fragments before storage/scoring.
        "fragment": "unavailable_after_normalization",
        "scheme": "https" if parsed.scheme.lower() == "https" else "http" if parsed.scheme.lower() == "http" else "other",
        "training_domain_frequency": "unseen_in_training" if frequency is None else _bands(frequency, (2, 6, 21)),
    }


def _read_prepared(path: Path) -> list[dict]:
    rows = []
    with path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or not {"url", "label", "domain_group_hash"}.issubset(reader.fieldnames):
            raise ValueError("Prepared data must contain url,label,domain_group_hash")
        for row in reader:
            if row["label"] not in {"0", "1"} or not row["url"] or not row["domain_group_hash"]:
                raise ValueError("Prepared data contains malformed rows")
            rows.append({"url": row["url"], "label": int(row["label"]), "domain": row["domain_group_hash"]})
    return rows


def _feature_error_rates(rows: list[dict], scores: np.ndarray, labels: np.ndarray,
                         predictions: np.ndarray, training_domain_frequency: dict[str, int]) -> dict:
    groups: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(lambda: [0, 0, 0, 0, 0]))
    for row, score, label, predicted in zip(rows, scores, labels, predictions):
        features = safe_features(row["url"], training_domain_frequency)
        band = min(int(float(score) * 4), 3)
        features["prediction_score"] = ("[0,.25)" if band == 0 else "[.25,.5)" if band == 1
                                        else "[.5,.75)" if band == 2 else "[.75,1]")
        for name, value in features.items():
            tally = groups[name][value]
            tally[0] += 1
            if label == 0:
                tally[1] += 1
                tally[2] += int(bool(predicted))
            else:
                tally[4] += 1
                tally[3] += int(not bool(predicted))
    return {
        name: {
            value: {"support": counts[0], "benign_support": counts[1], "false_positive_count": counts[2],
                    "false_positive_rate": counts[2] / counts[1] if counts[1] else None,
                    "phishing_support": counts[4], "false_negative_count": counts[3],
                    "false_negative_rate": counts[3] / counts[4] if counts[4] else None}
            for value, counts in sorted(values.items())
        }
        for name, values in sorted(groups.items())
    }


def _summarize_split(rows: list[dict], scores: np.ndarray, threshold: float,
                     training_domain_frequency: dict[str, int], *, seed: int, replicates: int) -> dict:
    labels = np.asarray([row["label"] for row in rows], dtype=np.int8)
    predictions = scores >= threshold
    tn, fp, fn, tp = (int(x) for x in confusion_matrix(labels, predictions, labels=[0, 1]).ravel())
    metrics = metric_values(np.array([tn, fp, fn, tp]))
    metrics.update({
        "threshold_fixed_from_training_validation": threshold,
        "average_precision_pr_auc": float(average_precision_score(labels, scores)) if len(set(labels)) > 1 else None,
        "roc_auc": float(roc_auc_score(labels, scores)) if len(set(labels)) > 1 else None,
        "f1_sklearn": float(f1_score(labels, predictions, zero_division=0)),
        "precision_sklearn": float(precision_score(labels, predictions, zero_division=0)),
        "recall_sklearn": float(recall_score(labels, predictions, zero_division=0)),
        "exact_binomial_95_percent_intervals": exact_intervals(metrics),
    })
    grouped: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0, 0])
    for row, score, label, predicted in zip(rows, scores, labels, predictions):
        domain = row["domain"]
        index = (0 if not predicted else 1) if label == 0 else (2 if not predicted else 3)
        grouped[domain][index] += 1
    metrics["feature_error_rates"] = _feature_error_rates(rows, scores, labels, predictions, training_domain_frequency)
    metrics["domain_cluster_bootstrap_95_percent_intervals"] = {
        "method": "percentile bootstrap resampling registrable-domain groups with replacement",
        "seed": seed, "replicates": replicates, "domain_groups": len(grouped),
        "intervals": cluster_bootstrap(np.asarray(list(grouped.values()), dtype=np.int64), seed=seed, replicates=replicates),
    }
    return metrics


def analyze(prepared: Path, artifact: Path, base_evaluation: Path, output: Path,
            *, seed: int = 440221, replicates: int = 1000) -> dict:
    prepared, artifact = prepared.resolve(), artifact.resolve()
    baseline = json.loads(base_evaluation.read_text(encoding="utf-8"))
    bundle = joblib.load(artifact)
    metadata = bundle.get("metadata", {})
    if metadata.get("feature_schema") != MODEL_FEATURE_SCHEMA:
        raise ValueError("Unsupported saved artifact feature schema")
    if sha256_file(prepared) != metadata.get("dataset_sha256"):
        raise ValueError("Prepared dataset hash does not match saved artifact")
    threshold = float(metadata["threshold_selection"]["selected_threshold"])
    if not math.isclose(threshold, float(baseline["threshold_from_training_validation_only"]), rel_tol=0, abs_tol=1e-12):
        raise ValueError("Saved artifact threshold differs from the existing evaluation report")
    rows = _read_prepared(prepared)
    splits: dict[str, list[dict]] = {key: [] for key in ("train", "validation", "test")}
    for row in rows:
        splits[__import__("common").split_name(row["domain"])].append(row)
    train_frequency = Counter(row["domain"] for row in splits["train"])
    training_domain_frequency = {key: value for key, value in train_frequency.items()}
    result = {
        "analysis_type": "exploratory descriptive analysis of existing domain-grouped validation and consumed test partitions; no selection or tuning",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "dataset_sha256": sha256_file(prepared), "artifact_sha256": sha256_file(artifact),
        "model_version": metadata["model_version"], "label_order": {"0": "benign", "1": "phishing"},
        "fixed_threshold": threshold, "threshold_source": "saved artifact; validation-selected in original experiment; not changed",
        "feature_interpretation": "Descriptive associations only; not causal explanations. Feature groups are extracted locally from normalized URLs and no identifiers/raw values are exported.",
        "feature_band_definitions": {
            "url_length": "characters: 0-50, 51-100, 101-200, 201+",
            "digit_count/hyphen_count/dot_count": "URL character count: 0, 1-3, 4-7, 8+ (dot bands 0-1, 2-3, 4-7, 8+)",
            "path_segments": "0, 1-2, 3-5, 6+ nonempty path segments",
            "training_domain_frequency": "registrable-domain row count in train: 1, 2-5, 6-20, 21+; domains with no training occurrence are marked unseen_in_training",
            "prediction_score": "fixed-width score bands [0,.25), [.25,.5), [.5,.75), [.75,1]",
            "fragment": "unavailable because the shared inference normalizer strips fragments",
        "scheme": "normalized inference accepts only HTTP and HTTPS; unsupported source schemes were excluded during preparation",
        },
        "environment": {"python": platform.python_version(), "os": platform.platform(), "machine": platform.machine(),
                        "processor": platform.processor(), "numpy": np.__version__, "scikit_learn": sklearn.__version__,
                        "bootstrap_seed": seed, "bootstrap_replicates": replicates},
        "partitions": {},
        "prior_batch_performance_context_only": baseline.get("performance"),
        "limitations": ["The test partition has already been consumed and results are exploratory.",
                        "Cluster bootstrap intervals describe domain-group sampling uncertainty, not source independence.",
                        "Dataset has no reliable timestamps or source identifiers; domain-frequency effects may reflect collection/source artifacts.",
                        "By design, registrable domains are disjoint across partitions, so every validation/test domain is unseen in training and within-domain training-frequency effects cannot be estimated.",
                        "URL format groups are descriptive and not causal.",
                        "No raw URLs, hosts, domains, queries, or row-level identifiers are included."],
    }
    for split in ("validation", "test"):
        part = splits[split]
        scores = bundle["model"].predict_proba([normalize_url(row["url"]) for row in part])[:, 1]
        result["partitions"][split] = _summarize_split(part, scores, threshold, training_domain_frequency,
                                                       seed=seed, replicates=replicates)
    output.mkdir(parents=True, exist_ok=False)
    report_path = output / "error-analysis.json"
    report_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = ["# Exploratory URL phishing error analysis", "",
             "This report describes existing validation and consumed test partitions. It is not an independent final evaluation and was not used to select or tune anything.", "",
             f"- Model: `{metadata['model_version']}`", f"- Fixed validation-selected threshold: `{threshold:.9f}`",
             f"- Dataset SHA-256: `{result['dataset_sha256']}`", f"- Artifact SHA-256: `{result['artifact_sha256']}`", "",
             "## Partition metrics", "", "| Split | N | Phishing prevalence | FPR (FP / benign) | FNR (FN / phishing) | Precision | Recall | Specificity | F1 | AP | ROC-AUC |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for split, m in result["partitions"].items():
        lines.append(f"| {split} | {m['sample_count']} | {m['phishing_prevalence']:.4f} | {m['false_positive_rate']:.4f} ({m['false_positive_count']}/{m['false_positive_denominator_benign']}) | {m['false_negative_rate']:.4f} ({m['false_negative_count']}/{m['false_negative_denominator_phishing']}) | {m['precision_phishing']:.4f} | {m['recall_phishing']:.4f} | {m['specificity_benign']:.4f} | {m['f1_phishing']:.4f} | {m['average_precision_pr_auc']:.4f} | {m['roc_auc']:.4f} |")
    lines.extend(["", "## 95% uncertainty intervals", "", "Exact binomial intervals treat rows as Bernoulli observations; domain-cluster intervals resample whole domains. Cluster intervals are the more relevant descriptive uncertainty estimate under this split design, but neither interval addresses source independence.", "", "| Split | Metric | Exact binomial interval | Domain-cluster bootstrap interval |", "|---|---|---:|---:|"])
    for split, m in result["partitions"].items():
        for metric in ("false_positive_rate", "false_negative_rate", "precision_phishing", "recall_phishing"):
            exact = m["exact_binomial_95_percent_intervals"][metric]["interval"]
            cluster = m["domain_cluster_bootstrap_95_percent_intervals"]["intervals"][metric]
            exact_text = "unavailable" if exact is None else f"[{exact[0]:.4f}, {exact[1]:.4f}]"
            cluster_text = "unavailable" if cluster is None else f"[{cluster[0]:.4f}, {cluster[1]:.4f}]"
            lines.append(f"| {split} | {metric} | {exact_text} | {cluster_text} |")
    lines.extend(["", "## Feature group errors", "", "Rates are calculated within the corresponding true class; support and denominators are included. These are descriptive associations, not causes.", ""])
    for split, m in result["partitions"].items():
        lines.extend([f"### {split}", "", "| Feature | Group | Support | Benign support | FP / benign | FPR | Phishing support | FN / phishing | FNR |", "|---|---|---:|---:|---:|---:|---:|---:|---:|"])
        for feature, groups in m["feature_error_rates"].items():
            for value, values in groups.items():
                fpr = "—" if values["false_positive_rate"] is None else f"{values['false_positive_rate']:.4f}"
                fnr = "—" if values["false_negative_rate"] is None else f"{values['false_negative_rate']:.4f}"
                lines.append(f"| {feature} | {value} | {values['support']} | {values['benign_support']} | {values['false_positive_count']}/{values['benign_support']} | {fpr} | {values['phishing_support']} | {values['false_negative_count']}/{values['phishing_support']} | {fnr} |")
    lines.extend(["", "## Interval methods and limitations", "", "The JSON report gives 95% Clopper–Pearson intervals for fixed-threshold binomial rates and percentile intervals from a seeded bootstrap that resamples whole registrable-domain groups. Cluster intervals estimate variation under this dataset's domain groups; they do not establish source independence. Dataset provenance, labels, source IDs, and timestamps remain unresolved/unavailable.", "",
                  "## Reproduction", "", "From repository root, with the ML environment installed:", "", "```powershell", "$env:PYTHONPATH = \"$(Get-Location)\\backend;$(Get-Location)\\ml-training\\url-phishing-mitake-v0.1.0\"", "python ml-training\\url-phishing-mitake-v0.1.0\\analyze_errors.py `", "  ml-training\\url-phishing-mitake-v0.1.0\\data\\prepared.csv `", "  ml-training\\url-phishing-mitake-v0.1.0\\models\\url-char-tfidf-mitake-v0.1.0-research-1ea71ccf.joblib `", "  --baseline ml-training\\url-phishing-mitake-v0.1.0\\reports\\evaluation.json `", "  --output ml-training\\url-phishing-mitake-v0.1.0\\analysis\\run-YYYYMMDD `", "  --replicates 1000", "```", ""])
    (output / "error-analysis.md").write_text("\n".join(lines), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Exploratory, aggregate-only analysis of fixed URL model partitions")
    parser.add_argument("prepared", type=Path)
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=440221)
    parser.add_argument("--replicates", type=int, default=1000)
    args = parser.parse_args()
    if args.replicates < 100:
        parser.error("--replicates must be at least 100")
    result = analyze(args.prepared, args.artifact, args.baseline, args.output, seed=args.seed, replicates=args.replicates)
    print(json.dumps({"output": str(args.output.resolve()), "threshold": result["fixed_threshold"], "partitions": {k: {"FPR": v["false_positive_rate"], "FNR": v["false_negative_rate"]} for k,v in result["partitions"].items()}}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
