"""Weighted risk scoring + separate, explicit confidence calculation.

RISK     R = sum_i(w_i * s_i) / sum_i(w_i)          over signals with status OK.
         Configured weights (default .30/.30/.25/.15) sum to 1. If a signal is UNAVAILABLE or FAILED the remaining
         weights are renormalised, so a missing signal is never treated as "zero risk". When all four are
         available this is exactly R = w1*s1 + w2*s2 + w3*s3 + w4*s4.

CONFIDENCE (how much to trust R - independent from R's magnitude)
         C = 0.4*evidence_quality + 0.3*availability + 0.3*corroboration     (weights configurable)
   availability      = sum of configured weights of the OK signals (1.0 when all four ran).
   evidence_quality  = mean over OK signals of q_i = min(1, 0.4 + 0.2*n_refs) * provenance_factor,
                       n_refs = number of evidence/reference links the signal cites (max counted: 3);
                       provenance_factor: collected 1.0, manual 0.6, synthetic 0.3 (configurable).
   corroboration     = 0 with a single OK signal, else ((n_ok - 1)/3) * (1 - (max_s - min_s)):
                       more independent signals that *agree* (high or low) => more confidence.
   Synthetic entities are additionally capped at `synthetic_confidence_cap` (default 0.40).

COVERAGE   coverage = sum of configured weights of the OK signals (same value as availability above).
         When every signal runs coverage = 1.0. If coverage >= scoring_coverage_floor (default 0.60)
         the renormalised score is treated as representative; below the floor the score is still
         computed (never silently zeroed) but the assessment is flagged `provisional` in
         confidence_breakdown and a note is attached, so thin-evidence rankings are visible instead of
         looking like full results. When NO signal can run there is no score at all and severity is
         UNKNOWN - that is the "insufficient evidence" case, not a low-risk verdict.

The thresholds and weights are illustrative heuristics. They have NOT been validated against labelled data.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.config import Settings
from app.models.enums import Provenance, Severity, SignalStatus, SignalType
from app.services.detection.base import SignalResult

ALL_SIGNALS = [t.value for t in SignalType]


@dataclass
class ScoreComputation:
    risk_score: float | None
    severity: Severity
    confidence: float
    confidence_breakdown: dict[str, Any]
    configured_weights: dict[str, float]
    effective_weights: dict[str, float]
    component_scores: dict[str, float | None]
    thresholds: dict[str, float]
    notes: str


def severity_for(score: float | None, s: Settings) -> Severity:
    if score is None:
        return Severity.UNKNOWN
    if score >= s.severity_critical:
        return Severity.CRITICAL
    if score >= s.severity_high:
        return Severity.HIGH
    if score >= s.severity_medium:
        return Severity.MEDIUM
    return Severity.LOW


def confidence_label(c: float, s: Settings) -> str:
    return "high" if c >= s.confidence_high else "medium" if c >= s.confidence_medium else "low"


def provenance_factor(p: Provenance, s: Settings) -> float:
    return {
        Provenance.COLLECTED: s.provenance_factor_collected,
        Provenance.MANUAL: s.provenance_factor_manual,
        Provenance.SYNTHETIC: s.provenance_factor_synthetic,
    }[p]


def compute_score(results: list[SignalResult], provenance: Provenance, s: Settings) -> ScoreComputation:
    weights = s.weights
    ok = {r.signal_type.value: r for r in results if r.status == SignalStatus.OK and r.score is not None}
    components = {t: (ok[t].score if t in ok else None) for t in ALL_SIGNALS}
    thresholds = {"medium": s.severity_medium, "high": s.severity_high, "critical": s.severity_critical}
    missing = [t for t in ALL_SIGNALS if t not in ok]

    if not ok:
        return ScoreComputation(
            None, Severity.UNKNOWN, 0.0,
            {"evidence_quality": 0.0, "availability": 0.0, "corroboration": 0.0, "label": "low", "available_signals": [],
             "unavailable_signals": missing, "coverage": 0.0, "coverage_floor": s.scoring_coverage_floor,
             "provisional": True, "provenance": provenance.value, "synthetic_cap_applied": False, "formula": _FORMULA},
            weights, {t: 0.0 for t in ALL_SIGNALS}, components, thresholds,
            "No detection signal had enough data; no risk score was computed. This is NOT a low-risk result.",
        )

    wsum = sum(weights[t] for t in ok)
    eff = {t: (weights[t] / wsum if t in ok else 0.0) for t in ALL_SIGNALS}
    risk = round(min(1.0, max(0.0, sum(eff[t] * ok[t].score for t in ok))), 4)

    pf = provenance_factor(provenance, s)
    q = []
    for t, r in ok.items():
        n_refs = min(len([x for x in r.evidence_refs if x.get("type") in ("evidence", "brand_reference")]), 3)
        q.append(min(1.0, 0.4 + 0.2 * n_refs) * pf)
    evidence_quality = sum(q) / len(q)
    availability = sum(weights[t] for t in ok)
    scores = [ok[t].score for t in ok]
    corroboration = 0.0 if len(ok) < 2 else ((len(ok) - 1) / (len(ALL_SIGNALS) - 1)) * (1 - (max(scores) - min(scores)))
    conf = (s.confidence_w_evidence * evidence_quality + s.confidence_w_availability * availability + s.confidence_w_corroboration * corroboration)
    capped = provenance == Provenance.SYNTHETIC and conf > s.synthetic_confidence_cap
    if capped:
        conf = s.synthetic_confidence_cap
    conf = round(min(1.0, max(0.0, conf)), 4)
    provisional = availability < s.scoring_coverage_floor
    note = "Heuristic, unvalidated scoring model - requires human review before any enforcement action."
    if missing:
        note += " Weights were renormalised over available signals; unavailable: " + ", ".join(missing) + "."
    if provisional:
        note += (f" Provisional: signal coverage {availability:.2f} is below the {s.scoring_coverage_floor:.2f}"
                 " evidence floor, so this ranking rests on partial evidence.")
    if provenance == Provenance.SYNTHETIC:
        note += " Entity is synthetic demonstration data; confidence is capped."
    return ScoreComputation(
        risk, severity_for(risk, s), conf,
        {"evidence_quality": round(evidence_quality, 4), "availability": round(availability, 4),
         "corroboration": round(corroboration, 4), "label": confidence_label(conf, s), "available_signals": sorted(ok),
         "unavailable_signals": missing, "coverage": round(availability, 4),
         "coverage_floor": s.scoring_coverage_floor, "provisional": provisional,
         "provenance": provenance.value, "provenance_factor": pf,
         "synthetic_cap_applied": capped, "formula": _FORMULA},
        weights, {t: round(v, 6) for t, v in eff.items()}, {t: (round(v, 4) if v is not None else None) for t, v in components.items()},
        thresholds, note,
    )


_FORMULA = (
    "confidence = w_e*evidence_quality + w_a*availability + w_c*corroboration; "
    "corroboration = ((n_ok-1)/3)*(1-(max-min)); synthetic entities capped"
)
