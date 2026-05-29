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
from pathlib import Path

from sqlalchemy import func, or_, distinct

from .db import session_scope
from .models import Entity, EntityMention, EntityRelation

logger = logging.getLogger(__name__)


class ChunkLoader:
    """Load and cache chunk data from JSON files for enrichment."""

    def __init__(self, processed_dir: Path):
        self.processed_dir = Path(processed_dir)
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._cache_limit = 100

    def _load_chunks_json(self, report_id: str) -> Dict[str, Any]:
        """
        Load chunks JSON for a report (cached).

        Tries union, state, local_body subdirectories.
        Returns empty dict if not found.
        """
        # Check cache first
        if report_id in self._cache:
            return self._cache[report_id]

        # Try each tier subdirectory
        result = {}
        for tier in ["union", "state", "local_body"]:
            chunks_file = self.processed_dir / tier / f"{report_id}_chunks.json"
            if chunks_file.exists():
                try:
                    with open(chunks_file, "r", encoding="utf-8") as f:
                        result = json.load(f)
                        break
                except Exception as e:
                    logger.warning(f"Error loading {chunks_file}: {e}")
                    result = {}

        # Store in cache (with simple LRU: clear if we exceed limit)
        if len(self._cache) >= self._cache_limit:
            # Remove oldest entry (arbitrary key)
            self._cache.pop(next(iter(self._cache)))
        self._cache[report_id] = result

        return result

    def get_finding_description(self, finding_id: str) -> Optional[str]:
        """
        Extract finding description from chunks JSON.

        Parses finding_id to get report_id, loads chunks, searches
        semantic_enrichment.findings for matching finding_id.
        Returns finding['text'] or None if not found.
        """
        if not finding_id:
            return None

        # Parse finding_id to extract report_id
        # Format: {report_id}_finding_{number}
        parts = finding_id.rsplit("_finding_", 1)
        if len(parts) != 2:
            return None

        report_id = parts[0]
        chunks = self._load_chunks_json(report_id)

        if not chunks:
            return None

        # Search semantic_enrichment.findings for matching finding_id
        findings = chunks.get("semantic_enrichment", {}).get("findings", [])
        for finding in findings:
            if finding.get("finding_id") == finding_id:
                # Prefer 'text' over 'summary'
                return finding.get("text") or finding.get("summary")

        return None

    def get_chunk_context(self, chunk_id: str, mention_text: str) -> Optional[str]:
        """
        Extract context snippet around mention_text from chunk.

        Parses chunk_id to get report_id, loads chunks JSON,
        finds chunk by chunk_id, and extracts ~200 chars around mention_text.
        """
        if not chunk_id or not mention_text:
            return None

        # Parse chunk_id to extract report_id
        # Format varies, but all contain the report_id at the start
        # Try to extract report_id from chunk_id (everything before _child_ or _parent_)
        report_id_candidate = chunk_id.split("_child_")[0].split("_parent_")[0]
        if not report_id_candidate:
            return None

        chunks = self._load_chunks_json(report_id_candidate)

        if not chunks:
            return None

        # Search child_chunks for matching chunk_id
        child_chunks = chunks.get("child_chunks", [])
        for chunk in child_chunks:
            if chunk.get("chunk_id") == chunk_id:
                content = chunk.get("content", "")
                if not content:
                    continue

                # Find mention_text in content
                idx = content.find(mention_text)
                if idx == -1:
                    # If exact match not found, use the first 200 chars
                    return content[:200] + "..." if len(content) > 200 else content

                # Extract ~200 chars around the mention
                start = max(0, idx - 100)
                end = min(len(content), idx + len(mention_text) + 100)
                snippet = content[start:end]

                # Add ellipsis if truncated
                if start > 0:
                    snippet = "..." + snippet
                if end < len(content):
                    snippet = snippet + "..."

                return snippet

        return None


class EntityService:
    """Read-only entity graph queries."""

    def __init__(self, processed_dir: Optional[Path] = None):
        """Initialize EntityService with optional processed_dir for enrichment."""
        if processed_dir:
            self.chunk_loader = ChunkLoader(processed_dir)
        else:
            # Try to get from settings as fallback
            try:
                from src.api.config import settings
                self.chunk_loader = ChunkLoader(settings.PROCESSED_DIR)
            except (ImportError, AttributeError):
                self.chunk_loader = None

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
            q = session.query(distinct(EntityMention.report_id)).filter(
                EntityMention.entity_id == entity_id
            )
            if audit_year_range:
                start, end = audit_year_range
                q = q.filter(EntityMention.audit_year.between(start, end))
            report_ids = [r[0] for r in q.all()]
            logger.info(
                f"get_reports_for_entity(entity_id={entity_id}): found {len(report_ids)} reports"
            )
            return report_ids

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
    # Count aggregates for home page stats
    # -------------------------------------------------------------------------

    def count_all(self) -> int:
        """Get total count of all entities."""
        with session_scope() as session:
            return session.query(func.count(Entity.id)).scalar() or 0

    def count_by_type(self, entity_type: str) -> int:
        """Get count of entities of a specific type."""
        with session_scope() as session:
            return (
                session.query(func.count(Entity.id))
                .filter(Entity.entity_type == entity_type)
                .scalar()
                or 0
            )

    def count_mentions(self) -> int:
        """Get total count of all entity mentions."""
        with session_scope() as session:
            return session.query(func.count(EntityMention.id)).scalar() or 0

    def random_weighted_entity(
        self, min_mentions: int = 10
    ) -> Optional[Dict[str, Any]]:
        """
        Get a random entity weighted by mention count.

        Args:
            min_mentions: Minimum mention_count threshold

        Returns:
            Random entity dict, or None if no entities match
        """
        import random

        with session_scope() as session:
            # Fetch top 100 entities by mention_count
            entities = (
                session.query(Entity)
                .filter(Entity.mention_count >= min_mentions)
                .order_by(Entity.mention_count.desc())
                .limit(100)
                .all()
            )

            if not entities:
                return None

            # Weighted random choice by mention_count
            weights = [e.mention_count for e in entities]
            chosen = random.choices(entities, weights=weights, k=1)[0]

            return self._entity_to_dict(chosen)

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
        result = {
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

        # Enrich with finding description if applicable
        if m.finding_id and self.chunk_loader:
            description = self.chunk_loader.get_finding_description(m.finding_id)
            result["description"] = description

        # Enrich with context snippet for mentions with chunk_id
        if m.chunk_id and m.mention_text and self.chunk_loader:
            context = self.chunk_loader.get_chunk_context(m.chunk_id, m.mention_text)
            result["context_snippet"] = context

        # Enrich with report title
        try:
            from src.rag_pipeline.report_registry import get_registry
            registry = get_registry()
            report_info = registry.get_report(m.report_id)
            result["report_title"] = (
                report_info.report_title if report_info else m.report_id
            )
        except (ImportError, AttributeError):
            result["report_title"] = m.report_id

        return result


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
        # Try to get processed_dir from settings
        try:
            from src.api.config import settings
            _service_instance = EntityService(processed_dir=settings.PROCESSED_DIR)
        except (ImportError, AttributeError):
            # Fallback: initialize without processed_dir (enrichment will be disabled)
            _service_instance = EntityService()
    return _service_instance
