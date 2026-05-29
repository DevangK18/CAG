# CAG-GATEWAY RAG Pipeline: Complete Reference (Phases 11–13 + Bridge Phase)

**Project**: CAG-GATEWAY — RAG over Indian CAG audit reports
**Period covered**: April 2026
**Baseline**: RAG Pipeline v3.2 (hybrid search + Cohere reranking + query enhancement)
**Final state**: Production-grade modern RAG with agentic retrieval, cross-report entity graph, groundedness verification, auto-filtering, and full observability

This is the canonical reference for everything built in this period. Use it for onboarding, debugging, ops, and as input when planning future phases.

---

## Table of Contents

1. [Why these phases existed](#1-why-these-phases-existed)
2. [Shipping order and the actual story](#2-shipping-order-and-the-actual-story)
3. [Phase 13: Groundedness Verification](#3-phase-13-groundedness-verification)
4. [Phase 11: Agentic Retrieval Loop](#4-phase-11-agentic-retrieval-loop)
5. [Phase 12: Cross-Report Entity Graph](#5-phase-12-cross-report-entity-graph)
6. [Bridge Phase: A, B, C, D](#6-bridge-phase-a-b-c-d)
7. [How everything fits together](#7-how-everything-fits-together)
8. [Configuration and feature flags](#8-configuration-and-feature-flags)
9. [Observability — what's recorded where](#9-observability--whats-recorded-where)
10. [Postgres setup, usage, and operations](#10-postgres-setup-usage-and-operations)
11. [Production deployment and migration](#11-production-deployment-and-migration)
12. [Known limitations and follow-ups](#12-known-limitations-and-follow-ups)
13. [Lessons learned](#13-lessons-learned)
14. [File index](#14-file-index)

---

## 1. Why these phases existed

Before this work began, the system was already past "naive RAG." It had hybrid BM25+vector search, Cohere reranking, multi-query expansion, query classification via `QueryEnhancer`, hierarchy-aware reranking, sufficiency checks, and passage reordering. About 85–90% of what people mean by "Modern RAG."

The remaining 10–15% gap was three things, plus operational rigor:

1. **No iterative reasoning.** Every query made exactly one retrieval pass. Multi-hop questions like "What caused toll delays AND what was the financial impact?" produced shallow answers.

2. **No cross-report entity reasoning.** Vector search alone can't reliably answer "Show me all NHAI findings across 2022–2025." Entities mentioned under different names ("NHAI", "National Highways Authority", "Nhai") were treated as different things.

3. **No answer verification.** The LLM could hallucinate a ₹500 crore figure when the source said ₹124 crore. Citations existed but their accuracy wasn't checked.

4. **No production observability.** No way to know if retrieval got worse, if certain query types failed, what costs were trending, or what the agentic loop was actually doing.

These four gaps map to Phases 11, 12, 13, and the Bridge Phase (which split into A/B/C/D).

---

## 2. Shipping order and the actual story

The phases were specced in numerical order but **shipped differently**, and there were many bug-fix cycles along the way. Here's how it actually played out:

| Phase | Specced | Shipped | Why this order |
|-------|---------|---------|----------------|
| 13 (Groundedness) | 3rd | **1st** | Smallest scope. Provides observation data. Lowest risk. |
| 11 (Agentic) | 1st | **2nd** | Builds on existing infra. Generalizes the comparative pattern. |
| 12 (Entity Graph) | 2nd | **3rd** | Largest. Required several rounds to get canonicalization right. |
| Bridge A (auto-filter) | — | **4th** | Cheapest precision win for home page queries. |
| Bridge D (comparative cap) | — | **5th** | Surgical, half-day work. |
| Bridge C (observability) | — | **6th** | Required 3 review cycles before working correctly. |
| Bridge B (two-pass canonicalization) | — | **7th** | Built dormant; activates at scale. |

Phase 12 alone went through **three rounds of fixes** (cross-state contamination, empty-batch silent drops, mention coverage gap). Bridge C went through three review cycles before observability actually captured data correctly. The iteration mattered — every round caught a real bug.

---

## 3. Phase 13: Groundedness Verification

### What it does

After the LLM generates an answer, a separate LLM call (gpt-4o-mini) verifies each factual claim against the retrieved context. Output: a per-claim grounding report with overall pass/fail score.

### Architecture

```
RAGService.ask()
    ├─ retrieve()                      (existing)
    ├─ _generate_answer()               (existing)
    ├─ groundedness_service.verify(answer, retrieval_result)   ← NEW
    │   └─ Single LLM call. Returns claim list with grounded:bool per claim.
    └─ return RAGResponse(..., groundedness=report.to_dict())

streaming_wrapper.generate_stream()
    ├─ stream tokens, accumulate full_answer
    ├─ _maybe_verify_groundedness(rag, full_answer, retrieval_result, loop)
    │   └─ Runs verification in thread pool
    └─ yield {"type": "groundedness", "data": ...}
```

### Why this design

- **LLM-judge over NLI**: zero new infrastructure, reuses existing OpenAI/Anthropic/Gemini clients
- **Fail-open**: if verification itself errors, the answer still ships
- **Streams as final event**: emitted between last `token` and `done`, so frontend can show ✓/⚠ without delaying tokens

### Files

- **Created**: `src/rag_pipeline/groundedness_service.py`
- **Modified**: `src/core/config.py` (GroundednessConfig), `src/rag_pipeline/models.py`, `src/rag_pipeline/rag_service.py`, `src/api/models.py`, `src/api/services/streaming_wrapper.py`

### Output shape

```json
{
  "verified": true,
  "overall_score": 0.85,
  "num_claims": 7,
  "num_grounded": 6,
  "num_ungrounded": 1,
  "claims": [
    {
      "claim_text": "₹124.18 crore loss at Nathavalasa toll plaza",
      "cited_source": "Section 3.2.1, p.36",
      "grounded": true,
      "confidence": 0.95,
      "reason": "Exact figure appears in cited source"
    }
  ],
  "provider_used": "openai"
}
```

### Cost & latency

- **Cost**: ~$0.0005/query (gpt-4o-mini, ~1500 input tokens, ~500 output)
- **Latency**: +200–400ms (thread-pooled, doesn't block token streaming)

---

## 4. Phase 11: Agentic Retrieval Loop

### What it does

Adds a parallel `/chat/agentic` endpoint that:
1. Classifies query complexity (simple / multi-hop / cross-report) via a planner LLM call
2. Decomposes complex queries into 2–4 sub-queries
3. For each sub-query: retrieves → checks sufficiency → reformulates and retries up to 3x
4. Merges all sub-query results into one `RetrievalResult`
5. Synthesizes a unified answer with citations preserved

Simple queries short-circuit to the existing `RAGService.ask()` path. **No regression for 70–80% of queries.**

### Architecture

```
POST /chat/agentic/stream
    │
    ▼
AgenticRAGService.ask()
    │
    ├─ _decompose(query)              ← Planner LLM call (gpt-4o-mini)
    │   returns {complexity, sub_queries, report_filter_hint}
    │
    ├─ if complexity == "simple":
    │       return rag.ask(...)        ← short-circuit
    │
    ├─ for sub_query in plan.sub_queries:
    │       sub_result = _run_subquery_loop(sub_query, ...)
    │           └─ for iteration in range(max_iterations_per_subquery=3):
    │                   result = rag.retrieval.retrieve(current_query, ...)
    │                   if rag._check_context_sufficiency(result):
    │                       break
    │                   current_query = _reformulate(...)
    │
    ├─ merged = merge_retrieval_results(sub_query_retrievals)
    ├─ answer = _synthesize_answer(question, sub_queries, merged)
    ├─ groundedness = rag.groundedness_service.verify(answer, merged)
    │
    └─ return RAGResponse(..., agentic_trace=trace.to_dict())
```

### Why this design

- **Composes, doesn't extend.** `AgenticRAGService` takes `RAGService` as a dependency. Clean separation, easy to A/B test.
- **Separate endpoint, not router-inside-/chat.** Existing `/chat` stays byte-identical.
- **Hard caps everywhere**: max iterations per sub-query, max sub-queries, token budget, wall-clock timeout. Prevents runaway loops.
- **Reuses existing infra**: `retrieve()`, `_check_context_sufficiency()`, `build_citations()` all reused.

### Files

- **Created**: `src/rag_pipeline/agentic_service.py`, `src/rag_pipeline/retrieval_utils.py`
- **Modified**: `src/core/config.py` (AgenticConfig), `src/rag_pipeline/models.py`, `src/rag_pipeline/rag_service.py`, `src/api/routes/chat.py`, `src/api/services/streaming_wrapper.py`, `src/api/models.py`, `frontend/lib/api.ts`, `frontend/hooks/useChatStream.ts`

### Streaming events emitted

| Event type | When | Payload |
|------------|------|---------|
| `planning` | After `_decompose` returns | `{complexity, sub_queries, reason}` |
| `sub_query` | Before each sub-query loop | `{index, query, total}` |
| `iteration` | After each loop completes | `{sub_index, iterations, sufficient, num_chunks}` |
| `reformulation` | When query rewritten | `{sub_index, new_query}` |
| `citation_map` | After merge | (same shape as regular path) |
| `synthesizing` | Just before token streaming | `null` |
| `token` | Each LLM token | string |
| `groundedness` | After token stream | (Phase 13 shape) |
| `agentic_trace` | Just before done | full trace object |
| `done` | End | `null` |

### Cost & latency

- **Simple queries**: unchanged — short-circuited
- **Multi-hop queries**: +5–12s latency, +$0.01–0.03 per query
- **Hard limits**: 3 iterations/sub-query, 4 sub-queries max, 30k token budget, 20s wall-clock

### Important note on planner

The planner is **hard-wired to OpenAI** (`gpt-4o-mini`). If your main LLM is Claude or Gemini, agentic mode requires `OPENAI_API_KEY`. Acceptable trade-off ($0.0002/call) but worth noting for ops.

---

## 5. Phase 12: Cross-Report Entity Graph

### What it does

A Postgres-backed knowledge graph tracking every entity (ministry, PSU, scheme, state government, local body, etc.) mentioned across the corpus. Three tables:

- `entities` — canonical entities with aliases and metadata
- `entity_mentions` — every occurrence of an entity in chunks/findings/recommendations, linked back to source
- `entity_relations` — co-occurrence edges within findings (sparse)

Plus an HTTP API at `/api/entities/*` for the frontend, and integration into `ask_comparative()` for entity-aware narrowing.

### Why this design

- **Hybrid canonicalization**: per-report normalization piggybacks on the existing overview batch (zero new per-report LLM cost). Cross-corpus dedup is a separate explicit CLI command.
- **Postgres, not Neo4j**: graph is small (~400 entities, ~25k mentions). Postgres handles it trivially.
- **Aho-Corasick mention scanning**: catches mentions in chunk text regardless of whether `entities_mentioned` was pre-populated. ~119× more mentions than relying on chunk metadata alone.
- **Idempotent indexing**: re-indexing a report DELETES existing mentions for that report first. Safe to re-run.

### Three-stage pipeline

```
Stage 1: PER-REPORT NORMALIZATION (in existing batch pipeline)
─────────────────────────────────────────────────────────────
Anthropic overview batch already extracted: audit_scope, audit_objectives,
topics, glossary. NEW 5th field added: normalized_entities.

Each entity record:
{
  canonical_form_in_report: "National Highways Authority of India",
  entity_type: "psu",
  aliases_seen: ["NHAI", "National Highway Authority", ...],
  first_seen_page: 12,
  tier_context: "union"
}

Output: data/batch_jobs/overviews/{report_id}_overview_llm.json


Stage 2: CROSS-CORPUS CANONICALIZATION (explicit CLI step)
─────────────────────────────────────────────────────────────
Operator runs: python -m src.entity_graph.cli canonicalize --reset

  1. collect_normalized_entities()  → flat list
  2. pre_bucket()                   → group by lowercase canonical
  3. collapse_buckets()             → consolidate aliases
  4. canonicalize_via_llm()         → batch through gpt-4o-mini in chunks of 80
  5. (If raw count > two_pass_threshold) pass2_dedup_via_llm()  ← Bridge B
  6. _scrub_generic_aliases()       → strip "State", "Department", etc.
  7. load_canonical_to_db()         → upsert into Postgres

Output: data/entity_graph/canonical_entities.json + Postgres entities table


Stage 3: MENTION INDEXING (idempotent)
─────────────────────────────────────────────────────────────
Operator runs: python -m src.entity_graph.cli index

For each *_chunks.json:
  1. Extract from semantic_enrichment.findings.entities_mentioned
  2. Extract from semantic_enrichment.recommendations.target_entity
  3. Extract from per-chunk entities_mentioned
  4. Aho-Corasick scan of every chunk's content for canonical aliases
  5. Resolve each mention to canonical entity_id via AliasResolver
  6. Insert EntityMention rows
  7. Build co-occurrence EntityRelations within findings

Output: ~25k mentions across 37 reports (~700 avg per report)
```

### Database schema

```sql
-- Database: cag_entity_graph

CREATE TABLE entities (
    id BIGSERIAL PRIMARY KEY,
    canonical_name TEXT UNIQUE NOT NULL,
    entity_type TEXT NOT NULL,           -- ministry|psu|scheme|state_government|...
    aliases JSONB NOT NULL,              -- ["NHAI", "National Highways Authority"]
    primary_tier TEXT,                   -- union|state|local_body
    first_seen_year INTEGER,
    last_seen_year INTEGER,
    mention_count INTEGER DEFAULT 0,
    finding_count INTEGER DEFAULT 0,
    report_count INTEGER DEFAULT 0
);

CREATE TABLE entity_mentions (
    id BIGSERIAL PRIMARY KEY,
    entity_id BIGINT REFERENCES entities(id),
    report_id TEXT NOT NULL,
    chunk_id TEXT,
    finding_id TEXT,
    recommendation_id TEXT,
    mention_text TEXT,
    page INTEGER,
    finding_type TEXT,
    severity TEXT,
    amount_crore NUMERIC,
    audit_year TEXT,
    government_body_type TEXT,
    state_name TEXT
);

CREATE TABLE entity_relations (
    id BIGSERIAL PRIMARY KEY,
    source_entity_id BIGINT REFERENCES entities(id),
    target_entity_id BIGINT REFERENCES entities(id),
    relation_type TEXT,
    report_id TEXT,
    finding_id TEXT,
    confidence REAL,
    UNIQUE (source_entity_id, target_entity_id, relation_type, finding_id)
);

-- Indexes on entity_mentions
CREATE INDEX ON entity_mentions(entity_id);
CREATE INDEX ON entity_mentions(report_id);
CREATE INDEX ON entity_mentions(audit_year);
CREATE INDEX ON entity_mentions(finding_type);
```

### Files

- **Created**: `src/entity_graph/` package (`__init__.py`, `db.py`, `models.py`, `canonicalizer.py`, `mention_indexer.py`, `entity_service.py`, `cli.py`), `src/api/routes/entities.py`, `docs/entity_graph_setup.md`
- **Modified**: `pyproject.toml`, `src/batch_pipeline/prompts/overview_extraction.py`, `src/batch_pipeline/merge_utils.py`, `src/batch_pipeline/batch_service.py`, `src/core/config.py`, `src/api/main.py`, `src/rag_pipeline/agentic_service.py`, `src/rag_pipeline/rag_service.py`, `src/rag_pipeline/indexer.py`

### HTTP API

```
GET  /api/entities/search?q=NHAI&entity_type=psu&primary_tier=union&limit=10
GET  /api/entities/{id}
GET  /api/entities/{id}/mentions?finding_type=loss_of_revenue&audit_year=2023-24
GET  /api/entities/{id}/reports
GET  /api/entities/{id}/related
GET  /api/entities/{id}/findings?min_amount_crore=10&severity=high
```

### Final stats (post-Bridge B)

```
Entities: 390 (Union 192, State 118, Local Body 80)
Mentions: 24,865 (avg 698 per report, range 116–2164)
State governments: 20 separate canonical entities, no contamination
Generic aliases: 0 entities polluted

Top 10 most-mentioned:
  1. Building and Other Construction Workers' Welfare Fund (2031)
  2. Mukhyamanthrigala Nagarothana Yojane Phase-III (1412)
  3. Income Tax Act, 1961 (1240)
  4. Steel Authority of India Limited (887)
  5. Panchayati Raj Institutions (673)
  6. National Highways Authority of India (650)
  7. Public Sector Entities (621)
  8. Ministry of Road Transport and Highways (487)
  9. Income Tax Appellate Tribunal (444)
 10. Rail Land Development Authority (430)
```

### Three rounds of fixes Phase 12 went through

1. **Cross-state contamination** — initial canonicalize merged 13 state governments into one. Fixed via `GENERIC_ALIAS_STOP_LIST`, `INDIAN_STATE_NAMES` boundary check, and `_scrub_generic_aliases` post-processing.
2. **Empty-batch silent drops** — LLM returned valid JSON with empty arrays for ~47% of batches. Fixed via fallback prompt + `_local_passthrough_conversion`.
3. **Mention coverage gap** — chunks had `entities_mentioned: None`, only 216 mentions across 37 reports. Fixed via `AliasScanner` using Aho-Corasick — jumped to 25,836 mentions (119× improvement).

---

## 6. Bridge Phase: A, B, C, D

The Bridge Phase happened between Phases 11/12/13 completion and the planned 700-report ingestion. Its purpose: harden the pipeline before scaling.

### Bridge A: Auto-filter retrieval

**Goal**: When a query mentions a year, state, ministry, sector, or government tier, automatically apply that as a Qdrant payload filter — but only when the calling context didn't already set a filter.

**Behavior matrix**:

| Calling context | Explicit filters? | Auto-filter? |
|----------------|-------------------|--------------|
| Directory chat (specific report) | `{report_id: X}` | No (already filtered) |
| Time series query | `{report_id: [...]}` | No |
| Home page chat | `{}` | YES |
| Agentic sub-query in directory context | `{report_id: X}` | No |
| Agentic sub-query in home page context | `{}` | YES |

**Detection rules** (all rule-based, no LLM call):
- Years: `\b(20\d{2})\b` → single year converts to `audit_year: "YYYY-YY+1"`, multiple → `report_year: {gte, lte}`
- States: substring match against 28 states + 8 UTs with aliases
- Tiers: union (Central, GoI, ministry of), local_body (panchayat, ULB, ATIR)
- Audit categories: performance, compliance, financial, revenue, commercial, atir

**Critical guard for short ambiguous aliases**: `up`, `mp`, `tn`, `hp`, `wb`, `jk` require ≥2 occurrences OR explicit context cue. Without this, "audit process **up** to 2023" silently filters to Uttar Pradesh.

**Files**:
- Created: `src/rag_pipeline/auto_filter.py`
- Modified: `src/core/config.py` (AutoFilterConfig), `src/rag_pipeline/rag_service.py`, `src/rag_pipeline/agentic_service.py`, `src/rag_pipeline/retrieval_utils.py` (added `merge_filters` and `has_explicit_report_filter`)

### Bridge B: Two-pass canonicalization

**Goal**: Improve canonicalization quality at scale by adding a second LLM pass over the output of pass 1.

**Activation**: Controlled by `entity_graph.two_pass_threshold` (default 1000 raw records). Below this, single-pass only. Above, two-pass automatically.

```
At 37 reports (594 records):  pass 2 SKIPPED, identical to before
At 700 reports (~11k records): pass 2 ACTIVATES, ~$10–15 cost, cleaner result
```

**How pass 2 works**: Sorts pass-1 canonicals by (entity_type, primary_tier, canonical_name) so the LLM sees similar entities together. Batches of 250. LLM returns merge pairs `[{keep_id, absorb_id, reason}]` rather than rewriting entities (safer — pass 2 can only merge, never invent).

**Cross-state guard preserved in pass 2**: Same `INDIAN_STATE_NAMES` check blocks merges between different state governments.

**Verified at 37 reports with threshold lowered to 100**: produced 3 valid merges, blocked 9 cross-state merge attempts. Final count 390 (vs 393 single-pass).

### Bridge C: Query observability

**Goal**: Capture every query (dev and prod) with full context for debugging, regression detection, and cost tracking. Postgres-backed in the same DB as entity graph.

**Schema** — 50 columns in `query_logs` table:

```sql
CREATE TABLE query_logs (
    id BIGSERIAL PRIMARY KEY,
    query_id UUID UNIQUE NOT NULL,
    parent_query_id UUID,                         -- for agentic sub-queries
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    environment VARCHAR(20) NOT NULL,             -- 'dev' / 'prod'
    interaction_mode VARCHAR(40) NOT NULL,        -- 'directory' / 'series' / 'home' / 'agentic_sub' / 'comparative'

    -- Inputs
    query_text TEXT NOT NULL,
    style VARCHAR(40),
    report_ids_filter TEXT[],
    series_id VARCHAR(100),
    explicit_filters JSONB,
    auto_filters JSONB,
    merged_filters JSONB,

    -- Enhancement & retrieval
    query_enhancement JSONB,
    retrieved_chunks JSONB,                        -- summary; full content if dev_debug
    retrieval_search_type VARCHAR(40),
    retrieval_total_candidates INTEGER,
    retrieval_total_after_rerank INTEGER,
    rerank_scores REAL[],
    context_sufficient BOOLEAN,
    reranker_used VARCHAR(40),

    -- Agentic
    agentic_complexity VARCHAR(40),
    agentic_sub_query_count INTEGER,
    agentic_total_iterations INTEGER,
    agentic_reformulation_count INTEGER,
    agentic_bail_reason VARCHAR(80),
    agentic_trace JSONB,

    -- Generation (full prompts only in dev)
    llm_provider VARCHAR(40),
    llm_model VARCHAR(80),
    llm_system_prompt TEXT,
    llm_user_prompt TEXT,
    llm_raw_response TEXT,
    final_answer TEXT,
    answer_length_chars INTEGER,
    citations_count INTEGER,

    -- Groundedness
    groundedness_score REAL,
    groundedness_verified BOOLEAN,
    groundedness_num_claims INTEGER,
    groundedness_num_grounded INTEGER,
    groundedness_report JSONB,

    -- Cost & latency
    token_usage_prompt INTEGER,
    token_usage_completion INTEGER,
    token_usage_total INTEGER,
    cost_estimate_usd NUMERIC(10, 6),
    latency_total_ms INTEGER,
    latency_breakdown_ms JSONB,

    -- Status
    success BOOLEAN NOT NULL,
    error_message TEXT,

    -- Session
    client_session_id VARCHAR(100),
    user_agent TEXT
);
```

**Context manager pattern**: A single `with self.query_logger.start_query(...) as ctx:` block wraps each query. Code calls `ctx.record_*()` at appropriate points. Single source of truth for what gets logged.

**Async writes**: Fire-and-forget via `asyncio.create_task(asyncio.to_thread(_sync_write))`. DB hiccups never block the response.

**Dev vs prod**: `dev_debug=True` captures full LLM prompts and full chunk content. Production strips these to save space.

**Files**:
- Created: `src/observability/__init__.py`, `src/observability/models.py`, `src/observability/query_logger.py`, `src/observability/cost_calculator.py`
- Modified: `src/core/config.py` (ObservabilityConfig), `src/api/main.py`, `src/rag_pipeline/rag_service.py`, `src/rag_pipeline/agentic_service.py`, `src/api/services/streaming_wrapper.py`

### Bridge D: Comparative breadth cap

**Goal**: Cap the number of reports `ask_comparative()` runs per-report retrieval against, with smart selection.

**Default**: `entity_graph.comparative_max_reports = 20`

**Smart selection logic** when narrowed_report_ids exceeds cap:
1. If matched entities exist: sort by sum of entity mention counts in each report
2. Else if query mentions years: sort by year proximity to mentioned years
3. Else: sort by `report_year` descending (most recent first)

Always logs: `"Capped narrowed reports {original_count} → {cap}"` so you can audit what was excluded.

**Files**: Modified `src/core/config.py`, `src/rag_pipeline/rag_service.py` (added `_smart_select_reports()`)

---

## 7. How everything fits together

### The full query flow (home page chat with agentic mode)

```
User message → POST /api/chat/agentic/stream
                    │
                    ▼
        Lifespan-initialized: query_logger attached to rag.query_logger
                    │
                    ▼
        AgenticRAGService.ask()
        ├─ Open QueryLogContext (interaction_mode="home")
        │
        ├─ _decompose() → planning event
        │
        ├─ if simple: delegate to RAGService.ask()
        │
        ├─ for each sub_query:
        │     ├─ AutoFilterExtractor.extract()  ← Bridge A
        │     │   merges with parent filters
        │     ├─ RetrievalService.retrieve()
        │     ├─ check_sufficiency()
        │     ├─ if insufficient: reformulate, retry (max 3x)
        │     └─ ctx.record_retrieval()
        │
        ├─ merge_retrieval_results()           ← shared with comparative
        │
        ├─ _generate_answer() → stream tokens
        │   ctx.record_generation()
        │
        ├─ groundedness_service.verify()       ← Phase 13
        │   ctx.record_groundedness()
        │
        ├─ yield groundedness event
        ├─ yield agentic_trace event
        ├─ yield done event
        │
        └─ Close QueryLogContext  ← Bridge C: writes row to query_logs
```

### Mode-specific flows

**Directory chat** (`/api/chat` with explicit `report_ids: [X]`):
- AutoFilterExtractor runs but filters yield to explicit `report_id`
- `interaction_mode = "directory"` in query_logs
- Single-pass retrieval, no agentic, no entity narrowing

**Time series query** (`/api/series/{id}/query`):
- `report_ids` set to the series's reports (5–10)
- `ask_comparative()` runs per-report retrieval, merges
- Entity narrowing applies (Bridge D smart cap if > 20)
- `interaction_mode = "comparative"`

**Home page chat** (`/api/chat/agentic` or `/api/chat`):
- No `report_ids` filter
- AutoFilterExtractor extracts state/year/tier/category from query text (Bridge A)
- Agentic mode decomposes if multi-hop
- `interaction_mode = "home"` (or `"agentic_sub"` for sub-queries)

### Architecture diagram

```
                ┌──────────────────────────────────────┐
                │            USER QUERY                 │
                └──────────────────────────────────────┘
                              │
              ┌───────────────┼───────────────┐
              │               │               │
        /chat/stream    /chat/agentic    /series/{id}/query
              │               │               │
              ▼               ▼               ▼
        RAGService       AgenticRAG        RAGService
        .ask()          Service.ask()     .ask_comparative()
              │               │               │
              │               │     ┌─────────┴────────┐
              │               │     │ EntityService   │ ← Phase 12
              │               │     │ extract+narrow  │
              │               │     └─────────┬───────┘
              │               │               │
              │     ┌─────────▼─────────┐     │
              │     │ Planner (decompose)│     │ ← Phase 11
              │     └─────────┬─────────┘     │
              │               │               │
              │     ┌─────────▼─────────┐     │
              │     │ Sub-query loop    │     │
              │     │ (3x reformulation)│     │
              │     └─────────┬─────────┘     │
              │               │               │
              │     ┌─────────▼─────────┐     │
              │     │AutoFilterExtractor│     │ ← Bridge A
              │     │  (each sub-query) │     │
              │     └─────────┬─────────┘     │
              │               │               │
              │     ┌─────────▼─────────┐     │
              │     │ merge_retrieval   │◀────┘
              │     │  (shared helper)  │
              │     └─────────┬─────────┘
              │               │
              ▼               ▼
        ┌──────────────────────────────┐
        │   _generate_answer()         │
        └──────────────┬───────────────┘
                       │
        ┌──────────────▼───────────────┐
        │   GroundednessService        │ ← Phase 13
        └──────────────┬───────────────┘
                       │
        ┌──────────────▼───────────────┐
        │ QueryLogger writes row       │ ← Bridge C
        │ to query_logs table          │
        └──────────────┬───────────────┘
                       │
                       ▼
        ┌──────────────────────────────┐
        │   RAGResponse (stream/sync)  │
        └──────────────────────────────┘
```

---

## 8. Configuration and feature flags

### Feature flag matrix

| Feature | Config path | Default | Where |
|---------|------------|---------|-------|
| Groundedness verification | `groundedness.enabled` | `True` (post-activation) | `RAGConfig` |
| Block on low groundedness | `groundedness.block_on_failure` | `False` | `RAGConfig` |
| Agentic mode | `agentic.enabled` | `True` (post-activation) | `RAGConfig` |
| Entity graph | `entity_graph.enabled` | `True` (post-activation) | `RAGConfig` |
| Comparative entity narrowing | `entity_graph.enable_comparative_filtering` | `True` | `RAGConfig` |
| Two-pass canonicalization threshold | `entity_graph.two_pass_threshold` | `1000` | `RAGConfig` |
| Comparative max reports | `entity_graph.comparative_max_reports` | `20` | `RAGConfig` |
| Auto-filter | `auto_filter.enabled` | `True` | `RAGConfig` |
| Year inference | `auto_filter.allow_year_inference` | `True` | `RAGConfig` |
| Tier inference | `auto_filter.allow_tier_inference` | `True` | `RAGConfig` |
| State confidence threshold | `auto_filter.state_confidence_min_occurrences` | `1` | `RAGConfig` |
| Observability | `observability.enabled` | `True` | `RAGConfig` |
| Dev debug (full prompts/chunks) | `observability.dev_debug` | `True` | `RAGConfig` |
| Sampling rate | `observability.sampling_rate` | `1.0` | `RAGConfig` |
| Log query text | `observability.log_query_text` | `True` | `RAGConfig` |

### How to turn things off

**Disable agentic mode** (if you want to A/B test against regular `/chat`):
```python
# src/core/config.py
agentic.enabled: bool = False
```
The endpoint `/chat/agentic` returns 503; existing `/chat` is unaffected.

**Disable groundedness** (if you want to skip the +400ms latency):
```python
groundedness.enabled: bool = False
```
Streaming `groundedness` event simply isn't emitted.

**Disable entity graph entirely**:
```python
entity_graph.enabled: bool = False
```
Comparative path falls back to its old per-report retrieval without entity narrowing.

**Disable just comparative entity filtering** (keep entity API for frontend):
```python
entity_graph.enable_comparative_filtering: bool = False
```

**Disable auto-filter** (return to "report_id only" filtering):
```python
auto_filter.enabled: bool = False
```

**Disable observability** (no query_logs writes):
```python
observability.enabled: bool = False
```
Or sample down: `sampling_rate: 0.1` for 10% of queries.

**Switch to production observability mode** (strip prompts and chunk content):
```python
# .env.production
APP_ENV=prod

# src/core/config.py
observability.dev_debug: bool = False  # or controlled by APP_ENV
```

### Environment variables

```bash
# .env (Mac scripts) and .env.production (Docker app)

# Postgres for entity graph + observability
ENTITY_GRAPH_DSN=postgresql+psycopg://cag:cag_dev_pass@localhost:5433/cag_entity_graph    # .env
ENTITY_GRAPH_DSN=postgresql+psycopg://cag:cag_dev_pass@host.docker.internal:5433/cag_entity_graph  # .env.production

# Application environment (controls dev_debug behavior)
APP_ENV=dev      # or 'prod'

# Existing
OPENAI_API_KEY=...
ANTHROPIC_API_KEY=...
GOOGLE_API_KEY=...
COHERE_API_KEY=...
QDRANT_URL=...
QDRANT_API_KEY=...
```

---

## 9. Observability — what's recorded where

### What's captured per query

Every query through any path produces one row in `query_logs`. Sub-queries from agentic mode each get their own row, linked to the parent via `parent_query_id`.

**Always captured**:
- `query_id` (UUID), `parent_query_id` (for agentic sub-queries)
- `timestamp`, `environment`, `interaction_mode`
- `query_text`, `style`, `report_ids_filter`, `series_id`
- `explicit_filters`, `auto_filters`, `merged_filters`
- `query_enhancement` (question_type, expanded_queries, suggested_filters)
- `retrieved_chunks` summary (chunk_id, score, first 200 chars)
- `retrieval_total_candidates`, `retrieval_total_after_rerank`, `rerank_scores`
- `context_sufficient`, `reranker_used`
- Agentic data: `complexity`, `sub_query_count`, `total_iterations`, `bail_reason`, `trace`
- `llm_provider`, `llm_model`
- `final_answer`, `answer_length_chars`, `citations_count`
- `groundedness_score`, `groundedness_verified`, `groundedness_report`
- `latency_total_ms`, `latency_breakdown_ms` (enhancement, retrieval, generation, groundedness)
- `success`, `error_message`
- `client_session_id`, `user_agent`

**Captured only in dev mode (`dev_debug=True`)**:
- `llm_system_prompt` (full text)
- `llm_user_prompt` (full text including all chunks)
- `llm_raw_response` (full text before token streaming)
- Full chunk content in `retrieved_chunks`

**Currently NULL** (known gap, deferred fix):
- `token_usage_prompt`, `token_usage_completion`, `token_usage_total`
- `cost_estimate_usd`

LLM provider responses include token counts but `record_generation()` is currently called with `prompt_tokens=None`. Worth fixing if cost dashboards become important.

### Useful queries

```sql
-- Daily query volume by mode
SELECT DATE(timestamp), interaction_mode, COUNT(*) 
FROM query_logs
WHERE environment = 'prod' AND timestamp > NOW() - INTERVAL '30 days'
GROUP BY 1, 2 ORDER BY 1 DESC;

-- Average groundedness by interaction mode
SELECT interaction_mode, AVG(groundedness_score)::numeric(4,3), COUNT(*) 
FROM query_logs
WHERE environment = 'prod' AND groundedness_score IS NOT NULL
GROUP BY 1;

-- Slowest 100 queries (perf debugging)
SELECT query_text, latency_total_ms, agentic_complexity, retrieval_total_candidates
FROM query_logs WHERE environment = 'prod' 
ORDER BY latency_total_ms DESC LIMIT 100;

-- Queries where groundedness failed
SELECT query_text, groundedness_score, final_answer 
FROM query_logs
WHERE groundedness_verified = false 
  AND timestamp > NOW() - INTERVAL '7 days'
ORDER BY timestamp DESC LIMIT 50;

-- Auto-filter effectiveness (what filters are being inferred)
SELECT auto_filters, COUNT(*)
FROM query_logs
WHERE auto_filters IS NOT NULL AND auto_filters != '{}'::jsonb
GROUP BY 1 ORDER BY 2 DESC LIMIT 20;

-- Agentic queries that bailed
SELECT query_text, agentic_bail_reason, agentic_total_iterations 
FROM query_logs
WHERE agentic_bail_reason IS NOT NULL 
ORDER BY timestamp DESC;

-- Entity graph health
SELECT 
  (SELECT COUNT(*) FROM entities) AS entities,
  (SELECT COUNT(*) FROM entity_mentions) AS mentions,
  (SELECT COUNT(DISTINCT report_id) FROM entity_mentions) AS reports_with_mentions;
```

### What's NOT in query_logs (yet)

- Per-token cost breakdown (token counts not currently captured)
- User identity (intentional — no auth in this project)
- IP addresses (intentional privacy choice)

### Sampling for production scale

At low volume (today): `sampling_rate=1.0` — log everything. At high volume (post 700-report ingestion): consider dropping to `0.1` (10%) once you have enough baseline data. **Errors and groundedness failures should always be logged regardless of sampling.**

---

## 10. Postgres setup, usage, and operations

This section is intentionally complete because the Postgres setup proved more confusing than it should have been during development.

### Why we use Postgres

Two subsystems share one Postgres database (`cag_entity_graph`):
- **Entity graph** (Phase 12): three tables for canonical entities, mentions, relations
- **Query logs** (Bridge C): one table for observability

The choice of Postgres over Neo4j or other graph DBs was deliberate — the graph is small (~400 entities, ~25k mentions), so SQL with proper indexes handles it. One less service to run, one fewer skill stack to maintain.

### The two-DSN pattern (important)

There are **two execution contexts** that need different hostnames for the SAME Postgres instance:

| Context | What runs | Hostname needed |
|---------|-----------|-----------------|
| Mac terminal — `poetry run python -m src.entity_graph.cli ...` | Python on Mac | `localhost` |
| Mac terminal — `psql ...` | psql on Mac | `localhost` |
| Inside Docker container — API serving requests | Python in container | `host.docker.internal` |

Why: `host.docker.internal` is a Docker-only DNS name. Mac's resolver doesn't know it (unless you hack `/etc/hosts`). Containers know it because Docker Desktop injects it.

**Solution**: Two `.env` files with different `ENTITY_GRAPH_DSN` values:

```bash
# .env (used by your Mac for poetry run, scripts, psql)
ENTITY_GRAPH_DSN=postgresql+psycopg://cag:cag_dev_pass@localhost:5433/cag_entity_graph

# .env.production (used by Docker containers — see docker-compose.prod.yml: env_file)
ENTITY_GRAPH_DSN=postgresql+psycopg://cag:cag_dev_pass@host.docker.internal:5433/cag_entity_graph
```

### Local development setup (current state)

You're running Postgres as a **standalone Docker container** (`cag-postgres`), not part of `docker-compose.prod.yml`. The container maps host port `5433` → container port `5432`.

To set up from scratch on a new machine:

```bash
# 1. Pull and run Postgres
docker run -d \
  --name cag-postgres \
  -p 5433:5432 \
  -e POSTGRES_PASSWORD=admin_pass \
  -v cag_postgres_data:/var/lib/postgresql/data \
  postgres:16

# 2. Create user and database
docker exec -it cag-postgres psql -U postgres <<EOF
CREATE USER cag WITH PASSWORD 'cag_dev_pass';
CREATE DATABASE cag_entity_graph OWNER cag;
GRANT ALL PRIVILEGES ON DATABASE cag_entity_graph TO cag;
EOF

# 3. Verify
psql "postgresql://cag:cag_dev_pass@localhost:5433/cag_entity_graph" -c "SELECT 1;"
```

### Operating commands you'll run regularly

```bash
# View entity graph stats
poetry run python -m src.entity_graph.cli stats

# Re-canonicalize entities (after new reports ingested)
poetry run python -m src.entity_graph.cli canonicalize --reset

# Re-index mentions across all reports
poetry run python -m src.entity_graph.cli index

# Index a single report (after new ingestion)
poetry run python -m src.entity_graph.cli index-report --file data/processed/.../NEW_chunks.json

# Initialize tables (one-time)
poetry run python -m src.entity_graph.cli init-db

# Direct SQL access
psql "postgresql://cag:cag_dev_pass@localhost:5433/cag_entity_graph"

# Inside psql:
# \l       — list databases
# \dt      — list tables
# \d entities — describe entities table
# \q       — quit
```

### Backup and restore

**Daily backup (recommended)**:

```bash
# Save to ~/cag_backups/
mkdir -p ~/cag_backups
docker exec cag-postgres pg_dump -U cag cag_entity_graph | \
  gzip > ~/cag_backups/cag_$(date +%Y%m%d_%H%M%S).sql.gz

# Keep last 7 days only
find ~/cag_backups/ -name "cag_*.sql.gz" -mtime +7 -delete
```

Add this to a cron job for daily automated backups.

**Restore from backup**:

```bash
# Drop and recreate
docker exec -it cag-postgres psql -U postgres <<EOF
DROP DATABASE cag_entity_graph;
CREATE DATABASE cag_entity_graph OWNER cag;
EOF

# Restore
gunzip -c ~/cag_backups/cag_20260429_120000.sql.gz | \
  docker exec -i cag-postgres psql -U cag cag_entity_graph
```

### Common operational tasks

**Inspect a specific query log entry**:
```bash
psql "postgresql://cag:cag_dev_pass@localhost:5433/cag_entity_graph" \
  -c "SELECT * FROM query_logs WHERE id = 19;" \
  --expanded-output
```

**Clean up old query logs** (after they exceed disk budget):
```sql
-- Delete logs older than 90 days
DELETE FROM query_logs WHERE timestamp < NOW() - INTERVAL '90 days';
VACUUM ANALYZE query_logs;
```

**Reset entity graph** (if canonicalization gets corrupted):
```bash
# WARNING: destroys all entity data; you'll need to re-canonicalize and re-index
poetry run python -m src.entity_graph.cli canonicalize --reset
poetry run python -m src.entity_graph.cli index
```

### Connection pool sizing

In `src/entity_graph/db.py`:
- Default `pool_size=5`, `max_overflow=10`
- For low traffic (current): fine
- For higher traffic (post-700 reports): bump to `pool_size=10, max_overflow=20`

### Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `failed to resolve host 'host.docker.internal'` from Mac terminal | Using `.env.production` DSN in Mac context | Use `localhost:5433` in `.env` |
| Empty `query_logs` rows with `latency_total_ms=0` | The pre-Bridge-C-final-fix bug (already fixed) | If recurs, check `QueryLogContext.__exit__` is present |
| `entity_mentions` count drops to 0 | Someone ran `canonicalize --reset` without `index` after | Run `poetry run python -m src.entity_graph.cli index` |
| `dropped_entities.json` appears | Canonicalization batches failed | Inspect file, manually merge if needed |
| Postgres connection pool exhausted | High query volume | Bump `pool_size` in `db.py` |

---

## 11. Production deployment and migration

When you push these changes to your live website, here's what changes from local dev.

### What's different in production

1. **Postgres lives somewhere else** — not on the same host as the API container. Could be a managed service (RDS, Render, Supabase) or a self-hosted VPS Postgres
2. **`APP_ENV=prod`** instead of `dev` — this strips full LLM prompts and chunk content from query_logs to save space
3. **`dev_debug=False`** — same effect
4. **Sampling considered** — at scale, `sampling_rate=0.1` may be appropriate
5. **Backup is automated** via your hosting provider, not a manual cron

### Migration plan

#### Step 1: Provision Postgres on production

**Option A: Managed Postgres (recommended)**
- AWS RDS, Google Cloud SQL, Supabase, Render, Neon, etc.
- Get a connection string like `postgresql://user:pass@some-host.amazonaws.com:5432/cag_entity_graph`
- Configure firewall to allow connections from your production VPS or container

**Option B: Self-hosted on your VPS**
- Add Postgres to your production `docker-compose.prod.yml`:
  ```yaml
  postgres:
    image: postgres:16
    container_name: cag-postgres
    restart: unless-stopped
    environment:
      POSTGRES_USER: cag
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: cag_entity_graph
    volumes:
      - cag_postgres_data:/var/lib/postgresql/data
    networks:
      - cag-network
    # NO public port mapping — only accessible inside Docker network
  
  volumes:
    cag_postgres_data:
  ```
- DSN becomes `postgresql+psycopg://cag:${POSTGRES_PASSWORD}@postgres:5432/cag_entity_graph` (using compose service name as host)

**For 700 reports + production traffic**, managed Postgres is worth it. Better backups, monitoring, easier failover.

#### Step 2: Migrate data from local to production

```bash
# On your local Mac
docker exec cag-postgres pg_dump -U cag -Fc cag_entity_graph > cag_local_dump.dump

# Upload to production server (via scp, etc.)
scp cag_local_dump.dump user@production-server:~/

# On production server, restore to managed Postgres
pg_restore -h <prod-host> -U <prod-user> -d cag_entity_graph cag_local_dump.dump
```

**Verify after migration**:
```bash
psql "<production-DSN>" -c "
  SELECT 
    (SELECT COUNT(*) FROM entities) as entities,
    (SELECT COUNT(*) FROM entity_mentions) as mentions;
"
# Expect: ~390 entities, ~25k mentions (matching local)
```

#### Step 3: Update production environment variables

In your production `.env.production` (or whatever your prod env file is):

```bash
# Replace localhost/host.docker.internal with production Postgres host
ENTITY_GRAPH_DSN=postgresql+psycopg://cag:PROD_PASSWORD@your-prod-host:5432/cag_entity_graph

# Production environment
APP_ENV=prod

# Existing API keys, Qdrant URL, etc. (unchanged)
```

#### Step 4: Adjust config defaults for production

In `src/core/config.py` or via env overrides:

```python
@dataclass
class ObservabilityConfig:
    enabled: bool = True
    environment: str = "prod"      # not "dev"
    dev_debug: bool = False         # don't log full prompts in prod
    sampling_rate: float = 1.0      # log everything for first month
    # ... after 30 days of data: change to 0.1 (10% sampling)
```

#### Step 5: Build and deploy

```bash
docker compose -f docker-compose.prod.yml build --no-cache
docker compose -f docker-compose.prod.yml up -d
docker logs -f cag-app   # watch startup
```

Look for the success markers:
```
RAG service initialized
Entity graph engine initialized
Query observability enabled (env=prod, dev_debug=False)
```

#### Step 6: Production smoke tests

```bash
# Test the streaming endpoint
curl -N -X POST https://your-domain.com/api/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"query":"What is PRIASoft?","style":"concise"}'

# Verify the row landed in production Postgres
psql "<production-DSN>" -c "
  SELECT interaction_mode, latency_total_ms, success, environment
  FROM query_logs
  ORDER BY timestamp DESC LIMIT 5;
"
# Expect: environment='prod', latency > 0
```

#### Step 7: Set up production backups

If managed Postgres: backups are usually automatic. Verify your provider's policy.

If self-hosted: set up nightly `pg_dump` to S3 or equivalent:

```bash
#!/bin/bash
# /etc/cron.daily/postgres-backup
DATE=$(date +%Y%m%d)
docker exec cag-postgres pg_dump -U cag cag_entity_graph | \
  gzip | \
  aws s3 cp - s3://your-backup-bucket/cag/cag_${DATE}.sql.gz
```

### Production checklist

Before pushing to live:

- [ ] Production Postgres provisioned and accessible
- [ ] Local data migrated to production Postgres
- [ ] `ENTITY_GRAPH_DSN` updated in production `.env.production`
- [ ] `APP_ENV=prod` set
- [ ] `dev_debug=False` in config or env
- [ ] Backup strategy in place
- [ ] Monitoring/alerting on Postgres connection failures
- [ ] All four feature flags reviewed (groundedness, agentic, entity_graph, observability)
- [ ] Tested smoke queries against production endpoint
- [ ] Verified `query_logs` writes are landing in production DB

### Cost considerations at scale

For ~10k queries/day in production:

| Cost item | Estimated monthly |
|-----------|-------------------|
| Postgres (managed, small instance) | $15–25 |
| OpenAI embeddings + reranking + planner | $30–60 |
| OpenAI groundedness verification | $15 |
| Anthropic Claude Sonnet (main generation) | $200–400 |
| Cohere reranking | $20 |
| **Total LLM + DB** | **~$280–520** |

The biggest cost is Claude Sonnet generation. Most of the new infrastructure (entity graph, observability) adds <5% to total cost.

---

## 12. Known limitations and follow-ups

### Phase 13 (Groundedness)

- Comparative path runs one verify call per query — fine at current scale, would batch at high volume
- No automatic regeneration on low scores yet (`regenerate_on_failure=False`)

### Phase 11 (Agentic)

- Planner hard-wired to OpenAI gpt-4o-mini (requires OPENAI_API_KEY even if main provider is Claude)
- `report_filter_hint` extracted by planner but not currently used by `ask()` — TODO
- Sub-queries run sequentially, not parallelized

### Phase 12 (Entity Graph)

- Per-chunk `entities_mentioned` field still mostly None (Aho-Corasick scanner side-steps this)
- Entity types use 10 categories with some inconsistencies (e.g., "Government of India" is `entity_type: organization`, state governments are `entity_type: state_government`)
- Some OCR artifacts in aliases (`Gol` instead of `GoI`)
- No entity-level descriptions or summaries
- No temporal modeling beyond first/last seen year

### Bridge A (Auto-filter)

- Rule-based only; no LLM fallback for ambiguous cases (could be added)
- Short ambiguous aliases (UP, MP, TN) require ≥2 occurrences or context cue — may miss some valid single-mention queries

### Bridge B (Two-pass canonicalization)

- Uses fixed `gpt-4o-mini`; no provider fallback if OpenAI is down

### Bridge C (Observability)

- **Token usage and `cost_estimate_usd` are NULL** — `record_generation()` is called with `prompt_tokens=None`. Fix requires capturing tokens from each LLM provider's response object. Deferred but worth doing before cost dashboards become important.
- **Some queries skip groundedness logging** — investigate `groundedness_verified IS NULL` rows in production
- **Directory queries seem 4× slower than home queries** in early data — probably statistical noise from 2 samples, but worth monitoring

### Bridge D (Comparative cap)

- `_smart_select_reports` makes one DB call per (report, entity) pair — at 700 reports with 5 matched entities = 3500 lookups. Could be batched into one query. Optimize when comparative latency becomes a real bottleneck.

### Cross-cutting

- Frontend doesn't yet consume agentic streaming events richly — they're logged to console only
- No A/B testing infrastructure for trying config variants
- No production cost dashboard yet (data is there, dashboards aren't built)

---

## 13. Lessons learned

Worth carrying forward into future phases:

### 1. "Tests pass" ≠ "implementation correct" for data pipelines

All 31 entity graph unit tests passed during initial Phase 12 implementation, while `Government of Himachal Pradesh` had 11 other states' aliases collapsed into it. Unit tests verify code structure; data quality requires inspection of actual outputs. **For data-pipeline work, always spot-check 20+ real outputs before declaring done.**

### 2. Always inspect actual data, not just row counts

Bridge C's first verification was: "row appeared in query_logs, success=true, return 200" — and we declared victory. The empty data inside those rows was invisible until we asked the right question. **First verification step is always `SELECT * FROM <table> ORDER BY ts DESC LIMIT 1` and read every column**, not `SELECT count(*)`.

### 3. Silent LLM failure modes are insidious

The canonicalizer's first version had a 47% data loss rate that looked like success. The LLM returned valid JSON with empty arrays — a successful API call as far as the code was concerned, but a complete data drop. **Defensive check**: when an LLM returns an empty result for non-empty input, retry with a fallback prompt and ultimately fall back to local logic.

### 4. Aho-Corasick > LLM for known-vocabulary scanning

Once you have a canonical entity list, you don't need an LLM to find mentions in text. Multi-pattern string matching is 1000× faster, deterministic, and free. **Use LLMs to *build* vocabularies; use string-matching to *apply* them.**

### 5. Composition over extension for orchestrators

`AgenticRAGService` takes `RAGService` as a dependency rather than subclassing it. This made A/B testing trivial, kept the existing path byte-identical, and made Phase 12's comparative refactor straightforward. **Wrapping > inheriting for orchestrators.**

### 6. Hard caps prevent runaway loops

Every iterative agent needs: max iterations, max sub-queries, token budget, wall-clock timeout, confidence threshold for early stop. **All five must trip independently.** The agentic loop has all of them.

### 7. Ship the smallest piece first

Phase 13 was specced last but shipped first. It generated observation data (real grounding scores) that informed Phases 11 and 12. **For multi-phase efforts, identify the smallest, most additive phase and ship it first.**

### 8. Postgres is enough until it isn't

Entity graph at 390 entities and 25k mentions is well within Postgres comfort zone. We considered Neo4j and rejected it as premature. **Don't introduce graph databases until you have a real graph traversal problem that joins can't solve.**

### 9. Existing infrastructure is your superpower

Phase 12's biggest cost saving came from piggybacking entity normalization on the existing overview batch. Phase 13's groundedness reused existing LLM clients. Phase 11's agentic loop reused `retrieve()`, `_check_context_sufficiency()`, and the streaming wrapper. **Look for what already exists before building new infrastructure.**

### 10. `@contextmanager` + manual `__enter__`/`__exit__` is a footgun

The biggest Bridge C bug: the streaming wrapper called `log_ctx = log_ctx.__enter__()` which reassigned the only reference to the `_GeneratorContextManager` wrapper. Python's GC immediately closed the abandoned generator, firing `finally` before any data was recorded. **Either use `with` blocks always, or make your context object a real class with `__enter__`/`__exit__` methods.** Never mix.

### 11. Two-DSN pattern for Docker + Mac development

`host.docker.internal` doesn't resolve on macOS, only inside containers. `localhost` works on Mac but not from inside a container. **Maintain two .env files** (or two values in env management) — one for Mac context, one for Docker context. Cleaner than hacking `/etc/hosts`.

---

## 14. File index

### New files (entire stack)

```
src/rag_pipeline/
  ├─ groundedness_service.py        ← Phase 13
  ├─ agentic_service.py              ← Phase 11
  ├─ retrieval_utils.py              ← Phase 12 + Bridge A (merge_filters lives here)
  └─ auto_filter.py                  ← Bridge A

src/entity_graph/                    ← Phase 12 (entire package)
  ├─ __init__.py
  ├─ db.py
  ├─ models.py
  ├─ canonicalizer.py                ← (extended in Bridge B)
  ├─ mention_indexer.py              ← (with AliasScanner)
  ├─ entity_service.py
  └─ cli.py

src/observability/                   ← Bridge C (entire package)
  ├─ __init__.py
  ├─ models.py                       ← QueryLog ORM
  ├─ query_logger.py                 ← QueryLogger + QueryLogContext
  └─ cost_calculator.py

src/api/routes/
  └─ entities.py                     ← Phase 12

docs/
  └─ entity_graph_setup.md           ← Phase 12

tests/
  ├─ entity_graph/                   ← Phase 12
  ├─ observability/                  ← Bridge C (E2E test for wiring)
  └─ rag_pipeline/                   ← Phase 11/12 ask_comparative tests
```

### Modified files

```
src/core/config.py                  ← +5 config classes
src/rag_pipeline/models.py          ← +2 optional fields on RAGResponse
src/rag_pipeline/rag_service.py     ← init services, ask/ask_comparative refactors
src/rag_pipeline/indexer.py         ← optional auto-index hook
src/api/models.py                   ← +2 fields on ChatResponse
src/api/main.py                     ← register /entities, query_logger plumbing
src/api/routes/chat.py              ← +2 agentic routes
src/api/services/streaming_wrapper.py ← _maybe_verify_groundedness, agentic streaming
src/batch_pipeline/prompts/overview_extraction.py  ← 5th output field
src/batch_pipeline/merge_utils.py   ← include normalized_entities
src/batch_pipeline/batch_service.py ← bump max_tokens
pyproject.toml                      ← +sqlalchemy, psycopg, alembic, pyahocorasick
frontend/lib/api.ts                 ← extend StreamEvent, add streamChatAgentic
frontend/hooks/useChatStream.ts     ← mode parameter, new event handlers
```

---

**End of reference document.**

This document, the codebase, the canonical entity data, and 30 days of accumulated `query_logs` together form the input for the next phase: building an evaluation set and running the 700-report ingestion. That work happens in a fresh chat.
