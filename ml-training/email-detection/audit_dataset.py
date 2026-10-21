"""Audit a local labeled-email CSV without printing or storing message contents."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from statistics import median


LABEL_HEADER = re.compile(r"label|target|class|category|type|verdict", re.I)
TEXT_HEADER = re.compile(r"email|message|body|content|subject|text|mail", re.I)
GROUP_HEADER = re.compile(r"sender|campaign|thread|source|message.?id|email.?id|group", re.I)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _missing(value: str | None) -> bool:
    return value is None or not value.strip()


def audit(input_path: Path, report_path: Path) -> dict:
    # Some email corpora contain complete quoted threads that exceed csv's small default cap.
    csv.field_size_limit(64 * 1024 * 1024)
    input_path = input_path.resolve()
    report_path = report_path.resolve()
    if input_path == report_path:
        raise ValueError("Audit report must not overwrite the source dataset")
    if not input_path.is_file():
        raise FileNotFoundError(input_path)

    counts: Counter[str] = Counter()
    missing: Counter[str] = Counter()
    label_counts: dict[str, Counter[str]] = defaultdict(Counter)
    marker_counts: dict[str, Counter[str]] = defaultdict(Counter)
    unique_groups: dict[str, set[str]] = defaultdict(set)
    row_hashes: set[str] = set()
    text_label_sets: dict[str, set[str]] = defaultdict(set)
    text_seen: Counter[str] = Counter()
    text_lengths: list[int] = []

    with input_path.open("r", encoding="utf-8-sig", newline="") as stream:
        sample = stream.read(16_384)
        stream.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|")
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(stream, dialect=dialect)
        columns = reader.fieldnames or []
        if not columns:
            raise ValueError("CSV has no header row")
        label_columns = [name for name in columns if LABEL_HEADER.search(name)]
        text_columns = [name for name in columns if TEXT_HEADER.search(name) and name not in label_columns]
        group_columns = [name for name in columns if GROUP_HEADER.search(name) and name not in label_columns]

        # Prefer one canonical email/message text column for duplicate analysis.
        preferred = ("email_text", "text", "body", "message", "email", "content")
        text_column = next((name for key in preferred for name in text_columns if name.strip().lower() == key),
                           text_columns[0] if text_columns else None)
        label_column = label_columns[0] if len(label_columns) == 1 else None

        for row in reader:
            counts["rows"] += 1
            for column in columns:
                value = row.get(column)
                if _missing(value):
                    missing[column] += 1
            normalized_row = "\x1f".join((row.get(column) or "").strip() for column in columns)
            row_hash = hashlib.sha256(normalized_row.encode("utf-8", "replace")).hexdigest()
            if row_hash in row_hashes:
                counts["duplicate_full_rows_after_cell_trim"] += 1
            row_hashes.add(row_hash)

            label = (row.get(label_column) or "").strip().casefold() if label_column else ""
            if label_column and label:
                label_counts[label_column][label] += 1
            for column in group_columns:
                value = (row.get(column) or "").strip()
                if value:
                    unique_groups[column].add(value)

            text = (row.get(text_column) or "") if text_column else ""
            if text_column:
                text_lengths.append(len(text))
                lowered = text.casefold()
                for marker in ("from:", "to:", "subject:", "date:", "message-id:", "received:",
                               "mime-version:", "content-type:", "unsubscribe", "http", "www.", "<html"):
                    if marker in lowered:
                        marker_counts[label][marker] += 1
                normalized_text = " ".join(text.casefold().split())
                if normalized_text:
                    text_hash = hashlib.sha256(normalized_text.encode("utf-8", "replace")).hexdigest()
                    text_seen[text_hash] += 1
                    if label:
                        text_label_sets[text_hash].add(label)

    ambiguous_text_keys = sum(len(labels) > 1 for labels in text_label_sets.values())
    duplicate_text_keys = sum(n > 1 for n in text_seen.values())
    labels = dict(label_counts[label_column]) if label_column else {}
    lower_labels = {key.casefold() for key in labels}
    phish_labels = {key for key in lower_labels if any(token in key for token in ("phish", "fraud", "malicious", "credential"))}
    nonphish_labels = {key for key in lower_labels if any(token in key for token in ("ham", "legitimate", "benign", "safe", "non-phish", "nonphish"))}
    spam_only = lower_labels and all(any(token in key for token in ("spam", "ham", "not spam", "non-spam")) for key in lower_labels)
    suitable_labels = bool(phish_labels and nonphish_labels) and not spam_only

    report = {
        "audited_at_utc": datetime.now(UTC).isoformat(),
        "input_file": input_path.name,
        "input_bytes": input_path.stat().st_size,
        "input_sha256": sha256_file(input_path),
        "rows": counts["rows"],
        "columns": columns,
        "candidate_text_columns": text_columns,
        "selected_text_column_for_duplicate_audit": text_column,
        "candidate_label_columns": label_columns,
        "selected_label_column": label_column,
        "label_counts": labels,
        "format_marker_presence_by_label": {label: dict(counts) for label, counts in marker_counts.items()},
        "missing_values_by_column": {column: missing[column] for column in columns if missing[column]},
        "duplicate_full_rows_after_cell_trim": counts["duplicate_full_rows_after_cell_trim"],
        "duplicate_normalized_text_keys": duplicate_text_keys,
        "duplicate_text_keys_with_multiple_labels": ambiguous_text_keys,
        "text_length_characters": ({"min": min(text_lengths), "median": median(text_lengths), "max": max(text_lengths)}
                                    if text_lengths else None),
        "grouping_columns_available": group_columns,
        "nonempty_unique_values_by_grouping_column": {column: len(values) for column, values in unique_groups.items()},
        "label_semantics_appear_phishing_specific": suitable_labels,
        "spam_labels_only_or_ambiguous": bool(spam_only) or not suitable_labels,
        "published_source_candidate": "https://www.kaggle.com/datasets/naserabdullahalam/phishing-email-dataset",
        "published_source_candidate_schema_and_counts_match": (
            input_path.name == "phishing_email.csv" and columns == ["text_combined", "label"]
            and counts["rows"] == 82486 and labels == {"0": 39595, "1": 42891}
        ),
        "published_source_label_mapping": {"0": "legitimate", "1": "spam_or_phishing"},
        "published_source_license": "CC BY-SA 4.0 (Kaggle dataset card)",
        "local_copy_provenance_verified": False,
        "rights_limitation": "The matching source card reports CC BY-SA 4.0, but this local file has no version/source checksum manifest; constituent corpora may also carry separate terms.",
        "message_contents_written_to_report": False,
        "limitations": [
            "Label-name screening is a heuristic; consult the source documentation before treating labels as phishing-specific.",
            "Duplicate text hashing ignores case and whitespace but does not establish semantic equivalence.",
            "This audit does not establish label correctness, collection time, or data usage rights.",
        ],
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--report", type=Path, default=Path("reports/dataset-audit.json"))
    args = parser.parse_args()
    print(json.dumps(audit(args.input, args.report), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
