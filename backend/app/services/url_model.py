"""Optional local URL-model inference for explicitly enabled shadow evaluation.

Artifacts are Python joblib pickles. Only load artifacts produced by the trusted training
pipeline and stored in a deployment-controlled filesystem path; never accept user uploads.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from app.services.url_model_features import FEATURE_NAMES, FEATURE_VERSION, features, normalize_url


@lru_cache(maxsize=2)
def _load_artifact(path: str, mtime_ns: int, size: int) -> dict[str, Any]:
    del mtime_ns, size
    from importlib import import_module

    value = import_module("joblib").load(path)
    if not isinstance(value, dict) or not hasattr(value.get("model"), "predict_proba"):
        raise ValueError("Invalid URL model artifact")
    metadata = value.get("metadata")
    if not isinstance(metadata, dict) or metadata.get("feature_schema") != FEATURE_VERSION:
        raise ValueError("Unsupported URL model artifact schema")
    if metadata.get("feature_names") != list(FEATURE_NAMES):
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
        score = float(bundle["model"].predict_proba([features(normalized)])[0][1])
        if not 0 <= score <= 1:
            raise ValueError("Model returned out-of-range score")
        return {
            "status": "scored", "model_version": bundle["metadata"].get("model_version", "unknown"),
            "feature_schema": FEATURE_VERSION, "score": score,
            "score_is_calibrated_probability": False,
            "threshold": bundle["metadata"].get("threshold_selected_on_validation"),
        }
    except Exception:
        return {"status": "error", "model_version": None, "score": None}
