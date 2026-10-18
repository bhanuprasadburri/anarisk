"""Shared building blocks for the on-demand investigation tools.

Every tool produces a list of :class:`Finding` dicts plus an overall risk/confidence pair.
The rules that govern this module are strict:

- Every finding must carry evidence (what was observed) and a source (how it was obtained).
- A check that could not be executed (DNS failure, no credentials, unsupported provider)
  is reported as ``unable_to_verify`` with a reason - never silently dropped and never
  reported as a pass.
- Risk (how concerning the evidence is) and confidence (how complete/corroborated the
  evidence is) are separate numbers.
- Missing data is never treated as proof of safety.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from app.core.config import get_settings
from app.utils.urls import registrable_domain
from app.utils.text import identity_similarity

log = logging.getLogger(__name__)

METHODOLOGY_VERSION = "tools-v1"

FindingStatus = Literal["verified", "suspicious", "inconclusive", "unable_to_verify", "info"]
Severity = Literal["none", "low", "medium", "high", "critical", "unknown"]

# Weight of each finding status in the overall risk computation.
_STATUS_WEIGHT: dict[str, float] = {
    "suspicious": 1.0,
    "verified": 0.85,  # a *negative* fact established by an authoritative source
    "inconclusive": 0.35,
    "unable_to_verify": 0.0,  # availability feeds confidence, not risk
    "info": 0.0,
}
_SEVERITY_ORDER = ["none", "low", "medium", "high", "critical"]

# Max characters of any submitted text kept in the persisted input summary.
MAX_STORED_INPUT = 4000


@dataclass
class Finding:
    check: str
    title: str
    status: FindingStatus
    severity: Severity = "none"
    summary: str = ""
    evidence: list[str] = field(default_factory=list)
    source: str = ""
    limitation: str | None = None
    weight: float = 1.0  # relative importance of this check within the tool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def dns_query(name: str, rdtype: str, lifetime: float = 4.0) -> tuple[list[str] | None, str | None]:
    """Resolve a DNS record. Returns (records, error). Never raises.

    Uses the system resolver. On failure the error is returned so callers can surface an
    honest 'unable to verify' finding instead of pretending the check passed.
    """
    try:
        import dns.resolver  # dnspython is a hard dependency

        answer = dns.resolver.resolve(name, rdtype, lifetime=lifetime, raise_on_no_answer=False)
        if answer is None or answer.rrset is None:
            return [], None  # authoritative absence of the record (a real, useful result)
        return [str(r) for r in answer], None
    except Exception as exc:  # NXDOMAIN, timeouts, no route, no resolver...
        return None, f"{type(exc).__name__}: {exc}"


def check_spf_and_dmarc(domain: str) -> list[Finding]:
    """SPF + DMARC discovery for a domain. Absence is 'inconclusive' (weak signal on its own);
    a lookup failure is 'unable_to_verify'."""
    findings: list[Finding] = []
    spf, spf_err = dns_query(domain, "TXT")
    if spf_err:
        findings.append(Finding(
            check="dns_spf", title="SPF record", status="unable_to_verify", severity="unknown",
            summary=f"Could not query DNS for an SPF record on {domain}.",
            evidence=[f"TXT lookup failed: {spf_err}"], source="DNS (system resolver)",
            limitation="DNS was unavailable; this says nothing about whether the domain is legitimate.",
        ))
    else:
        has_spf = any(rec.strip('"').lower().startswith("v=spf1") for rec in spf or [])
        findings.append(Finding(
            check="dns_spf", title="SPF record", status="verified" if has_spf else "inconclusive",
            severity="none" if has_spf else "low",
            summary=(f"{domain} publishes an SPF record." if has_spf
                     else f"No SPF record found on {domain}."),
            evidence=[f"TXT records inspected: {len(spf or [])}"],
            source="DNS (system resolver)",
            limitation="SPF can be published by malicious domains too; absence is a weak signal only.",
        ))
    dmarc_recs, dmarc_err = dns_query(f"_dmarc.{domain}", "TXT")
    if dmarc_err:
        findings.append(Finding(
            check="dns_dmarc", title="DMARC record", status="unable_to_verify", severity="unknown",
            summary=f"Could not query DNS for a DMARC record on {domain}.",
            evidence=[f"_dmarc TXT lookup failed: {dmarc_err}"], source="DNS (system resolver)",
            limitation="DNS was unavailable; no conclusion can be drawn.",
        ))
    else:
        has_dmarc = any(rec.strip('"').lower().startswith("v=dmarc1") for rec in dmarc_recs or [])
        findings.append(Finding(
            check="dns_dmarc", title="DMARC record", status="verified" if has_dmarc else "inconclusive",
            severity="none" if has_dmarc else "low",
            summary=(f"{domain} publishes a DMARC record." if has_dmarc
                     else f"No DMARC record found on {domain}."),
            evidence=[f"_dmarc TXT records inspected: {len(dmarc_recs or [])}"],
            source="DNS (system resolver)",
            limitation="A DMARC record only describes policy; it does not prove the sender is trustworthy.",
        ))
    return findings


def domain_lookalike_check(candidate_domain: str, official_domains: list[str]) -> Finding:
    """Compare a candidate domain against known-official domains."""
    cand = registrable_domain(candidate_domain)
    best_match, best_score, best_reason = None, 0.0, ""
    for off in official_domains:
        off_reg = registrable_domain(off)
        score, reason = identity_similarity(cand, off_reg)
        if score > best_score:
            best_match, best_score, best_reason = off_reg, score, reason
    if best_match is None:
        return Finding(
            check="lookalike_domain", title="Lookalike domain analysis", status="unable_to_verify",
            severity="unknown", summary="No official domains are registered in this workspace to compare against.",
            evidence=["0 official domain references available"], source="Workspace brand references",
            limitation="Add official domains for your brands to enable lookalike detection.",
        )
    if best_match == cand:
        return Finding(
            check="lookalike_domain", title="Lookalike domain analysis", status="verified", severity="none",
            summary=f"{cand} exactly matches the registered official domain {best_match}.",
            evidence=[f"exact match: {best_match}"], source="Workspace brand references",
            limitation="A matching domain does not prove the specific page or account is legitimate.",
        )
    if best_score >= 0.85:
        return Finding(
            check="lookalike_domain", title="Lookalike domain analysis", status="suspicious", severity="high",
            summary=f"{cand} closely resembles the official domain {best_match} (similarity {best_score:.2f}, {best_reason}).",
            evidence=[f"candidate: {cand}", f"official: {best_match}", f"similarity: {best_score:.2f} ({best_reason})"],
            source="Workspace brand references + string similarity",
            limitation="Similarity is a heuristic; verify the domain owner before drawing conclusions.",
        )
    if best_score >= 0.65:
        return Finding(
            check="lookalike_domain", title="Lookalike domain analysis", status="inconclusive", severity="medium",
            summary=f"{cand} shares some similarity with official domain {best_match} (similarity {best_score:.2f}).",
            evidence=[f"candidate: {cand}", f"closest official: {best_match}", f"similarity: {best_score:.2f}"],
            source="Workspace brand references + string similarity",
            limitation="Shared words can be coincidental; needs analyst judgement.",
        )
    return Finding(
        check="lookalike_domain", title="Lookalike domain analysis", status="info", severity="none",
        summary=f"{cand} does not closely resemble any registered official domain (closest: {best_match}, {best_score:.2f}).",
        evidence=[f"closest official: {best_match}", f"similarity: {best_score:.2f}"],
        source="Workspace brand references + string similarity",
        limitation="Only covers domains registered in this workspace; unknown brands cannot be checked.",
    )


def url_heuristic_check(url: str, claimed_brand_domains: list[str] | None = None) -> Finding:
    """Static (offline) URL risk indicators. No network access."""
    from app.utils.urls import domain_label, extract_urls, parse_url, tld_of  # local import keeps utils pure

    s = get_settings()
    parsed = parse_url(url)
    if parsed is None:
        return Finding(
            check="url_static", title="URL structure", status="unable_to_verify", severity="unknown",
            summary="The submitted value is not a valid http(s) URL.",
            evidence=[f"input: {url[:200]}"], source="URL parser",
            limitation="Could not analyse; provide a full http:// or https:// URL.",
        )
    indicators: list[str] = []
    if parsed.is_ip:
        indicators.append("host is a raw IP address")
    if parsed.has_userinfo:
        indicators.append("URL contains userinfo (@) - a classic spoofing technique")
    if parsed.scheme == "http":
        indicators.append("unencrypted http://")
    if parsed.host.startswith("xn--") or ".xn--" in parsed.host:
        indicators.append("punycode/IDN host (homograph risk)")
    tld = tld_of(parsed.host)
    if tld in s.suspicious_tlds:
        indicators.append(f"risky TLD '.{tld}'")
    if parsed.host in s.url_shorteners:
        indicators.append("known URL shortener (destination hidden)")
    label = domain_label(parsed.host)
    for kw in s.suspicious_keywords:
        if kw in label or kw in parsed.path.lower():
            indicators.append(f"phishing-associated keyword '{kw}' in URL")
            break
    depth = parsed.path.count("/")
    if depth >= 4:
        indicators.append(f"deeply nested path (depth {depth}) - common in redirect chains")
    for off in claimed_brand_domains or []:
        if parsed.host != off and off in parsed.host and registrable_domain(off) != registrable_domain(parsed.host):
            indicators.append(f"official domain '{off}' embedded in a different host")
    if not indicators:
        return Finding(
            check="url_static", title="URL structure", status="info", severity="none",
            summary=f"No static risk indicators found in {parsed.canonical}.",
            evidence=[f"canonical: {parsed.canonical}", "checked: scheme, userinfo, TLD, shortener, keywords, structure"],
            source="Offline URL heuristics",
            limitation="Static structure says nothing about the content or reputation of the destination.",
        )
    sev = "high" if len(indicators) >= 3 or any("@" in i or "raw IP" in i for i in indicators) else "medium"
    return Finding(
        check="url_static", title="URL structure", status="suspicious", severity=sev,
        summary=f"{len(indicators)} static risk indicator(s) in {parsed.canonical}.",
        evidence=indicators, source="Offline URL heuristics",
        limitation="Indicators are heuristic; each one also occurs on legitimate URLs occasionally.",
    )


def compute_overall(findings: list[Finding]) -> tuple[float | None, Severity, float]:
    """Aggregate findings into (risk_score, severity, confidence).

    Risk is the weighted average of *available* findings (unable_to_verify contributes zero
    weight but reduces confidence). Confidence reflects how many checks produced a definite
    result and whether evidence corroborates across independent sources.
    """
    if not findings:
        return None, "unknown", 0.0
    total_w = sum(_STATUS_WEIGHT[f.status] * f.weight for f in findings)
    # denominator: weight of checks that produced a definite result (exclude pure info & unavailable)
    definite = [f for f in findings if f.status in ("verified", "suspicious", "inconclusive")]
    if not definite:
        # nothing checkable: risk unknown, confidence reflects availability only
        return None, "unknown", 0.0
    denom = sum(f.weight for f in definite)
    risk = max(0.0, min(1.0, total_w / denom)) if denom else 0.0
    if risk >= get_settings().severity_critical:
        sev: Severity = "critical"
    elif risk >= get_settings().severity_high:
        sev = "high"
    elif risk >= get_settings().severity_medium:
        sev = "medium"
    elif risk > 0:
        sev = "low"
    else:
        sev = "none"
    unavailable = sum(1 for f in findings if f.status == "unable_to_verify")
    availability = max(0.0, 1.0 - unavailable / len(findings))
    sources = {f.source for f in definite if f.source}
    corroboration = min(1.0, len(sources) / 3)
    confidence = round(0.5 * availability + 0.5 * corroboration, 3)
    return round(risk, 3), sev, confidence


def sanitize_input(data: dict[str, Any]) -> dict[str, Any]:
    """Truncate long strings so raw emails/bodies are stored only up to a bounded size."""
    out: dict[str, Any] = {}
    for k, v in data.items():
        if isinstance(v, str):
            out[k] = v[:MAX_STORED_INPUT] + ("…[truncated]" if len(v) > MAX_STORED_INPUT else "")
        elif isinstance(v, list):
            out[k] = [str(x)[:500] for x in v[:25]]
        else:
            out[k] = v
    return out
