from __future__ import annotations

import argparse
import csv
import hashlib
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

from common import LABEL_MAP, SOURCE_URL, digest, domain_group, normalize_url, sha256_file, split_name, write_json


def _scan(path: Path, url_column: str, label_column: str, *, output_path: Path | None = None,
          reference: Path | None = None) -> dict:
    path = path.resolve()
    if not path.is_file() or path.suffix.lower() != ".csv":
        raise ValueError("Input must be an existing CSV file")
    if output_path is not None and output_path.resolve() in {path, (reference.resolve() if reference else None)}:
        raise ValueError("Prepared output must not overwrite a source dataset")

    source_counts: Counter[str] = Counter()
    missing_url = missing_label = unknown_label = malformed = malformed_rows = 0
    exact_counts: Counter[bytes] = Counter()
    exact_label_bits: dict[bytes, int] = defaultdict(int)
    normalized_counts: Counter[bytes] = Counter()
    normalized_label_bits: dict[bytes, int] = defaultdict(int)
    normalized_domain: dict[bytes, str] = {}
    domain_counts: Counter[str] = Counter()
    domain_label_bits: dict[str, int] = defaultdict(int)
    normalized_changed = 0
    rows = 0

    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or not {url_column, label_column}.issubset(reader.fieldnames):
            raise ValueError(f"CSV must include columns {url_column!r} and {label_column!r}")
        for row in reader:
            rows += 1
            if None in row:
                malformed_rows += 1
                continue
            raw_url = (row.get(url_column) or "").strip()
            raw_label = (row.get(label_column) or "").strip()
            if not raw_url:
                missing_url += 1
                continue
            if not raw_label:
                missing_label += 1
                continue
            if raw_label not in LABEL_MAP:
                unknown_label += 1
                continue
            label = LABEL_MAP[raw_label]
            source_counts[raw_label] += 1
            url = normalize_url(raw_url)
            if not url:
                malformed += 1
                continue
            if url != raw_url:
                normalized_changed += 1
            group = domain_group(url)
            if not group:
                malformed += 1
                continue
            bit = 1 << label
            exact_key = hashlib.sha256(raw_url.encode("utf-8")).digest()
            normalized_key = hashlib.sha256(url.encode("utf-8")).digest()
            exact_counts[exact_key] += 1
            exact_label_bits[exact_key] |= bit
            normalized_counts[normalized_key] += 1
            normalized_label_bits[normalized_key] |= bit
            normalized_domain[normalized_key] = digest(group)
            domain_counts[digest(group)] += 1
            domain_label_bits[digest(group)] |= bit

    exact_conflict_keys = {key for key, bits in exact_label_bits.items() if bits == 3}
    normalized_conflict_keys = {key for key, bits in normalized_label_bits.items() if bits == 3}
    exact_duplicate_rows = sum(n - 1 for n in exact_counts.values() if n > 1)
    normalized_duplicate_rows = sum(n - 1 for n in normalized_counts.values() if n > 1)
    conflicting_rows = sum(normalized_counts[key] for key in normalized_conflict_keys)
    split_domain_sets = {name: set() for name in ("train", "validation", "test")}
    for group_hash in domain_counts:
        split_domain_sets[split_name(group_hash)].add(group_hash)
    overlap = {
        "train_validation": len(split_domain_sets["train"] & split_domain_sets["validation"]),
        "train_test": len(split_domain_sets["train"] & split_domain_sets["test"]),
        "validation_test": len(split_domain_sets["validation"] & split_domain_sets["test"]),
    }

    reference_result = None
    if reference is not None:
        ref_urls: set[bytes] = set()
        ref_domains: set[str] = set()
        ref_rows = ref_valid = 0
        ref_labels: Counter[str] = Counter()
        with reference.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if not reader.fieldnames or not {"url", "type"}.issubset(reader.fieldnames):
                raise ValueError("Reference dataset must contain url,type columns")
            for row in reader:
                ref_rows += 1
                ref_labels[(row.get("type") or "").strip().lower()] += 1
                normalized = normalize_url(row.get("url") or "")
                if not normalized:
                    continue
                ref_valid += 1
                ref_urls.add(hashlib.sha256(normalized.encode("utf-8")).digest())
                group = domain_group(normalized)
                if group:
                    ref_domains.add(digest(group))
        candidate_url_keys = set(normalized_counts)
        candidate_domains = set(domain_counts)
        reference_result = {
            "reference_file": reference.name,
            "reference_sha256": sha256_file(reference),
            "reference_rows": ref_rows,
            "reference_valid_url_rows": ref_valid,
            "reference_source_label_counts": dict(ref_labels),
            "shared_normalized_url_hashes": len(candidate_url_keys & ref_urls),
            "shared_registrable_domain_hashes": len(candidate_domains & ref_domains),
            "note": "Hash intersections are counts only; reference overlap means this candidate is not an independent source-level evaluation of that dataset.",
        }

    report = {
        "created_at_utc": datetime.now(UTC).isoformat(),
        "source_file": path.name,
        "source_sha256": sha256_file(path),
        "source_bytes": path.stat().st_size,
        "source_url_claimed": SOURCE_URL,
        "source_revision": "not recorded; local copy could not be byte-verified against an immutable revision",
        "license_declared_by_source_card": "CC BY-SA 4.0",
        "license_scope_note": "This is the Hugging Face repository metadata declaration, not independent proof of upstream rights. Local research only; no dataset/model redistribution, deployment, or containerization is authorized by this experiment.",
        "label_mapping": {"0": "benign", "1": "phishing"},
        "label_mapping_basis": "User-confirmed in the conversation on 2026-10-21; not defined in the dataset README/card.",
        "input_rows": rows,
        "source_label_counts": dict(source_counts),
        "missing_url_rows": missing_url,
        "missing_label_rows": missing_label,
        "unknown_label_rows": unknown_label,
        "malformed_csv_rows": malformed_rows,
        "malformed_or_unsupported_url_rows": malformed,
        "valid_unique_normalized_urls": len(normalized_counts),
        "exact_duplicate_rows": exact_duplicate_rows,
        "exact_conflicting_url_keys": len(exact_conflict_keys),
        "normalized_duplicate_rows": normalized_duplicate_rows,
        "normalized_conflicting_url_keys": len(normalized_conflict_keys),
        "rows_excluded_for_normalized_label_conflict": conflicting_rows,
        "normalization_changed_rows": normalized_changed,
        "registrable_domain_groups": len(domain_counts),
        "registrable_domains_with_both_labels": sum(bits == 3 for bits in domain_label_bits.values()),
        "grouping": "tldextract Public Suffix List bundled snapshot; group key hashed in prepared data and reports",
        "group_split_domain_overlap": overlap,
        "timestamps_available": False,
        "source_ids_available": False,
        "urls_fetched": False,
        "raw_url_values_in_report": False,
        "reference_overlap": reference_result,
        "limitations": [
            "The dataset card README is empty and does not define integer label meanings; mapping is user-confirmed.",
            "The local file's exact source revision is not recorded or byte-verified against the hosted copy.",
            "Historical source, timestamps, label verification process, and upstream rights are undocumented.",
            "Normalized duplicates use the AnaRisk inference normalizer; source URL is retained only in the unchanged original file.",
        ],
    }

    if output_path is not None:
        output_path = output_path.resolve()
        report_path = output_path.with_name("data-quality.json")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        seen: set[bytes] = set()
        kept = Counter()
        with path.open("r", encoding="utf-8-sig", newline="") as src, output_path.open("w", encoding="utf-8", newline="") as dst:
            reader = csv.DictReader(src)
            writer = csv.DictWriter(dst, fieldnames=["url", "label", "domain_group_hash"])
            writer.writeheader()
            for row in reader:
                raw_url = (row.get(url_column) or "").strip()
                raw_label = (row.get(label_column) or "").strip()
                if not raw_url or raw_label not in LABEL_MAP:
                    continue
                normalized = normalize_url(raw_url)
                if not normalized:
                    continue
                key = hashlib.sha256(normalized.encode("utf-8")).digest()
                if normalized_label_bits.get(key) == 3 or key in seen:
                    continue
                group = domain_group(normalized)
                if not group:
                    continue
                seen.add(key)
                label = LABEL_MAP[raw_label]
                kept[str(label)] += 1
                writer.writerow({"url": normalized, "label": label, "domain_group_hash": digest(group)})
        report.update({
            "prepared_file": output_path.name,
            "prepared_sha256": sha256_file(output_path),
            "prepared_rows": sum(kept.values()),
            "prepared_label_counts": dict(kept),
            "prepared_bytes": output_path.stat().st_size,
        })
        write_json(report_path, report)

        manifest = {
            "dataset_id": "Mitake/PhishingURLsANDBenignURLs",
            "dataset_url": SOURCE_URL,
            "source_file": path.name,
            "source_sha256": report["source_sha256"],
            "source_revision": report["source_revision"],
            "access_date": datetime.now(UTC).date().isoformat(),
            "source_card_license": "CC BY-SA 4.0",
            "license_evidence": SOURCE_URL,
            "attribution": "Mitake, PhishingURLsANDBenignURLs, https://huggingface.co/datasets/Mitake/PhishingURLsANDBenignURLs, CC BY-SA 4.0; changes: URL normalization, duplicate/conflict audit, and derived train/validation/test partitions.",
            "label_mapping": report["label_mapping"],
            "label_mapping_basis": report["label_mapping_basis"],
            "intended_use": "private offline anti-phishing research only",
            "distribution_status": "not authorized by this workflow; do not redistribute dataset or derived model",
            "source_provenance_status": "unverified local copy; hosted card matches name/schema/row count/size, but immutable source revision and exact file hash were not established",
            "rights_limitation": "The card declares CC BY-SA 4.0. This records the declaration only; upstream rights and whether model weights constitute a share-alike adaptation have not been independently determined.",
        }
        write_json(output_path.parent.parent / "provenance-manifest.json", manifest)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit/prepare the local Mitake CSV without fetching any URL")
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, help="Write a deduplicated URL-only training CSV and reports")
    parser.add_argument("--reference", type=Path, help="Optional legacy url,type CSV for overlap counts")
    parser.add_argument("--url-column", default="url")
    parser.add_argument("--label-column", default="label")
    args = parser.parse_args()
    report = _scan(args.input, args.url_column, args.label_column, output_path=args.output, reference=args.reference)
    if args.output is None:
        print("Audit only. No URL values are included.")
        print(f"rows={report['input_rows']} valid_unique={report['valid_unique_normalized_urls']} sha256={report['source_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
