"""
Mention indexer: walks every processed report and writes EntityMention
rows linking content to canonical entities.

Idempotent: re-indexing a report DELETES old mentions for that report first.
"""

import json
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Set
from collections import defaultdict

from sqlalchemy import func

from .db import session_scope, init_db
from .models import Entity, EntityMention, EntityRelation

logger = logging.getLogger(__name__)


# =============================================================================
# Alias resolver
# =============================================================================

class AliasResolver:
    """Maps raw mentions to canonical entity IDs.

    Built once per index run by loading the entire entities table.
    """

    def __init__(self, session):
        self.alias_to_id: Dict[str, int] = {}
        for ent in session.query(Entity).all():
            aliases = json.loads(ent.aliases) if ent.aliases else []
            for a in aliases + [ent.canonical_name]:
                key = (a or "").lower().strip()
                if key:
                    # First-write wins (canonical names are loaded first; aliases secondary)
                    if key not in self.alias_to_id:
                        self.alias_to_id[key] = ent.id

    def resolve(self, raw: str) -> Optional[int]:
        if not raw:
            return None
        return self.alias_to_id.get(raw.lower().strip())


# =============================================================================
# Alias Scanner (Aho-Corasick multi-pattern matching)
# =============================================================================

class AliasScanner:
    """Efficient multi-pattern matcher for scanning chunk text for entity aliases.

    Uses Aho-Corasick automaton for O(n + m) matching where n = text length,
    m = number of matches. Much faster than O(n * k) naive approach where
    k = number of aliases.
    """

    MIN_ALIAS_LENGTH = 4  # Skip short aliases to avoid false positives

    def __init__(self, session):
        """Build Aho-Corasick automaton from all entity aliases."""
        import ahocorasick

        self.automaton = ahocorasick.Automaton()
        self.alias_to_entity_id: Dict[str, int] = {}

        for ent in session.query(Entity).all():
            aliases = json.loads(ent.aliases) if ent.aliases else []
            all_names = [ent.canonical_name] + aliases

            for alias in all_names:
                if not alias or len(alias) < self.MIN_ALIAS_LENGTH:
                    continue
                key = alias.lower().strip()
                if not key:
                    continue
                # Store mapping (first-write wins for duplicates)
                if key not in self.alias_to_entity_id:
                    self.alias_to_entity_id[key] = ent.id
                    # Add to automaton: value is (entity_id, original_alias)
                    self.automaton.add_word(key, (ent.id, alias))

        self.automaton.make_automaton()
        logger.info(f"AliasScanner built with {len(self.alias_to_entity_id)} aliases")

    def scan_text(self, text: str) -> List[tuple]:
        """Scan text for all alias matches.

        Returns list of (start_pos, end_pos, entity_id, matched_alias) tuples.
        Filters out nested/overlapping matches (keeps longest match at each position).
        """
        if not text:
            return []

        text_lower = text.lower()
        raw_matches: List[tuple] = []

        # Aho-Corasick iter returns (end_pos, (entity_id, alias)) for each match
        for end_pos, (entity_id, alias) in self.automaton.iter(text_lower):
            start_pos = end_pos - len(alias) + 1
            raw_matches.append((start_pos, end_pos + 1, entity_id, alias))

        # Filter overlapping matches: keep longest match at each position
        if not raw_matches:
            return []

        # Sort by start position, then by length descending
        raw_matches.sort(key=lambda m: (m[0], -(m[1] - m[0])))

        filtered: List[tuple] = []
        last_end = -1

        for match in raw_matches:
            start_pos, end_pos, entity_id, alias = match
            # Skip if this match starts inside a previous match
            if start_pos < last_end:
                continue
            filtered.append(match)
            last_end = end_pos

        return filtered


# =============================================================================
# Indexing
# =============================================================================

def _extract_audit_year(metadata: dict) -> Optional[str]:
    """Extract audit_year string like '2022-23' from report metadata."""
    title = metadata.get("report_title") or ""
    match = re.search(r"(\d{4})-(\d{2,4})", title)
    if match:
        y1, y2 = match.group(1), match.group(2)
        return f"{y1}-{y2 if len(y2) == 2 else y2[-2:]}"
    if metadata.get("report_year"):
        return str(metadata["report_year"])
    return None


def scan_chunks_for_canonical_aliases(
    data: dict,
    scanner: AliasScanner,
    session,
    report_id: str,
    audit_year: Optional[str],
    govt_type: str,
    state_name: Optional[str],
    existing_mentions: Set[tuple],
) -> int:
    """Scan all chunk content for entity aliases using Aho-Corasick.

    This provides comprehensive entity coverage independent of the
    entities_mentioned field being populated in chunks.

    Args:
        data: Parsed report JSON (with child_chunks)
        scanner: AliasScanner instance with prebuilt Aho-Corasick automaton
        session: SQLAlchemy session
        report_id: Report identifier
        audit_year: Extracted audit year string
        govt_type: Government body type (union/state/local_body)
        state_name: State name for state/local reports
        existing_mentions: Set of (entity_id, chunk_id) tuples already added

    Returns:
        Number of mentions inserted
    """
    inserted = 0
    chunks = data.get("child_chunks") or []

    for chunk in chunks:
        content = chunk.get("content") or ""
        if not content:
            continue

        chunk_id = chunk.get("chunk_id")
        page = chunk.get("source_page_physical")

        # Scan chunk content for all alias matches
        matches = scanner.scan_text(content)

        for start_pos, end_pos, entity_id, matched_alias in matches:
            # Skip if we already have a mention for this entity in this chunk
            key = (entity_id, chunk_id)
            if key in existing_mentions:
                continue

            # Extract the actual text that matched (preserving original case)
            mention_text = content[start_pos:end_pos]

            m = EntityMention(
                entity_id=entity_id,
                report_id=report_id,
                chunk_id=chunk_id,
                finding_id=None,
                mention_text=mention_text,
                page=page,
                audit_year=audit_year,
                government_body_type=govt_type,
                state_name=state_name,
            )
            session.add(m)
            existing_mentions.add(key)
            inserted += 1

    return inserted


def index_report(report_path: Path) -> int:
    """
    Index entity mentions from one processed *_chunks.json file.

    Idempotent: deletes existing mentions for this report_id first.
    Returns number of mentions inserted.
    """
    with open(report_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    meta = data.get("report_metadata") or {}
    report_id = meta.get("report_id")
    if not report_id:
        logger.warning(f"Skipping {report_path.name}: no report_id")
        return 0

    audit_year = _extract_audit_year(meta)
    govt_type = meta.get("government_body_type") or "union"
    state_name = meta.get("state_name")

    se = data.get("semantic_enrichment") or {}
    inserted = 0

    init_db()
    with session_scope() as session:
        resolver = AliasResolver(session)
        scanner = AliasScanner(session)

        # Idempotent: clear existing mentions for this report
        session.query(EntityMention).filter_by(report_id=report_id).delete()
        session.query(EntityRelation).filter_by(report_id=report_id).delete()

        # Track (entity_id, chunk_id) pairs to avoid duplicate mentions
        existing_mentions: Set[tuple] = set()

        # ---- From findings ----
        for finding in se.get("findings") or []:
            entities_ids_in_this_finding: List[int] = []
            chunk_id = finding.get("source_chunk_id")
            for raw in finding.get("entities_mentioned") or []:
                eid = resolver.resolve(raw)
                if eid is None:
                    continue
                amount_crore = None
                amt = finding.get("total_amount_inr") or finding.get("amount_crore")
                if amt:
                    amount_crore = float(amt) / 10_000_000 if amt > 1000 else float(amt)

                m = EntityMention(
                    entity_id=eid,
                    report_id=report_id,
                    chunk_id=chunk_id,
                    finding_id=finding.get("finding_id") or finding.get("id"),
                    mention_text=raw,
                    page=finding.get("page"),
                    finding_type=finding.get("finding_type") or finding.get("type"),
                    severity=finding.get("severity"),
                    amount_crore=amount_crore,
                    audit_year=audit_year,
                    government_body_type=govt_type,
                    state_name=state_name,
                )
                session.add(m)
                inserted += 1
                entities_ids_in_this_finding.append(eid)
                # Track this (entity_id, chunk_id) pair
                if chunk_id:
                    existing_mentions.add((eid, chunk_id))

            # Co-occurrence relations (sparse)
            unique_ids = sorted(set(entities_ids_in_this_finding))
            for i, src in enumerate(unique_ids):
                for tgt in unique_ids[i + 1:]:
                    session.add(EntityRelation(
                        source_entity_id=src,
                        target_entity_id=tgt,
                        relation_type="co_occurs_in_finding",
                        report_id=report_id,
                        finding_id=finding.get("finding_id") or finding.get("id"),
                    ))

        # ---- From recommendations ----
        for rec in se.get("recommendations") or []:
            target = rec.get("target_entity") or rec.get("recommendation_target")
            if not target:
                continue
            eid = resolver.resolve(target)
            if eid is None:
                continue
            chunk_id = rec.get("source_chunk_id")
            m = EntityMention(
                entity_id=eid,
                report_id=report_id,
                chunk_id=chunk_id,
                finding_id=None,
                recommendation_id=rec.get("recommendation_id") or rec.get("id"),
                mention_text=target,
                page=rec.get("page"),
                audit_year=audit_year,
                government_body_type=govt_type,
                state_name=state_name,
            )
            session.add(m)
            inserted += 1
            # Track this (entity_id, chunk_id) pair
            if chunk_id:
                existing_mentions.add((eid, chunk_id))

        # ---- From per-chunk entities_mentioned (covers content not in findings) ----
        for chunk in data.get("child_chunks") or []:
            chunk_id = chunk.get("chunk_id")
            for raw in chunk.get("entities_mentioned") or []:
                eid = resolver.resolve(raw)
                if eid is None:
                    continue
                # Skip if already covered by a finding-level mention for this chunk
                key = (eid, chunk_id)
                if key in existing_mentions:
                    continue
                m = EntityMention(
                    entity_id=eid,
                    report_id=report_id,
                    chunk_id=chunk_id,
                    finding_id=None,
                    mention_text=raw,
                    page=chunk.get("source_page_physical"),
                    audit_year=audit_year,
                    government_body_type=govt_type,
                    state_name=state_name,
                )
                session.add(m)
                inserted += 1
                existing_mentions.add(key)

        # ---- Comprehensive alias scan using Aho-Corasick ----
        # Scans all chunk content for entity aliases, providing coverage
        # independent of entities_mentioned being pre-populated
        alias_scan_count = scan_chunks_for_canonical_aliases(
            data=data,
            scanner=scanner,
            session=session,
            report_id=report_id,
            audit_year=audit_year,
            govt_type=govt_type,
            state_name=state_name,
            existing_mentions=existing_mentions,
        )
        inserted += alias_scan_count
        if alias_scan_count > 0:
            logger.debug(f"Alias scan added {alias_scan_count} mentions for {report_id}")

        # ---- Refresh entity-level counts ----
        session.flush()
        _refresh_entity_counts(session)

    logger.info(f"Indexed {inserted} mentions from {report_id}")
    return inserted


def _refresh_entity_counts(session):
    """Recompute mention_count, finding_count, report_count per entity."""
    mention_counts = dict(
        session.query(EntityMention.entity_id, func.count(EntityMention.id))
        .group_by(EntityMention.entity_id)
        .all()
    )
    finding_counts = dict(
        session.query(EntityMention.entity_id, func.count(EntityMention.id))
        .filter(EntityMention.finding_id.isnot(None))
        .group_by(EntityMention.entity_id)
        .all()
    )
    report_counts = dict(
        session.query(
            EntityMention.entity_id,
            func.count(func.distinct(EntityMention.report_id)),
        )
        .group_by(EntityMention.entity_id)
        .all()
    )
    year_min = dict(
        session.query(EntityMention.entity_id, func.min(EntityMention.audit_year))
        .filter(EntityMention.audit_year.isnot(None))
        .group_by(EntityMention.entity_id)
        .all()
    )
    year_max = dict(
        session.query(EntityMention.entity_id, func.max(EntityMention.audit_year))
        .filter(EntityMention.audit_year.isnot(None))
        .group_by(EntityMention.entity_id)
        .all()
    )

    for ent in session.query(Entity).all():
        ent.mention_count = mention_counts.get(ent.id, 0)
        ent.finding_count = finding_counts.get(ent.id, 0)
        ent.report_count = report_counts.get(ent.id, 0)
        # Best-effort year extraction from "YYYY-YY" strings
        first_yr = year_min.get(ent.id)
        last_yr = year_max.get(ent.id)
        if first_yr:
            try:
                ent.first_seen_year = int(str(first_yr).split("-")[0])
            except ValueError:
                pass
        if last_yr:
            try:
                ent.last_seen_year = int(str(last_yr).split("-")[0])
            except ValueError:
                pass


def index_all(processed_dir: Path) -> int:
    """Walk processed_dir and index every *_chunks.json. Returns total mentions inserted."""
    json_files = list(processed_dir.glob("**/*_chunks.json"))
    total = 0
    for jf in json_files:
        try:
            total += index_report(jf)
        except Exception as e:
            logger.error(f"Failed to index {jf.name}: {e}", exc_info=True)
    logger.info(f"Total mentions indexed: {total}")
    return total
