"""Signal B - impersonation and copied text: names, handles, publisher identities and bios vs official references.

Also reports credential / payment solicitation language found in the same text (the report's
"asking people to share passwords or send money" reason) as its own metadata flag, explanation
line and a small bounded score bonus - a reason for review, not a verdict.
"""
from __future__ import annotations

import re

from app.models.enums import ReferenceKind, SignalStatus, SignalType
from app.services.detection.base import DetectionContext, SignalResult
from app.services.detection.common import attrs, entity_bio, entity_name_fields
from app.utils.text import identity_similarity, normalize_text, squash_identity, text_overlap

OFFICIAL_CLAIM_WORDS = ("official", "verified", "support", "customer care", "helpdesk", "help desk", "authentic", "original")


def solicitation_matches(text: str, phrases: list[str]) -> list[str]:
    """Configured phrases that appear in `text` (normalised input, word-bounded so 'otp' misses 'hotpot')."""
    if not text:
        return []
    return sorted(p for p in phrases if re.search(rf"\b{re.escape(p.lower())}\b", text))


def _scale(sim: float, floor: float) -> float:
    """Map similarity in [floor,1] to [0,1]; below the floor it is treated as no resemblance."""
    return 0.0 if sim < floor else round((sim - floor) / (1 - floor), 4)


class ImpersonationDetector:
    signal_type = SignalType.IMPERSONATION

    def run(self, ctx: DetectionContext) -> SignalResult:
        s, e = ctx.settings, ctx.entity
        a = attrs(e)
        refs = ctx.references
        name_refs = [(r, r.value) for r in refs if r.kind in (ReferenceKind.NAME, ReferenceKind.HANDLE)]
        name_refs.append((None, ctx.brand.name))  # the brand's own name is always an official identity
        pub_refs = [(r, r.value) for r in refs if r.kind == ReferenceKind.PUBLISHER] + name_refs
        bio_refs = [(r, r.value) for r in refs if r.kind == ReferenceKind.BIO]
        if ctx.brand.description:
            bio_refs.append((None, ctx.brand.description))
        pkg_refs = [(r, r.value) for r in refs if r.kind == ReferenceKind.APP_PACKAGE]

        fields = entity_name_fields(e)
        publisher = a.get("publisher_name")
        bio = entity_bio(e)
        package_id = a.get("package_id")
        if not fields and not publisher and not bio:
            return SignalResult.unavailable(self.signal_type, "entity has no name, handle, publisher or bio text to compare")

        matches: list[dict] = []
        best_name = (0.0, None)
        for fname, fval in fields:
            for r, ov in name_refs:
                sim, why = identity_similarity(fval, ov)
                if sim > best_name[0]:
                    best_name = (sim, {"field": fname, "value": fval, "official": ov, "reference_id": str(r.id) if r else None, "similarity": round(sim, 3), "reason": why})
        if package_id:
            for r, ov in pkg_refs:
                sim, why = identity_similarity(package_id, ov)
                if sim > best_name[0]:
                    best_name = (sim, {"field": "package_id", "value": package_id, "official": ov, "reference_id": str(r.id), "similarity": round(sim, 3), "reason": why})
        name_eff = _scale(best_name[0], s.impersonation_min_similarity)
        if best_name[1] and best_name[0] >= s.impersonation_min_similarity:
            matches.append({"kind": "name", **best_name[1]})

        pub_eff, best_pub = 0.0, None
        if publisher:
            for r, ov in pub_refs:
                sim, why = identity_similarity(publisher, ov)
                if sim >= s.impersonation_min_similarity and (best_pub is None or sim > best_pub["similarity"]):
                    best_pub = {"kind": "publisher", "field": "publisher_name", "value": publisher, "official": ov, "reference_id": str(r.id) if r else None, "similarity": round(sim, 3), "reason": why}
            if best_pub:
                pub_eff = _scale(best_pub["similarity"], s.impersonation_min_similarity)
                matches.append(best_pub)

        bio_eff, best_bio = 0.0, None
        if bio:
            for r, ov in bio_refs:
                ov_ratio = text_overlap(bio, ov)
                if ov_ratio >= 0.6 and (best_bio is None or ov_ratio > best_bio["similarity"]):
                    # both sides stored verbatim so the analyst can read the comparison side by side
                    best_bio = {"kind": "bio", "field": "bio/description", "value": bio, "official": ov, "reference_id": str(r.id) if r else None, "similarity": round(ov_ratio, 3), "reason": "word-set overlap with official text"}
            if best_bio:
                bio_eff = _scale(best_bio["similarity"], 0.6)
                matches.append(best_bio)

        components = {"name": name_eff, "publisher": round(pub_eff * 0.9, 4), "bio": round(bio_eff * 0.85, 4)}
        base = max(components.values())
        independent = sum(1 for v in components.values() if v >= 0.3)
        score = min(1.0, base + (0.10 if independent >= 2 else 0.0))
        text_all = normalize_text(" ".join(v for _, v in fields) + " " + (publisher or ""))
        claims_official = any(w in text_all for w in OFFICIAL_CLAIM_WORDS)
        if claims_official and name_eff >= 0.3:
            score = min(1.0, score + 0.05)
        # credential / payment solicitation in the asset's own text (bounded bonus, like claims_official)
        solicited = solicitation_matches(
            normalize_text(" ".join(v for _, v in fields) + " " + (publisher or "") + " " + (bio or "")),
            s.solicitation_phrases,
        )
        if solicited:
            score = min(1.0, score + 0.05)
        score = round(score, 4)

        # explanation
        parts = []
        if best_name[1] and name_eff > 0:
            m = best_name[1]
            parts.append(f"{m['field']} '{m['value']}' resembles official '{m['official']}' (similarity {m['similarity']:.2f}: {m['reason']})")
        if best_pub:
            parts.append(f"publisher '{best_pub['value']}' resembles official '{best_pub['official']}' (similarity {best_pub['similarity']:.2f})")
        if best_bio:
            parts.append(f"bio/description overlaps official text ({best_bio['similarity']:.0%} word overlap) - likely copied")
        if claims_official and name_eff >= 0.3:
            parts.append("name claims official/support status")
        if solicited:
            parts.append("text asks for credentials or money (matched: " + ", ".join(solicited[:3]) + ")")
        if independent >= 2:
            parts.append("multiple independent identity fields agree")
        expl = ("Impersonation indicators: " + "; ".join(parts) + ".") if parts else "No meaningful resemblance to official names, handles, publisher or bio text."
        ev_refs = [{"type": "brand_reference", "id": m["reference_id"]} for m in matches if m.get("reference_id")]
        return SignalResult(
            self.signal_type, SignalStatus.OK, score, expl, ev_refs,
            {"components": components, "matches": matches, "claims_official": claims_official,
             "solicits_sensitive_action": bool(solicited), "solicitation_phrases_matched": solicited,
             "compared_fields": [f for f, _ in fields] + (["publisher_name"] if publisher else []) + (["bio"] if bio else [])},
        )
