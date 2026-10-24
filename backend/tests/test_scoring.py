import pytest
from pydantic import ValidationError

from app.core.config import PLACEHOLDER_SECRET, Settings, get_settings
from app.models.enums import Provenance, Severity, SignalStatus, SignalType
from app.services.detection.base import SignalResult
from app.services.scoring import compute_score, severity_for


def R(t, score, refs=0):
    if score is None:
        return SignalResult.unavailable(t, "no data")
    return SignalResult(t, SignalStatus.OK, score, "x", [{"type": "evidence", "id": str(i)} for i in range(refs)])


S = SignalType
def four(a, b, c, d, refs=0):
    return [R(S.BRAND_LOGO, a, refs), R(S.IMPERSONATION, b, refs), R(S.URL_RISK, c, refs), R(S.BEHAVIOR, d, refs)]


def test_default_weights_match_documentation(settings):
    assert settings.weights == pytest.approx({"brand_logo": 0.30, "impersonation": 0.30, "url_risk": 0.25, "behavior": 0.15})
    assert sum(settings.weights.values()) == pytest.approx(1.0)


def test_weighted_formula_exact(settings):
    c = compute_score(four(0.9, 0.8, 0.7, 0.6), Provenance.COLLECTED, settings)
    assert c.risk_score == pytest.approx(0.30 * 0.9 + 0.30 * 0.8 + 0.25 * 0.7 + 0.15 * 0.6)
    assert c.component_scores == {"brand_logo": 0.9, "impersonation": 0.8, "url_risk": 0.7, "behavior": 0.6}
    assert c.effective_weights == pytest.approx(c.configured_weights)


def test_missing_signals_renormalise_not_zero(settings):
    c = compute_score(four(1.0, 1.0, None, None), Provenance.MANUAL, settings)
    assert c.risk_score == 1.0                                                       # not 0.6 (which would treat missing as zero risk)
    assert c.effective_weights["url_risk"] == 0 and c.effective_weights["brand_logo"] == pytest.approx(0.5)
    assert c.component_scores["url_risk"] is None and "unavailable" in c.notes
    assert c.confidence_breakdown["unavailable_signals"] == ["url_risk", "behavior"]


def test_failed_signal_treated_like_unavailable(settings):
    results = four(0.5, 0.5, 0.5, None)
    results[2] = SignalResult.failed(S.URL_RISK, "boom")
    c = compute_score(results, Provenance.MANUAL, settings)
    assert c.risk_score == 0.5 and "url_risk" in c.confidence_breakdown["unavailable_signals"]


def test_all_unavailable_is_unknown_not_low(settings):
    c = compute_score(four(None, None, None, None), Provenance.MANUAL, settings)
    assert c.risk_score is None and c.severity == Severity.UNKNOWN and c.confidence == 0.0 and "NOT a low-risk result" in c.notes


@pytest.mark.parametrize("score,sev", [(None, "unknown"), (0.0, "low"), (0.399, "low"), (0.4, "medium"), (0.599, "medium"), (0.6, "high"), (0.799, "high"), (0.8, "critical"), (1.0, "critical")])
def test_severity_thresholds(settings, score, sev):
    assert severity_for(score, settings).value == sev


def test_confidence_components_are_explicit_and_separate_from_risk(settings):
    all_agree_high = compute_score(four(0.9, 0.9, 0.9, 0.9, refs=3), Provenance.COLLECTED, settings)
    all_agree_low = compute_score(four(0.05, 0.05, 0.05, 0.05, refs=3), Provenance.COLLECTED, settings)
    bd = all_agree_high.confidence_breakdown
    assert bd["availability"] == 1.0 and bd["corroboration"] == 1.0 and bd["evidence_quality"] == 1.0
    assert all_agree_high.confidence == pytest.approx(1.0)
    assert all_agree_low.confidence == pytest.approx(all_agree_high.confidence)     # confidence is independent of magnitude
    assert all_agree_low.risk_score < 0.1 < 0.8 < all_agree_high.risk_score


def test_confidence_drops_with_disagreement_missing_signals_and_weak_evidence(settings):
    strong = compute_score(four(0.9, 0.9, 0.9, 0.9, refs=3), Provenance.COLLECTED, settings).confidence
    disagree = compute_score(four(0.9, 0.0, 0.9, 0.0, refs=3), Provenance.COLLECTED, settings).confidence
    fewer = compute_score(four(0.9, 0.9, None, None, refs=3), Provenance.COLLECTED, settings).confidence
    no_refs = compute_score(four(0.9, 0.9, 0.9, 0.9, refs=0), Provenance.COLLECTED, settings).confidence
    single = compute_score(four(0.9, None, None, None, refs=3), Provenance.COLLECTED, settings)
    assert strong > disagree and strong > fewer and strong > no_refs
    assert single.confidence_breakdown["corroboration"] == 0.0 and single.confidence < strong


def test_provenance_lowers_confidence_and_synthetic_is_capped(settings):
    col = compute_score(four(0.9, 0.9, 0.9, 0.9, refs=3), Provenance.COLLECTED, settings)
    man = compute_score(four(0.9, 0.9, 0.9, 0.9, refs=3), Provenance.MANUAL, settings)
    syn = compute_score(four(0.9, 0.9, 0.9, 0.9, refs=3), Provenance.SYNTHETIC, settings)
    assert col.confidence > man.confidence > syn.confidence
    assert syn.confidence <= settings.synthetic_confidence_cap and syn.confidence_breakdown["synthetic_cap_applied"] is True
    assert syn.risk_score == col.risk_score                                          # provenance never changes the risk number


def test_settings_normalise_weights_and_validate():
    s = Settings(weight_brand_logo=3, weight_impersonation=3, weight_url_risk=2.5, weight_behavior=1.5, _env_file=None)
    assert sum(s.weights.values()) == pytest.approx(1.0) and s.weights["brand_logo"] == pytest.approx(0.30)
    with pytest.raises(ValidationError):
        Settings(weight_brand_logo=0, weight_impersonation=0, weight_url_risk=0, weight_behavior=0, _env_file=None)
    with pytest.raises(ValidationError):
        Settings(severity_medium=0.7, severity_high=0.6, _env_file=None)


def test_custom_weights_change_score():
    s = Settings(weight_brand_logo=1, weight_impersonation=0, weight_url_risk=0, weight_behavior=0, _env_file=None)
    assert compute_score(four(0.2, 1, 1, 1), Provenance.COLLECTED, s).risk_score == 0.2


def test_production_refuses_unsafe_configuration():
    with pytest.raises(ValidationError):
        Settings(environment="production", secret_key=PLACEHOLDER_SECRET, _env_file=None)    # placeholder secret
    with pytest.raises(ValidationError):
        Settings(environment="production", secret_key="short", _env_file=None)
    with pytest.raises(ValidationError):
        Settings(environment="production", secret_key="x" * 40, cors_origins=["*"], _env_file=None)
    assert Settings(environment="production", secret_key="x" * 40, cors_origins=["https://app.example"], _env_file=None).environment == "production"


def test_full_coverage_is_not_provisional(settings):
    c = compute_score(four(0.9, 0.8, 0.7, 0.6), Provenance.COLLECTED, settings)
    bd = c.confidence_breakdown
    assert bd["coverage"] == pytest.approx(1.0) and bd["coverage_floor"] == 0.60
    assert bd["provisional"] is False and "Provisional" not in c.notes
    assert bd["coverage"] == pytest.approx(bd["availability"])       # coverage IS the sum of observed weights


def test_thin_evidence_is_marked_provisional(settings):
    # only the 0.15-weight behaviour signal ran: coverage 0.15 < 0.60 evidence floor
    c = compute_score([R(S.BEHAVIOR, 0.8)], Provenance.COLLECTED, settings)
    bd = c.confidence_breakdown
    assert bd["coverage"] == pytest.approx(0.15) and bd["provisional"] is True
    assert "Provisional" in c.notes and "partial evidence" in c.notes
    assert c.risk_score == 0.8            # still scored (weights renormalised), not zeroed and not hidden


def test_coverage_at_or_above_floor_is_representative(settings):
    # logo + impersonation + url_risk = 0.85 >= 0.60 -> representative even though behaviour is missing
    c = compute_score(four(0.5, 0.5, 0.5, None), Provenance.COLLECTED, settings)
    bd = c.confidence_breakdown
    assert bd["coverage"] == pytest.approx(0.85) and bd["provisional"] is False
    assert "Provisional" not in c.notes


def test_no_evidence_is_zero_coverage_and_unknown(settings):
    c = compute_score(four(None, None, None, None), Provenance.MANUAL, settings)
    bd = c.confidence_breakdown
    assert bd["coverage"] == 0.0 and bd["provisional"] is True
    assert c.risk_score is None and c.severity == Severity.UNKNOWN   # insufficient evidence, not a low-risk verdict


def test_coverage_floor_is_validated():
    with pytest.raises(ValidationError):
        Settings(scoring_coverage_floor=1.5, _env_file=None)
    with pytest.raises(ValidationError):
        Settings(scoring_coverage_floor=-0.1, _env_file=None)
    assert Settings(scoring_coverage_floor=0.0, _env_file=None).scoring_coverage_floor == 0.0
