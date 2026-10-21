"""Prepare a local ``url,type`` malicious-URL CSV without fetching its URLs.

This adapter preserves source categories while deriving the documented binary target:
benign=0; phishing/defacement/malware=1. It never changes the input file.
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

from app.services.url_model_features import group_key, normalize_url

MALICIOUS_CATEGORIES = {"phishing", "defacement", "malware"}
LABELS = {"benign": 0, **{category: 1 for category in MALICIOUS_CATEGORIES}}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def prepare(input_path: Path, output_path: Path, report_path: Path, *, source_url: str | None = None,
            license_name: str | None = None) -> dict:
    input_path = input_path.resolve()
    output_path = output_path.resolve()
    report_path = report_path.resolve()
    if not input_path.is_file():
        raise FileNotFoundError(input_path)
    if input_path in (output_path, report_path) or output_path == report_path:
        raise ValueError("Input, prepared output, and report must be separate files")
    if input_path.suffix.lower() != ".csv":
        raise ValueError("Input must be a CSV file")

    original_sha256 = _sha256(input_path)
    category_counts: Counter[str] = Counter()
    missing_url = missing_label = malformed = unknown_label = duplicate_rows = 0
    exact_labels: dict[str, set[str]] = defaultdict(set)
    exact_counts: Counter[str] = Counter()
    records: dict[str, dict[str, str | int]] = {}
    hostname_labels: dict[str, set[str]] = defaultdict(set)
    hostname_counts: Counter[str] = Counter()
    registrable_domains: set[str] = set()
    registrable_domain_labels: dict[str, set[str]] = defaultdict(set)

    with input_path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not {"url", "type"}.issubset(reader.fieldnames or []):
            raise ValueError("CSV must have url and type columns")
        for row in reader:
            raw_url = (row.get("url") or "").strip()
            original_label = (row.get("type") or "").strip().lower()
            if not raw_url:
                missing_url += 1
                continue
            if not original_label:
                missing_label += 1
                continue
            if original_label not in LABELS:
                unknown_label += 1
                continue
            category_counts[original_label] += 1
            url = normalize_url(raw_url)
            if not url:
                malformed += 1
                continue
            exact_labels[raw_url].add(original_label)
            exact_counts[raw_url] += 1
            host = (urlsplit(url).hostname or "").lower().rstrip(".")
            if host:
                hostname_labels[host].add(original_label)
                hostname_counts[host] += 1
                domain = group_key(url)
                if domain:
                    registrable_domains.add(domain)
                    registrable_domain_labels[domain].add(original_label)
            if url in records:
                duplicate_rows += 1
                continue
            records[url] = {"url": url, "label": LABELS[original_label],
                            "source_category": original_label, "original_label": original_label}

    conflicting_exact_urls = sum(len(labels) > 1 for labels in exact_labels.values())
    # Exclude every normalized URL whose source labels disagree, regardless of row order.
    normalized_labels: dict[str, set[str]] = defaultdict(set)
    with input_path.open("r", encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            label = (row.get("type") or "").strip().lower()
            url = normalize_url((row.get("url") or "").strip())
            if url and label in LABELS:
                normalized_labels[url].add(label)
    conflicting_normalized_urls = {url for url, labels in normalized_labels.items() if len(labels) > 1}
    for url in conflicting_normalized_urls:
        records.pop(url, None)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["url", "label", "source_category", "original_label"])
        writer.writeheader()
        writer.writerows(records.values())

    binary_counts = Counter(str(row["label"]) for row in records.values())
    report = {
        "prepared_at_utc": datetime.now(UTC).isoformat(),
        "input_file": input_path.name,
        "input_sha256": original_sha256,
        "input_bytes": input_path.stat().st_size,
        "source_url": source_url,
        "license": license_name,
        "provenance_note": "Source URL and license are recorded only when explicitly supplied; a CSV alone does not establish either.",
        "input_rows": sum(category_counts.values()) + missing_url + missing_label + unknown_label,
        "source_category_counts": dict(category_counts),
        "binary_label_definition": {"0": "benign source category", "1": "phishing, defacement, or malware source category"},
        "clean_rows": len(records),
        "binary_label_counts": dict(binary_counts),
        "missing_url_rows": missing_url,
        "missing_label_rows": missing_label,
        "unknown_label_rows": unknown_label,
        "malformed_url_rows": malformed,
        "duplicate_normalized_url_rows": duplicate_rows,
        "exact_duplicate_url_rows": sum(count - 1 for count in exact_counts.values()),
        "conflicting_exact_url_keys": conflicting_exact_urls,
        "conflicting_normalized_urls_excluded": len(conflicting_normalized_urls),
        "unique_hostnames": len(hostname_labels),
        "unique_registrable_domains_estimate": len(registrable_domains),
        "registrable_domains_by_source_category": {
            category: sum(category in labels for labels in registrable_domain_labels.values())
            for category in sorted(LABELS)
        },
        "registrable_domains_with_multiple_source_categories": sum(
            len(labels) > 1 for labels in registrable_domain_labels.values()
        ),
        "hostnames_repeated": sum(count > 1 for count in hostname_counts.values()),
        "hostnames_with_multiple_source_categories": sum(len(labels) > 1 for labels in hostname_labels.values()),
        "dates_available": False,
        "normalization": "HTTP(S) scheme and IDNA hostname normalized; fragments and credentials removed; path and query preserved",
        "urls_fetched": False,
        "output_file": output_path.name,
        "output_sha256": _sha256(output_path),
        "limitations": [
            "Labels are source assertions and their collection/verification dates are unavailable in this CSV.",
            "Binary malicious means any of phishing, defacement, or malware; the binary model cannot identify the category.",
            "This report does not independently verify source provenance or license terms.",
        ],
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("report", type=Path)
    parser.add_argument("--source-url")
    parser.add_argument("--license")
    args = parser.parse_args()
    try:
        print(json.dumps(prepare(args.input, args.output, args.report, source_url=args.source_url,
                                 license_name=args.license), indent=2))
    except (OSError, ValueError, csv.Error) as exc:
        print(f"dataset preparation failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
