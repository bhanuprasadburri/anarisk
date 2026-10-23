"""Privacy-preserving inventory and overlap audit for candidate URL datasets.

No URLs are emitted. Dataset files are read-only; the PhishVN archive is inspected
in memory and never extracted.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import sys
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

csv.field_size_limit(min(sys.maxsize, 2**31 - 1))

ROOT = Path(__file__).resolve().parents[2]
MITAKE = ROOT / "ml-training/url-phishing-mitake-v0.1.0"
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(MITAKE))
from app.services.url_model_features import normalize_url  # noqa: E402
from common import domain_group  # noqa: E402

HERE = Path(__file__).resolve().parent
MAX_ARCHIVE_BYTES = 100 * 1024 * 1024
ALLOWED_ARCHIVE_SUFFIXES = {".csv", ".md", ".txt", ".cff", ".json", ".yml", ".yaml", ".toml"}


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def parse_timestamp(value: str | None) -> str | None:
    if not value or not value.strip():
        return None
    candidate = value.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(candidate).isoformat()
    except ValueError:
        return None


def inspect_zip(path: Path) -> tuple[dict[str, bytes], dict]:
    raw_hash = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            raw_hash.update(block)
    archive_info = {"file": path.name, "bytes": path.stat().st_size, "sha256": raw_hash.hexdigest()}
    if path.stat().st_size > MAX_ARCHIVE_BYTES:
        raise ValueError("archive exceeds configured compressed size limit")
    selected: dict[str, bytes] = {}
    total_uncompressed = 0
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        if len(infos) > 1000:
            raise ValueError("archive contains too many entries")
        for info in infos:
            name = info.filename
            pure = PurePosixPath(name)
            if pure.is_absolute() or ".." in pure.parts or "\\" in name or re.match(r"^[A-Za-z]:", name):
                raise ValueError("unsafe archive path")
            if info.flag_bits & 1:
                raise ValueError("encrypted archive entry is unsupported")
            if info.is_dir():
                continue
            if name != "LICENSE" and Path(name).suffix.lower() not in ALLOWED_ARCHIVE_SUFFIXES:
                raise ValueError("unexpected archive file type")
            total_uncompressed += info.file_size
            if total_uncompressed > MAX_ARCHIVE_BYTES or (info.file_size and info.file_size / max(info.compress_size, 1) > 200):
                raise ValueError("archive expansion limit exceeded")
            selected[name] = archive.read(info)
    manifest = selected.get("MANIFEST.txt", b"").decode("utf-8", errors="replace")
    expected: dict[str, str] = {}
    # Manifest lines are: SHA256  bytes  relative/path
    for line in manifest.splitlines():
        match = re.match(r"^([0-9a-fA-F]{64})\s+(.+?)\s+\(\d+ bytes\)$", line.strip())
        if match:
            expected[match.group(2).strip()] = match.group(1).lower()
    checks = {}
    for name, checksum in expected.items():
        actual = selected.get(name)
        checks[name] = {"expected_sha256": checksum, "actual_sha256": sha256_bytes(actual) if actual is not None else None,
                        "matches": actual is not None and sha256_bytes(actual) == checksum}
    archive_info.update({"entry_count": len(infos), "uncompressed_bytes": total_uncompressed,
                         "manifest_file_count": len(expected), "manifest_checks": checks,
                         "all_manifest_checks_match": bool(checks) and all(v["matches"] for v in checks.values())})
    return selected, archive_info


def read_rows(path: Path | None = None, content: bytes | None = None):
    if (path is None) == (content is None):
        raise ValueError("provide exactly one of path or content")
    if content is not None:
        stream = io.StringIO(content.decode("utf-8-sig"), newline="")
        reader = csv.DictReader(stream)
        if not reader.fieldnames:
            stream.close()
            raise ValueError("CSV has no header")
        headers = list(reader.fieldnames)
        def memory_rows():
            try:
                yield from reader
            finally:
                stream.close()
        return headers, memory_rows()
    def file_rows():
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if not reader.fieldnames:
                raise ValueError("CSV has no header")
            yield list(reader.fieldnames), reader
    # Read the header separately, then reopen for a one-pass stream.
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        headers = next(csv.reader(stream), None)
    if not headers:
        raise ValueError("CSV has no header")
    def iter_file_rows():
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            yield from reader
    return headers, iter_file_rows()


def audit_table(name: str, headers: list[str], rows: list[dict[str, str]], url_col: str,
                label_col: str | None, label_map: dict[str, int] | None, source_col: str | None = None,
                timestamp_col: str | list[str] | None = None, tier_col: str | None = None,
                split_col: str | None = None) -> tuple[dict, dict]:
    missing_cols = [c for c in (url_col, label_col) if c and c not in headers]
    if missing_cols:
        return {"name": name, "schema": headers, "rows": None, "schema_valid": False,
                "missing_required_columns": missing_cols}, {"urls": set(), "domains": set(), "labels": {}, "sources": Counter()}
    missing = Counter()
    raw_keys: set[str] = set()
    normalized_labels: dict[str, set[int]] = defaultdict(set)
    norm_occurrences = Counter()
    domain_labels: dict[str, set[int]] = defaultdict(set)
    domain_counts = Counter()
    source_counts = Counter()
    tier_counts = Counter()
    timestamp_cols = [timestamp_col] if isinstance(timestamp_col, str) else list(timestamp_col or [])
    timestamp_counts: dict[str, Counter] = defaultdict(Counter)
    timestamp_bounds: dict[str, list[str | None]] = {col: [None, None] for col in timestamp_cols}
    row_label_counts = Counter()
    split_counts = Counter()
    split_urls: dict[str, set[str]] = defaultdict(set)
    split_domains: dict[str, set[str]] = defaultdict(set)
    invalid_urls = invalid_labels = 0
    row_count = 0
    for row in rows:
        row_count += 1
        for col in headers:
            if row.get(col) is None or not row.get(col, "").strip():
                missing[col] += 1
        raw = (row.get(url_col) or "").strip()
        normalized = normalize_url(raw) if raw else ""
        if not normalized:
            invalid_urls += 1
            continue
        raw_keys.add(digest(raw))
        label = None
        if label_col:
            raw_label = (row.get(label_col) or "").strip().lower()
            if label_map is None or raw_label not in label_map:
                invalid_labels += 1
            else:
                label = label_map[raw_label]
                row_label_counts[str(label)] += 1
        key = digest(normalized)
        norm_occurrences[key] += 1
        group = domain_group(normalized)
        if group:
            dh = digest(group)
            domain_counts[dh] += 1
        if label is not None:
            normalized_labels[key].add(label)
            if group:
                domain_labels[dh].add(label)
        if source_col:
            source_counts[(row.get(source_col) or "").strip() or "<missing>"] += 1
        if tier_col:
            tier_counts[(row.get(tier_col) or "").strip() or "<missing>"] += 1
        split_name = (row.get(split_col) or "").strip() if split_col else ""
        if split_col:
            split_counts[split_name or "<missing>"] += 1
            if split_name:
                split_urls[split_name].add(key)
                if group:
                    split_domains[split_name].add(digest(group))
        for col in timestamp_cols:
            parsed = parse_timestamp(row.get(col))
            timestamp_counts[col]["parsed" if parsed else "missing_or_invalid"] += 1
            if parsed:
                bounds = timestamp_bounds[col]
                bounds[0] = parsed if bounds[0] is None else min(bounds[0], parsed)
                bounds[1] = parsed if bounds[1] is None else max(bounds[1], parsed)
    norm_keys = set(norm_occurrences)
    conflicted = {k for k, labels in normalized_labels.items() if len(labels) > 1}
    split_pairs = {}
    for i, left in enumerate(sorted(split_urls)):
        for right in sorted(split_urls)[i + 1:]:
            split_pairs[f"{left}__vs__{right}"] = {
                "normalized_url_overlap": len(split_urls[left] & split_urls[right]),
                "registrable_domain_overlap": len(split_domains[left] & split_domains[right]),
            }
    summary = {
        "name": name, "schema": headers, "rows": row_count, "schema_valid": True,
        "missing_values_by_column": dict(sorted(missing.items())), "invalid_or_unsupported_url_rows": invalid_urls,
        "invalid_or_ambiguous_label_rows": invalid_labels, "valid_normalized_urls": len(norm_keys),
        "exact_url_duplicates_beyond_first": max(0, row_count - invalid_urls - len(raw_keys)),
        "normalized_url_duplicates_beyond_first": sum(n - 1 for n in norm_occurrences.values()),
        "normalized_urls_with_conflicting_labels": len(conflicted),
        "mapped_label_row_counts": dict(sorted(row_label_counts.items())),
        "normalized_url_label_counts": {str(label): sum(label in labels for labels in normalized_labels.values()) for label in (0, 1)},
        "registrable_domain_groups": len(domain_counts),
        "domains_with_conflicting_labels": sum(len(labels) > 1 for labels in domain_labels.values()),
        "source_counts": dict(sorted(source_counts.items())), "tier_counts": dict(sorted(tier_counts.items())),
        "split_field": split_col, "split_counts": dict(sorted(split_counts.items())),
        "split_pair_overlap": split_pairs,
        "timestamp_field": timestamp_cols[0] if timestamp_cols else None,
        "timestamp_fields": timestamp_cols,
        "timestamp_parse_counts": {col: dict(counts) for col, counts in timestamp_counts.items()},
        "timestamp_ranges": {col: bounds for col, bounds in timestamp_bounds.items()},
        "timestamp_range": timestamp_bounds[timestamp_cols[0]] if timestamp_cols else None,
    }
    details = {"urls": norm_keys, "raw_urls": raw_keys, "domains": set(domain_counts),
               "labels": {k: next(iter(v)) for k, v in normalized_labels.items() if len(v) == 1}, "sources": source_counts}
    return summary, details


def compare(a: dict, b: dict) -> dict:
    au, bu = a["urls"], b["urls"]
    ar, br = a.get("raw_urls", set()), b.get("raw_urls", set())
    ad, bd = a["domains"], b["domains"]
    overlap = au & bu
    conflicts = sum(a["labels"].get(k) != b["labels"].get(k) for k in overlap
                    if k in a["labels"] and k in b["labels"])
    return {"left_unique_normalized_urls": len(au), "right_unique_normalized_urls": len(bu),
            "normalized_url_overlap": len(overlap), "left_overlap_fraction": len(overlap) / len(au) if au else None,
            "right_overlap_fraction": len(overlap) / len(bu) if bu else None,
            "left_unique_raw_url_values": len(ar), "right_unique_raw_url_values": len(br),
            "exact_raw_url_overlap": len(ar & br),
            "registrable_domain_overlap": len(ad & bd), "left_unique_domains": len(ad), "right_unique_domains": len(bd),
            "conflicting_labels_on_overlapping_urls": conflicts,
            "note": "Domain overlap is not URL overlap and neither alone establishes source independence."}


def validate_partition_isolation(partitions: dict[str, list[dict[str, str]]]) -> None:
    """Reject normalized URL/domain leakage across already assigned partitions."""
    seen_urls: dict[str, str] = {}
    seen_domains: dict[str, str] = {}
    for partition, rows in partitions.items():
        for row in rows:
            url_hash = row["url_hash"]
            domain_hash = row["domain_hash"]
            if url_hash in seen_urls and seen_urls[url_hash] != partition:
                raise ValueError("normalized URL crosses evaluation partitions")
            if domain_hash in seen_domains and seen_domains[domain_hash] != partition:
                raise ValueError("registrable domain crosses evaluation partitions")
            seen_urls[url_hash] = partition
            seen_domains[domain_hash] = partition


def deterministic_manifest(candidates: dict, acquisition: dict, rights: str, publisher_records: dict) -> dict:
    """Stable manifest payload; generated-at belongs in the run report, not this record."""
    return {"candidates": candidates, "acquisition": acquisition, "publisher_records": publisher_records,
            "data_rights": rights}


def inventory(data_dir: Path, out_dir: Path = HERE) -> tuple[dict, dict]:
    zip_path = data_dir / "PhishVN_v3.1.0_open.zip"
    phishvn_bytes, zip_meta = inspect_zip(zip_path) if zip_path.exists() else ({}, {"status": "not available locally"})
    definitions = [
        ("PhishVN_v3.1.0_open", "PhishVN", "url", "label", {"benign": 0, "phishing": 1}, "source", ["collected_at", "scraped_at"], "tier", "split"),
        ("PhiLegit-100K.local", "PhiLegit-100K.csv", "URL", "label_legit_1_phish_0", {"0": 1, "1": 0}, "source_dataset", None, None, None),
        ("LegitPhish.local_candidate", "url_features_extracted1.csv", "URL", "ClassLabel", {"0": 1, "1": 0}, None, None, None, None),
        ("Mitake_existing", "PhishBenignDataset.csv", "url", "label", {"0": 0, "1": 1}, None, None, None, None),
        ("legacy_malicious_phish", "malicious_phish.csv", "url", "type", {"benign": 0, "phishing": 1}, "type", None, None, None),
        ("legacy_phishing_url_pair", "phishing_url_pair.cleaned.csv", "url", "label", {"0": 0, "1": 1}, None, None, None, None),
    ]
    summaries, detail_map, files_meta = [], {}, {}
    for key, filename, url_col, label_col, label_map, source_col, time_col, tier_col, split_col in definitions:
        content = None
        path = data_dir / filename
        if key.startswith("PhishVN"):
            member = "data/dataset_url.csv"
            content = phishvn_bytes.get(member)
            if content is None:
                summaries.append({"name": key, "status": "official archive data/dataset_url.csv not available"})
                continue
            headers, rows = read_rows(content=content)
            files_meta[key] = {"archive_member": member, "bytes": len(content), "sha256": sha256_bytes(content)}
        elif not path.is_file():
            summaries.append({"name": key, "status": "not available locally"})
            continue
        else:
            headers, rows = read_rows(path=path)
            h = hashlib.sha256()
            with path.open("rb") as f:
                for block in iter(lambda: f.read(1024 * 1024), b""):
                    h.update(block)
            files_meta[key] = {"local_filename": filename, "bytes": path.stat().st_size, "sha256": h.hexdigest(),
                               "source_identity_verified": key in {"Mitake_existing", "legacy_malicious_phish", "legacy_phishing_url_pair"}}
        summary, details = audit_table(key, headers, rows, url_col, label_col, label_map, source_col, time_col, tier_col, split_col)
        if key.startswith("PhiLegit"):
            summary["label_mapping_status"] = "provisional header interpretation; publisher README/archive unavailable locally; not approved for label-based conclusions"
        if key.startswith("LegitPhish"):
            summary["label_mapping_status"] = "publisher card/paper documents 0=phishing, 1=legitimate; local file identity remains unverified"
        summaries.append(summary)
        detail_map[key] = details
    pairs = {}
    names = list(detail_map)
    for i, left in enumerate(names):
        for right in names[i + 1:]:
            pairs[f"{left}__vs__{right}"] = compare(detail_map[left], detail_map[right])
    result = {"generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
              "privacy": "No raw URL, hostname, path, query, credential, or per-record hash is serialized.",
              "normalizer": "backend/app/services/url_model_features.normalize_url; domain grouping uses Mitake common.domain_group with bundled tldextract PSL snapshot; network suffix fetching disabled.",
              "archive": zip_meta, "datasets": summaries, "overlaps": pairs}
    acquisition = {"PhishVN": "Version-4 card lists dataset_url.csv, vn_compphish.csv, splits, abuse_type.csv, attacks, docs and MANIFEST with Download All. No download; supplied direct ZIP URL returned HTTP 404. Documented API requires OAuth2; current shell requests blocked by network policy; local ZIP origin unverified.",
                   "PhiLegit-100K": "Current card describes PhiLegit-100K.csv and README_PhiLegit-100K.md with Download All; no RAR is verified in the rendered card text. No publisher payload acquired. API requires OAuth2; shell requests blocked; local CSV identity unverified.",
                   "LegitPhish": "Current card describes URL plus features and Download All; exact downloadable filenames not exposed to the configured page reader. No publisher payload acquired. API requires OAuth2; shell requests blocked; local CSV identity unverified."}
    rights = "Publisher CC BY 4.0 declarations are recorded as publisher claims; upstream source terms, intended commercial use and derived-model distribution remain subject to legal review."
    publisher_records = {
        "PhishVN": {"official_title": "PhishVN v3.1.0 open", "identifier": "10.17632/b97hxbxtpd.4",
                     "official_page": "https://data.mendeley.com/datasets/b97hxbxtpd/4", "publisher": "Mendeley Data",
                     "authors": ["Thai Nguyen Vu"], "release_version": "4 (open data documented as v3.1.0)",
                     "official_version_date": "2026-08-18", "access_recheck_date": "2026-10-22",
                     "official_files_documented": ["dataset_url.csv", "vn_compphish.csv", "splits/url_train.csv", "splits/url_val.csv", "splits/url_test.csv", "abuse_type.csv", "attacks/", "docs/", "MANIFEST.txt"],
                     "retrieval_date": None, "license_claim": "CC BY 4.0",
                     "license_url": "https://creativecommons.org/licenses/by/4.0/",
                     "attribution": "Cite the dataset and attribute upstream contributors applicable to reused strata, including NCSC/Tin Nhiem Mang, Tranco, ChongLuaDao and OpenPhish.",
                     "upstream_sources": ["NCSC/Tin Nhiem Mang", "Tranco", "ChongLuaDao", "OpenPhish"],
                     "download_status": "Current card lists the files above with Download All. No download in this task. User-provided direct URL returned HTTP 404; documented API requires OAuth2; shell network blocked; local archive origin unverified."},
        "PhiLegit-100K": {"official_title": "PhiLegit-100K", "identifier": "10.17632/726pyz4j53.1",
                           "official_page": "https://data.mendeley.com/datasets/726pyz4j53/1", "publisher": "Mendeley Data",
                           "authors": ["Shakil Mia", "Jannatul Jeor Bushra", "Marufa Tasnim"], "release_version": "1",
                           "official_version_date": "2026-09-22", "access_recheck_date": "2026-10-22",
                           "official_files_documented": ["PhiLegit-100K.csv", "README_PhiLegit-100K.md"],
                           "retrieval_date": None, "reported_file": "PhiLegit-100K.csv (actual payload not acquired)",
                           "license_claim": "CC BY 4.0", "license_url": "https://creativecommons.org/licenses/by/4.0/",
                           "attribution": "Dataset card attributes PhiUSIIL and LegitPhish upstream datasets; exact notice and upstream terms require official archive/README review.",
                           "upstream_sources": ["PhiUSIIL", "LegitPhish"],
                           "download_status": "Current card describes a CSV and README with Download All. No publisher payload acquired; API requires OAuth2; shell network blocked; local CSV origin unverified."},
        "LegitPhish": {"official_title": "LegitPhish", "identifier": "10.17632/hx4m73v2sf.2",
                       "official_page": "https://data.mendeley.com/datasets/hx4m73v2sf/2", "publisher": "Mendeley Data",
                       "authors": ["Rachana Potpelwar", "Uday Kulkarni", "Jaishri Waghmare"], "release_version": "2",
                       "official_version_date": "2025-05-22", "access_recheck_date": "2026-10-22",
                       "official_page_file_details": "Card describes the URL field and engineered features and exposes Download All; exact downloadable filenames were not visible through the configured page reader.",
                       "retrieval_date": None, "license_claim": "CC BY 4.0",
                       "license_url": "https://creativecommons.org/licenses/by/4.0/",
                       "attribution": "Cite the dataset and review upstream source terms before reuse.",
                       "upstream_sources": ["URLHaus", "PhishTank", "UCI", "Google Search API", "Wikipedia", "Stack Overflow"],
                       "download_status": "No publisher file acquired; API requires OAuth2; shell network blocked; local feature CSV origin unverified."},
    }
    manifest = deterministic_manifest(files_meta, acquisition, rights, publisher_records)
    manifest["phishvn_archive"] = zip_meta
    (out_dir / "overlap_results.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out_dir / "dataset_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result, manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "ml-training/data")
    parser.add_argument("--output-dir", type=Path, default=HERE)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    result, _ = inventory(args.data_dir, args.output_dir)
    print(json.dumps({"dataset_summaries": result["datasets"], "overlap_pairs": len(result["overlaps"]),
                      "archive_manifest_matches": result["archive"].get("all_manifest_checks_match")}, indent=2))


if __name__ == "__main__":
    main()
