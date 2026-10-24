"""Audit and prepare the local URL-Phish CSV without fetching any URLs."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

from app.services.url_model_features import normalize_url

REFERENCE_COLUMNS = {"url", "dom", "tld"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def prepare(source: Path, output: Path, report_path: Path) -> dict:
    source, output, report_path = source.resolve(), output.resolve(), report_path.resolve()
    if not source.is_file() or source in {output, report_path} or output == report_path:
        raise ValueError("Expected distinct input, prepared output, and report files")

    labels: dict[str, set[int]] = defaultdict(set)
    rows: dict[str, int] = {}
    counts: Counter[str] = Counter()
    missing: Counter[str] = Counter()
    malformed = changed = duplicate = 0
    with source.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        columns = reader.fieldnames or []
        if len(columns) != 26 or not REFERENCE_COLUMNS | {"label"} <= set(columns):
            raise ValueError("Expected the documented 26-column URL-Phish schema")
        feature_columns = set(columns) - REFERENCE_COLUMNS - {"label"}
        if len(feature_columns) != 22:
            raise ValueError("Expected 22 numeric feature columns")
        for raw in reader:
            counts[raw.get("label", "")] += 1
            for key, value in raw.items():
                if value is None or not value.strip():
                    missing[key] += 1
            raw_url = (raw.get("url") or "").strip()
            label = (raw.get("label") or "").strip()
            if not raw_url or label not in {"0", "1"}:
                continue
            try:
                # Validate every supplied feature rather than silently accepting bad cells.
                for key in feature_columns:
                    if raw.get(key, "").strip():
                        float(raw[key])
            except (ValueError, TypeError):
                continue
            url = normalize_url(raw_url)
            if not url:
                malformed += 1
                continue
            changed += url != raw_url
            y = int(label)
            labels[url].add(y)
            if url in rows:
                duplicate += 1
            else:
                rows[url] = y

    conflicts = {url for url, values in labels.items() if len(values) > 1}
    for url in conflicts:
        rows.pop(url, None)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["url", "label", "source_category"])
        writer.writeheader()
        writer.writerows({"url": url, "label": y, "source_category": "phishing" if y else "benign"}
                         for url, y in rows.items())

    report = {
        "prepared_at_utc": datetime.now(UTC).isoformat(),
        "source_file": source.name, "source_sha256": sha256(source), "source_bytes": source.stat().st_size,
        "source_rows": sum(counts.values()), "source_label_counts": dict(counts),
        "binary_label_mapping": {"0": "benign", "1": "phishing"},
        "source_columns": columns, "feature_columns_validated_but_not_used": sorted(feature_columns),
        "reference_columns_excluded": sorted(REFERENCE_COLUMNS), "missing_cells_by_column": dict(missing),
        "malformed_urls": malformed, "normalized_urls_changed": changed,
        "duplicate_normalized_rows": duplicate, "conflicting_normalized_urls_excluded": len(conflicts),
        "prepared_rows": len(rows), "prepared_label_counts": dict(Counter(str(y) for y in rows.values())),
        "prepared_sha256": sha256(output),
        "provenance": "Local file schema matches URL-Phish; local file revision is not verified against the publisher.",
        "limitations": ["Publisher page row count differs from local row count.",
                        "No timestamps or collection-source IDs are present for temporal/source holdouts.",
                        "Training uses raw normalized URL text; validated engineered values are not model inputs.",
                        "URLs were not fetched or resolved."],
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare(args.source, args.output, args.report), indent=2))
