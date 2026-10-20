"""Prepare PhreshPhish URL labels for offline research without fetching indicators/pages.

Input is a local CSV or Parquet copy obtained by the operator from the pinned source
revision. HTML is ignored. Output contains normalized URLs and labels and must be kept
outside source control because it is threat-indicator data.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

SOURCE = "phreshphish/phreshphish"
LICENSE = "CC-BY-4.0; anti-phishing research use per dataset card"
SOURCE_URL = "https://huggingface.co/datasets/phreshphish/phreshphish"
LABELS = {"phish": 1, "benign": 0}
MAX_URL_CHARS = 25_000


def normalize_url(raw: str) -> str:
    """Canonicalize safe URL text only; never resolve, request, or execute it."""
    value = (raw or "").strip()
    if not value or len(value) > MAX_URL_CHARS or any(ord(c) < 32 for c in value):
        return ""
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", value):
        value = "https://" + value
    try:
        p = urlsplit(value)
        if p.scheme.lower() not in {"http", "https"} or not p.hostname:
            return ""
        # Do not retain credentials or fragments. Preserve path/query because they can be
        # discriminative and may contain sensitive tokens; the output is research-only.
        host = p.hostname.encode("idna").decode("ascii").lower().rstrip(".")
        if not host or len(host) > 253:
            return ""
        port = p.port
        netloc = host + (f":{port}" if port and port not in (80, 443) else "")
        path = p.path or "/"
        return urlunsplit((p.scheme.lower(), netloc, path, p.query, ""))
    except (ValueError, UnicodeError):
        return ""


def _rows(path: Path):
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            yield from csv.DictReader(f)
        return
    if path.suffix.lower() in {".parquet", ".pq"}:
        try:
            import pyarrow.parquet as pq
        except ImportError as exc:
            raise RuntimeError("Install backend/requirements-ml.txt to read Parquet") from exc
        parquet = pq.ParquetFile(path)
        required = {"url", "label"}
        if not required.issubset(parquet.schema.names):
            raise ValueError("Parquet input must have url and label columns")
        for batch in parquet.iter_batches(batch_size=8192, columns=[c for c in ("url", "label", "date") if c in parquet.schema.names]):
            yield from batch.to_pylist()
        return
    raise ValueError("Input must be a .csv or .parquet file")


def prepare(input_path: Path, output_path: Path, source_split: str, source_revision: str, retrieved_at: str | None) -> dict:
    if not input_path.is_file():
        raise FileNotFoundError(input_path)
    if not re.fullmatch(r"[0-9a-fA-F]{40}", source_revision):
        raise ValueError("Provide the pinned 40-character Hugging Face dataset commit SHA")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    input_sha = hashlib.sha256()
    with input_path.open("rb") as src:
        for chunk in iter(lambda: src.read(1024 * 1024), b""):
            input_sha.update(chunk)
    seen: set[str] = set()
    labels: Counter[str] = Counter()
    source_dates: list[str] = []
    invalid = duplicate = unknown = 0
    with output_path.open("w", encoding="utf-8", newline="") as out:
        writer = csv.DictWriter(out, fieldnames=["url", "label", "date", "source_split"])
        writer.writeheader()
        for row in _rows(input_path):
            raw_label = str(row.get("label", "")).strip().lower()
            if raw_label not in LABELS:
                unknown += 1
                continue
            url = normalize_url(str(row.get("url", "")))
            if not url:
                invalid += 1
                continue
            digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
            if digest in seen:
                duplicate += 1
                continue
            seen.add(digest)
            label = LABELS[raw_label]
            labels[raw_label] += 1
            source_date = str(row.get("date", "") or "")[:32]
            if source_date:
                source_dates.append(source_date)
            writer.writerow({"url": url, "label": label, "date": source_date, "source_split": source_split})
    report = {
        "source": SOURCE, "source_url": SOURCE_URL, "license_and_scope": LICENSE,
        "source_revision": source_revision.lower(), "retrieved_at_utc": retrieved_at,
        "prepared_at_utc": datetime.now(UTC).isoformat(), "input_file": input_path.name,
        "input_sha256": input_sha.hexdigest(), "source_split": source_split,
        "output_file": output_path.name, "rows_by_label": dict(labels),
        "rows_written": sum(labels.values()), "invalid_rows": invalid,
        "unknown_label_rows": unknown, "duplicate_normalized_url_rows": duplicate,
        "source_date_range": [min(source_dates), max(source_dates)] if source_dates else None,
        "normalization": "lowercase HTTP(S) scheme and IDNA hostname; remove fragment and credentials; preserve path/query",
        "safety": "URLs and HTML were not fetched or executed; HTML is not included in output",
        "limitations": ["source labels may be stale or noisy", "URL-only features do not analyze webpage content", "research only; not production validation"],
    }
    output_sha = hashlib.sha256()
    with output_path.open("rb") as out:
        for chunk in iter(lambda: out.read(1024 * 1024), b""):
            output_sha.update(chunk)
    report["output_sha256"] = output_sha.hexdigest()
    report_path = output_path.with_suffix(output_path.suffix + ".manifest.json")
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("input", type=Path)
    ap.add_argument("output", type=Path)
    ap.add_argument("--source-split", required=True, choices=("train", "test"), help="Preserve the dataset's official split")
    ap.add_argument("--source-revision", required=True, help="Pinned 40-character source commit SHA")
    ap.add_argument("--retrieved-at", help="Actual retrieval timestamp in ISO 8601 UTC; omit if unknown")
    args = ap.parse_args()
    try:
        print(json.dumps(prepare(args.input, args.output, args.source_split, args.source_revision, args.retrieved_at), indent=2))
    except (OSError, ValueError, RuntimeError, csv.Error) as exc:
        print(f"dataset preparation failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
