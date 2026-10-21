"""Load and quality-check the known two-column phishing-email corpus."""
from __future__ import annotations

import csv
import hashlib
from collections import Counter, defaultdict
from pathlib import Path

from email_model import normalize_email_text

SEED = 20261021
LABEL_MAP = {"0": 0, "1": 1}


def canonical_text(value: str) -> str:
    return " ".join(value.casefold().split())


def _hash_text(value: str) -> str:
    return hashlib.sha256(canonical_text(value).encode("utf-8", "replace")).hexdigest()


def load_dataset(path: Path, *, minimum_rows: int = 100) -> tuple[list[dict], dict]:
    path = path.resolve()
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    file_hash = digest.hexdigest()
    rows_by_text: dict[str, dict] = {}
    labels_by_text: dict[str, set[int]] = defaultdict(set)
    label_counts: Counter[str] = Counter()
    missing_text = missing_label = invalid_label = malformed_rows = duplicates_removed = 0
    truncated_rows = 0
    csv.field_size_limit(64 * 1024 * 1024)
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != ["text_combined", "label"]:
            raise ValueError("Expected the inspected source schema: text_combined,label")
        for row in reader:
            text = row.get("text_combined") or ""
            label_raw = (row.get("label") or "").strip()
            if not label_raw:
                missing_label += 1
                continue
            if label_raw not in LABEL_MAP:
                invalid_label += 1
                continue
            label = LABEL_MAP[label_raw]
            label_counts[label_raw] += 1
            if not text.strip():
                missing_text += 1
                continue
            text_hash = _hash_text(text)
            labels_by_text[text_hash].add(label)
            normalized, truncated = normalize_email_text(text)
            truncated_rows += int(truncated)
            if not normalized:
                malformed_rows += 1
                continue
            if text_hash in rows_by_text:
                duplicates_removed += 1
                continue
            rows_by_text[text_hash] = {"text": normalized, "text_hash": text_hash, "label": label}

    conflicting_hashes = {key for key, labels in labels_by_text.items() if len(labels) > 1}
    for key in conflicting_hashes:
        rows_by_text.pop(key, None)
    rows = list(rows_by_text.values())
    if len(rows) < minimum_rows or {row["label"] for row in rows} != {0, 1}:
        raise ValueError(f"Dataset must contain at least {minimum_rows} valid rows and both classes")
    prepared_hash = hashlib.sha256()
    for row in sorted(rows, key=lambda item: item["text_hash"]):
        prepared_hash.update(row["text_hash"].encode("ascii"))
        prepared_hash.update(b":")
        prepared_hash.update(str(row["label"]).encode("ascii"))
        prepared_hash.update(b"\n")
    report = {
        "input_sha256": file_hash,
        "prepared_rows": len(rows),
        "prepared_sha256": prepared_hash.hexdigest(),
        "prepared_label_counts": dict(Counter(str(row["label"]) for row in rows)),
        "source_label_counts_before_cleaning": dict(label_counts),
        "missing_text_rows": missing_text,
        "missing_label_rows": missing_label,
        "invalid_label_rows": invalid_label,
        "malformed_or_empty_after_preprocessing_rows": malformed_rows,
        "duplicate_normalized_text_rows_removed": duplicates_removed,
        "conflicting_duplicate_text_groups_excluded": len(conflicting_hashes),
        "truncated_rows": truncated_rows,
        "normalization": "NFKC; email addresses, URLs and IPv4 values replaced with tokens; whitespace collapsed; first 200,000 characters retained.",
    }
    return rows, report


def grouped_split(rows: list[dict], seed: int = SEED) -> dict[str, list[dict]]:
    result = {"train": [], "validation": [], "test": []}
    for row in rows:
        bucket = int.from_bytes(hashlib.sha256(f"{seed}:{row['text_hash']}".encode()).digest()[:8], "big") % 100
        name = "train" if bucket < 70 else "validation" if bucket < 85 else "test"
        result[name].append(row)
    return result
