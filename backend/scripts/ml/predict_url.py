"""Print a structured prediction from a trusted local AnaRisk model artifact."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.services.url_model import predict_url


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="URL to score; no network request is made")
    parser.add_argument("--artifact", type=Path, default=Path("../ml-training/models/url-char-tfidf-v0.1.0-research.joblib"))
    args = parser.parse_args()
    result = predict_url(args.url, args.artifact)
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "scored" else 2


if __name__ == "__main__":
    raise SystemExit(main())
