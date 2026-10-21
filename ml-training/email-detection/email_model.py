"""Offline research inference for the isolated email text model."""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any

MAX_RAW_EMAIL_CHARS = 5_000_000
MAX_EMAIL_CHARS = 200_000
FEATURE_SCHEMA = "email-word-tfidf-v1"
_EMAIL_RE = re.compile(r"(?i)\b[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}\b")
_URL_RE = re.compile(r"(?i)\b(?:https?://|www\.)[^\s<>\"']+")
_IPV4_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


def normalize_email_text(raw_email: str) -> tuple[str, bool]:
    """Apply fixed redaction/size controls identically in training and inference."""
    if not isinstance(raw_email, str) or len(raw_email) > MAX_RAW_EMAIL_CHARS:
        return "", False
    value = unicodedata.normalize("NFKC", raw_email)
    value = _EMAIL_RE.sub(" emailaddress ", value)
    value = _URL_RE.sub(" urladdress ", value)
    value = _IPV4_RE.sub(" ipaddress ", value)
    value = " ".join(value.split())
    truncated = len(value) > MAX_EMAIL_CHARS
    if truncated:
        value = value[:MAX_EMAIL_CHARS]
    return value, truncated


@lru_cache(maxsize=2)
def _load_artifact(path: str, mtime_ns: int, size: int) -> dict[str, Any]:
    del mtime_ns, size
    import joblib

    bundle = joblib.load(path)
    if not isinstance(bundle, dict) or not hasattr(bundle.get("model"), "predict_proba"):
        raise ValueError("Invalid email model artifact")
    metadata = bundle.get("metadata")
    if not isinstance(metadata, dict) or metadata.get("feature_schema") != FEATURE_SCHEMA:
        raise ValueError("Unsupported email model artifact schema")
    threshold = metadata.get("threshold_selection", {}).get("selected_threshold")
    if not isinstance(threshold, (int, float)) or not 0 <= threshold <= 1:
        raise ValueError("Email model artifact has no valid validation threshold")
    return bundle


def predict_email(raw_email: str, artifact_path: str | Path) -> dict[str, Any]:
    if not isinstance(raw_email, str) or not raw_email.strip() or len(raw_email) > MAX_RAW_EMAIL_CHARS:
        return {"status": "invalid_input", "model_version": None, "score": None}
    normalized, truncated = normalize_email_text(raw_email)
    if not normalized:
        return {"status": "invalid_input", "model_version": None, "score": None}
    path = Path(artifact_path).expanduser()
    if not path.is_file():
        return {"status": "unavailable", "model_version": None, "score": None}
    try:
        stat = path.stat()
        bundle = _load_artifact(str(path.resolve()), stat.st_mtime_ns, stat.st_size)
        metadata = bundle["metadata"]
        score = float(bundle["model"].predict_proba([normalized])[0][1])
        if not 0 <= score <= 1:
            raise ValueError("Model returned out-of-range score")
        threshold = float(metadata["threshold_selection"]["selected_threshold"])
        return {
            "status": "scored",
            "model_version": metadata["model_version"],
            "feature_schema": FEATURE_SCHEMA,
            "prediction": "spam_or_phishing_proxy" if score >= threshold else "legitimate",
            "score": score,
            "score_is_calibrated_probability": False,
            "threshold": threshold,
            "input_truncated": truncated,
        }
    except Exception:
        return {"status": "error", "model_version": None, "score": None}
