"""Prepare the Training.parquet / Testing.parquet phishing URL pair for URL-only research."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from app.services.url_model_features import group_key, normalize_url

LABELS = {"legitimate": 0, "phishing": 1}
EXPECTED = ("Training.parquet", "Testing.parquet")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def prepare(data_dir: Path, output_path: Path, report_path: Path) -> dict:
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise RuntimeError("Install backend/requirements-ml.txt to read Parquet") from exc

    data_dir = data_dir.resolve()
    output_path = output_path.resolve()
    report_path = report_path.resolve()
    files = {name: data_dir / name for name in EXPECTED}
    if any(not path.is_file() for path in files.values()):
        raise FileNotFoundError("Expected Training.parquet and Testing.parquet in the supplied data directory")
    if output_path in files.values() or report_path in files.values() or output_path == report_path:
        raise ValueError("Source Parquet files, prepared output, and report must be separate")

    source_rows: dict[str, list[tuple[str, str]]] = {}
    source_metadata: dict[str, dict[str, int | str]] = {}
    source_nulls: dict[str, dict[str, int]] = {}
    rows_by_label: Counter[str] = Counter()
    missing_url = missing_status = malformed = unknown_status = 0
    input_columns: set[str] = set()
    normalized_status: dict[str, set[str]] = defaultdict(set)
    normalized_sources: dict[str, set[str]] = defaultdict(set)
    for name, path in files.items():
        parquet = pq.ParquetFile(path)
        source_metadata[name] = {
            "bytes": path.stat().st_size,
            "sha256": _sha256(path),
            "rows": parquet.metadata.num_rows,
        }
        input_columns.update(parquet.schema.names)
        if not {"url", "status"}.issubset(parquet.schema.names):
            raise ValueError(f"{name} must contain url and status columns")
        current: list[tuple[str, str]] = []
        table = pq.read_table(path)
        source_nulls[name] = {field.name: table[field.name].null_count for field in table.schema
                              if table[field.name].null_count}
        for raw, status in zip(table["url"].to_pylist(), table["status"].to_pylist()):
            if raw is None or not str(raw).strip():
                missing_url += 1
                continue
            if status is None or not str(status).strip():
                missing_status += 1
                continue
            label = str(status).strip().lower()
            if label not in LABELS:
                unknown_status += 1
                continue
            rows_by_label[label] += 1
            url = normalize_url(str(raw))
            if not url:
                malformed += 1
                continue
            current.append((url, label))
            normalized_status[url].add(label)
            normalized_sources[url].add(name)
        source_rows[name] = current

    source_domain_sets = {
        name: {group_key(url) for url, _ in rows if group_key(url)}
        for name, rows in source_rows.items()
    }
    all_records: dict[str, dict[str, str | int]] = {}
    source_occurrences: Counter[str] = Counter()
    for name in EXPECTED:
        for url, original_label in source_rows[name]:
            source_occurrences[url] += 1
            if url not in all_records:
                all_records[url] = {
                    "url": url, "label": LABELS[original_label],
                    "source_category": original_label, "original_label": original_label,
                    "source_files": name,
                }
    conflicts = {url for url, labels in normalized_status.items() if len(labels) > 1}
    for url in conflicts:
        all_records.pop(url, None)
    for url, row in all_records.items():
        row["source_files"] = ";".join(name for name in EXPECTED if name in normalized_sources[url])

    output_path.parent.mkdir(parents=True, exist_ok=True)
    import csv

    with output_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["url", "label", "source_category", "original_label", "source_files"])
        writer.writeheader()
        writer.writerows(all_records.values())

    domain_labels: dict[str, set[str]] = defaultdict(set)
    for url, row in all_records.items():
        domain = group_key(url)
        if domain:
            domain_labels[domain].add(str(row["source_category"]))
    report = {
        "prepared_at_utc": datetime.now(UTC).isoformat(),
        "source_files": source_metadata,
        "missing_values_by_source_file": source_nulls,
        "input_rows": sum(rows_by_label.values()) + missing_url + missing_status + unknown_status,
        "source_label_counts_before_deduplication": dict(rows_by_label),
        "binary_label_definition": {"0": "legitimate", "1": "phishing"},
        "training_input_columns": ["url"],
        "target_column_excluded_from_features": "status",
        "ignored_non_url_columns": sorted(input_columns - {"url", "status"}),
        "ignored_non_url_column_count": len(input_columns - {"url", "status"}),
        "missing_url_rows": missing_url,
        "missing_status_rows": missing_status,
        "unknown_status_rows": unknown_status,
        "malformed_url_rows": malformed,
        "normalized_duplicate_rows_removed": sum(source_occurrences.values()) - len(source_occurrences),
        "conflicting_normalized_urls_excluded": len(conflicts),
        "clean_rows": len(all_records),
        "clean_label_counts": dict(Counter(str(row["original_label"]) for row in all_records.values())),
        "unique_hostnames": len({urlsplit(url).hostname for url in all_records}),
        "unique_registrable_domains_estimate": len(domain_labels),
        "registrable_domains_with_multiple_source_categories": sum(len(labels) > 1 for labels in domain_labels.values()),
        "original_split_registrable_domain_overlap": len(source_domain_sets[EXPECTED[0]] & source_domain_sets[EXPECTED[1]]),
        "original_split_exact_normalized_url_overlap": len(
            {url for url, _ in source_rows[EXPECTED[0]]} & {url for url, _ in source_rows[EXPECTED[1]]}
        ),
        "original_splits_repartitioned": True,
        "grouping_note": "Rows from both source files are combined and reassigned by registrable domain for evaluation because the provided source split overlaps on domains.",
        "provenance_and_license": "Not established by the Parquet schema or filenames; verify the source dataset card before redistribution.",
        "timestamps_available": False,
        "urls_fetched": False,
        "output_file": output_path.name,
        "output_sha256": _sha256(output_path),
        "limitations": [
            "Only URL string text is used for learning; the excluded columns include page, DNS, popularity, and external report fields.",
            "The dataset's source, collection dates, label verification, and license are not embedded in these Parquet files.",
            "A domain-based random split cannot estimate performance on future URLs.",
        ],
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data_dir", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(prepare(args.data_dir, args.output, args.report), indent=2))
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"dataset preparation failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
