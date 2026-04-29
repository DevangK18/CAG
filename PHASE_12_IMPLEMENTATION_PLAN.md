# Phase 12: Cross-Report Entity Graph + Comparative Path Refactor

**For**: Claude Code execution
**Date**: April 2026
**Baseline**: RAG Pipeline v3.2 + Phase 11 (Agentic) + Phase 13 (Groundedness) shipped
**Target**: Cross-report entity graph + groundedness for `ask_comparative()` + entity-graph filtering for comparative path
**Database**: 100% Postgres (per design decision)
**Canonicalization mode**: Hybrid (per-report normalization in existing batch + explicit cross-corpus pass)

---

## Table of Contents

1. [Guiding principles](#guiding-principles)
2. [Architecture overview](#architecture-overview)
3. [Step 1: Per-report entity normalization (extends existing batch pipeline)](#step-1-per-report-entity-normalization)
4. [Step 2: Postgres setup + entity graph schema](#step-2-postgres-setup--entity-graph-schema)
5. [Step 3: Cross-corpus canonicalization (one-off batch)](#step-3-cross-corpus-canonicalization)
6. [Step 4: Mention indexer (writes to Postgres)](#step-4-mention-indexer)
7. [Step 5: Entity query service](#step-5-entity-query-service)
8. [Step 6: API routes (`/entities`)](#step-6-api-routes)
9. [Step 7: Comparative path refactor (groundedness + entity filtering)](#step-7-comparative-path-refactor)
10. [Step 8: Integration with indexer + agentic loop](#step-8-integration)
11. [Configuration, ops, testing, rollout](#configuration-ops-testing-rollout)

---

## Guiding principles

Same as previous phases:

- **No breaking changes.** All existing endpoints, batch flows, and signatures continue to work byte-identically when Phase 12 is disabled.
- **Additive.** New tables, new package (`src/entity_graph/`), new API prefix (`/api/entities`). Existing files modified with surgical changes only.
- **Match conventions.** Dual-import pattern, `logger = logging.getLogger(__name__)`, dataclasses for data objects, Pydantic for API. The two existing batch pipelines (`BatchService` + `EnrichmentService`) are not refactored — Phase 12 plugs alongside them.
- **Postgres-native, no SQLite fallback.** Per the design decision. Connection details via env vars.
- **Hybrid canonicalization.** Per-report normalization runs inside the existing overview batch (no new LLM call per report). Cross-corpus dedup runs as a separate explicit CLI command on demand.
- **Comparative path uses entity graph.** Per design decision: `ask_comparative()` consults the entity graph to identify candidate reports before per-report retrieval.

---

## Architecture overview

```
┌──────────────────────────── INDEXING TIME ────────────────────────────┐
│                                                                       │
│  PDF → parsing pipeline → chunks.json → enrichment batch              │
│                              ↓                                        │
│                    overview batch (Anthropic)                         │
│                              ↓                                        │
│                  overview_llm.json (NEW: includes                     │
│                    "normalized_entities" block)                       │
│                                                                       │
│  ┌─── On-demand CLI (operator runs after new reports land) ────┐     │
│  │  python -m src.entity_graph.cli canonicalize                 │     │
│  │    → reads all overview_llm.json files                       │     │
│  │    → batches normalized_entities through gpt-4o-mini         │     │
│  │    → produces canonical_entities.json + loads to Postgres    │     │
│  │                                                              │     │
│  │  python -m src.entity_graph.cli index                        │     │
│  │    → walks all *_chunks.json files                           │     │
│  │    → writes entity_mentions + entity_relations to Postgres   │     │
│  └──────────────────────────────────────────────────────────────┘     │
│                                                                       │
└───────────────────────────────────────────────────────────────────────┘

┌──────────────────────────── QUERY TIME ───────────────────────────────┐
│                                                                       │
│  POST /api/entities/search?q=NHAI         ← UI entity browser         │
│  POST /api/entities/{id}/mentions         ← UI entity detail          │
│  POST /api/entities/{id}/related          ← related entities          │
│  POST /api/entities/{id}/findings         ← findings for entity       │
│                                                                       │
│  POST /api/chat/agentic     ← agentic loop calls EntityService        │
│                              for entity-bound sub-queries             │
│                                                                       │
│  POST /api/series/{id}/query  → ask_comparative()                     │
│                              → uses EntityService to narrow report    │
│                                set if query mentions a known entity   │
│                              → builds merged RetrievalResult          │
│                              → groundedness check on merged result    │
│                                                                       │
└───────────────────────────────────────────────────────────────────────┘
```

The graph itself contains:

- **`entities`** table: canonical names, types (ministry/psu/scheme/state_govt/local_body/organization/place), aliases, mention counts
- **`entity_mentions`** table: every mention found in chunks/findings/recommendations, linked back to chunk_id and report
- **`entity_relations`** table: co-occurrence edges within the same finding (sparse, optional)

---

## Step 1: Per-report entity normalization

Extend your existing **overview extraction prompt** to produce a structured `normalized_entities` block. This piggybacks on the LLM call you're already making — zero new cost.

### Files to modify

#### `src/batch_pipeline/prompts/overview_extraction.py`

Add a 5th output field. The prompt currently extracts `audit_scope`, `audit_objectives`, `topics_covered`, `glossary_terms`. Add `normalized_entities`.

Find the section starting `## YOUR TASK: Extract ONLY these 4 fields`. Change to `## YOUR TASK: Extract these 5 fields`.

After the "### 4. glossary_terms" block, add:

```
### 5. normalized_entities

Extract every distinct organizational, scheme, geographic, and governance entity mentioned in this report. For each entity:

```json
{
  "canonical_form_in_report": "Full official name as it appears most authoritatively in this report",
  "entity_type": "ministry | department | psu | autonomous_body | scheme | state_government | local_body | regulatory_authority | organization | place",
  "aliases_seen": ["all variant spellings, abbreviations, and partial forms seen in this report"],
  "first_seen_page": physical_page_number,
  "tier_context": "union | state | local_body — which government tier this entity belongs to"
}
```

Rules for normalized_entities:
- Extract 20-50 entities per report (this is a high-yield list, not exhaustive)
- ONE entry per logical entity. If "Ministry of Railways", "MoR", and "Min. of Railways" all appear, produce ONE entry with all three in aliases_seen
- Use the LONGEST/MOST OFFICIAL form as canonical_form_in_report (e.g., "National Highways Authority of India" not "NHAI")
- Always include the acronym in aliases_seen if both forms appear
- For state government entities, use "Government of [State]" as canonical (e.g., "Government of Mizoram")
- For local bodies, be specific: "Aizawl Municipal Corporation" not "AMC" as canonical, but include "AMC" in aliases
- entity_type uses the most specific applicable category
- tier_context: based on the report tier and the entity's level
  - Central ministries/PSUs/national schemes → "union"
  - State departments/State PSEs/state schemes → "state"
  - PRIs/ULBs/Village Councils/local schemes → "local_body"
- DO NOT include: generic terms ("the Ministry", "the State"), single-letter abbreviations, or vague entities ("various departments")
- DO include: specific named ministries, PSUs, schemes, autonomous bodies, named programmes, named regulators, geographic units (states, districts, specific project locations)
```

Update the OUTPUT FORMAT block at the bottom from:

```json
{{
  "audit_scope": {{ ... }},
  "audit_objectives": [ ... ],
  "topics_covered": [ ... ],
  "glossary_terms": [ ... ]
}}
```

to:

```json
{{
  "audit_scope": {{ ... }},
  "audit_objectives": [ ... ],
  "topics_covered": [ ... ],
  "glossary_terms": [ ... ],
  "normalized_entities": [ ... ]
}}
```

That's it for the prompt. Same Anthropic call, ~5-10% more output tokens, no schema migration needed. The next time `BatchService.submit_overview_batch()` runs, every overview JSON will have the new field.

#### `src/batch_pipeline/merge_utils.py`

Add `normalized_entities` to the merge fields list. Find:

```python
llm_fields = ["audit_scope", "audit_objectives", "topics_covered", "glossary_terms"]
```

Replace with:

```python
llm_fields = [
    "audit_scope",
    "audit_objectives",
    "topics_covered",
    "glossary_terms",
    "normalized_entities",  # Phase 12: per-report entity normalization
]
```

That's the entire merge change. The merged overview JSON now carries the normalized entity list.

#### `src/batch_pipeline/batch_service.py`

In `submit_overview_batch()`, raise the `max_tokens` for `overview` from 16000 to 18000 to accommodate the new field. Find:

```python
self.max_tokens = {
    "overview": 16000,
    ...
}
```

Replace `"overview": 16000,` with `"overview": 18000,`. Phase 12 only.

### Verification before moving on

After re-running the overview batch on at least one report:

```bash
python -c "
import json
with open('data/batch_jobs/overviews/MZ_2019_Annual_Technical_Inspection_Report_..._overview_llm.json') as f:
    d = json.load(f)
ne = d.get('normalized_entities', [])
print(f'Got {len(ne)} normalized entities')
for e in ne[:5]:
    print(f\"  {e['canonical_form_in_report']} ({e['entity_type']}, {e['tier_context']})\")
    print(f'    aliases: {e[\"aliases_seen\"]}')
"
```

Expected output: 20-50 entities with the 5 keys per entry.

---

## Step 2: Postgres setup + entity graph schema

### Dependencies to add

In `pyproject.toml` (under `[tool.poetry.dependencies]`):

```toml
sqlalchemy = "^2.0.36"
psycopg = {version = "^3.2.0", extras = ["binary"]}
alembic = "^1.14.0"
```

Then run `poetry lock && poetry export --only main -o requirements.docker.txt`.

Note: I'm using `psycopg` (v3) not `psycopg2`. Modern, fully async-capable, fewer install headaches. Stays sync for our use.

### Connection configuration

#### `src/core/config.py`

Add a new config class. Match the existing patterns (`QueryEnhancementConfig`, `GroundednessConfig`, `AgenticConfig` style):

```python
@dataclass
class EntityGraphConfig:
    """Configuration for the entity graph (Phase 12)."""

    enabled: bool = False  # OFF by default; turn on after canonicalization runs

    # Postgres DSN — required when enabled
    # Example: postgresql+psycopg://cag_user:pass@localhost:5432/cag_entity_graph
    dsn: Optional[str] = None

    # Canonicalization model (cross-corpus dedup)
    canonicalization_model: str = "gpt-4o-mini"
    canonicalization_batch_size: int = 80  # entities per LLM call

    # Auto-index on chunk indexing? If True, indexer.py also writes to entity graph
    auto_index_on_ingest: bool = True

    # Comparative integration: use entity graph to narrow report selection?
    enable_comparative_filtering: bool = True

    def __post_init__(self):
        self.dsn = os.getenv("ENTITY_GRAPH_DSN", self.dsn)
```

Add to `RAGConfig`:

```python
@dataclass
class RAGConfig:
    # ... existing fields ...
    entity_graph: EntityGraphConfig = field(default_factory=EntityGraphConfig)
```

Add to the `validate()` method:

```python
def validate(self) -> List[str]:
    errors = []
    # ... existing checks ...
    if self.entity_graph.enabled and not self.entity_graph.dsn:
        errors.append("ENTITY_GRAPH_DSN not set (required when entity_graph.enabled)")
    return errors
```

### `src/entity_graph/__init__.py` (NEW package, empty file)

### `src/entity_graph/db.py` (NEW)

```python
"""
Postgres connection management for the entity graph.

Uses SQLAlchemy 2.0 with psycopg v3 driver.
"""

import os
import logging
from contextlib import contextmanager
from typing import Optional, Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker, Session

from .models import Base

logger = logging.getLogger(__name__)


_engine: Optional[Engine] = None
_SessionLocal: Optional[sessionmaker] = None


def _resolve_dsn() -> str:
    """Resolve the Postgres DSN from env or raise."""
    dsn = os.getenv("ENTITY_GRAPH_DSN")
    if not dsn:
        raise RuntimeError(
            "ENTITY_GRAPH_DSN not set. Required for entity graph operations."
        )
    return dsn


def get_engine() -> Engine:
    """Lazy-initialize the SQLAlchemy engine."""
    global _engine
    if _engine is None:
        dsn = _resolve_dsn()
        _engine = create_engine(
            dsn,
            echo=False,
            future=True,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=10,
        )
        logger.info(f"Entity graph engine initialized")
    return _engine


def get_session_factory() -> sessionmaker:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), expire_on_commit=False)
    return _SessionLocal


def init_db():
    """Create tables if they don't exist. Idempotent."""
    Base.metadata.create_all(get_engine())
    logger.info("Entity graph schema initialized")


@contextmanager
def session_scope() -> Iterator[Session]:
    """Standard session context manager."""
    SessionLocal = get_session_factory()
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
```

### `src/entity_graph/models.py` (NEW)

```python
"""
SQLAlchemy ORM models for the entity graph.

Three tables:
- entities: canonical entities with aliases + counts
- entity_mentions: every mention found in chunks/findings/recommendations
- entity_relations: co-occurrence edges within findings (sparse)
"""

from datetime import datetime
from typing import List, Optional

from sqlalchemy import (
    Integer,
    String,
    Text,
    Float,
    DateTime,
    ForeignKey,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Entity(Base):
    __tablename__ = "entities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    canonical_name: Mapped[str] = mapped_column(String(500), nullable=False, unique=True, index=True)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)

    # Aliases stored as JSON-encoded array (Postgres TEXT[] would also work but JSON is portable)
    aliases: Mapped[str] = mapped_column(Text, nullable=False, default="[]")

    # Tier hint (union/state/local_body) — informational; mentions can span tiers
    primary_tier: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    first_seen_year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    last_seen_year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    mention_count: Mapped[int] = mapped_column(Integer, default=0)
    finding_count: Mapped[int] = mapped_column(Integer, default=0)
    report_count: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    mentions: Mapped[List["EntityMention"]] = relationship(
        back_populates="entity", cascade="all, delete-orphan"
    )


class EntityMention(Base):
    __tablename__ = "entity_mentions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("entities.id", ondelete="CASCADE"), index=True
    )
    report_id: Mapped[str] = mapped_column(String(300), nullable=False, index=True)

    # nullable: chunk-level mentions point to chunk_id; finding-level mentions may not
    chunk_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    finding_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True, index=True)
    recommendation_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)

    mention_text: Mapped[str] = mapped_column(String(500), nullable=False)
    page: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    finding_type: Mapped[Optional[str]] = mapped_column(String(80), nullable=True, index=True)
    severity: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    amount_crore: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Tier metadata (denormalized for fast filtering)
    audit_year: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, index=True)
    government_body_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, index=True)
    state_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    entity: Mapped["Entity"] = relationship(back_populates="mentions")


class EntityRelation(Base):
    __tablename__ = "entity_relations"
    __table_args__ = (
        UniqueConstraint(
            "source_entity_id",
            "target_entity_id",
            "relation_type",
            "finding_id",
            name="uq_entity_relation",
        ),
        Index("idx_relations_source", "source_entity_id"),
        Index("idx_relations_target", "target_entity_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_entity_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("entities.id", ondelete="CASCADE")
    )
    target_entity_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("entities.id", ondelete="CASCADE")
    )
    relation_type: Mapped[str] = mapped_column(String(80), nullable=False)
    report_id: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    finding_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
```

### Postgres provisioning (operator runbook)

This is documentation, not code. Add to `docs/entity_graph_setup.md` (NEW):

```markdown
# Entity Graph Postgres Setup

## 1. Create database and user

```bash
sudo -u postgres psql
```

```sql
CREATE USER cag_user WITH PASSWORD 'change_this_secret';
CREATE DATABASE cag_entity_graph OWNER cag_user;
GRANT ALL PRIVILEGES ON DATABASE cag_entity_graph TO cag_user;
\q
```

## 2. Set environment variable

In your `.env`:

```
ENTITY_GRAPH_DSN=postgresql+psycopg://cag_user:change_this_secret@localhost:5432/cag_entity_graph
```

## 3. Initialize schema

```bash
python -m src.entity_graph.cli init-db
```

## 4. (When ready) Run canonicalization + index

```bash
python -m src.entity_graph.cli canonicalize
python -m src.entity_graph.cli index
```
```

---

## Step 3: Cross-corpus canonicalization

### `src/entity_graph/canonicalizer.py` (NEW)

This is the one-off batch LLM step. It reads the per-report `normalized_entities` blocks (output of Step 1), batches them across all reports, and produces a global canonical dictionary.

```python
"""
Cross-corpus canonicalization (Phase 12).

Reads per-report `normalized_entities` from each *_overview_llm.json,
batches them through gpt-4o-mini, and produces a global canonical
entity dictionary loaded into Postgres.

Run via:
    python -m src.entity_graph.cli canonicalize --overviews-dir data/batch_jobs/overviews
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Set, Optional, Any
from collections import defaultdict

from openai import OpenAI

from .db import session_scope, init_db
from .models import Entity

logger = logging.getLogger(__name__)


# =============================================================================
# Prompt
# =============================================================================

CANONICALIZATION_SYSTEM_PROMPT = """You merge entity records from multiple Indian CAG audit reports into a canonical entity dictionary.

You will receive a JSON list of entity records from different reports. Each record has:
- canonical_form_in_report: how the entity was named in that one report
- entity_type: classification
- aliases_seen: variant spellings/abbreviations seen in that report
- tier_context: union | state | local_body

Your task: merge records that refer to the SAME real-world entity.

Rules:
- Two records refer to the same entity if any of their aliases overlap (case-insensitive) OR their canonical_form_in_report differ only in casing/abbreviation/minor wording
- The merged canonical_name should be the LONGEST and MOST OFFICIAL form across all merged records
- The merged aliases must include EVERY variant from all merged records (deduplicated case-insensitively)
- entity_type: prefer the most specific type (e.g., "psu" over "organization" if both apply)
- primary_tier: pick the tier_context that appears most often across the merged records
- Be conservative: if two records LOOK similar but their aliases don't overlap, keep them SEPARATE
- Skip records where canonical_form_in_report is too generic ("the Ministry", "the State") or under 4 characters

Return ONLY valid JSON:
{
  "merged_entities": [
    {
      "canonical_name": "National Highways Authority of India",
      "entity_type": "psu",
      "aliases": ["NHAI", "National Highways Authority", "National Highway Authority of India"],
      "primary_tier": "union"
    }
  ]
}"""


# =============================================================================
# Collection
# =============================================================================

def collect_normalized_entities(overviews_dir: Path) -> List[Dict[str, Any]]:
    """
    Walk every *_overview_llm.json in overviews_dir and return
    a flat list of normalized entity records.
    """
    overview_files = sorted(overviews_dir.glob("*_overview_llm.json"))
    if not overview_files:
        raise RuntimeError(f"No overview files found in {overviews_dir}")

    all_records: List[Dict[str, Any]] = []
    for f in overview_files:
        try:
            with open(f, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            records = data.get("normalized_entities") or []
            for r in records:
                # Tag the record with source for debugging
                r["_source_file"] = f.name
                all_records.append(r)
        except Exception as e:
            logger.warning(f"Failed to read {f.name}: {e}")

    logger.info(f"Collected {len(all_records)} normalized entity records from {len(overview_files)} reports")
    return all_records


# =============================================================================
# Pre-merge: bucket by lowercase canonical for cheap pre-dedup
# =============================================================================

def pre_bucket(records: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """
    Group records by case-insensitive canonical_form_in_report.

    This is a free first-pass dedup: 'NHAI' from 50 reports collapses to 1 bucket.
    Reduces the LLM workload massively.
    """
    buckets: Dict[str, List[Dict]] = defaultdict(list)
    for r in records:
        key = (r.get("canonical_form_in_report") or "").lower().strip()
        if not key or len(key) < 3:
            continue
        buckets[key].append(r)
    logger.info(f"Pre-bucketed into {len(buckets)} unique lowercase canonicals")
    return buckets


def collapse_buckets(buckets: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """
    For each bucket, collapse to one consolidated record with merged aliases.
    Keep the longest canonical_form_in_report seen as the bucket's canonical.

    Output records are still pre-LLM; they need cross-bucket dedup.
    """
    consolidated: List[Dict[str, Any]] = []
    for key, recs in buckets.items():
        # Pick longest canonical
        best_canonical = max(
            (r.get("canonical_form_in_report") or "" for r in recs),
            key=len,
        )

        # Merge aliases case-insensitively
        all_aliases: Set[str] = set()
        for r in recs:
            all_aliases.add(r.get("canonical_form_in_report") or "")
            for a in r.get("aliases_seen") or []:
                if a:
                    all_aliases.add(a)
        all_aliases.discard("")

        # entity_type: most common
        type_counts: Dict[str, int] = defaultdict(int)
        for r in recs:
            t = r.get("entity_type") or "organization"
            type_counts[t] += 1
        best_type = max(type_counts.items(), key=lambda x: x[1])[0]

        # tier: most common
        tier_counts: Dict[str, int] = defaultdict(int)
        for r in recs:
            t = r.get("tier_context") or "union"
            tier_counts[t] += 1
        best_tier = max(tier_counts.items(), key=lambda x: x[1])[0]

        consolidated.append({
            "canonical_form_in_report": best_canonical,
            "entity_type": best_type,
            "aliases_seen": sorted(all_aliases),
            "tier_context": best_tier,
            "_occurrence_count": len(recs),
        })
    return consolidated


# =============================================================================
# LLM cross-bucket canonicalization
# =============================================================================

def canonicalize_via_llm(
    consolidated: List[Dict[str, Any]],
    model: str = "gpt-4o-mini",
    batch_size: int = 80,
) -> List[Dict[str, Any]]:
    """
    Send consolidated records to LLM in batches for cross-bucket merging.

    Within a single batch, the LLM merges 'NHAI' and 'National Highways Authority of India'
    even if they ended up in different buckets (because of casing/spelling).

    Returns canonical entities ready to load into Postgres.
    """
    client = OpenAI()
    canonical: List[Dict[str, Any]] = []

    # Sort by occurrence_count desc — most common entities go in first batches
    # (helps the LLM see the high-frequency canonical names first)
    consolidated_sorted = sorted(
        consolidated, key=lambda r: -r.get("_occurrence_count", 0)
    )

    for i in range(0, len(consolidated_sorted), batch_size):
        batch = consolidated_sorted[i : i + batch_size]
        # Strip internal fields before sending
        clean_batch = [
            {k: v for k, v in r.items() if not k.startswith("_")}
            for r in batch
        ]

        user_prompt = (
            f"Merge these entity records:\n\n{json.dumps(clean_batch, indent=2, ensure_ascii=False)}\n\n"
            "Return JSON with 'merged_entities' array."
        )

        try:
            resp = client.chat.completions.create(
                model=model,
                temperature=0.0,
                max_tokens=4000,
                messages=[
                    {"role": "system", "content": CANONICALIZATION_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
            )
            parsed = json.loads(resp.choices[0].message.content)
            merged = parsed.get("merged_entities") or []
            canonical.extend(merged)
            logger.info(
                f"Batch {i // batch_size + 1}/{(len(consolidated_sorted) - 1) // batch_size + 1}: "
                f"{len(batch)} input → {len(merged)} merged"
            )
        except Exception as e:
            logger.error(f"Batch {i // batch_size + 1} failed: {e}")
            continue

    # Final pass: merge across-batch overlaps (same alias appearing in two LLM batches)
    final = _final_alias_merge(canonical)
    logger.info(f"After final alias merge: {len(final)} canonical entities")
    return final


def _final_alias_merge(entities: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Cross-batch alias merge.

    If batch 1 produced {NHAI, [NHAI, National Highways Authority]} and
    batch 2 produced {National Highways Authority of India, [NHAI]}, merge them.
    """
    alias_to_idx: Dict[str, int] = {}
    out: List[Dict[str, Any]] = []

    for ent in entities:
        cname = ent.get("canonical_name") or ""
        aliases = ent.get("aliases") or []
        all_aliases_lower = {a.lower().strip() for a in aliases if a}
        all_aliases_lower.add(cname.lower().strip())
        all_aliases_lower.discard("")

        # Find existing entity with overlapping alias
        target_idx = None
        for a in all_aliases_lower:
            if a in alias_to_idx:
                target_idx = alias_to_idx[a]
                break

        if target_idx is None:
            out.append({
                "canonical_name": cname,
                "entity_type": ent.get("entity_type") or "organization",
                "aliases": sorted(set(aliases + [cname])),
                "primary_tier": ent.get("primary_tier"),
            })
            new_idx = len(out) - 1
            for a in all_aliases_lower:
                alias_to_idx[a] = new_idx
        else:
            existing = out[target_idx]
            existing_aliases = set(existing["aliases"])
            existing_aliases.update(aliases)
            existing_aliases.add(cname)
            existing_aliases.discard("")

            if len(cname) > len(existing["canonical_name"]):
                existing["canonical_name"] = cname

            existing["aliases"] = sorted(existing_aliases)
            for a in all_aliases_lower:
                alias_to_idx[a] = target_idx

    return out


# =============================================================================
# Persist to Postgres
# =============================================================================

def load_canonical_to_db(canonical_entities: List[Dict[str, Any]]) -> int:
    """
    Upsert canonical entities into Postgres.

    Match on canonical_name (unique-indexed). Update aliases on conflict.
    """
    init_db()
    inserted = 0
    updated = 0

    with session_scope() as session:
        for ent_dict in canonical_entities:
            cname = (ent_dict.get("canonical_name") or "").strip()
            if not cname:
                continue

            existing = session.query(Entity).filter_by(canonical_name=cname).first()
            if existing:
                # Merge aliases
                existing_aliases = set(json.loads(existing.aliases))
                new_aliases = set(ent_dict.get("aliases") or [])
                merged = sorted(existing_aliases | new_aliases)
                existing.aliases = json.dumps(merged)
                if ent_dict.get("entity_type") and ent_dict["entity_type"] != "organization":
                    existing.entity_type = ent_dict["entity_type"]
                if ent_dict.get("primary_tier"):
                    existing.primary_tier = ent_dict["primary_tier"]
                updated += 1
            else:
                ent = Entity(
                    canonical_name=cname,
                    entity_type=ent_dict.get("entity_type") or "organization",
                    aliases=json.dumps(ent_dict.get("aliases") or [cname]),
                    primary_tier=ent_dict.get("primary_tier"),
                )
                session.add(ent)
                inserted += 1

    logger.info(f"Canonical load: {inserted} new, {updated} updated")
    return inserted + updated


# =============================================================================
# Top-level orchestrator
# =============================================================================

def canonicalize_all(
    overviews_dir: Path,
    output_path: Optional[Path] = None,
    model: str = "gpt-4o-mini",
    batch_size: int = 80,
) -> List[Dict[str, Any]]:
    """End-to-end canonicalization pipeline."""
    raw = collect_normalized_entities(overviews_dir)
    buckets = pre_bucket(raw)
    consolidated = collapse_buckets(buckets)
    canonical = canonicalize_via_llm(consolidated, model=model, batch_size=batch_size)

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump({"entities": canonical}, f, indent=2, ensure_ascii=False)
        logger.info(f"Wrote canonical dictionary: {output_path}")

    load_canonical_to_db(canonical)
    return canonical
```

### Cost expectations

For a corpus of ~50 reports:

- Step 1 (pre-bucketing): zero LLM cost, just dedup
- Pre-bucketed records: ~30 entities/report × 50 reports = 1,500 records, dedupes to ~500-800 unique buckets
- LLM batches: 800 / 80 = 10 batches at gpt-4o-mini = **~$1-3 one-time**

Incremental updates: when 5 new reports arrive, you re-run canonicalize. The bucketing absorbs ~80% of new entities (already known). Only new buckets hit the LLM. Cost: **<$1 for 5 new reports**.

---

## Step 4: Mention indexer

After canonicalization is loaded into Postgres, walk every report and write `EntityMention` rows.

### `src/entity_graph/mention_indexer.py` (NEW)

```python
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

        # Idempotent: clear existing mentions for this report
        session.query(EntityMention).filter_by(report_id=report_id).delete()
        session.query(EntityRelation).filter_by(report_id=report_id).delete()

        # ---- From findings ----
        for finding in se.get("findings") or []:
            entities_ids_in_this_finding: List[int] = []
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
                    chunk_id=finding.get("source_chunk_id"),
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
            m = EntityMention(
                entity_id=eid,
                report_id=report_id,
                chunk_id=rec.get("source_chunk_id"),
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

        # ---- From per-chunk entities_mentioned (covers content not in findings) ----
        for chunk in data.get("child_chunks") or []:
            for raw in chunk.get("entities_mentioned") or []:
                eid = resolver.resolve(raw)
                if eid is None:
                    continue
                # Skip if already covered by a finding-level mention for this chunk
                # (cheap check; perfect dedup not necessary)
                m = EntityMention(
                    entity_id=eid,
                    report_id=report_id,
                    chunk_id=chunk.get("chunk_id"),
                    finding_id=None,
                    mention_text=raw,
                    page=chunk.get("source_page_physical"),
                    audit_year=audit_year,
                    government_body_type=govt_type,
                    state_name=state_name,
                )
                session.add(m)
                inserted += 1

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
```

---

## Step 5: Entity query service

### `src/entity_graph/entity_service.py` (NEW)

Public-facing query API. Used by HTTP routes AND the agentic loop AND `ask_comparative()`.

```python
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
```

---

## Step 6: API routes

### `src/api/routes/entities.py` (NEW)

```python
"""
Entity graph HTTP endpoints (Phase 12).
"""

from fastapi import APIRouter, HTTPException, Request, Query
from typing import Optional

from src.entity_graph.entity_service import get_entity_service
from ..rate_limit import limiter, RATE_LIMIT_CHAT  # reuse existing

router = APIRouter()


def _require_service():
    service = get_entity_service()
    if not service:
        raise HTTPException(
            status_code=503,
            detail="Entity graph not enabled. Set ENTITY_GRAPH_DSN and run canonicalize+index.",
        )
    return service


@router.get("/search")
@limiter.limit(RATE_LIMIT_CHAT)
async def search_entities(
    request: Request,
    q: str = Query(..., min_length=2, max_length=200),
    entity_type: Optional[str] = None,
    primary_tier: Optional[str] = None,
    limit: int = Query(10, le=50),
):
    """Search entities by name or alias."""
    service = _require_service()
    return {
        "results": service.search_entities(q, entity_type, primary_tier, limit),
    }


@router.get("/{entity_id}")
@limiter.limit(RATE_LIMIT_CHAT)
async def get_entity(request: Request, entity_id: int):
    service = _require_service()
    ent = service.get_entity(entity_id)
    if not ent:
        raise HTTPException(404, "Entity not found")
    return ent


@router.get("/{entity_id}/mentions")
@limiter.limit(RATE_LIMIT_CHAT)
async def get_mentions(
    request: Request,
    entity_id: int,
    finding_type: Optional[str] = None,
    audit_year: Optional[str] = None,
    government_body_type: Optional[str] = None,
    limit: int = Query(100, le=500),
):
    service = _require_service()
    return {
        "mentions": service.get_mentions(
            entity_id, finding_type, audit_year, government_body_type, limit
        )
    }


@router.get("/{entity_id}/reports")
@limiter.limit(RATE_LIMIT_CHAT)
async def get_reports_for_entity(request: Request, entity_id: int):
    service = _require_service()
    return {"report_ids": service.get_reports_for_entity(entity_id)}


@router.get("/{entity_id}/related")
@limiter.limit(RATE_LIMIT_CHAT)
async def get_related(request: Request, entity_id: int, limit: int = Query(20, le=100)):
    service = _require_service()
    return {"related": service.get_related_entities(entity_id, limit)}


@router.get("/{entity_id}/findings")
@limiter.limit(RATE_LIMIT_CHAT)
async def get_findings(
    request: Request,
    entity_id: int,
    min_amount_crore: Optional[float] = None,
    severity: Optional[str] = None,
    limit: int = Query(50, le=200),
):
    service = _require_service()
    return {
        "findings": service.get_findings_for_entity(
            entity_id, min_amount_crore, severity, limit
        )
    }
```

### `src/api/main.py` — register the router

Find the existing router includes:

```python
app.include_router(reports.router, prefix="/api/reports", tags=["Reports"])
app.include_router(assets.router, prefix="/api/reports", tags=["Charts & Tables"])
app.include_router(series.router, prefix="/api/series", tags=["Time Series"])
app.include_router(chat.router, prefix="/api/chat", tags=["Chat"])
app.include_router(overview.router, prefix="/api")
app.include_router(summaries.router, prefix="/api")
```

Add at the end:

```python
# Phase 12: Entity graph (only registers routes; service is lazy)
from .routes import entities
app.include_router(entities.router, prefix="/api/entities", tags=["Entities"])
```

Also add to the lifespan logger lines:

```python
logger.info("  - GET  /api/entities/search?q=...   - Search entities (Phase 12)")
logger.info("  - GET  /api/entities/{id}/mentions  - Entity mentions (Phase 12)")
```

---

## Step 7: Comparative path refactor

This is the most delicate piece — refactoring `ask_comparative()` to:
1. Optionally use the entity graph to narrow report selection
2. Build a merged `RetrievalResult` so groundedness can run
3. Eliminate the broken `groundedness_dict` reference

### First: extract a shared `_merge_retrievals` helper

Currently the merge logic lives in `agentic_service.py::AgenticRAGService._merge_retrievals`. We'll extract it into a free function.

#### `src/rag_pipeline/retrieval_utils.py` (NEW)

```python
"""
Retrieval utilities shared between agentic and comparative paths.
"""

import logging
from copy import copy
from typing import List

try:
    from .models import RetrievalResult, ParentContext, RetrievedChunk
except ImportError:
    from models import RetrievalResult, ParentContext, RetrievedChunk

logger = logging.getLogger(__name__)


def merge_retrieval_results(retrievals: List[RetrievalResult]) -> RetrievalResult:
    """
    Merge multiple RetrievalResults into one.

    Deduplicates by chunk_id; keeps highest-scored copy per chunk.
    Re-groups by parent.

    Used by:
    - AgenticRAGService for sub-query merging
    - ask_comparative() for cross-report merging (Phase 12)
    """
    if not retrievals:
        return RetrievalResult(
            query="",
            total_candidates=0,
            total_after_rerank=0,
            parents=[],
            filters_applied={},
            reranker_used="none",
            search_type="merged_empty",
        )

    seen_chunks: dict = {}  # chunk_id -> RetrievedChunk
    parent_map: dict = {}   # parent_chunk_id -> ParentContext (copy)

    for result in retrievals:
        for parent in result.parents:
            if parent.chunk_id not in parent_map:
                p_copy = copy(parent)
                p_copy.children = []
                parent_map[parent.chunk_id] = p_copy

            for child in parent.children:
                if child.chunk_id not in seen_chunks:
                    seen_chunks[child.chunk_id] = child
                    parent_map[parent.chunk_id].children.append(child)
                else:
                    existing = seen_chunks[child.chunk_id]
                    if child.score > existing.score:
                        existing.score = child.score

    parents_list = [p for p in parent_map.values() if p.children]
    parents_list.sort(key=lambda p: -max(c.score for c in p.children))

    return RetrievalResult(
        query=retrievals[0].query,
        total_candidates=sum(r.total_candidates for r in retrievals),
        total_after_rerank=len(seen_chunks),
        parents=parents_list,
        filters_applied=retrievals[0].filters_applied if retrievals else {},
        reranker_used=retrievals[0].reranker_used if retrievals else "none",
        search_type="merged",
    )
```

### Update `src/rag_pipeline/agentic_service.py` to use the shared helper

Find `AgenticRAGService._merge_retrievals` (around line 411). Replace its body to delegate to the shared function:

```python
    def _merge_retrievals(self, retrievals: List[RetrievalResult]) -> RetrievalResult:
        """Merge multiple RetrievalResults. Phase 12: uses shared helper."""
        try:
            from .retrieval_utils import merge_retrieval_results
        except ImportError:
            from retrieval_utils import merge_retrieval_results
        return merge_retrieval_results(retrievals)
```

This keeps the public method on `AgenticRAGService` for backward-compat (the streaming wrapper calls it via `rag.agentic_service._merge_retrievals`), but the actual logic is now shared.

### Refactor `ask_comparative()` in `rag_service.py`

This is the meat of the carry-over fix. The current method (around line 1655-1762) builds context manually by string concatenation. We rewrite it to:

1. Optionally narrow report selection via entity graph
2. Run per-report retrieval producing `RetrievalResult` objects
3. Merge them via shared helper
4. Run groundedness on the merged result

Find `ask_comparative()` and replace the entire method body. Here is the new implementation:

```python
    def ask_comparative(
        self,
        question: str,
        report_ids: List[str],
        top_k_per_report: int = 5,
        compare_years: bool = True,
        style: ResponseStyle = ResponseStyle.ADAPTIVE,
    ) -> RAGResponse:
        """
        Cross-report comparative query.

        Phase 12 changes:
        - Optionally narrows report_ids using entity graph (if entity_graph.enabled
          and enable_comparative_filtering=True and query mentions a known entity)
        - Builds per-report RetrievalResult objects, then merges via
          retrieval_utils.merge_retrieval_results
        - Runs groundedness verification on the merged result
        """
        from .retrieval_utils import merge_retrieval_results

        logger.info(f"Comparative query across {len(report_ids)} reports: '{question}'")

        # ---- Phase 12: optionally narrow report set via entity graph ----
        narrowed_report_ids = list(report_ids)
        entity_filter_applied = False

        if (
            self.config.entity_graph.enabled
            and self.config.entity_graph.enable_comparative_filtering
        ):
            try:
                from src.entity_graph.entity_service import get_entity_service
            except ImportError:
                from entity_graph.entity_service import get_entity_service

            entity_service = get_entity_service()
            if entity_service:
                matched = entity_service.extract_entities_from_query(question)
                if matched:
                    # Union of reports that mention ANY of the matched entities,
                    # intersected with original report_ids
                    candidate_reports: set = set()
                    for ent in matched:
                        candidate_reports.update(
                            entity_service.get_reports_for_entity(ent["id"])
                        )
                    intersected = [r for r in report_ids if r in candidate_reports]
                    if intersected:
                        narrowed_report_ids = intersected
                        entity_filter_applied = True
                        logger.info(
                            f"Entity-graph narrowing: {len(report_ids)} → "
                            f"{len(intersected)} reports (matched: "
                            f"{[e['canonical_name'] for e in matched]})"
                        )
                    else:
                        logger.info(
                            f"Entity match found ({[e['canonical_name'] for e in matched]}) "
                            f"but no reports in series mention them; "
                            f"falling back to original report_ids"
                        )

        # ---- Per-report retrieval ----
        per_report_retrievals: List[RetrievalResult] = []
        years_covered: set = set()

        for report_id in narrowed_report_ids:
            try:
                report_filter = {"report_id": report_id}
                result = self.retrieval.retrieve(
                    question,
                    top_k=top_k_per_report,
                    filters=report_filter,
                    enhancement=None,  # comparative doesn't need expansion
                )
                if result.total_after_rerank > 0:
                    per_report_retrievals.append(result)
                    # Track years for prompt context
                    for parent in result.parents:
                        for child in parent.children:
                            if child.report_year:
                                years_covered.add(str(child.report_year))
            except Exception as e:
                logger.warning(f"Comparative retrieval failed for {report_id}: {e}")
                continue

        if not per_report_retrievals:
            return RAGResponse(
                query=question,
                answer="No relevant information found in the specified reports.",
                citations=[],
                sources_used=0,
                context_length=0,
                reranker_used="none",
                search_type="comparative_empty",
                model_used=self._get_model_name(),
                groundedness=None,
                agentic_trace=None,
            )

        # ---- Merge into single RetrievalResult ----
        merged = merge_retrieval_results(per_report_retrievals)

        # ---- Build context string ----
        context = merged.to_context_string(
            include_neighbors=False,  # Cross-report comparison: skip neighbors for clarity
            include_semantic_tags=True,
        )

        years_str = (
            ", ".join(sorted(years_covered)) if years_covered else "multiple years"
        )

        # ---- Generate ----
        system_prompt = TIME_SERIES_SYSTEM_PROMPT
        user_prompt = TIME_SERIES_QUERY_TEMPLATE.format(
            context=context,
            question=question,
            years=years_str,
        )
        user_prompt += (
            f"\n\n📌 REMINDER: You have data from these years: {years_str}. "
            f"Include year in every citation."
        )

        if self.config.llm.provider == LLMProvider.CLAUDE:
            answer = self._generate_claude(user_prompt, system_prompt)
        elif self.config.llm.provider == LLMProvider.GEMINI:
            answer = self._generate_gemini(user_prompt, system_prompt)
        else:
            answer = self._generate_openai(user_prompt, system_prompt)

        # ---- Phase 13: groundedness verification on merged result ----
        groundedness_dict = None
        if self.groundedness_service:
            try:
                report = self.groundedness_service.verify(answer, merged)
                groundedness_dict = report.to_dict()
                if (
                    not report.verified
                    and self.config.groundedness.block_on_failure
                ):
                    gcaveat = (
                        f"⚠️ **Groundedness check**: Only {report.num_grounded} of "
                        f"{report.num_claims} factual claims could be verified "
                        f"against the retrieved sources. Treat with caution.\n\n"
                    )
                    answer = gcaveat + answer
            except Exception as e:
                logger.warning(f"Comparative groundedness failed: {e}")

        # ---- Build citations from merged result ----
        citations = self.build_citations(merged)

        return RAGResponse(
            query=question,
            answer=answer,
            citations=citations,
            sources_used=merged.total_after_rerank,
            context_length=len(context),
            reranker_used=merged.reranker_used,
            search_type="comparative",
            model_used=self._get_model_name(),
            groundedness=groundedness_dict,
            agentic_trace=(
                {"entity_filter_applied": entity_filter_applied,
                 "narrowed_from": len(report_ids),
                 "narrowed_to": len(narrowed_report_ids)}
                if entity_filter_applied
                else None
            ),
        )
```

A note about `agentic_trace` here: I'm reusing that field to signal "entity filter narrowed your comparative" rather than introducing a new field. Acceptable because the field is `Optional[Dict[str, Any]]` — it just carries different shapes for different paths. If you want stricter typing, add a separate `comparative_metadata` field on `RAGResponse` instead.

---

## Step 8: Integration

### `src/entity_graph/cli.py` (NEW)

Operator CLI for everything entity-graph related:

```python
"""
Entity graph CLI.

Usage:
    python -m src.entity_graph.cli init-db
    python -m src.entity_graph.cli canonicalize [--overviews-dir DIR]
    python -m src.entity_graph.cli index [--processed-dir DIR]
    python -m src.entity_graph.cli index-report --file PATH
    python -m src.entity_graph.cli stats
"""

import argparse
import json
import logging
from pathlib import Path

from sqlalchemy import func

from .canonicalizer import canonicalize_all
from .mention_indexer import index_all, index_report
from .db import init_db, session_scope
from .models import Entity, EntityMention

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def cmd_init_db(args):
    init_db()
    print("✅ Schema created (or verified)")


def cmd_canonicalize(args):
    init_db()
    overviews_dir = Path(args.overviews_dir)
    output_path = Path(args.output) if args.output else Path("data/entity_graph/canonical_entities.json")
    entities = canonicalize_all(
        overviews_dir=overviews_dir,
        output_path=output_path,
        model=args.model,
        batch_size=args.batch_size,
    )
    print(f"✅ Canonicalized {len(entities)} entities")
    print(f"   Output: {output_path}")


def cmd_index(args):
    init_db()
    total = index_all(Path(args.processed_dir))
    print(f"✅ Indexed {total} mentions across the corpus")


def cmd_index_report(args):
    init_db()
    count = index_report(Path(args.file))
    print(f"✅ Indexed {count} mentions from {args.file}")


def cmd_stats(args):
    init_db()
    with session_scope() as session:
        num_entities = session.query(Entity).count()
        num_mentions = session.query(EntityMention).count()
        by_type = dict(
            session.query(Entity.entity_type, func.count(Entity.id))
            .group_by(Entity.entity_type)
            .all()
        )
        by_tier = dict(
            session.query(Entity.primary_tier, func.count(Entity.id))
            .group_by(Entity.primary_tier)
            .all()
        )
        top10 = (
            session.query(Entity.canonical_name, Entity.mention_count, Entity.entity_type)
            .order_by(Entity.mention_count.desc())
            .limit(10)
            .all()
        )

    print(f"Entities: {num_entities}")
    print(f"Mentions: {num_mentions}")
    print(f"By type: {json.dumps(by_type, indent=2)}")
    print(f"By tier: {json.dumps(by_tier, indent=2)}")
    print("Top 10 most-mentioned entities:")
    for name, count, etype in top10:
        print(f"  {count:>6}  ({etype:<20})  {name}")


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init-db", help="Create schema if missing")
    p_init.set_defaults(func=cmd_init_db)

    p_can = sub.add_parser("canonicalize", help="Run cross-corpus canonicalization")
    p_can.add_argument("--overviews-dir", default="data/batch_jobs/overviews")
    p_can.add_argument("--output", default=None)
    p_can.add_argument("--model", default="gpt-4o-mini")
    p_can.add_argument("--batch-size", type=int, default=80)
    p_can.set_defaults(func=cmd_can_can if False else cmd_canonicalize)

    p_idx = sub.add_parser("index", help="Index all reports' mentions")
    p_idx.add_argument("--processed-dir", default="data/processed")
    p_idx.set_defaults(func=cmd_index)

    p_one = sub.add_parser("index-report", help="Index one report's mentions")
    p_one.add_argument("--file", required=True)
    p_one.set_defaults(func=cmd_index_report)

    p_stats = sub.add_parser("stats", help="Print entity graph statistics")
    p_stats.set_defaults(func=cmd_stats)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
```

### Optional: auto-index hook in `indexer.py`

In `src/rag_pipeline/indexer.py`, the existing `Indexer.index_file()` method handles ingestion of one report into Qdrant. We add an opt-in hook to also write entity mentions:

Find the end of `index_file()` (around the return statement):

```python
        return {
            "report_id": report_id,
            "children": children_indexed,
            "parents": parents_indexed,
            "has_enrichment": semantic_enrichment is not None,
        }
```

Replace with:

```python
        # Phase 12: Optionally index entity mentions
        if (
            self.config.entity_graph.enabled
            and self.config.entity_graph.auto_index_on_ingest
        ):
            try:
                try:
                    from src.entity_graph.mention_indexer import index_report
                except ImportError:
                    from entity_graph.mention_indexer import index_report

                mentions = index_report(json_path)
                logger.info(f"  Entity mentions indexed: {mentions}")
            except Exception as e:
                # Non-fatal: chunk indexing succeeded; entity indexing failed
                logger.warning(f"Entity mention indexing failed for {json_path.name}: {e}")

        return {
            "report_id": report_id,
            "children": children_indexed,
            "parents": parents_indexed,
            "has_enrichment": semantic_enrichment is not None,
        }
```

This means: when you re-index Qdrant, mentions update automatically — assuming canonicalization has already run at least once. New reports work fine because mention indexing is idempotent (deletes-then-inserts per report).

### Optional: agentic loop hint

Already supported via `AgenticRAGService._decompose`'s `report_filter_hint` field (currently TODO'd in the code). When you're ready, you can wire up similar logic to what we wrote for `ask_comparative()`. Out of scope for Phase 12 itself — flag as a future improvement.

---

## Configuration, ops, testing, rollout

### `.env` additions

```
# Phase 12: Entity Graph
ENTITY_GRAPH_DSN=postgresql+psycopg://cag_user:secret@localhost:5432/cag_entity_graph
```

### One-time setup runbook

```bash
# 1. Install new dependencies (after updating pyproject.toml)
poetry install
poetry export --only main -o requirements.docker.txt

# 2. Create Postgres DB + user (one-time)
sudo -u postgres psql -c "CREATE USER cag_user WITH PASSWORD 'secret';"
sudo -u postgres psql -c "CREATE DATABASE cag_entity_graph OWNER cag_user;"

# 3. Set env var (.env file)
echo "ENTITY_GRAPH_DSN=postgresql+psycopg://cag_user:secret@localhost:5432/cag_entity_graph" >> .env

# 4. Initialize schema
python -m src.entity_graph.cli init-db

# 5. Re-run overview batch on existing reports to get normalized_entities
# (assumes you have an existing batch entry point for this; if not, adapt)
python -c "
from pathlib import Path
from src.batch_pipeline.batch_service import BatchService
service = BatchService()
files = list(Path('data/processed').glob('**/*_chunks.json'))
batch_id = service.submit_overview_batch(files)
print(f'Submitted: {batch_id} — wait ~24h for batch completion')
"

# 6. After batch completes, process and merge results
python -m src.batch_pipeline.process_results

# 7. Run cross-corpus canonicalization
python -m src.entity_graph.cli canonicalize

# 8. Index mentions
python -m src.entity_graph.cli index

# 9. Verify
python -m src.entity_graph.cli stats
# Expect ~500-1500 entities, ~10k-50k mentions for your current corpus
```

### Incremental flow when new reports arrive

```bash
# 1. New reports parsed into chunks.json
# 2. Run overview batch on just the new reports (existing flow)
# 3. After overview merge, re-run canonicalize (it's a full re-run, but mostly bucket-cached)
python -m src.entity_graph.cli canonicalize

# 4. Index just the new reports
python -m src.entity_graph.cli index-report --file data/processed/union/NEW_REPORT_chunks.json
# OR re-index everything (cheap, idempotent)
python -m src.entity_graph.cli index
```

### Feature flag matrix

| Stage | `entity_graph.enabled` | `enable_comparative_filtering` | `auto_index_on_ingest` |
|-------|-----------------------|-------------------------------|------------------------|
| Dev / first canonicalization | True | False | False |
| After canonicalization done | True | False | True |
| Production rollout | True | True | True |

### Tests

Create `tests/entity_graph/` with:

#### `tests/entity_graph/conftest.py`

```python
import os
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.entity_graph.models import Base


@pytest.fixture(scope="function")
def test_db(monkeypatch):
    """In-memory SQLite for unit tests (Postgres-compatible SQL only)."""
    os.environ["ENTITY_GRAPH_DSN"] = "sqlite:///:memory:"
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    yield SessionLocal()
```

(Note: tests use SQLite in-memory because it's free and fast. Production uses Postgres. The SQL we write is portable across both.)

#### `tests/entity_graph/test_canonicalizer.py`

Test cases:
1. `pre_bucket` groups records with same lowercase canonical
2. `collapse_buckets` merges aliases and picks longest canonical
3. `_final_alias_merge` collapses cross-batch overlaps
4. End-to-end with mocked OpenAI client

#### `tests/entity_graph/test_mention_indexer.py`

Test cases:
1. `AliasResolver` resolves an alias to entity ID
2. `index_report` populates EntityMention rows correctly from a fixture chunks.json
3. Re-indexing the same report is idempotent (delete-before-insert)
4. Co-occurrence relations created for findings with multiple entities

#### `tests/entity_graph/test_entity_service.py`

Test cases:
1. `search_entities` matches by alias substring
2. `get_mentions` filters work
3. `get_related_entities` returns top co-occurring
4. `extract_entities_from_query` extracts known entities from a query string

#### `tests/rag_pipeline/test_ask_comparative.py`

Test cases (this is for the refactor):
1. Comparative with empty retrievals returns the empty-state response
2. Comparative with mocked retrievals returns merged response with citations
3. Groundedness runs on merged result when service is set
4. Entity-filtering narrows report_ids when query mentions a known entity (mock entity_service)
5. Entity-filtering falls back to original report_ids when no reports match

### Rollout plan

| Week | Action |
|------|--------|
| 1 | Dependency add, schema setup, modify overview prompt, run batch on 1 test report, verify normalized_entities populated |
| 2 | Re-run overview batch on full corpus (assumes ~24h Anthropic batch turnaround) |
| 3 | Run canonicalize + index. Manually inspect canonical_entities.json — does "NHAI" merge correctly? Does "Min. of Railways" + "Ministry of Railways" merge? Tune prompt if needed and re-run |
| 4 | Enable `entity_graph.enabled = True` in dev; smoke-test `/api/entities/*` endpoints |
| 5 | Refactor `ask_comparative()` (Step 7); test against existing time-series queries; verify groundedness now runs |
| 6 | Enable `enable_comparative_filtering = True`; A/B test queries with and without entity narrowing |
| 7 | Production rollout |

### Files created (10)

- `src/entity_graph/__init__.py`
- `src/entity_graph/db.py`
- `src/entity_graph/models.py`
- `src/entity_graph/canonicalizer.py`
- `src/entity_graph/mention_indexer.py`
- `src/entity_graph/entity_service.py`
- `src/entity_graph/cli.py`
- `src/api/routes/entities.py`
- `src/rag_pipeline/retrieval_utils.py`
- `docs/entity_graph_setup.md`

### Files modified (8)

- `pyproject.toml` (3 new deps)
- `src/batch_pipeline/prompts/overview_extraction.py` (add 5th output field)
- `src/batch_pipeline/merge_utils.py` (1-line list extension)
- `src/batch_pipeline/batch_service.py` (max_tokens bump)
- `src/core/config.py` (new EntityGraphConfig + RAGConfig field + validate())
- `src/api/main.py` (register entities router + lifespan logging)
- `src/rag_pipeline/agentic_service.py` (delegate `_merge_retrievals` to shared helper)
- `src/rag_pipeline/rag_service.py` (rewrite `ask_comparative()`)
- `src/rag_pipeline/indexer.py` (optional auto-index hook)

### Total scope

**~6-8 engineering days** including tests, plus the wall-clock time for the overview batch re-run (~24-48h Anthropic batch latency) and one-off canonicalization (~30 minutes including manual inspection).

The two long pole items are:
1. Anthropic overview batch re-run on the full corpus (mostly waiting)
2. Manual review of `canonical_entities.json` after the first canonicalize run — fix obvious miss-merges and re-run if necessary

After Phase 12, you have:
- Frontend can build entity-centric UI ("Show me everything about NHAI")
- Time-series queries scoped to specific entities ("Compare NHAI findings 2022-2025")
- Groundedness coverage for the comparative path
- A foundation for Phase 14 (if you ever do it: entity graph as a tool inside the agentic loop)
