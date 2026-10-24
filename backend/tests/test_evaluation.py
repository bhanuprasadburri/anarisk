"""Phase 5 evaluation: metric units (hand-computable) + full-fixture invariants.

The fixture is synthetic and hand-labeled (see its own description); these tests assert
behaviour and invariants - never invented headline numbers. The runnable measurement is
``scripts/evaluate_ranking.py``.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.evaluation import (
    DEFAULT_FIXTURE,
    average_precision,
    evidence_completeness,
    official_assets_in_queue,
    precision_at_k,
    recall_at_threshold,
    run_evaluation,
)

REQUIRED_CATEGORIES = {
    "official_asset",
    "close_copy_scam",
    "harmless_lookalike",
    "fan_parody",
    "app_publisher_difference",
    "missing_evidence",
    "multilingual",
    "duplicate_observation",
}


# --------------------------------------------------------------------------
# Metric units - small hand-computable cases pin the definitions.
# --------------------------------------------------------------------------


def test_precision_at_k_uses_actual_k_for_short_queues():
    # k=10 on a 3-item queue is measured over all 3 (the report shows actual k = 3).
    assert precision_at_k([1, 0, 1], 10) == pytest.approx(2 / 3)
    assert precision_at_k([1, 1, 0, 1], 3) == pytest.approx(2 / 3)
    assert precision_at_k([], 10) is None
    assert precision_at_k([1], 0) is None


def test_average_precision_matches_step_wise_threshold_definition():
    # Perfect ordering of both positives first.
    assert average_precision([(0.9, 1), (0.8, 1), (0.7, 0)], 2) == pytest.approx(1.0)
    # One positive ranked second of two: precision 1/2 at recall 1 -> AP = 0.5.
    assert average_precision([(0.9, 0), (0.8, 1)], 1) == pytest.approx(0.5)
    # Tied scores are one threshold: both positives retrieved together -> AP = 1.0.
    assert average_precision([(0.5, 1), (0.5, 1)], 2) == pytest.approx(1.0)
    # A positive the system could not score stays in the denominator (never silently safe).
    assert average_precision([(0.9, 1)], 2) == pytest.approx(0.5)
    assert average_precision([], 1) is None
    assert average_precision([(0.9, 0)], 0) is None


def test_recall_at_threshold_counts_below_threshold_and_unscored_as_missed():
    ranked = [(0.9, 1), (0.5, 0), (0.3, 1)]
    assert recall_at_threshold(ranked, 3, 0.4) == pytest.approx(1 / 3)
    assert recall_at_threshold(ranked, 2, 0.9) == pytest.approx(1 / 2)
    assert recall_at_threshold(ranked, 0, 0.4) is None


def test_evidence_completeness_reports_missing_fields_separately():
    flags = [
        {"source_identity": True, "official_comparison": True, "timestamps": True, "score_reasons": True},
        {"source_identity": True, "official_comparison": False, "timestamps": True, "score_reasons": True},
    ]
    share, missing = evidence_completeness(flags)
    assert share == pytest.approx(0.5)
    assert missing == {
        "source_identity": 0,
        "official_comparison": 1,
        "timestamps": 0,
        "score_reasons": 0,
    }
    empty_share, empty_missing = evidence_completeness([])
    assert empty_share is None
    assert set(empty_missing.values()) == {0}


def test_official_assets_in_queue_flags_only_verified_officials():
    assert official_assets_in_queue(["a", "b"], ["c"]) == []
    assert official_assets_in_queue(["a", "b"], ["b", "c"]) == ["b"]


# --------------------------------------------------------------------------
# Full fixture: coverage, invariants, measured behaviour.
# --------------------------------------------------------------------------


def test_fixture_is_synthetic_and_covers_every_required_category():
    fixture = json.loads(Path(DEFAULT_FIXTURE).read_text(encoding="utf-8"))
    assert fixture.get("synthetic") is True
    items = fixture["items"]
    assert {it["category"] for it in items} == REQUIRED_CATEGORIES
    assert all(it.get("provenance") == "synthetic" for it in items)
    # Labels are authored ground truth independent of the score rules: both classes exist.
    assert {it["label"] for it in items} == {0, 1}


def test_verified_official_assets_never_enter_the_queue():
    report = run_evaluation()
    assert report.n_official_in_queue == 0
    # Exclusion happened through the guard, not by dropping items elsewhere:
    # every inventory-backed official was recognised and excluded before scoring.
    assert report.n_official_excluded == report.n_inventory_backed_official
    # Coverage over officials the inventory cannot know is reported separately (0 < c <= 1).
    assert report.inventory_coverage is not None
    assert 0 < report.inventory_coverage <= 1
    # The unregistered official is visible as a counted limitation, never hidden.
    assert report.n_unverified_official_in_queue == 1


def test_queue_metrics_are_measured_from_the_queue_and_deterministic():
    first = run_evaluation()
    second = run_evaluation()
    assert first.as_dict() == second.as_dict()

    # k is the actual top-10 size, reported from the real queue length.
    assert first.k == min(10, first.n_queued)
    assert first.n_queued > first.k

    # Precision@10 recomputes from the queue's own labels (no pinned magic constant).
    labels = [entry.label for entry in first.queue]
    assert first.precision_at_k == pytest.approx(sum(labels[: first.k]) / first.k)
    assert 0.0 <= (first.average_precision or 0.0) <= 1.0
    assert 0.0 <= (first.recall_at_threshold or 0.0) <= 1.0
    assert first.threshold == pytest.approx(0.40)  # configured medium threshold

    # The threat with no signal data stays unscored (unknown, never silently safe)
    # and its loss shows up in the denominators rather than as a pass.
    assert first.n_unscored == 1
    assert first.unscored_ids == ["missing-evidence-threat"]
    assert first.n_positives == 8


def test_provisional_duplicate_and_boundary_behaviours_are_visible():
    report = run_evaluation()
    by_id = {entry.id: entry for entry in report.queue}

    # Below the coverage floor the score is still computed and flagged provisional.
    partial = by_id["partial-coverage-threat"]
    assert partial.provisional is True
    assert partial.risk_score > 0

    # Repeated observations of one stable identity collapse to a single queue entry.
    assert report.duplicates_collapsed == 1
    assert "phish-lookalike-domain" in by_id
    assert "duplicate-phish-observation" not in by_id

    # Ranking is by risk score descending with an id tie-break (reproducible).
    scores = [entry.risk_score for entry in report.queue]
    assert scores == sorted(scores, reverse=True)


def test_evidence_completeness_is_derived_from_item_content():
    report = run_evaluation()
    assert report.evidence_completeness is not None
    assert report.evidence_missing_fields["source_identity"] == 1  # fan-parody-profile: no source_url
    assert report.evidence_missing_fields["official_comparison"] == 1  # whois tool: no brand_reference
    assert report.evidence_missing_fields["timestamps"] == 1  # whois tool: observed_at is null
    assert report.evidence_missing_fields["score_reasons"] == 0
    # Two of the twelve queued detections carry a gap -> 10/12 complete.
    assert report.evidence_completeness == pytest.approx(10 / 12)


def test_fixture_validation_rejects_bad_labels_and_unlabeled_items():
    fixture = json.loads(Path(DEFAULT_FIXTURE).read_text(encoding="utf-8"))
    bad = json.loads(json.dumps(fixture))
    official = next(it for it in bad["items"] if it["category"] == "official_asset")
    official["label"] = 1  # an inventory official may never be ground-truthed as a threat
    with pytest.raises(ValueError, match="contradicts"):
        run_evaluation(fixture=bad)

    unlabeled = json.loads(json.dumps(fixture))
    unlabeled["items"][0]["provenance"] = "collected"  # fixtures may not pose as real data
    with pytest.raises(ValueError, match="synthetic"):
        run_evaluation(fixture=unlabeled)
