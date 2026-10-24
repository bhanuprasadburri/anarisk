"""Phase 5 evaluation of the Round 2 ranking: labeled fixtures + measured metrics."""
from app.evaluation.harness import DEFAULT_FIXTURE, EvaluationReport, load_fixture, run_evaluation
from app.evaluation.metrics import (
    average_precision,
    evidence_completeness,
    official_assets_in_queue,
    precision_at_k,
    recall_at_threshold,
)

__all__ = [
    "DEFAULT_FIXTURE",
    "EvaluationReport",
    "load_fixture",
    "run_evaluation",
    "average_precision",
    "evidence_completeness",
    "official_assets_in_queue",
    "precision_at_k",
    "recall_at_threshold",
]
