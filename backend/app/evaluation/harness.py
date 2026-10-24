"""Run the labeled Round 2 evaluation set through the real production pipeline.

Pipeline per fixture item (exactly the code production uses, no parallel reimplementation):

1. Build an in-memory ``DigitalEntity`` and the brand's reference inventory.
2. ``is_official_asset()`` decides inclusion - verified official identities are excluded
   before scoring (never by display-name similarity, only by registered identity).
3. ``compute_score()`` (the four-family weighted model) turns the item's detector-output
   signals into risk / severity / confidence, with the coverage floor rule intact.
4. Repeated observations of one stable identity collapse to a single queue entry
   (mirrors ingestion idempotency); the highest observed risk wins.
5. The queue is ranked by risk score (ties broken by id for reproducibility) and the
   Phase 5 metrics are computed from authored ground-truth labels.

Honesty rules enforced in code:

* Every fixture item must declare ``provenance: "synthetic"`` - a tiny synthetic set
  demonstrates behaviour, not production accuracy, and can never pose as collected data.
* Labels are authored per scenario (category + label), independent of the score rules.
* Official-asset items must be labeled 0 (an inventory-verified official is not a threat
  by definition); violations fail loading instead of quietly skewing metrics.
* Metrics return None rather than a fabricated 0 when undefined (empty queue, no positives).

No network, no database: only in-memory ORM objects and pure functions.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.core.config import Settings, get_settings
from app.evaluation.metrics import (
    average_precision,
    evidence_completeness,
    official_assets_in_queue,
    precision_at_k,
    recall_at_threshold,
)
from app.models import BrandReference, DigitalEntity
from app.models.enums import EntityType, Provenance, ReferenceKind, SignalStatus, SignalType
from app.services.detection.base import SignalResult
from app.services.official import is_official_asset, normalize_reference
from app.services.scoring import compute_score

DEFAULT_FIXTURE = (
    Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "evaluation" / "round2_eval_set.json"
)

KNOWN_CATEGORIES = frozenset({
    "official_asset",
    "close_copy_scam",
    "harmless_lookalike",
    "fan_parody",
    "app_publisher_difference",
    "missing_evidence",
    "multilingual",
    "duplicate_observation",
})

PRECISION_AT_K = 10


@dataclass
class QueueEntry:
    id: str
    category: str
    label: int
    risk_score: float
    severity: str
    confidence: float
    provisional: bool
    observed_at: str | None


@dataclass
class EvaluationReport:
    fixture: str
    scoring_model_version: str
    configured_weights: dict[str, float]
    threshold: float
    coverage_floor: float

    n_items: int
    n_labeled_official: int
    n_inventory_backed_official: int
    inventory_coverage: float | None
    n_official_excluded: int
    n_official_in_queue: int  # inventory-backed (verified) officials in the queue - MUST be 0
    n_unverified_official_in_queue: int  # officials the inventory cannot know - reported, not a failure
    duplicates_collapsed: int

    n_positives: int
    n_negatives: int
    n_queued: int
    n_unscored: int
    unscored_ids: list[str]

    k: int
    precision_at_k: float | None
    recall_at_threshold: float | None
    average_precision: float | None
    evidence_completeness: float | None
    evidence_missing_fields: dict[str, int]

    queue: list[QueueEntry] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_fixture(raw: dict[str, Any]) -> dict[str, Any]:
    """Validate a labeled fixture; errors are explicit, never silent.

    Runs on every path into the harness (disk load or programmatic pass) so a bad
    fixture can never be evaluated quietly.
    """
    items = raw.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("fixture has no items")
    seen_ids: set[str] = set()
    for item in items:
        for key in ("id", "category", "label", "entity", "signals"):
            if key not in item:
                raise ValueError(f"fixture item {item.get('id', '<no id>')} missing '{key}'")
        if item["id"] in seen_ids:
            raise ValueError(f"duplicate fixture item id {item['id']}")
        seen_ids.add(item["id"])
        if item["category"] not in KNOWN_CATEGORIES:
            raise ValueError(f"fixture item {item['id']} has unknown category {item['category']!r}")
        if item["label"] not in (0, 1):
            raise ValueError(f"fixture item {item['id']} label must be 0 or 1")
        if item.get("provenance", "synthetic") != "synthetic":
            raise ValueError(
                f"fixture item {item['id']} must be labeled synthetic - evaluation fixtures "
                "may never claim collected provenance"
            )
        if item["category"] == "official_asset" and item["label"] != 0:
            raise ValueError(
                f"fixture item {item['id']} is an inventory official but labeled a threat; "
                "ground truth contradicts the registered inventory"
            )
        entity = item["entity"]
        if entity.get("entity_type") not in {t.value for t in EntityType}:
            raise ValueError(f"fixture item {item['id']} has invalid entity_type")
        if entity.get("canonical_id") is None or entity.get("display_name") is None:
            raise ValueError(f"fixture item {item['id']} entity needs canonical_id and display_name")
        for sig in item["signals"]:
            if sig.get("signal_type") not in {t.value for t in SignalType}:
                raise ValueError(f"fixture item {item['id']} has invalid signal_type {sig.get('signal_type')!r}")
            if sig.get("status", "ok") not in {s.value for s in SignalStatus}:
                raise ValueError(f"fixture item {item['id']} has invalid signal status")
    return raw


def load_fixture(path: Path | str = DEFAULT_FIXTURE) -> dict[str, Any]:
    """Read the labeled fixture from disk and validate it."""
    return validate_fixture(json.loads(Path(path).read_text(encoding="utf-8")))


def _build_entity(item: dict[str, Any], brand_id) -> DigitalEntity:
    e = item["entity"]
    return DigitalEntity(
        brand_id=brand_id,
        entity_type=EntityType(e["entity_type"]),
        canonical_id=e["canonical_id"],
        display_name=e["display_name"],
        platform=e.get("platform"),
        source_url=e.get("source_url"),
        provenance=Provenance.SYNTHETIC,
        attributes=dict(e.get("attributes") or {}),
    )


def _build_inventory(fixture: dict[str, Any], brand_id) -> list[BrandReference]:
    refs: list[BrandReference] = []
    for entry in fixture.get("inventory", []):
        kind = ReferenceKind(entry["kind"])
        refs.append(
            BrandReference(
                brand_id=brand_id,
                kind=kind,
                value=entry["value"],
                normalized_value=normalize_reference(kind, entry["value"]),
                platform=entry.get("platform"),
                provenance=Provenance.SYNTHETIC,
            )
        )
    return refs


def _signal_results(item: dict[str, Any]) -> list[SignalResult]:
    results = []
    for sig in item["signals"]:
        status = SignalStatus(sig.get("status", "ok"))
        results.append(
            SignalResult(
                signal_type=SignalType(sig["signal_type"]),
                status=status,
                score=sig.get("score") if status == SignalStatus.OK else None,
                explanation=sig.get("explanation", ""),
                evidence_refs=list(sig.get("evidence_refs") or []),
            )
        )
    return results


def _evidence_flags(item: dict[str, Any], comp) -> dict[str, bool]:
    """Completeness derived from the item's actual content, not self-declared claims."""
    entity = item["entity"]
    ok_signals = [s for s in item["signals"] if s.get("status", "ok") == SignalStatus.OK.value]
    return {
        "source_identity": bool(entity.get("source_url")),
        "official_comparison": any(
            ref.get("type") == "brand_reference"
            for sig in item["signals"]
            for ref in (sig.get("evidence_refs") or [])
        ),
        "timestamps": bool(item.get("observed_at")),
        # Every signal that contributed to the score must carry a human-readable reason;
        # unavailable signals are legitimately absent and are not counted as missing.
        "score_reasons": bool(ok_signals)
        and all((s.get("explanation") or "").strip() for s in ok_signals),
    }


def run_evaluation(
    fixture: dict[str, Any] | None = None,
    *,
    fixture_path: Path | str = DEFAULT_FIXTURE,
    settings: Settings | None = None,
) -> EvaluationReport:
    """Evaluate the labeled fixture and return every Phase 5 measure with real values."""
    settings = settings or get_settings()
    if fixture is None:
        fixture = load_fixture(fixture_path)
    else:
        validate_fixture(fixture)
    items = fixture["items"]
    brand_id = uuid4()
    inventory = _build_inventory(fixture, brand_id)

    labeled_official = [it for it in items if it["category"] == "official_asset"]
    backed_official = [it for it in labeled_official if it.get("inventory_backed")]
    backed_ids = {it["id"] for it in backed_official}

    excluded: list[tuple[str, str]] = []
    observations: list[dict[str, Any]] = []

    for item in items:
        entity = _build_entity(item, brand_id)
        reason = is_official_asset(entity, inventory)
        if reason is not None:
            excluded.append((item["id"], reason))
            continue
        comp = compute_score(_signal_results(item), Provenance.SYNTHETIC, settings)
        observations.append({"item": item, "comp": comp})

    # Stable-identity dedup: repeated observations collapse to one queue entry
    # (mirrors idempotent ingestion keyed on canonical identity); highest risk wins.
    deduped: dict[str, dict[str, Any]] = {}
    duplicates_collapsed = 0
    for row in observations:
        cid = row["item"]["entity"]["canonical_id"]
        existing = deduped.get(cid)
        if existing is None:
            deduped[cid] = row
            continue
        duplicates_collapsed += 1
        old_score = existing["comp"].risk_score
        new_score = row["comp"].risk_score
        if (new_score if new_score is not None else -1.0) > (old_score if old_score is not None else -1.0):
            deduped[cid] = row

    rows = list(deduped.values())
    unscored_rows = [r for r in rows if r["comp"].risk_score is None]
    queue_rows = [r for r in rows if r["comp"].risk_score is not None]
    queue_rows.sort(key=lambda r: (-r["comp"].risk_score, r["item"]["id"]))

    queue = [
        QueueEntry(
            id=row["item"]["id"],
            category=row["item"]["category"],
            label=row["item"]["label"],
            risk_score=row["comp"].risk_score,
            severity=row["comp"].severity.value,
            confidence=row["comp"].confidence,
            provisional=bool(row["comp"].confidence_breakdown.get("provisional")),
            observed_at=row["item"].get("observed_at"),
        )
        for row in queue_rows
    ]

    ranked = [(entry.risk_score, entry.label) for entry in queue]
    ranked_labels = [entry.label for entry in queue]
    total_positives = sum(1 for row in rows if row["item"]["label"] == 1)
    total_negatives = sum(1 for row in rows if row["item"]["label"] == 0)

    k = min(PRECISION_AT_K, len(queue))
    threshold = settings.severity_medium

    queue_ids = [entry.id for entry in queue]
    verified_in_queue = official_assets_in_queue(queue_ids, [it["id"] for it in backed_official])
    unverified_in_queue = [
        entry.id
        for entry in queue
        if entry.category == "official_asset" and entry.id not in backed_ids
    ]

    completeness, missing_fields = evidence_completeness(
        [_evidence_flags(row["item"], row["comp"]) for row in queue_rows]
    )

    return EvaluationReport(
        fixture=str(fixture_path),
        scoring_model_version=settings.scoring_model_version,
        configured_weights=settings.weights,
        threshold=threshold,
        coverage_floor=settings.scoring_coverage_floor,
        n_items=len(items),
        n_labeled_official=len(labeled_official),
        n_inventory_backed_official=len(backed_official),
        inventory_coverage=(
            len(backed_official) / len(labeled_official) if labeled_official else None
        ),
        n_official_excluded=sum(1 for iid, _ in excluded if iid in backed_ids),
        n_official_in_queue=len(verified_in_queue),
        n_unverified_official_in_queue=len(unverified_in_queue),
        duplicates_collapsed=duplicates_collapsed,
        n_positives=total_positives,
        n_negatives=total_negatives,
        n_queued=len(queue),
        n_unscored=len(unscored_rows),
        unscored_ids=[r["item"]["id"] for r in unscored_rows],
        k=k,
        precision_at_k=precision_at_k(ranked_labels, k),
        recall_at_threshold=recall_at_threshold(ranked, total_positives, threshold),
        average_precision=average_precision(ranked, total_positives),
        evidence_completeness=completeness,
        evidence_missing_fields=missing_fields,
        queue=queue,
    )
