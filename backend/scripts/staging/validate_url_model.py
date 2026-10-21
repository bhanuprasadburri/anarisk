"""Fail-fast validation for the fixed, staging-only URL model artifact."""
from __future__ import annotations

import hashlib
import hmac
import importlib.metadata
import os
from pathlib import Path
import sys

ARTIFACT_PATH = "/app/var/models/url-char-tfidf-v0.1.0-research.joblib"
EXPECTED_ARTIFACT_SHA256 = "d4ff1b4ea161edcdeee78c6be1956b51f87ef8a23d5b59600a602d0033b4c005"
EXPECTED_VERSIONS = {
    "numpy": "2.5.4", "scikit-learn": "1.9.1", "joblib": "1.6.0",
    "scipy": "1.18.1", "threadpoolctl": "3.7.0",
}
EXPECTED_MODEL_VERSION = "anarisk-url-char-tfidf-0.1.0-research"
EXPECTED_FEATURE_SCHEMA = "char-tfidf-url-v1"
EXPECTED_THRESHOLD = 0.8578006147478512


class StartupValidationError(RuntimeError):
    pass


def validate_artifact(path: str | Path, expected_sha256: str) -> dict:
    artifact = Path(path)
    if not artifact.is_file():
        raise StartupValidationError(f"URL model artifact is missing at the configured staging path: {artifact}")
    if len(expected_sha256) != 64 or any(c not in "0123456789abcdefABCDEF" for c in expected_sha256):
        raise StartupValidationError("URL_MODEL_ARTIFACT_SHA256 must be a 64-character SHA-256 hex digest")
    if not hmac.compare_digest(expected_sha256.lower(), EXPECTED_ARTIFACT_SHA256):
        raise StartupValidationError("URL_MODEL_ARTIFACT_SHA256 differs from the image's approved artifact digest")
    digest = hashlib.sha256()
    with artifact.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    if not hmac.compare_digest(digest.hexdigest().lower(), expected_sha256.lower()):
        raise StartupValidationError("URL model artifact SHA-256 mismatch; refusing to load the artifact")
    try:
        actual = {name: importlib.metadata.version(name) for name in EXPECTED_VERSIONS}
    except importlib.metadata.PackageNotFoundError as exc:
        raise StartupValidationError(
            f"Missing ML dependency '{exc.name}'. Build the staging image from requirements-ml.txt."
        ) from exc
    mismatched = [f"{name} expected {expected}, found {actual[name]}"
                  for name, expected in EXPECTED_VERSIONS.items() if actual[name] != expected]
    if mismatched:
        raise StartupValidationError("Incompatible URL-model dependencies: " + "; ".join(mismatched))
    try:
        from app.services.url_model import _load_artifact

        stat = artifact.stat()
        bundle = _load_artifact(str(artifact.resolve()), stat.st_mtime_ns, stat.st_size)
    except Exception as exc:
        raise StartupValidationError(
            f"URL model could not be loaded; verify artifact compatibility and trusted training source ({type(exc).__name__})."
        ) from exc
    metadata = bundle.get("metadata", {})
    threshold = (metadata.get("threshold_selection") or {}).get("selected_threshold")
    try:
        threshold_matches = threshold is not None and abs(float(threshold) - EXPECTED_THRESHOLD) <= 1e-12
    except (TypeError, ValueError):
        threshold_matches = False
    if (metadata.get("model_version") != EXPECTED_MODEL_VERSION
            or metadata.get("feature_schema") != EXPECTED_FEATURE_SCHEMA or not threshold_matches):
        raise StartupValidationError("URL model metadata does not match the approved v0.1.0 research artifact")
    return metadata


def main() -> int:
    if os.getenv("URL_MODEL_SHADOW_ENABLED", "").lower() not in {"true", "1", "yes", "on"}:
        raise StartupValidationError("Staging image requires URL_MODEL_SHADOW_ENABLED=true")
    if os.getenv("URL_FETCH_ENABLED", "").lower() not in {"false", "0", "no", "off"}:
        raise StartupValidationError("Staging requires URL_FETCH_ENABLED=false")
    if os.getenv("RUN_MIGRATIONS", "false").lower() not in {"false", "0", "no", "off"}:
        raise StartupValidationError("Staging startup must not run migrations; set RUN_MIGRATIONS=false")
    if os.getenv("URL_MODEL_ARTIFACT_PATH", "") != ARTIFACT_PATH:
        raise StartupValidationError(f"URL_MODEL_ARTIFACT_PATH must be the deployer-controlled path {ARTIFACT_PATH}")
    digest = os.getenv("URL_MODEL_ARTIFACT_SHA256", "")
    validate_artifact(ARTIFACT_PATH, digest)
    print("[staging] URL model checksum, dependencies, and metadata validated; shadow mode only.", flush=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except StartupValidationError as exc:
        print(f"[staging] startup blocked: {exc}", file=sys.stderr, flush=True)
        sys.exit(78)
