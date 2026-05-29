# Claude Code Prompt: Update HowItWorks Section

Run with **Opus** (`claude-opus-4-20250514`) for best results — this is a large multi-file rewrite with architectural reasoning. Sonnet (`claude-sonnet-4-20250514`) will also work but may need more guidance per tab.

```bash
# Set model before running (if not default)
claude config set model claude-opus-4-20250514
```

Paste the following into Claude Code:

---

## Task

Update the `frontend/components/HowItWorks/` section to reflect the **current production state** of the CAG-GATEWAY platform, including everything from Phases 11, 12, 13, and Bridge A/B/C/D. The existing tabs are outdated and don't cover agentic retrieval, the entity graph, groundedness verification, auto-filtering, or query observability.

## Reference Documents

Read these files for the authoritative source of truth on what the system does today:

1. `docs/guides/RAG_PIPELINE.md` — Full pipeline documentation including Phases 11-13 + Bridge sections, architecture diagrams, stage-by-stage breakdown, streaming events, config reference, and API endpoints.
2. `docs/PHASES_11_12_13_BRIDGE_REFERENCE.md` — Deep implementation reference covering: why each phase existed, how they fit together, the full query flow diagram, configuration/feature flags, observability details, and lessons learned.

Read both fully before making any changes. These are the canonical sources — do not invent features or metrics not described in them.

## Existing Component Structure

```
frontend/components/HowItWorks/
├── shared/                    # Reusable UI components — DO NOT MODIFY
│   ├── CalloutBox.tsx
│   ├── CodeBlock.tsx
│   ├── DiagramCard.tsx
│   ├── DocSection.tsx
│   ├── MermaidDiagram.tsx
│   ├── TabbedPrompt.tsx
│   └── TechBadge.tsx
├── tabs/                      # Tab content — UPDATE THESE
│   ├── Overview.tsx
│   ├── RAGSearch.tsx
│   ├── DataPipeline.tsx
│   ├── AIFeatures.tsx
│   ├── FrontendArchitecture.tsx
│   └── Infrastructure.tsx
└── HowItWorks.tsx             # Main container with tab navigation
```

Read every file in `shared/` to understand the component API (props, usage patterns). Read `HowItWorks.tsx` to understand the tab structure and any shared state. Then read each tab file in `tabs/` to understand the current content and style conventions.

## What Each Tab Should Cover After Update

### 1. `Overview.tsx`
**Purpose:** High-level system summary for someone seeing CAG-GATEWAY for the first time.

Update to reflect:
- The system is a production-grade RAG platform for Indian CAG audit reports covering Union, State, and Local Body government tiers
- Two-pipeline architecture: offline indexing + online query
- Four query paths: directory chat (single report), time series (comparative), home page chat (open-ended), agentic (complex multi-hop)
- Key capabilities summary: hybrid search, agentic retrieval, entity graph, groundedness verification, auto-filtering, full observability
- Tech stack: FastAPI + React/TS + Qdrant + Postgres + Claude/GPT-4/Gemini + Cohere reranking
- Scale: ~37 reports currently, designed for 700+; ~390 canonical entities, ~25k entity mentions

### 2. `RAGSearch.tsx`
**Purpose:** The core RAG pipeline — how queries go from user input to cited answers.

This is the most important tab. Rewrite to cover the **full query pipeline** as described in RAG_PIPELINE.md Stages 2-6 plus Phases 11-13 + Bridge:

**Standard path:**
- Query Enhancement (LLM-powered expansion, classification, tier-aware vocabulary)
- Hybrid Search (dense embeddings + BM25 sparse vectors with CAG-specific boosts)
- Reranking (Cohere primary, BGE fallback)
- Neighbor Expansion (O(1) chunk ID prediction)
- Parent Grouping + Passage Reordering (lost-in-the-middle mitigation)
- Context Sufficiency Check (tier-adjusted thresholds)
- Tier Context Injection (State/Local terminology headers)
- LLM Generation with 6 response styles
- Citation building with report metadata

**Agentic path (Phase 11):**
- Planner decomposes complex queries into 2-4 sub-queries
- Per-sub-query retrieval loop with sufficiency checks and reformulation (up to 3x)
- Hard caps: 4 sub-queries, 3 iterations each, 30k token budget, 20s wall-clock
- Simple queries short-circuit to standard path (no regression for 70-80% of queries)
- Separate endpoint: `/chat/agentic/stream`

**Auto-filter (Bridge A):**
- Rule-based extraction of year, state, tier, audit category from query text
- Only activates when no explicit filters are set (home page + agentic sub-queries)
- Short ambiguous alias guard (UP, MP, TN require ≥2 occurrences)

**Groundedness Verification (Phase 13):**
- Post-generation LLM call (gpt-4o-mini) verifies each factual claim against retrieved context
- Per-claim grounding report with overall score
- Fail-open: verification errors don't block the answer
- Streams as final event between last token and done
- Cost: ~$0.0005/query, +200-400ms (thread-pooled)

**Streaming events:** Include a table or visual showing the event sequence for both standard and agentic paths (see the "Streaming Events" section in RAG_PIPELINE.md).

### 3. `DataPipeline.tsx`
**Purpose:** Offline data processing — how raw PDFs become searchable indexed content.

Update to include:
- Existing parsing pipeline (PDF → text extraction → chunking → semantic enrichment → JSON)
- Multi-tier directory structure (union/state/local_body)
- Indexing pipeline (JSON → embeddings → Qdrant with tier-aware payloads)
- **Entity Graph pipeline (Phase 12):** Three-stage process:
  - Stage 1: Per-report entity normalization (piggybacks on existing overview batch via Anthropic)
  - Stage 2: Cross-corpus canonicalization (CLI command, LLM-powered dedup with cross-state guards)
  - Stage 3: Mention indexing (Aho-Corasick scanner, ~25k mentions across 37 reports)
- Entity graph stats: 390 entities (192 Union, 118 State, 80 Local Body), 24,865 mentions
- **AI Summaries pipeline:** 5 variants via Batch API + Extended Thinking (already exists, preserve this content)
- **Overview extraction pipeline:** audit scope, objectives, topics, glossary, normalized_entities

### 4. `AIFeatures.tsx`
**Purpose:** AI-powered features beyond basic RAG.

Update to cover:
- **Agentic Retrieval (Phase 11):** Multi-hop query decomposition, iterative retrieval with reformulation, composition-over-extension design
- **Entity Graph (Phase 12):** Cross-report entity reasoning, canonical entity resolution with alias matching, integration with `ask_comparative()` for entity-aware report narrowing, HTTP API (`/api/entities/*`)
- **Groundedness Verification (Phase 13):** Post-generation hallucination checking, per-claim verification with confidence scores
- **Auto-filtering (Bridge A):** Intelligent query-to-filter extraction
- **Two-pass Canonicalization (Bridge B):** Scale-dependent quality improvement, activates above 1000 raw records
- **Comparative Breadth Cap (Bridge D):** Smart report selection when entity-narrowed set exceeds 20 reports
- **Query Observability (Bridge C):** 50-column query log, dev vs prod modes, latency breakdown
- **AI Summaries:** 5 summary variants (preserve existing content)
- **Query Enhancement:** LLM-powered expansion, classification, suggested filters

### 5. `Infrastructure.tsx`
**Purpose:** Deployment, services, databases, and operational details.

Update to include:
- **Qdrant:** Two collections (cag_child_chunks with hybrid vectors, cag_parent_chunks metadata-only), payload indexes for filtering
- **PostgreSQL (NEW):** Shared database `cag_entity_graph` with tables: entities, entity_mentions, entity_relations, query_logs. Two-DSN pattern for Docker + Mac development
- **LLM Providers:** Multi-provider support (Claude, GPT-4, Gemini) with provider-specific fallbacks. OpenAI required for embeddings, query enhancement, agentic planner, and groundedness regardless of main LLM_PROVIDER
- **Reranking:** Cohere primary + BGE local fallback
- **Docker:** docker-compose.prod.yml, Caddy reverse proxy
- **Configuration:** Feature flag matrix from Bridge reference (all features independently toggleable)
- **Environment variables:** Full list from RAG_PIPELINE.md

### 6. `FrontendArchitecture.tsx`
**Purpose:** Frontend architecture and component structure.

Minimally update to mention:
- Agentic streaming event handling in `useChatStream.ts` (mode parameter, new event types)
- `streamChatAgentic` function in `api.ts`
- Entity-related API calls if any entity UI exists
- Otherwise preserve existing content about the React/TS stack, hooks, components

## Style & Design Guidelines

- Match the **existing visual style** exactly. Read the shared components to understand how DiagramCard, CalloutBox, CodeBlock, DocSection, MermaidDiagram, TabbedPrompt, and TechBadge work and use them consistently.
- Keep the same tone: technical but accessible, explaining design decisions and trade-offs where interesting.
- Use the Mermaid diagrams from RAG_PIPELINE.md as a basis for MermaidDiagram components (the architecture diagrams and extended architecture diagrams).
- Don't invent metrics or numbers not in the reference docs. Use exact figures: 390 entities, 24,865 mentions, $0.0005/query for groundedness, etc.
- Each tab should be self-contained and readable on its own.
- Keep content dense but scannable — use the shared components (CalloutBox for key insights, CodeBlock for schemas/examples, DiagramCard for architecture, TechBadge for tech names).

## Implementation Approach

1. Read both reference docs completely
2. Read all shared components to understand their APIs
3. Read all existing tab files to understand current patterns
4. Update each tab file, preserving any existing content that's still accurate
5. Update `HowItWorks.tsx` if the tab labels or order should change (only if needed)
6. Do NOT modify anything in `shared/` — those components are stable

Focus on accuracy over brevity. The HowItWorks section is documentation for technical users who want to understand the system architecture.
