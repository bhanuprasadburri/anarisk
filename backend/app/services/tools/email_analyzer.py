"""Email / phishing analyzer.

Parses pasted email content or a safely parsed ``.eml`` upload using Python's standard
``email`` parser (no attachment is executed, decoded beyond headers, or fetched). Every
check maps to a :class:`Finding` with evidence, source and limitations.
"""
from __future__ import annotations

import re
from email import policy
from email.message import EmailMessage
from email.utils import parseaddr, parsedate_to_datetime
from typing import Any

from app.services.tools.common import (
    Finding, check_spf_and_dmarc, domain_lookalike_check, url_heuristic_check,
)
from app.utils.urls import extract_urls, parse_url, registrable_domain

FREEMAIL_DOMAINS = {
    "gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.uk", "hotmail.com", "outlook.com", "live.com",
    "msn.com", "icloud.com", "me.com", "aol.com", "protonmail.com", "proton.me", "zoho.com", "zohomail.com",
    "gmx.com", "gmx.net", "mail.com", "yandex.com", "mail.ru", "inbox.com", "hushmail.com", "tutanota.com",
    "cock.li", "guerrillamail.com", "tempmail.com", "10minutemail.com",
}

URGENCY_TERMS = [
    "immediately", "urgent", "within 24 hours", "within 48 hours", "suspend", "suspension", "terminated",
    "final notice", "last warning", "act now", "expires today", "unauthorized activity", "locked",
]
CREDENTIAL_TERMS = ["password", "otp", "one-time password", "verification code", "pin", "sign in to verify", "confirm your account"]
PAYMENT_TERMS = ["gift card", "wire transfer", "bitcoin", "crypto", "usdt", "western union", "moneygram", "pay to", "payment required"]
SENSITIVE_TERMS = ["social security", "ssn", "passport", "bank account number", "credit card", "cvv"]

DANGEROUS_EXTENSIONS = (".exe", ".scr", ".js", ".vbs", ".wsf", ".bat", ".cmd", ".ps1", ".lnk", ".iso", ".img", ".jar", ".msi")
MACRO_EXTENSIONS = (".docm", ".xlsm", ".pptm", ".dotm")
SUSPICIOUS_ATTACHMENT_NAMES = re.compile(r"(?i)(invoice|payment|receipt|refund|shipping|order|document|scan|copy|scan_[0-9])")


def _quoted(haystack: str, term: str, limit: int = 80) -> str | None:
    m = re.search(re.escape(term), haystack, re.IGNORECASE)
    if not m:
        return None
    start = max(0, m.start() - limit // 2)
    return "…" + haystack[start: m.end() + limit // 2].replace("\n", " ").strip() + "…"


def parse_eml(raw: bytes) -> dict[str, Any]:
    """Safely parse an uploaded .eml. Only headers, text bodies and attachment *metadata*."""
    if len(raw) > 2 * 1024 * 1024:
        raise ValueError("The uploaded email exceeds the 2 MB parsing limit.")
    from email.parser import BytesParser

    msg: EmailMessage = BytesParser(policy=policy.default).parsebytes(raw)
    from_name, from_addr = parseaddr(str(msg.get("From", "")))
    reply_to = str(msg.get("Reply-To", "")) or None
    return_path = str(msg.get("Return-Path", "")) or None
    body_parts: list[str] = []
    attachments: list[dict[str, Any]] = []
    for part in msg.walk():
        ctype = part.get_content_type()
        disposition = (part.get_content_disposition() or "").lower()
        if disposition == "attachment" or (part.get_filename() and disposition != "inline"):
            payload = part.get_payload(decode=True) or b""
            attachments.append({
                "filename": part.get_filename() or "(unnamed)",
                "content_type": ctype,
                "size_bytes": len(payload),
            })
        elif ctype in ("text/plain", "text/html") and disposition != "attachment":
            try:
                body_parts.append(part.get_content())
            except Exception:
                payload = part.get_payload(decode=True) or b""
                body_parts.append(payload.decode("utf-8", "replace"))
    body = "\n".join(p for p in body_parts if isinstance(p, str))
    date_hdr = str(msg.get("Date", "")) or None
    sent_at = None
    if date_hdr:
        try:
            sent_at = parsedate_to_datetime(date_hdr).isoformat()
        except (TypeError, ValueError):
            sent_at = None
    return {
        "from_name": from_name or None,
        "from_address": from_addr,
        "reply_to": reply_to,
        "return_path": return_path,
        "subject": str(msg.get("Subject", "")) or None,
        "date_header": sent_at,
        "body": body,
        "attachments": attachments,
    }


def analyze_email(
    payload: dict[str, Any],
    official_domains: list[str],
    official_handles: list[str],
    brand_names: list[str],
) -> tuple[str, list[Finding]]:
    """Run all email checks. `payload` is the already-parsed or manually supplied email data."""
    findings: list[Finding] = []
    claimed_brand = (payload.get("claimed_brand") or "").strip()
    claimed_domain = (payload.get("claimed_domain") or "").strip().lower() or None
    from_addr = (payload.get("from_address") or "").strip().lower()
    reply_to = (payload.get("reply_to") or "").strip().lower() or None
    subject = payload.get("subject") or ""
    body = payload.get("body") or ""
    text = f"{subject}\n{body}"

    from_name, from_domain = parseaddr(from_addr)[1], None
    if from_addr and "@" in from_addr:
        from_domain = from_addr.rsplit("@", 1)[1]
    if not from_addr or from_domain is None:
        findings.append(Finding(
            check="sender_address", title="Sender address", status="unable_to_verify", severity="unknown",
            summary="No valid sender address was provided.",
            evidence=[f"from_address: {from_addr or '(empty)'}"], source="Submission",
            limitation="Without a sender address most email checks cannot run.",
        ))
        subject_label = subject[:80] or "Email analysis"
        return subject_label, findings

    # 1. Sender address characteristics
    evidence = [f"From: {from_name or '?'} <{from_addr}>"]
    if reply_to:
        evidence.append(f"Reply-To: {reply_to}")
    if payload.get("return_path"):
        evidence.append(f"Return-Path: {payload['return_path']}")
    is_freemail = from_domain in FREEMAIL_DOMAINS
    if is_freemail and claimed_brand:
        findings.append(Finding(
            check="sender_address", title="Sender uses a free mailbox", status="suspicious", severity="medium",
            summary=f"The email claims to represent '{claimed_brand}' but is sent from a free mailbox ({from_domain}).",
            evidence=evidence + [f"{from_domain} is a consumer mail provider"],
            source="Submission + known freemail list",
            limitation="Freemail is also used by legitimate small businesses; weigh with other evidence.",
        ))
    else:
        findings.append(Finding(
            check="sender_address", title="Sender address", status="info", severity="none",
            summary=(f"Sender domain {from_domain} is a known free mailbox provider." if is_freemail
                     else f"Sender domain {from_domain} is a custom domain."),
            evidence=evidence, source="Submission + known freemail list",
            limitation="Address headers are forgeable; this describes what was submitted, not verified sender identity.",
        ))

    # 2. Reply-To mismatch
    if reply_to and "@" in reply_to:
        rt_domain = reply_to.rsplit("@", 1)[1]
        if rt_domain != from_domain:
            same_reg = registrable_domain(rt_domain) == registrable_domain(from_domain)
            findings.append(Finding(
                check="reply_to_mismatch", title="Reply-To differs from sender",
                status="inconclusive" if same_reg else "suspicious",
                severity="low" if same_reg else "high",
                summary=(f"Replies go to {rt_domain} while the email appears to come from {from_domain}"
                         + (" (same organisation domain)." if same_reg else ".")),
                evidence=[f"From domain: {from_domain}", f"Reply-To domain: {rt_domain}"],
                source="Submission headers",
                limitation="Reply-To is attacker-controlled; a mismatch is a strong deception pattern but not proof.",
            ))

    # 3. DNS: SPF / DMARC / MX for the sender domain
    findings.extend(check_spf_and_dmarc(from_domain))
    mx, mx_err = _query_mx(from_domain)
    if mx_err:
        findings.append(Finding(
            check="sender_mx", title="Mail exchanger (MX)", status="unable_to_verify", severity="unknown",
            summary=f"Could not query MX records for {from_domain}.", evidence=[f"MX lookup failed: {mx_err}"],
            source="DNS (system resolver)", limitation="DNS was unavailable; no conclusion can be drawn.",
        ))
    else:
        findings.append(Finding(
            check="sender_mx", title="Mail exchanger (MX)", status="verified" if mx else "inconclusive",
            severity="none" if mx else "low",
            summary=(f"{from_domain} publishes MX records ({mx[0]})." if mx
                     else f"{from_domain} publishes no MX records - it cannot receive email."),
            evidence=[f"MX: {', '.join(mx) if mx else '(none)'}"],
            source="DNS (system resolver)",
            limitation="MX presence is a weak infrastructure signal only.",
        ))

    # 4. Lookalike sender domain
    compare = [d for d in official_domains if d]
    if claimed_domain and claimed_domain not in compare:
        compare.append(claimed_domain)
    findings.append(domain_lookalike_check(from_domain, compare))

    # 5. Brand impersonation language
    mentioned = [b for b in brand_names + ([claimed_brand] if claimed_brand else []) if b and re.search(rf"\b{re.escape(b)}\b", text, re.IGNORECASE)]
    if mentioned:
        official_hit = any(
            from_domain == registrable_domain(d) or registrable_domain(from_domain) == registrable_domain(d)
            for d in official_domains
        )
        if official_hit:
            findings.append(Finding(
                check="brand_impersonation", title="Brand mention vs sender", status="verified", severity="none",
                summary=f"The email mentions {', '.join(sorted(set(mentioned)))} and comes from a registered official domain.",
                evidence=[f"mentioned: {m}" for m in sorted(set(mentioned))] + [f"sender domain matches official: {from_domain}"],
                source="Workspace brand references", limitation="A matching domain does not prove this specific sender is authorised.",
            ))
        else:
            findings.append(Finding(
                check="brand_impersonation", title="Brand mention vs sender", status="suspicious", severity="high",
                summary=(f"The email mentions {', '.join(sorted(set(mentioned)))} but the sender domain {from_domain} "
                         "is not a registered official domain for that brand."),
                evidence=[f"mentioned: {m}" for m in sorted(set(mentioned))] + [f"sender domain: {from_domain}"],
                source="Workspace brand references",
                limitation="Only brands registered in this workspace can be compared.",
            ))

    # 6. URLs in the body
    urls = extract_urls(body, limit=10)
    for u in urls[:5]:
        findings.append(url_heuristic_check(u, official_domains))
    if not urls:
        findings.append(Finding(
            check="urls", title="Links in the email", status="info", severity="none",
            summary="No http(s) links were found in the email body.",
            evidence=["0 URLs extracted"], source="Body scan",
            limitation="Link-free phishing (pure text requests) still exists.",
        ))

    # 7. Social-engineering language
    for group, terms, label in (
        (URGENCY_TERMS, URGENCY_TERMS, "urgency / threat language"),
        (CREDENTIAL_TERMS, CREDENTIAL_TERMS, "credential or OTP request"),
        (PAYMENT_TERMS, PAYMENT_TERMS, "payment demand"),
        (SENSITIVE_TERMS, SENSITIVE_TERMS, "sensitive-data request"),
    ):
        hits = [(t, _quoted(text, t)) for t in group if _quoted(text, t)]
        if hits:
            sev = {"urgency / threat language": "medium", "credential or OTP request": "high",
                   "payment demand": "high", "sensitive-data request": "high"}[label]
            findings.append(Finding(
                check=f"language_{label.split()[0]}", title=f"{label.capitalize()} detected",
                status="suspicious", severity=sev,
                summary=f"{len(hits)} {label} phrase(s) found in the email text.",
                evidence=[f"“{q}”" for _, q in hits[:6]], source="Text analysis (keyword lexicon)",
                limitation="Legitimate emails (bank alerts, IT helpdesks) can use the same words; context matters.",
            ))

    # 8. Attachments (metadata only)
    attachments = payload.get("attachments") or []
    if attachments:
        risky = []
        for a in attachments:
            name = (a.get("filename") or "").lower()
            if name.endswith(DANGEROUS_EXTENSIONS):
                risky.append(f"{a['filename']} ({a.get('content_type', '?')}) - executable script/binary type")
            elif name.endswith(MACRO_EXTENSIONS):
                risky.append(f"{a['filename']} - macro-enabled document")
            elif name.endswith(".zip") and SUSPICIOUS_ATTACHMENT_NAMES.search(name):
                risky.append(f"{a['filename']} - password-style invoice/payment archive is a common malware carrier")
        findings.append(Finding(
            check="attachments", title="Attachments", status="suspicious" if risky else "inconclusive",
            severity="high" if risky else "low",
            summary=(f"{len(risky)} risky attachment name(s) of {len(attachments)} total." if risky
                     else f"{len(attachments)} attachment(s); names alone look unremarkable."),
            evidence=risky or [f"{a.get('filename')} ({a.get('content_type')}, {a.get('size_bytes')} B)" for a in attachments[:8]],
            source="Parsed .eml metadata",
            limitation="Attachments are NOT executed, opened or malware-scanned; this is filename/type analysis only.",
        ))

    subject_label = (subject or from_addr)[:80]
    return subject_label, findings


def _query_mx(domain: str) -> tuple[list[str] | None, str | None]:
    from app.services.tools.common import dns_query

    recs, err = dns_query(domain, "MX")
    if err:
        return None, err
    out = []
    for r in recs or []:
        parts = r.split()
        out.append(parts[-1].rstrip(".") if parts else r)
    return out, None
