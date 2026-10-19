"""Risk graph built with NetworkX from persisted PostgreSQL relationships.

The graph is stateless: every request rebuilds it from the database (so "rebuild" == "load"). Connected components
of size >= 2 are *candidate* clusters; a cluster is only PROPOSED for investigation when evidence-based thresholds
pass (see `summarize_cluster`). A connected component is never treated as malicious by itself.
"""
from __future__ import annotations

import hashlib
import math
import uuid
from collections import Counter

import networkx as nx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import ConflictError, NotFoundError, ValidationFailure
from app.models import CaseEntity, DigitalEntity, EntityRelationship, EvidenceRecord, InvestigationCase, User
from app.models.enums import CaseStatus, EntityType, RelationshipType, Severity
from app.repositories.access import brand_scope, get_brand_for_user, get_entity_for_user
from app.schemas.graph import (
    ClusterSummary, GraphEdge, GraphNode, GraphResponse, RelatedEntity, RelationshipCreate,
)
from app.services import audit
from app.services.detection.common import official_domains, pair_indicators

_SEV_ORDER = [Severity.UNKNOWN, Severity.LOW, Severity.MEDIUM, Severity.HIGH, Severity.CRITICAL]
MAX_DISCOVERY_ENTITIES = 200


def cluster_id_for(entity_ids) -> str:
    return hashlib.sha1(",".join(sorted(str(i) for i in entity_ids)).encode()).hexdigest()[:16]


def build_graph(db: Session, actor: User, *, brand_id: uuid.UUID | None = None, entity_types: list[EntityType] | None = None,
                min_risk: float | None = None, severities: list[Severity] | None = None, min_confidence: float | None = None) -> nx.MultiGraph:
    s = get_settings()
    stmt = select(DigitalEntity).where(brand_scope(actor, DigitalEntity.brand_id))
    if brand_id:
        get_brand_for_user(db, actor, brand_id)
        stmt = stmt.where(DigitalEntity.brand_id == brand_id)
    if entity_types:
        stmt = stmt.where(DigitalEntity.entity_type.in_(entity_types))
    if min_risk is not None:
        stmt = stmt.where(DigitalEntity.current_risk_score >= min_risk)  # unassessed entities (NULL) are excluded
    if severities:
        stmt = stmt.where(DigitalEntity.current_severity.in_(severities))
    entities = db.scalars(stmt).all()
    g = nx.MultiGraph()  # one edge per persisted relationship (a pair can be linked in several ways)
    for e in entities:
        g.add_node(str(e.id), entity_type=e.entity_type, label=e.display_name, brand_id=str(e.brand_id), risk_score=e.current_risk_score,
                   confidence=e.current_confidence, severity=e.current_severity, provenance=e.provenance.value)
    if not entities:
        return g
    ids = [e.id for e in entities]
    thr = max(s.graph_min_edge_confidence, min_confidence or 0.0)
    rels = db.scalars(select(EntityRelationship).where(
        EntityRelationship.source_entity_id.in_(ids), EntityRelationship.target_entity_id.in_(ids), EntityRelationship.confidence >= thr)).all()
    for r in rels:
        g.add_edge(str(r.source_entity_id), str(r.target_entity_id), key=str(r.id), id=str(r.id), relationship_type=r.relationship_type,
                   confidence=r.confidence, evidence_id=str(r.evidence_id) if r.evidence_id else None, evidence_note=r.evidence_note,
                   created_at=r.created_at, auto_generated=r.auto_generated)
    return g


def clusters_of(g: nx.MultiGraph) -> list[set[str]]:
    return [c for c in nx.connected_components(g) if len(c) >= 2]


def to_response(g: nx.MultiGraph) -> GraphResponse:
    cl = clusters_of(g)
    cmap = {n: cluster_id_for(c) for c in cl for n in c}
    nodes = [GraphNode(id=n, cluster_id=cmap.get(n), **{k: d[k] for k in ("entity_type", "label", "brand_id", "risk_score", "confidence", "severity", "provenance")}) for n, d in g.nodes(data=True)]
    edges = [GraphEdge(source=a, target=b, **{k: d[k] for k in ("id", "relationship_type", "confidence", "evidence_id", "evidence_note", "created_at", "auto_generated")}) for a, b, d in g.edges(data=True)]
    return GraphResponse(nodes=nodes, edges=edges, node_count=len(nodes), edge_count=len(edges), cluster_count=len(cl))


def summarize_cluster(db: Session, g: nx.MultiGraph, members: set[str]) -> ClusterSummary:
    s = get_settings()
    sub = g.subgraph(members)
    risks = [d["risk_score"] for _, d in sub.nodes(data=True) if d["risk_score"] is not None]
    edge_conf = [d["confidence"] for _, _, d in sub.edges(data=True)]
    mean_conf = sum(edge_conf) / len(edge_conf) if edge_conf else 0.0
    types = Counter(d["entity_type"].value for _, d in sub.nodes(data=True))
    rel_types = Counter(d["relationship_type"].value for _, _, d in sub.edges(data=True))
    max_sev = max((d["severity"] for _, d in sub.nodes(data=True)), key=_SEV_ORDER.index, default=Severity.UNKNOWN)
    member_uuids = [uuid.UUID(m) for m in members]
    case_rows = db.execute(
        select(InvestigationCase.id, InvestigationCase.status).join(CaseEntity, CaseEntity.case_id == InvestigationCase.id)
        .where(CaseEntity.entity_id.in_(member_uuids)).distinct()).all()
    existing = [str(r.id) for r in case_rows]
    open_cases = [str(r.id) for r in case_rows if r.status != CaseStatus.RESOLVED]
    reasons, ok = [], True
    if len(members) < s.cluster_min_size:
        ok = False
        reasons.append(f"cluster has {len(members)} entities (< {s.cluster_min_size})")
    if mean_conf < s.cluster_min_mean_edge_confidence:
        ok = False
        reasons.append(f"mean link confidence {mean_conf:.2f} below {s.cluster_min_mean_edge_confidence}")
    if not risks:
        ok = False
        reasons.append("no member has been risk-assessed yet - analyze the entities first")
    elif max(risks) < s.cluster_min_max_risk:
        ok = False
        reasons.append(f"highest member risk {max(risks):.2f} below {s.cluster_min_max_risk}")
    if open_cases:
        ok = False
        reasons.append("already covered by open case(s): " + ", ".join(open_cases))
    if ok:
        reasons.append(f"{len(members)} linked entities, mean link confidence {mean_conf:.2f}, highest risk {max(risks):.2f}")
    return ClusterSummary(
        cluster_id=cluster_id_for(members), size=len(members), entity_ids=sorted(members), entity_type_counts=dict(types),
        relationship_type_counts=dict(rel_types), brand_ids=sorted({d["brand_id"] for _, d in sub.nodes(data=True)}),
        max_risk_score=max(risks) if risks else None, mean_risk_score=round(sum(risks) / len(risks), 4) if risks else None,
        mean_edge_confidence=round(mean_conf, 4), max_severity=max_sev, propose_for_investigation=ok, proposal_reasons=reasons,
        existing_case_ids=existing,
        headline=f"{len(members)} linked entities ({', '.join(f'{v} {k}' for k, v in types.items())}) joined by {', '.join(rel_types) or 'no relationships'}",
    )


def list_clusters(db: Session, actor: User, **filters) -> list[ClusterSummary]:
    g = build_graph(db, actor, **filters)
    out = [summarize_cluster(db, g, c) for c in clusters_of(g)]
    out.sort(key=lambda c: (c.propose_for_investigation, c.max_risk_score or 0, c.size), reverse=True)
    return out


def neighbors(db: Session, actor: User, entity_id: uuid.UUID, depth: int = 1) -> GraphResponse:
    entity = get_entity_for_user(db, actor, entity_id)
    g = build_graph(db, actor)
    if str(entity.id) not in g:
        return GraphResponse(nodes=[], edges=[], node_count=0, edge_count=0, cluster_count=0)
    return to_response(nx.ego_graph(g, str(entity.id), radius=depth))


def case_graph(db: Session, actor: User, case) -> GraphResponse:
    """Server-composed sub-graph of a case: its linked entities plus the relationships among them.

    Composed on the backend (not client-side aggregation) so the response honours the same
    brand-scope and edge-confidence rules as the full graph. Entities the caller can no longer
    see are omitted rather than leaked.
    """
    g = build_graph(db, actor)
    members = {str(ce.entity_id) for ce in case.entities} & set(g.nodes)
    return to_response(g.subgraph(members))


def related_entities(db: Session, actor: User, entity_id: uuid.UUID, max_depth: int = 3, min_path_confidence: float | None = None) -> list[RelatedEntity]:
    entity = get_entity_for_user(db, actor, entity_id)
    s = get_settings()
    g = build_graph(db, actor)
    root = str(entity.id)
    if root not in g:
        return []
    # strongest path = maximise product of edge confidences = minimise sum of -log(conf)
    H = nx.Graph()
    for a, b, d in g.edges(data=True):
        w = -math.log(max(d["confidence"], 1e-6))
        if not H.has_edge(a, b) or w < H[a][b]["w"]:
            H.add_edge(a, b, w=w)
    if root not in H:
        return []
    dist, paths = nx.single_source_dijkstra(H, root, weight="w")
    out = []
    for n, w in dist.items():
        if n == root or len(paths[n]) - 1 > max_depth:
            continue
        pc = math.exp(-w)
        if pc < (min_path_confidence if min_path_confidence is not None else s.graph_min_edge_confidence):
            continue
        p = paths[n]
        via = [max(g[p[i]][p[i + 1]].values(), key=lambda e: e["confidence"])["relationship_type"].value for i in range(len(p) - 1)]
        d = g.nodes[n]
        out.append(RelatedEntity(entity=GraphNode(id=n, **{k: d[k] for k in ("entity_type", "label", "brand_id", "risk_score", "confidence", "severity", "provenance")}),
                                 distance=len(p) - 1, path_confidence=round(pc, 4), via=via))
    out.sort(key=lambda r: (-r.path_confidence, r.distance))
    return out


def create_relationship(db: Session, actor: User, data: RelationshipCreate):
    if data.source_entity_id == data.target_entity_id:
        raise ValidationFailure("An entity cannot be related to itself")
    a = get_entity_for_user(db, actor, data.source_entity_id)
    b = get_entity_for_user(db, actor, data.target_entity_id)
    if data.evidence_id:
        ev = db.get(EvidenceRecord, data.evidence_id)
        if ev is None or ev.entity_id not in (a.id, b.id):
            raise ValidationFailure("evidence_id must reference evidence attached to one of the two entities")
    rel, created = upsert_relationship(db, a.id, b.id, data.relationship_type, data.confidence, data.evidence_note, data.evidence_id, auto=False, actor=actor, meta={})
    audit.record(db, actor, "relationship.create" if created else "relationship.update", "relationship", rel.id,
                 details={"type": data.relationship_type.value, "confidence": rel.confidence}, organization_id=a.brand.organization_id)
    db.commit()
    return rel, created


def upsert_relationship(db: Session, a_id: uuid.UUID, b_id: uuid.UUID, rtype: RelationshipType, confidence: float, note: str,
                        evidence_id: uuid.UUID | None, *, auto: bool, actor: User | None, meta: dict):
    src, tgt = (a_id, b_id) if a_id < b_id else (b_id, a_id)  # canonical order (undirected edge)
    rel = db.scalar(select(EntityRelationship).where(EntityRelationship.source_entity_id == src, EntityRelationship.target_entity_id == tgt,
                                                    EntityRelationship.relationship_type == rtype))
    if rel:
        if confidence > rel.confidence:
            rel.confidence, rel.evidence_note, rel.meta = confidence, note, meta
            if evidence_id:
                rel.evidence_id = evidence_id
        return rel, False
    rel = EntityRelationship(source_entity_id=src, target_entity_id=tgt, relationship_type=rtype, confidence=confidence, evidence_id=evidence_id,
                             evidence_note=note, meta=meta, auto_generated=auto, created_by_id=actor.id if actor else None)
    db.add(rel)
    db.flush()
    return rel, True


def discover_relationships(db: Session, actor: User, brand_id: uuid.UUID) -> dict:
    """Derive relationships from observable data (shared images/domains/identity/infrastructure/synchronised posts)."""
    brand = get_brand_for_user(db, actor, brand_id)
    s = get_settings()
    entities = db.scalars(select(DigitalEntity).where(DigitalEntity.brand_id == brand.id).order_by(DigitalEntity.last_seen_at.desc()).limit(MAX_DISCOVERY_ENTITIES)).all()
    ev_by_entity: dict[uuid.UUID, list] = {}
    if entities:
        for ev in db.scalars(select(EvidenceRecord).where(EvidenceRecord.entity_id.in_([e.id for e in entities]))):
            ev_by_entity.setdefault(ev.entity_id, []).append(ev)
    official = official_domains(brand.references)
    compared = created = existing = 0
    for i, a in enumerate(entities):
        for b in entities[i + 1:]:
            compared += 1
            for ind in pair_indicators(a, b, s, official=official, a_ev=ev_by_entity.get(a.id, []), b_ev=ev_by_entity.get(b.id, [])):
                ev_id = uuid.UUID(ind.evidence_id) if ind.evidence_id else None
                _, was_new = upsert_relationship(db, a.id, b.id, ind.kind, ind.confidence, ind.note, ev_id, auto=True, actor=actor, meta=ind.meta or {})
                created += was_new
                existing += not was_new
    audit.record(db, actor, "graph.discover", "brand", brand.id, details={"compared": compared, "created": created}, organization_id=brand.organization_id)
    db.commit()
    return {"pairs_compared": compared, "relationships_created": created, "relationships_existing": existing}
