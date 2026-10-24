"""Offline inference for the UCI Spambase 57-feature research model."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Sequence
import math

FEATURE_SCHEMA = "uci-spambase-57-v1"


@lru_cache(maxsize=2)
def _load(path: str, mtime_ns: int, size: int) -> dict[str, Any]:
    del mtime_ns, size
    import joblib
    value = joblib.load(path)
    if not isinstance(value, dict) or value.get("metadata", {}).get("feature_schema") != FEATURE_SCHEMA:
        raise ValueError("Unsupported Spambase artifact")
    if not hasattr(value.get("model"), "predict_proba") or len(value.get("metadata", {}).get("feature_names", [])) != 57:
        raise ValueError("Invalid Spambase artifact")
    return value


def predict_spambase(features: Sequence[float], artifact_path: str | Path) -> dict[str, Any]:
    if not isinstance(features, (list, tuple)) or len(features) != 57:
        return {"status": "invalid_input", "score": None}
    try:
        row = [float(value) for value in features]
        if not all(math.isfinite(value) for value in row):
            raise ValueError
        path = Path(artifact_path).expanduser()
        if not path.is_file():
            return {"status": "unavailable", "score": None}
        stat = path.stat()
        bundle = _load(str(path.resolve()), stat.st_mtime_ns, stat.st_size)
        score = float(bundle["model"].predict_proba([row])[0][1])
        threshold = float(bundle["metadata"]["threshold_selection"]["selected_threshold"])
        return {"status": "scored", "model_version": bundle["metadata"]["model_version"],
                "target": "unsolicited_commercial_spam", "score": score,
                "score_is_calibrated_probability": False,
                "prediction": "spam" if score >= threshold else "non_spam", "threshold": threshold}
    except (ValueError, TypeError, KeyError, OSError, ImportError):
        return {"status": "error", "score": None}
