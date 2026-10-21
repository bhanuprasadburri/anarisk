"""Optional local URL-model inference for explicitly enabled shadow evaluation.

Artifacts are Python joblib pickles. Only load artifacts produced by the trusted training
pipeline and stored in a deployment-controlled filesystem path; never accept user uploads.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from app.services.url_model_features import FEATURE_NAMES, FEATURE_VERSION, features, normalize_url

CHAR_TFIDF_FEATURE_VERSION = "char-tfidf-url-v1"


@lru_cache(maxsize=2)
def _load_artifact(path: str, mtime_ns: int, size: int) -> dict[str, Any]:
    del mtime_ns, size
    from importlib import import_module

    value = import_module("joblib").load(path)
    if not isinstance(value, dict) or not hasattr(value.get("model"), "predict_proba"):
        raise ValueError("Invalid URL model artifact")
    metadata = value.get("metadata")
    if isinstance(metadata, dict) and metadata.get("feature_schema") is None:
        # Keep supporting the original shadow artifacts created before schema metadata existed.
        metadata["feature_schema"] = FEATURE_VERSION
    if not isinstance(metadata, dict) or metadata.get("feature_schema") not in {FEATURE_VERSION, CHAR_TFIDF_FEATURE_VERSION}:
        raise ValueError("Unsupported URL model artifact schema")
    if metadata.get("feature_schema") == FEATURE_VERSION and metadata.get("feature_names") != list(FEATURE_NAMES):
        raise ValueError("URL model feature schema mismatch")
    return value


def predict_url(raw_url: str, artifact_path: str | Path) -> dict[str, Any]:
    normalized = normalize_url(raw_url)
    if not normalized:
        return {"status": "invalid_input", "model_version": None, "score": None}
    path = Path(artifact_path).expanduser()
    if not path.is_file():
        return {"status": "unavailable", "model_version": None, "score": None}
    try:
        stat = path.stat()
        bundle = _load_artifact(str(path.resolve()), stat.st_mtime_ns, stat.st_size)
        metadata = bundle["metadata"]
        feature_schema = metadata.get("feature_schema", FEATURE_VERSION)
        model_input = [features(normalized)] if feature_schema == FEATURE_VERSION else [normalized]
        score = float(bundle["model"].predict_proba(model_input)[0][1])
        if not 0 <= score <= 1:
            raise ValueError("Model returned out-of-range score")
        threshold_selection = metadata.get("threshold_selection")
        threshold = (threshold_selection.get("selected_threshold") if isinstance(threshold_selection, dict)
                     else metadata.get("threshold_selected_on_validation"))
        prediction = ("malicious" if score >= float(threshold) else "benign") if threshold is not None else None
        return {
            "status": "scored", "model_version": metadata.get("model_version", "unknown"),
            "feature_schema": feature_schema, "prediction": prediction, "score": score,
            "score_is_calibrated_probability": False,
            "threshold": threshold,
        }
    except Exception:
        return {"status": "error", "model_version": None, "score": None}
