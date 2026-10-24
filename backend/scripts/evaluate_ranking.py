"""Run the labeled Round 2 evaluation set and print the measured Phase 5 metrics.

Usage (from backend/):

    python scripts/evaluate_ranking.py [--fixture PATH] [--out REPORT.json]

Every number in the output is computed by running the fixture through the production
official-asset guard and the weighted scoring model - nothing is precomputed or invented.
Exit code 1 when the protection invariant fails (a verified official asset reached the
threat queue), so this script can gate CI.

The fixture is synthetic and hand-labeled: results demonstrate ranking behaviour on a
tiny set, not production accuracy.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.evaluation.harness import DEFAULT_FIXTURE, run_evaluation  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE, help="labeled fixture JSON")
    parser.add_argument("--out", type=Path, default=None, help="also write the full report as JSON")
    args = parser.parse_args()

    report = run_evaluation(fixture_path=args.fixture)
    payload = report.as_dict()
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    print(text)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")

    if report.n_official_in_queue:
        print(
            f"FAIL: {report.n_official_in_queue} verified official asset(s) in the threat queue",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
