from __future__ import annotations

import argparse
import json
from pathlib import Path

import joblib

from common import MODEL_FEATURE_SCHEMA
from app.services.url_model_features import normalize_url


def predict(raw_url: str, artifact: Path) -> dict:
    normalized = normalize_url(raw_url)
    if not normalized:
        raise ValueError("URL is empty, malformed, or exceeds the supported length")
    bundle = joblib.load(artifact)
    if not isinstance(bundle, dict) or not isinstance(bundle.get("metadata"), dict):
        raise ValueError("Invalid research model artifact")
    metadata = bundle["metadata"]
    if metadata.get("feature_schema") != MODEL_FEATURE_SCHEMA:
        raise ValueError("Unsupported feature schema")
    score = float(bundle["model"].predict_proba([normalized])[0][1])
    threshold = float(metadata["threshold_selection"]["selected_threshold"])
    return {
        "model_version": metadata["model_version"],
        "score": score,
        "score_is_calibrated_probability": False,
        "threshold": threshold,
        "prediction": "phishing" if score >= threshold else "benign",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline research inference; input is not printed or fetched")
    parser.add_argument("url")
    parser.add_argument("--artifact", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(predict(args.url, args.artifact), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
