"""Job offer / recruitment scam analyzer.

Assesses an employer, a recruiter, an offer, a sender address and an application link as
*separate* components, so a weak or unverifiable employer does not sink the whole assessment.
A company or recruiter that cannot be found online is reported as ``inconclusive`` /
``unable_to_verify`` - never as fraudulent.
"""
from __future__ import annotations

import re
from typing import Any

from rapidfuzz import fuzz

from app.services.tools.common import (
    Finding, check_spf_and_dmarc, domain_lookalike_check, url_heuristic_check,
)
from app.utils.text import identity_similarity
from app.utils.urls import parse_url, registrable_domain
from app.services.tools.email_analyzer import FREEMAIL_DOMAINS

FEE_TERMS = [
    "training fee", "training deposit", "registration fee", "onboarding fee", "kit fee", "uniform fee",
    "visa fee", "deposit", "pay to start", "pay to apply", "investment", "recharge", "top-up", "referral fee",
]
PAYMENT_METHOD_TERMS = ["gift card", "google play card", "steam card", "bitcoin", "crypto", "usdt", "wire transfer", "western union", "moneygram"]
SENSITIVE_REQUEST_TERMS = [
    "bank account", "account number", "routing number", "iban", "otp", "one-time password", "atm pin",
    "passport", "social security", "ssn", "credit card", "cvv",
]
TOO_GOOD_TERMS = ["earn from home", "guaranteed income", "no experience needed", "part-time salary", "unlimited income", "daily payout", "earn instantly"]
PLATFORM_HOSTS = {
    "linkedin.com": "LinkedIn", "linkedin.co": "LinkedIn", "indeed.com": "Indeed", "glassdoor.com": "Glassdoor",
    "naukri.com": "Naukri", "monster.com": "Monster", "ziprecruiter.com": "ZipRecruiter",
}


def _find_terms(text: str, terms: list[str]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for t in terms:
        m = re.search(re.escape(t), text, re.IGNORECASE)
        if m:
            start = max(0, m.start() - 60)
            out.append((t, "…" + text[start: m.end() + 60].replace("\n", " ").strip() + "…"))
    return out


def analyze_job_offer(
    payload: dict[str, Any],
    official_domains: list[str],
    brand_names: list[str],
) -> tuple[str, list[Finding]]:
    findings: list[Finding] = []
    employer = (payload.get("employer_name") or "").strip()
    employer_site = (payload.get("employer_website") or "").strip()
    recruiter_email = (payload.get("recruiter_email") or "").strip().lower()
    recruiter_name = (payload.get("recruiter_name") or "").strip()
    recruiter_profile_url = (payload.get("recruiter_profile_url") or "").strip()
    application_url = (payload.get("application_url") or "").strip()
    job_text = (payload.get("job_description") or "") + "\n" + (payload.get("offer_text") or "")

    # ---- 1. Employer identity ----
    employer_domain = None
    parsed_site = parse_url(employer_site) if employer_site else None
    if employer_site and parsed_site is None:
        findings.append(Finding(
            check="employer_website", title="Employer website", status="unable_to_verify", severity="unknown",
            summary="The employer website is not a valid http(s) URL.",
            evidence=[f"input: {employer_site[:200]}"], source="Submission", limitation="Provide the full official website URL.",
        ))
    elif parsed_site:
        employer_domain = parsed_site.host
        findings.append(Finding(
            check="employer_website", title="Employer website", status="verified", severity="none",
            summary=f"Employer website parsed: {parsed_site.canonical} (registrable domain {parsed_site.registrable_domain}).",
            evidence=[f"canonical: {parsed_site.canonical}"], source="Submission + URL parser",
            limitation="Parsing only confirms the URL's structure; nothing was fetched or validated as belonging to the employer.",
        ))
        findings.append(domain_lookalike_check(employer_domain, official_domains))
        findings.extend(check_spf_and_dmarc(employer_domain))
    elif employer:
        findings.append(Finding(
            check="employer_website", title="Employer website", status="inconclusive", severity="low",
            summary=f"No official website was provided for '{employer}'.",
            evidence=["employer_website is empty"], source="Submission",
            limitation="Not providing a website is not evidence of fraud - verify the employer independently.",
        ))
    if employer and brand_names:
        best, best_score = None, 0.0
        for b in brand_names:
            score = fuzz.token_set_ratio(employer.lower(), b.lower()) / 100
            if score > best_score:
                best, best_score = b, score
        if best and best_score >= 0.9:
            findings.append(Finding(
                check="employer_identity", title="Employer matches a registered brand", status="verified",
                severity="none",
                summary=f"'{employer}' matches the registered brand '{best}' (similarity {best_score:.2f}).",
                evidence=[f"input: {employer}", f"registered brand: {best}", f"similarity: {best_score:.2f}"],
                source="Workspace brand references",
                limitation="The name matches; this does not verify that THIS offer was made by that brand.",
            ))
        elif best and best_score >= 0.7:
            findings.append(Finding(
                check="employer_identity", title="Employer resembles a registered brand", status="inconclusive",
                severity="medium",
                summary=f"'{employer}' resembles registered brand '{best}' (similarity {best_score:.2f}) but is not identical.",
                evidence=[f"input: {employer}", f"closest brand: {best}", f"similarity: {best_score:.2f}"],
                source="Workspace brand references",
                limitation="Typosquatting and unrelated companies can produce the same similarity.",
            ))

    # ---- 2. Recruiter ----
    if recruiter_email and "@" in recruiter_email:
        rdomain = recruiter_email.rsplit("@", 1)[1]
        if employer_domain and rdomain != employer_domain and registrable_domain(rdomain) != registrable_domain(employer_domain):
            findings.append(Finding(
                check="recruiter_email_domain", title="Recruiter email vs employer domain",
                status="suspicious", severity="medium",
                summary=f"The recruiter emails from {rdomain}, which is not the employer's domain ({employer_domain}).",
                evidence=[f"recruiter email domain: {rdomain}", f"employer domain: {employer_domain}"],
                source="Submission",
                limitation="Recruiters do sometimes use agencies or HR platforms; check the sender's reputation before concluding.",
            ))
        elif rdomain in FREEMAIL_DOMAINS:
            findings.append(Finding(
                check="recruiter_email_domain", title="Recruiter uses a free mailbox",
                status="suspicious" if employer else "inconclusive", severity="medium" if employer else "low",
                summary=(f"The recruiter emails from a free mailbox ({rdomain})"
                         + (f" while representing '{employer}'." if employer else ".")),
                evidence=[f"recruiter email domain: {rdomain}"],
                source="Submission + known freemail list",
                limitation="Freemail is also used by freelancers and small recruiters.",
            ))
        else:
            findings.append(Finding(
                check="recruiter_email_domain", title="Recruiter email domain", status="info", severity="none",
                summary=f"Recruiter email domain {rdomain} is consistent with a corporate sender.",
                evidence=[f"recruiter email domain: {rdomain}"], source="Submission",
                limitation="Header/domain consistency is not identity verification.",
            ))
            if employer_domain and registrable_domain(rdomain) == registrable_domain(employer_domain):
                findings.extend(check_spf_and_dmarc(rdomain))

    if recruiter_name and employer:
        sim, reason = identity_similarity(recruiter_name, employer)
        # recruiter name ~ employer name similarity is informational; the real check is the profile URL below
        if sim >= 0.9:
            findings.append(Finding(
                check="recruiter_identity", title="Recruiter name vs employer name", status="info", severity="none",
                summary=f"The recruiter's name closely matches the employer name ({reason}).",
                evidence=[f"recruiter: {recruiter_name}", f"employer: {employer}"],
                source="String similarity", limitation="Informational only.",
            ))

    if recruiter_profile_url:
        pr = parse_url(recruiter_profile_url)
        if pr is None:
            findings.append(Finding(
                check="recruiter_profile", title="Recruiter profile URL", status="unable_to_verify", severity="unknown",
                summary="The recruiter profile URL is not a valid http(s) URL.",
                evidence=[f"input: {recruiter_profile_url[:200]}"], source="Submission", limitation="Provide the full profile URL.",
            ))
        else:
            platform = next((name for host, name in PLATFORM_HOSTS.items() if pr.host == host or pr.host.endswith("." + host)), None)
            if platform:
                findings.append(Finding(
                    check="recruiter_profile", title="Recruiter profile platform", status="verified", severity="none",
                    summary=f"The recruiter profile is hosted on {platform} ({pr.host}).",
                    evidence=[f"host: {pr.host}"], source="Submission + URL parser",
                    limitation="A profile on a known platform is not itself verified; platform profiles can be faked.",
                ))
            else:
                findings.append(Finding(
                    check="recruiter_profile", title="Recruiter profile platform", status="inconclusive", severity="low",
                    summary=f"The recruiter profile is on an unrecognised site ({pr.host}).",
                    evidence=[f"host: {pr.host}"], source="Submission + URL parser",
                    limitation="Recruiting happens on many platforms; unknown host is a weak signal.",
                ))
            findings.append(url_heuristic_check(recruiter_profile_url, official_domains))

    # ---- 3. Offer content: money, credentials, feasibility ----
    for label, terms, sev in (
        ("fee_or_payment_request", FEE_TERMS + PAYMENT_METHOD_TERMS, "high"),
        ("sensitive_data_request", SENSITIVE_REQUEST_TERMS, "high"),
        ("too_good_to_be_true", TOO_GOOD_TERMS, "medium"),
    ):
        hits = _find_terms(job_text, terms)
        if hits:
            findings.append(Finding(
                check=label, title={
                    "fee_or_payment_request": "Money is requested from the candidate",
                    "sensitive_data_request": "Sensitive data is requested",
                    "too_good_to_be_true": "Over-promising language",
                }[label],
                status="suspicious", severity=sev,
                summary=f"{len(hits)} matching phrase(s) in the job/offer text.",
                evidence=[f"“{q}”" for _, q in hits[:6]], source="Text analysis (keyword lexicon)",
                limitation="Keywords are heuristics; read each excerpt in full context.",
            ))
    if not job_text.strip():
        findings.append(Finding(
            check="offer_text", title="Offer text", status="inconclusive", severity="low",
            summary="No job description or offer text was submitted.",
            evidence=["job_description and offer_text are empty"], source="Submission",
            limitation="Without the offer text, language-based checks cannot run.",
        ))

    # ---- 4. Application link ----
    if application_url:
        ar = parse_url(application_url)
        findings.append(url_heuristic_check(application_url, official_domains))
        if ar and employer_domain and registrable_domain(ar.host) != registrable_domain(employer_domain):
            findings.append(Finding(
                check="application_link_domain", title="Application link domain vs employer",
                status="inconclusive", severity="medium",
                summary=f"The application link ({ar.host}) is on a different domain than the employer's website ({employer_domain}).",
                evidence=[f"application host: {ar.host}", f"employer domain: {employer_domain}"],
                source="Submission + URL parser",
                limitation="Applications often live on job boards or HR platforms (Workday, Greenhouse, Lever...).",
            ))
    else:
        findings.append(Finding(
            check="application_link", title="Application link", status="inconclusive", severity="low",
            summary="No application URL was provided.",
            evidence=["application_url is empty"], source="Submission",
            limitation="Applications may legitimately arrive as email attachments.",
        ))

    subject_label = (employer or "Job offer")[:80]
    return subject_label, findings
