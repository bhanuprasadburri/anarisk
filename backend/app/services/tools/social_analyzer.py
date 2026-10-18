"""Social profile verification tool.

Assesses a submitted profile (handle, display name, bio, linked domain) against the official
references registered in the workspace. Provider identity (e.g. Instagram's own API saying
"this account belongs to X") is only claimed when a real connector for that platform is
configured; otherwise the result is explicitly an assessment of *submitted public data*.
"""
from __future__ import annotations

import re
from typing import Any

from app.services.tools.common import Finding, domain_lookalike_check, url_heuristic_check
from app.utils.text import GENERIC_AFFIXES, identity_similarity, normalize_text
from app.utils.urls import extract_urls, parse_url, registrable_domain

PLATFORM_HOSTS: dict[str, tuple[str, ...]] = {
    "instagram": ("instagram.com",),
    "facebook": ("facebook.com", "fb.com", "fb.me"),
    "x": ("x.com", "twitter.com", "t.co"),
    "tiktok": ("tiktok.com",),
    "youtube": ("youtube.com", "youtu.be"),
    "linkedin": ("linkedin.com", "linkedin.co"),
    "threads": ("threads.net",),
    "snapchat": ("snapchat.com",),
    "telegram": ("t.me", "telegram.me", "telegram.org"),
}


def analyze_social_profile(
    payload: dict[str, Any],
    official_handles: list[dict[str, str]],   # [{"value": "@acme", "platform": "instagram", "brand": "Acme"}]
    official_domains: list[str],
    brand_names: list[str],
    provider_verified: bool = False,          # True only when a real platform connector vouches for the identity
) -> tuple[str, list[Finding]]:
    findings: list[Finding] = []
    platform = (payload.get("platform") or "").strip().lower()
    profile_url = (payload.get("profile_url") or "").strip()
    handle = (payload.get("handle") or "").strip().lstrip("@")
    display_name = (payload.get("display_name") or "").strip()
    bio = (payload.get("bio") or "").strip()
    claimed_brand = (payload.get("claimed_brand") or "").strip()

    # 1. Platform / URL validation
    parsed = parse_url(profile_url) if profile_url else None
    if profile_url and parsed is None:
        findings.append(Finding(
            check="profile_url", title="Profile URL", status="unable_to_verify", severity="unknown",
            summary="The profile URL is not a valid http(s) URL.",
            evidence=[f"input: {profile_url[:200]}"], source="Submission", limitation="Provide the full profile URL.",
        ))
    if parsed:
        expected_hosts = PLATFORM_HOSTS.get(platform, ())
        host_ok = any(parsed.host == h or parsed.host.endswith("." + h) for h in expected_hosts) if expected_hosts else None
        if host_ok is True:
            findings.append(Finding(
                check="profile_url", title="Platform matches URL host", status="verified", severity="none",
                summary=f"The URL host {parsed.host} matches the declared platform '{platform}'.",
                evidence=[f"host: {parsed.host}", f"expected: {', '.join(expected_hosts)}"],
                source="Submission + platform host list",
                limitation="Confirms the URL shape only; the page content was not fetched.",
            ))
        elif host_ok is False:
            findings.append(Finding(
                check="profile_url", title="Platform does not match URL host", status="suspicious", severity="medium",
                summary=f"Declared platform is '{platform}' but the URL host is {parsed.host}.",
                evidence=[f"host: {parsed.host}", f"expected: {', '.join(expected_hosts)}"],
                source="Submission + platform host list",
                limitation="Mirrors and third-party viewer sites exist; check the destination before concluding.",
            ))
        else:
            findings.append(Finding(
                check="profile_url", title="Profile URL", status="info", severity="none",
                summary=f"Profile URL host {parsed.host} is not a recognised platform for '{platform or 'any platform'}'.",
                evidence=[f"host: {parsed.host}"], source="Submission + URL parser", limitation=None,
            ))
        # handle embedded in URL path, e.g. instagram.com/<handle>/
        m = re.match(r"^/([A-Za-z0-9._]+)/?$", parsed.path)
        if m and not handle:
            handle = m.group(1)

    # 2. Handle / display name vs official references
    if not handle and not display_name:
        findings.append(Finding(
            check="identity_similarity", title="Identity comparison", status="inconclusive", severity="low",
            summary="Neither a handle nor a display name was submitted; identity comparison cannot run.",
            evidence=["handle and display_name are empty"], source="Submission",
            limitation="Submit the profile handle and display name for comparison.",
        ))
    comparisons = [h for h in official_handles if not platform or not h.get("platform") or h["platform"] == platform]
    if not comparisons and official_handles:
        comparisons = official_handles  # fall back to all platforms when none match
    best: tuple[float, str, str, str] | None = None  # (score, reason, official_value, brand)
    for ref in comparisons:
        for candidate in (handle, display_name):
            if not candidate:
                continue
            score, reason = identity_similarity(candidate, ref["value"].lstrip("@"))
            if best is None or score > best[0]:
                best = (score, reason, ref["value"], ref.get("brand", "?"))
    if best is None:
        findings.append(Finding(
            check="identity_similarity", title="Identity vs official references", status="unable_to_verify",
            severity="unknown", summary="No official handle references are registered in this workspace.",
            evidence=["0 official handle references available"], source="Workspace brand references",
            limitation="Add official handles in Settings → Brands to enable impersonation checks.",
        ))
    else:
        score, reason, official_value, brand = best
        if score >= 0.99:
            findings.append(Finding(
                check="identity_similarity", title="Handle matches official reference", status="verified",
                severity="none",
                summary=f"The submitted identity exactly matches the official reference {official_value} for '{brand}' ({reason}).",
                evidence=[f"submitted handle: @{handle or '-'}", f"display name: {display_name or '-'}",
                          f"official: {official_value}", f"match: {reason}"],
                source="Workspace brand references",
                limitation=("This confirms the handle matches a registered reference; provider-level identity "
                            "verification requires a configured platform connector."),
            ))
        elif score >= 0.85:
            findings.append(Finding(
                check="identity_similarity", title="Handle closely resembles official reference",
                status="suspicious", severity="high",
                summary=f"'{handle or display_name}' closely resembles the official {brand} reference {official_value} "
                        f"without being identical (similarity {score:.2f}, {reason}).",
                evidence=[f"submitted: {handle or display_name}", f"official: {official_value}",
                          f"similarity: {score:.2f} ({reason})"],
                source="Workspace brand references + string similarity",
                limitation="Near-identical handles are the core impersonation pattern, but confirm before enforcement.",
            ))
        elif score >= 0.65:
            findings.append(Finding(
                check="identity_similarity", title="Handle partially resembles official reference",
                status="inconclusive", severity="medium",
                summary=f"'{handle or display_name}' partially resembles official reference {official_value} ({score:.2f}).",
                evidence=[f"submitted: {handle or display_name}", f"official: {official_value}", f"similarity: {score:.2f}"],
                source="Workspace brand references + string similarity",
                limitation="Partial resemblance is common across unrelated accounts.",
            ))
        else:
            findings.append(Finding(
                check="identity_similarity", title="Handle vs official references", status="info", severity="none",
                summary=f"'{handle or display_name}' does not resemble the closest official reference {official_value} ({score:.2f}).",
                evidence=[f"closest official: {official_value}", f"similarity: {score:.2f}"],
                source="Workspace brand references + string similarity", limitation=None,
            ))

    # 3. Generic-affix impersonation pattern (brand + "official/support/helpdesk")
    identity_core = normalize_text(handle or display_name)
    if brand_names and identity_core:
        for b in brand_names:
            nb = normalize_text(b)
            if nb and nb in identity_core:
                extras = [re.sub(r"[^a-z0-9]", "", e) for e in identity_core.replace(nb, " ").split()]
                generic_hits = [e for e in extras if e and e in GENERIC_AFFIXES]
                if generic_hits:
                    findings.append(Finding(
                        check="impersonation_pattern", title="Classic impersonation naming pattern",
                        status="suspicious", severity="medium",
                        summary=(f"The identity combines the brand name '{b}' with generic words "
                                 f"({', '.join(generic_hits)}) - the most common impersonation formula."),
                        evidence=[f"identity: {identity_core}", f"brand: {nb}", f"generic words: {generic_hits}"],
                        source="Text analysis",
                        limitation="Some brands legitimately run '@<brand>official' style accounts; compare with the official reference list.",
                    ))
                    break

    # 4. Bio analysis + linked domains
    urls = extract_urls(bio, limit=5)
    for u in urls[:3]:
        findings.append(url_heuristic_check(u, official_domains))
    if parsed is None and not urls:
        findings.append(Finding(
            check="linked_domains", title="Linked domains", status="info", severity="none",
            summary="No linked domain was submitted for analysis.",
            evidence=["no profile URL or bio links provided"], source="Submission", limitation=None,
        ))

    # 5. Provenance of this assessment
    findings.append(Finding(
        check="assessment_provenance", title="Identity verification provenance", status="info", severity="none",
        summary=("Identity claims are provider-verified through a configured platform connector."
                 if provider_verified else
                 "This is an assessment based on submitted public data and workspace references - "
                 "NOT provider-verified identity. No social platform API was queried."),
        evidence=[f"provider_verified: {provider_verified}"],
        source="Platform connector status",
        limitation=None if provider_verified else "Connect a platform integration (Settings → Integrations) to enable provider-verified lookups.",
    ))

    subject_label = (f"@{handle}" if handle else (display_name or profile_url))[:80]
    return subject_label, findings
