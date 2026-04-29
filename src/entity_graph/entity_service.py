"""
Entity graph query service.

Public API used by:
- /api/entities/* HTTP routes (UI)
- AgenticRAGService for entity-bound retrieval
- ask_comparative() to narrow report selection
"""

import json
import logging
from typing import List, Dict, Optional, Any

from sqlalchemy import func, or_, distinct

from .db import session_scope
from .models import Entity, EntityMention, EntityRelation

logger = logging.getLogger(__name__)


class EntityService:
    """Read-only entity graph queries."""

    # -------------------------------------------------------------------------
    # Search & lookup
    # -------------------------------------------------------------------------

    def search_entities(
        self,
        query: str,
        entity_type: Optional[str] = None,
        primary_tier: Optional[str] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Search by canonical_name or alias substring (case-insensitive)."""
        q_lower = f"%{query.lower().strip()}%"
        with session_scope() as session:
            stmt = session.query(Entity).filter(
                or_(
                    func.lower(Entity.canonical_name).like(q_lower),
                    func.lower(Entity.aliases).like(q_lower),
                )
            )
            if entity_type:
                stmt = stmt.filter(Entity.entity_type == entity_type)
            if primary_tier:
                stmt = stmt.filter(Entity.primary_tier == primary_tier)
            stmt = stmt.order_by(Entity.mention_count.desc()).limit(limit)
            return [self._entity_to_dict(e) for e in stmt.all()]

    def get_entity(self, entity_id: int) -> Optional[Dict[str, Any]]:
        with session_scope() as session:
            ent = session.get(Entity, entity_id)
            return self._entity_to_dict(ent) if ent else None

    def resolve_alias(self, raw: str) -> Optional[Dict[str, Any]]:
        """Best-effort alias resolution. Returns canonical entity dict or None."""
        q_lower = raw.lower().strip()
        with session_scope() as session:
            ent = (
                session.query(Entity)
                .filter(
                    or_(
                        func.lower(Entity.canonical_name) == q_lower,
                        func.lower(Entity.aliases).like(f"%{q_lower}%"),
                    )
                )
                .order_by(Entity.mention_count.desc())
                .first()
            )
            return self._entity_to_dict(ent) if ent else None

    # -------------------------------------------------------------------------
    # Mentions, reports, related
    # -------------------------------------------------------------------------

    def get_mentions(
        self,
        entity_id: int,
        finding_type: Optional[str] = None,
        audit_year: Optional[str] = None,
        government_body_type: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        with session_scope() as session:
            q = session.query(EntityMention).filter_by(entity_id=entity_id)
            if finding_type:
                q = q.filter(EntityMention.finding_type == finding_type)
            if audit_year:
                q = q.filter(EntityMention.audit_year == audit_year)
            if government_body_type:
                q = q.filter(EntityMention.government_body_type == government_body_type)
            q = q.order_by(EntityMention.audit_year.desc().nullslast()).limit(limit)
            return [self._mention_to_dict(m) for m in q.all()]

    def get_reports_for_entity(
        self,
        entity_id: int,
        audit_year_range: Optional[tuple] = None,
    ) -> List[str]:
        """Distinct report_ids that mention this entity."""
        with session_scope() as session:
            q = session.query(distinct(EntityMention.report_id)).filter_by(
                entity_id=entity_id
            )
            if audit_year_range:
                start, end = audit_year_range
                q = q.filter(EntityMention.audit_year.between(start, end))
            return [r[0] for r in q.all()]

    def get_findings_for_entity(
        self,
        entity_id: int,
        min_amount_crore: Optional[float] = None,
        severity: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Distinct findings involving this entity."""
        with session_scope() as session:
            q = session.query(EntityMention).filter(
                EntityMention.entity_id == entity_id,
                EntityMention.finding_id.isnot(None),
            )
            if severity:
                q = q.filter(EntityMention.severity == severity)
            if min_amount_crore is not None:
                q = q.filter(EntityMention.amount_crore >= min_amount_crore)
            q = q.order_by(EntityMention.amount_crore.desc().nullslast()).limit(limit)
            return [self._mention_to_dict(m) for m in q.all()]

    def get_related_entities(
        self,
        entity_id: int,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """Co-occurring entities ranked by shared-finding count."""
        with session_scope() as session:
            from_source = dict(
                session.query(
                    EntityRelation.target_entity_id, func.count(EntityRelation.id)
                )
                .filter_by(source_entity_id=entity_id, relation_type="co_occurs_in_finding")
                .group_by(EntityRelation.target_entity_id)
                .all()
            )
            from_target = dict(
                session.query(
                    EntityRelation.source_entity_id, func.count(EntityRelation.id)
                )
                .filter_by(target_entity_id=entity_id, relation_type="co_occurs_in_finding")
                .group_by(EntityRelation.source_entity_id)
                .all()
            )
            merged: Dict[int, int] = {}
            for eid, c in from_source.items():
                merged[eid] = merged.get(eid, 0) + c
            for eid, c in from_target.items():
                merged[eid] = merged.get(eid, 0) + c

            top = sorted(merged.items(), key=lambda x: -x[1])[:limit]
            results = []
            for eid, count in top:
                ent = session.get(Entity, eid)
                if ent:
                    d = self._entity_to_dict(ent)
                    d["co_occurrence_count"] = count
                    results.append(d)
            return results

    # -------------------------------------------------------------------------
    # Used by ask_comparative for entity-aware filtering
    # -------------------------------------------------------------------------

    def extract_entities_from_query(self, query: str) -> List[Dict[str, Any]]:
        """
        Naive entity extraction from a query string.

        Tries each capitalized token sequence against the alias table.
        Returns matched canonical entities (deduped).

        This is intentionally simple — for the agentic loop we already have an LLM
        decomposing queries, so we don't need NER here. Just substring matching
        against known aliases.
        """
        import re
        # Capture capitalized phrases: "NHAI", "Ministry of Railways", etc.
        candidates = re.findall(
            r"\b[A-Z][A-Za-z0-9]+(?:\s+(?:of\s+|and\s+)?[A-Z][A-Za-z0-9]+){0,4}\b",
            query,
        )
        # Also try acronyms (all-caps tokens 3-6 chars)
        candidates.extend(re.findall(r"\b[A-Z]{3,6}\b", query))

        seen_ids: set = set()
        results: List[Dict[str, Any]] = []
        for cand in candidates:
            ent = self.resolve_alias(cand)
            if ent and ent["id"] not in seen_ids:
                seen_ids.add(ent["id"])
                results.append(ent)
        return results

    # -------------------------------------------------------------------------
    # Serialization
    # -------------------------------------------------------------------------

    def _entity_to_dict(self, ent: Entity) -> Dict[str, Any]:
        return {
            "id": ent.id,
            "canonical_name": ent.canonical_name,
            "entity_type": ent.entity_type,
            "primary_tier": ent.primary_tier,
            "aliases": json.loads(ent.aliases) if ent.aliases else [],
            "first_seen_year": ent.first_seen_year,
            "last_seen_year": ent.last_seen_year,
            "mention_count": ent.mention_count,
            "finding_count": ent.finding_count,
            "report_count": ent.report_count,
        }

    def _mention_to_dict(self, m: EntityMention) -> Dict[str, Any]:
        return {
            "id": m.id,
            "entity_id": m.entity_id,
            "report_id": m.report_id,
            "chunk_id": m.chunk_id,
            "finding_id": m.finding_id,
            "recommendation_id": m.recommendation_id,
            "mention_text": m.mention_text,
            "page": m.page,
            "finding_type": m.finding_type,
            "severity": m.severity,
            "amount_crore": m.amount_crore,
            "audit_year": m.audit_year,
            "government_body_type": m.government_body_type,
            "state_name": m.state_name,
        }


# Singleton getter (matches your report_service pattern)

_service_instance: Optional[EntityService] = None


def get_entity_service() -> Optional[EntityService]:
    """
    Returns the singleton EntityService.

    Returns None if the entity_graph feature is disabled (no DSN configured),
    so callers can branch cleanly.
    """
    global _service_instance
    import os
    if not os.getenv("ENTITY_GRAPH_DSN"):
        return None
    if _service_instance is None:
        _service_instance = EntityService()
    return _service_instance
