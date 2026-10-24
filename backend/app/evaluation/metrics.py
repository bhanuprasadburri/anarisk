"""Ranking-quality and protection metrics for the Round 2 evaluation set (Phase 5).

Implements the acceptance checks from the Round 2 report against labeled data:

* Precision@k with the ACTUAL k reported when fewer than 10 cases exist
  (the harness computes ``k = min(10, len(queue))``).
* Recall at the chosen threshold (the configured medium-severity threshold by default).
* Average precision over labeled cases, evaluated step-wise across distinct score
  thresholds - the same definition scikit-learn's ``average_precision_score`` uses for
  binary labels - so precision/recall behaviour is summarised across thresholds rather
  than at one cut-off. Implemented directly so evaluation adds no new dependency.
* Evidence completeness: the proportion of queued detections carrying source identity,
  an official comparison target, observation timestamps and traceable score reasons,
  with missing fields counted separately (never folded into a single silent number).

All functions are pure: inputs are ground-truth labels and measured scores, outputs are
plain floats/counts. None of these functions invent data - they return ``None`` where a
metric is undefined (empty queue, no positives).
"""
from __future__ import annotations

from typing import Sequence

#: The four completeness fields named by the report's "Evidence completeness" check.
EVIDENCE_FIELDS = ("source_identity", "official_comparison", "timestamps", "score_reasons")


def precision_at_k(ranked_labels: Sequence[int], k: int) -> float | None:
    """Precision@k over ground-truth labels in ranked order (best first).

    Uses ``min(k, len(ranked_labels))`` so a queue shorter than k is measured honestly;
    callers report that actual k separately. Returns None when nothing is ranked.
    """
    if k <= 0 or not ranked_labels:
        return None
    actual = min(k, len(ranked_labels))
    return sum(1 for label in ranked_labels[:actual] if label == 1) / actual


def recall_at_threshold(
    ranked: Sequence[tuple[float, int]], total_positives: int, threshold: float
) -> float | None:
    """Recall at a score threshold: retrieved positives / ALL labeled positives.

    ``ranked`` holds (score, label) pairs for everything the system could score.
    Labeled positives the system could not score are absent by definition and are
    therefore never counted as retrieved - missing evidence must not look like safety.
    Returns None when the fixture contains no positives (undefined, not zero).
    """
    if total_positives <= 0:
        return None
    hits = sum(1 for score, label in ranked if label == 1 and score >= threshold)
    return hits / total_positives


def average_precision(
    ranked: Sequence[tuple[float, int]], total_positives: int
) -> float | None:
    """Step-wise average precision over distinct score thresholds.

    ``ranked`` is (score, label) pairs sorted by score descending. Equal scores are
    evaluated as one threshold (ties never leak ordering information). The denominator
    is the total number of labeled positives, so unscored positives penalise the metric
    exactly as an average-precision definition over labeled cases requires.

    Returns None when nothing is scored or the fixture has no positives.
    """
    if not ranked or total_positives <= 0:
        return None
    ap = 0.0
    prev_recall = 0.0
    tp = 0
    seen = 0
    i = 0
    ordered = sorted(ranked, key=lambda pair: -pair[0])
    while i < len(ordered):
        score = ordered[i][0]
        group_positives = 0
        group_size = 0
        while i < len(ordered) and ordered[i][0] == score:
            group_size += 1
            if ordered[i][1] == 1:
                group_positives += 1
            i += 1
        tp += group_positives
        seen += group_size
        precision = tp / seen
        recall = tp / total_positives
        ap += (recall - prev_recall) * precision
        prev_recall = recall
    return ap


def evidence_completeness(
    item_flags: Sequence[dict[str, bool]],
) -> tuple[float | None, dict[str, int]]:
    """Share of queued detections that carry every required field + per-field misses.

    ``item_flags`` is one {field: present} mapping per queued detection, derived by the
    harness from the fixture's actual content (not self-declared completeness claims).
    Returns (share complete, {field: missing count}); None when nothing is queued.
    """
    missing = {field: 0 for field in EVIDENCE_FIELDS}
    if not item_flags:
        return None, missing
    complete = 0
    for flags in item_flags:
        item_complete = True
        for field in EVIDENCE_FIELDS:
            if not flags.get(field):
                missing[field] += 1
                item_complete = False
        if item_complete:
            complete += 1
    return complete / len(item_flags), missing


def official_assets_in_queue(
    queue_ids: Sequence[str], verified_official_ids: Sequence[str]
) -> list[str]:
    """Invariant 1: verified official assets that reached the threat queue (must be []).

    'Verified' means the identity is backed by the registered inventory - exactly the
    population the report requires to be zero in the queue. Coverage over officials the
    inventory does NOT know about is reported separately by the harness, because the
    guarantee explicitly does not extend to unknown official assets.
    """
    official = set(verified_official_ids)
    return [item_id for item_id in queue_ids if item_id in official]
