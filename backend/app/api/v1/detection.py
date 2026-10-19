import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import Pagination, require_permission
from app.core.rate_limit import rate_limit
from app.db.session import get_db
from app.models import User
from app.models.enums import EntityType, Provenance, Severity, SignalStatus, SignalType
from app.schemas.common import Page
from app.schemas.detection import (
    AssessmentOut, BulkAnalyzeRequest, BulkAnalyzeResult, DetectionEntityRef, DetectionItem, ModelInfo, SignalOut,
)
from app.services import analysis

# Prefix-free router: the /detection/* routes keep their historical paths while the
# /detections* feed used by the web app is added alongside them.
router = APIRouter(tags=["Detection & Risk Scoring"])

# Plain-English description of the ACTUAL heuristics in app/services/detection/*.py.
RULE_DESCRIPTIONS = [
    {"signal_type": "brand_logo", "label": "Visual brand impersonation",
     "rules": ("Compares 64-bit perceptual hashes (pHash) of every image attached to the entity (attributes.image_phashes / uploaded "
               "evidence) with the brand's registered official images. Distance 0 => 1.0, <= near_duplicate (default 6) => 0.95..0.60, "
               "linearly down to 0 at max_distance (default 14) bits. A byte-identical file match scores 1.0. "
               "UNAVAILABLE (never 0) when the entity has no image data or the brand has no official images to compare against.")},
    {"signal_type": "impersonation", "label": "Identity impersonation",
     "rules": ("Compares the entity's name/handle/publisher/package_id with the brand's official NAME, HANDLE and PUBLISHER references "
               "and the brand name itself (normalised identity similarity), and its bio/description with official BIO text (word-set "
               "overlap). Similarity below impersonation_min_similarity (0.55) counts as no resemblance; the raw similarity is rescaled "
               "to 0..1 over [0.55, 1]. Publisher similarity is weighted 0.9, bio overlap 0.85; the score is the strongest component, "
               "plus 0.10 when two or more independent components reach 0.3, plus 0.05 when the name claims official/support status.")},
    {"signal_type": "url_risk", "label": "Suspicious URL / infrastructure",
     "rules": ("Every URL/domain/link on the entity is analysed against the brand's official domains. Indicators and weights: "
               "lookalike domain 0.35-0.80 (identity similarity >= 0.75 with an official domain label), brand name in host 0.45, "
               "brand name in path 0.25, configured suspicious TLD 0.15, punycode 0.30, raw IP host 0.40, '@' userinfo 0.40, "
               "URL shortener 0.25, >= 3 subdomain levels 0.15, multiple hyphens 0.10, long URL 0.05, request-style keywords "
               "(login/verify/claim/...) 0.10 each capped at 0.25, plain HTTP 0.05. Combined score = 1 - product(1 - weight). "
               "The entity score is the highest-risk URL. UNAVAILABLE when the entity carries no parseable URL.")},
    {"signal_type": "behavior", "label": "Inauthentic account behaviour",
     "rules": ("Three components, each UNAVAILABLE (never 0) when its input data is missing, combined with weights "
               "account_age 0.4, velocity 0.3, coordination 0.3, renormalised over available components. "
               "account_age: created < 7d => 1.0, < 30d => 0.7, < 90d => 0.4, < 365d => 0.15, else 0. "
               "velocity: posts/day over velocity_posts_per_day_saturation (20) or followers/day over 500, both capped at 1.0. "
               "coordination: probability-style combination of shared indicators with peer entities of the same brand "
               "(shares image 0.50, similar identity 0.40, shares domain 0.40, same infrastructure 0.50, coordinated behaviour 0.60; "
               "+0.10 when shared with >= 3 peers), plus a repeat-submission factor when the entity was submitted >= 3 times.")},
]


@router.get("/detection/model", response_model=ModelInfo,
            summary="Active scoring model: version, weights, thresholds, confidence formula and plain-English rule descriptions")
def model(_: User = Depends(require_permission("entity:read"))):
    from app.core.config import get_settings

    s = get_settings()
    return ModelInfo(model_version=s.scoring_model_version, weights=s.weights,
                     severity_thresholds={"medium": s.severity_medium, "high": s.severity_high, "critical": s.severity_critical},
                     confidence={"weights": {"evidence_quality": s.confidence_w_evidence, "availability": s.confidence_w_availability, "corroboration": s.confidence_w_corroboration},
                                 "provenance_factors": {"collected": s.provenance_factor_collected, "manual": s.provenance_factor_manual, "synthetic": s.provenance_factor_synthetic},
                                 "synthetic_cap": s.synthetic_confidence_cap, "labels": {"medium": s.confidence_medium, "high": s.confidence_high}},
                     rule_description=RULE_DESCRIPTIONS)


@router.post("/detection/analyze", response_model=BulkAnalyzeResult, dependencies=[Depends(rate_limit("analyze", "analyze_rate_limit_per_minute"))],
             summary="Analyze several entities (by ids) or every entity of a brand (max 200)")
def analyze(body: BulkAnalyzeRequest, user: User = Depends(require_permission("entity:analyze")), db: Session = Depends(get_db)):
    assessments, skipped = analysis.analyze_many(db, user, body.entity_ids, body.brand_id)
    return BulkAnalyzeResult(analyzed=len(assessments), skipped=skipped, assessments=[AssessmentOut.model_validate(a) for a in assessments])


@router.get("/detection/signals", response_model=Page[SignalOut], summary="Signal results (latest assessment per entity unless latest_only=false)")
def signals(p: Pagination = Depends(), entity_id: uuid.UUID | None = None, signal_type: SignalType | None = None, status: SignalStatus | None = None,
            latest_only: bool = True, user: User = Depends(require_permission("entity:read")), db: Session = Depends(get_db)):
    rows, total = analysis.list_signals(db, user, p.page, p.page_size, entity_id, signal_type, status, latest_only)
    outs = []
    for sig, ent in rows:
        out = SignalOut.model_validate(sig)
        out.entity = DetectionEntityRef(id=ent.id, display_name=ent.display_name, entity_type=ent.entity_type.value,
                                        canonical_id=ent.canonical_id, platform=ent.platform, provenance=ent.provenance.value)
        outs.append(out)
    return Page.build(outs, total, p.page, p.page_size)


@router.get("/detection/assessments/{assessment_id}", response_model=AssessmentOut)
def assessment(assessment_id: uuid.UUID, user: User = Depends(require_permission("entity:read")), db: Session = Depends(get_db)):
    return analysis.get_assessment(db, user, assessment_id)


# ------------------------------ detections feed ------------------------------
@router.get("/detections", response_model=Page[DetectionItem],
            summary="Flattened latest assessment per entity: filters q, severity, entity_type, brand_id, status, provenance, from, to; sort risk_score|confidence|assessed_at")
def list_detections(p: Pagination = Depends(), q: str | None = Query(None, max_length=100), severity: Severity | None = None,
                    entity_type: EntityType | None = None, brand_id: uuid.UUID | None = None,
                    status: str | None = Query(None, pattern="^(analyzed|partial|unavailable)$"), provenance: Provenance | None = None,
                    date_from: datetime | None = Query(None, alias="from"), date_to: datetime | None = Query(None, alias="to"),
                    sort: str = Query("assessed_at", pattern="^(risk_score|confidence|assessed_at)$"),
                    order: str = Query("desc", pattern="^(asc|desc)$"),
                    user: User = Depends(require_permission("entity:read")), db: Session = Depends(get_db)):
    items, total = analysis.list_detections(db, user, page=p.page, page_size=p.page_size, q=q, severity=severity, entity_type=entity_type,
                                            brand_id=brand_id, status=status, provenance=provenance, date_from=date_from, date_to=date_to,
                                            sort=sort, order=order)
    return Page.build(items, total, p.page, p.page_size)


@router.get("/detections/{assessment_id}", response_model=AssessmentOut, summary="Full assessment behind a detection (same shape as /detection/assessments/{id})")
def get_detection(assessment_id: uuid.UUID, user: User = Depends(require_permission("entity:read")), db: Session = Depends(get_db)):
    return analysis.get_assessment(db, user, assessment_id)


@router.post("/detections/{assessment_id}/re-analyze", response_model=AssessmentOut,
             dependencies=[Depends(rate_limit("analyze", "analyze_rate_limit_per_minute"))],
             summary="Re-run the four detection families on the assessment's entity; returns the NEW assessment (history is preserved)")
def reanalyze(assessment_id: uuid.UUID, user: User = Depends(require_permission("entity:analyze")), db: Session = Depends(get_db)):
    from app.repositories.access import get_entity_for_user

    current = analysis.get_assessment(db, user, assessment_id)
    entity = get_entity_for_user(db, user, current.entity_id)
    return analysis.analyze_entity(db, user, entity)
