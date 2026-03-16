# CLAUDE.md

## Project Overview

CAG Interactive Gateway: AI-powered system for querying India's public audit reports. Parses PDFs into structured JSON, enriches with semantic metadata, provides RAG-powered Q&A.

**Multi-tier support:** Handles Union, State, and Local Body reports with tier-specific metadata and organization.

## Architecture

### Parsing Pipeline (`src/parsing_pipeline/`)
10-phase pipeline: Manifest → Triage → OCR → Scaffolding → Layout → TOC Reconciliation → LLM Validation → Content Extraction → Chunking → Assembly → Semantic Enrichment → Batch Summaries

**Key phases:**
- Phase 4: Document Scaffolding (TOC extraction with printed TOC pre-pass, quantile bucketing)
- Phase 5.5: TOC Reconciliation (fuses heuristic + Docling section-header detections)
- Phase 5.7: LLM TOC Validation (Claude Haiku for low-quality TOCs)
- Phase 7: Hierarchical Chunking (Y-aware parent-child assignment)

### RAG Pipeline (`src/rag_pipeline/`)
Hybrid search (dense + sparse BM25), parent-child chunking, reranking, SSE streaming. **LLM provider flexibility**: switch between Claude/OpenAI/Gemini via `LLM_PROVIDER` env var.

### Batch Pipeline (`src/batch_pipeline/`)
Claude/OpenAI Batch API for LLM enrichment and Gemini visual extraction

### API (`src/api/`)
FastAPI backend with `/reports`, `/chat`, `/series` endpoints

### Frontend (`frontend/`)
React + TypeScript, Zustand state, react-pdf viewer, ReactMarkdown chat, How It Works docs

## Common Commands

### Setup
```bash
poetry install && cp .env.example .env
cd frontend && npm install
```

### Run Parsing Pipeline
```bash
# Union reports (default)
python -m src.parsing_pipeline.main "CAG_Union_Reports.xlsx"

# State/Local Body reports (auto-detected from filename)
python -m src.parsing_pipeline.main "CAG_State_Reports.xlsx"
python -m src.parsing_pipeline.main "CAG_Local_Body_Reports.xlsx"

# Quick runner with Phase 10 control
python run_pipeline_quick.py "Newtest.xlsx"                    # Phases 1-9
python run_pipeline_quick.py "Newtest.xlsx" --phase10a         # + LLM summaries
python run_pipeline_quick.py "Newtest.xlsx" --phase10b         # + Gemini visuals

python -m src.batch_pipeline.check_status      # Check batch jobs
python -m src.batch_pipeline.process_results   # Process results
```

### Run RAG Pipeline
```bash
docker run -p 6333:6333 qdrant/qdrant
python -m src.rag_pipeline.indexer --input-dir data/processed
python -m src.rag_pipeline.cli --interactive
```

### Run API/Frontend
```bash
uvicorn src.api.main:app --reload --port 8000
cd frontend && npm run dev
```

### Testing
```bash
pytest                              # All tests
pytest tests/parsing_pipeline/     # Specific suite
pytest --cov=src                   # With coverage
```

## Key Patterns

- **Parent-Child Chunking**: Child chunks link to parent chunks (sections)
  - Y-aware assignment using heading Y-coordinates
  - Specificity sorting: prefers deeper TOC levels
- **Hybrid Search**: Dense vector + sparse BM25
- **3-Tier Table Extraction**: pdfplumber → Docling TableFormer → Gemini Vision
- **Streaming**: SSE with citation metadata

## Multi-Tier Architecture

Supports Union, State, and Local Body audit reports with tier-specific handling:

**Tier Detection:**
- Filename-based: `CAG_Union_Reports.xlsx`, `CAG_State_Reports.xlsx`, `CAG_Local_Body_Reports.xlsx`
- Column override: `Government Body Type` column in manifest

**Tier-Specific Fields:**
- `government_body_type`: "union" | "state" | "local_body"
- `state_name`: State name for State/Local reports (null for Union)
- `department`: State/Local department (null for Union; Union uses `ministry`)
- `audit_category`: "compliance" | "performance" | "financial" | "revenue" | "commercial" | "atir"
- `report_subtype`: "PSE" | "Revenue" | "PRI_ULB" | null

**Report ID Formats:**
- Union: `{year}_{serial}_{title}` (e.g., `2025_20_Skill_Development`)
- State: `{ST}_{year}_{no}_{title}` (e.g., `OD_2025_05_School_Education_Odisha`)
- Local ATIR: `{ST}_ATIR_{year}_{title}` (e.g., `MH_ATIR_2019_Local_Bodies`)

**Directory Structure:**
- `data/raw/{union,state,local_body}/` — PDFs organized by tier
- `data/processed/{union,state,local_body}/` — JSON outputs organized by tier

**Migration:** Use `scripts/migrate_union_data.py` to add tier fields to existing Union data (see `scripts/MIGRATION_README.md`)

**Key files:** `manifest_ingestion_service.py`, `data_contracts.py`

## Critical Implementation Details

### Table/Chart Extraction
**3-tier strategy:**
- Native PDFs: pdfplumber → Docling TableFormer (quality gate: ≥3 cells) → Gemini fallback
- Scanned PDFs: Docling TableFormer → Gemini fallback
- All tables/charts track `extraction_method` field

**Key files:** `layout_analysis_service.py`, `content_extraction_service.py`, `pdfplumber_table_extractor.py`, `gemini_visual_extractor.py`

### TOC Extraction
**Multi-layer strategy (Phase 4 → 5.5 → 5.7):**
- Phase 4: Quantile bucketing, printed TOC pre-pass (first ~15 pages)
- Phase 5.5: Reconciliation (fuses heuristic + Docling detections, 3 strategies based on quality)
- Phase 5.7: LLM validation for quality < 50 (Claude Haiku, ~$0.50-$2 for 1,297 reports)
- Impact: 90% → 97%+ TOC accuracy

**Key files:** `scaffolding_service.py`, `toc_reconciliation_service.py`, `toc_llm_validator.py`, `chunking_service.py`

### Semantic Enrichment
Features: Structured tables, multi-page stitching, report type adaptation, entity extraction, cross-reference resolution, recommendation extraction, executive summary parsing, visual asset registry, footnotes

**52 passing tests | $0.00 cost (algorithmic only)**

### Chat & Citations
**Markdown Rendering (`ChatMessage.tsx` v5.0):**
- ReactMarkdown with remark-gfm, rehype-raw
- `normalizeMarkdownContent()` inserts missing newlines for block elements
- Supports headings, lists, tables, code, blockquotes, links
- Backend `FORMATTING_GUIDELINES` in `rag_service.py` instruct LLM on proper markdown

**Citation System (2026-02-28 fixes):**
- Bug #1 (Key Mismatch): Backend adds `[Source: section, p.XX]` labels to context, LLM copies exact labels. Frontend normalization preserves structure. Page-only fallback for edge cases. **Impact:** 95%+ match rate
- Bug #2 (Page Off-by-One): Fixed `page_physical=page-1` → `page_physical=page` in `streaming_wrapper.py`. **Impact:** Correct page navigation
- Feature (Shortened Pills): Display text truncated to 30 chars, full text in tooltip. Function: `shortenCitationLabel()` in `ChatMessage.tsx`

**Files modified:** `models.py`, `rag_service.py`, `streaming_wrapper.py`, `citationUtils.ts`, `ChatMessage.tsx`

### How It Works Documentation
6 interactive tabs (Overview, Data Pipeline, RAG & Search, AI Features, Frontend Architecture, Infrastructure) with 16+ Mermaid diagrams, reusable components, professional styling

**Key files:** `frontend/components/HowItWorks/`

## Directory Structure

```
src/
├── parsing_pipeline/
│   ├── main.py
│   ├── modules/              # scaffolding, toc_reconciliation, toc_llm_validator, chunking, etc.
│   └── extractors/           # pdfplumber, gemini
├── rag_pipeline/            # retrieval_service, rag_service, models, indexer
├── batch_pipeline/          # Batch API + Gemini visual extraction
├── api/                     # FastAPI + streaming_wrapper + rate_limit.py
└── core/                    # config, data_contracts, table_contracts, chart_contracts

data/
├── raw/                     # Downloaded PDFs
│   ├── union/               # Union reports
│   ├── state/               # State reports
│   └── local_body/          # Local Body reports
├── processed/               # Structured JSONs
│   ├── union/               # Union JSON outputs
│   ├── state/               # State JSON outputs
│   └── local_body/          # Local Body JSON outputs
├── extraction_images/       # Table/chart images
└── batch_jobs/              # Batch API tracking

frontend/
├── components/
│   ├── AccessGate.tsx       # Invite-only access control
│   ├── ChatMessage.tsx      # v5.0 ReactMarkdown + citations
│   ├── HowItWorks/          # 6-tab docs
│   ├── PDFViewer.tsx
│   └── ReportCard.tsx
├── hooks/
├── stores/
└── lib/                     # api.ts, citationUtils.ts, posthog.ts
```

## Pipeline Status

**✅ FULLY OPERATIONAL (2026-03-15)**

- **Multi-tier expansion**: Union, State, and Local Body report support with tier-specific metadata
- Phase 1-4 enhancements: semantic enrichment, table extraction, TOC improvements
- TOC accuracy: ~97% (Phase 5.5 reconciliation + 5.7 LLM validation)
- V2 table/chart extraction: 3-tier strategy operational
- Chat: ReactMarkdown integration, 95%+ citation match rate, correct PDF navigation
- How It Works: 6-tab technical documentation with Mermaid diagrams
- Test coverage: 188+ tests (100 TOC, 29 LLM validator, 52 semantic enrichment, 7 chunking)
- Metrics: 771 parent chunks, 2,524 child chunks, 184 findings, 204 recommendations, ₹14+ lakh crore extracted (2-report test run)

## Configuration

**Environment variables:**
```bash
OPENAI_API_KEY=...        # Embeddings + Batch API
ANTHROPIC_API_KEY=...     # Claude LLM + Batch API + Phase 5.7 TOC validation (optional)
COHERE_API_KEY=...        # Reranking
GOOGLE_API_KEY=...        # Gemini visual extraction
QDRANT_URL=http://localhost:6333

# Rate Limiting
RATE_LIMIT_CHAT=30/hour   # Limits LLM-hitting endpoints (chat, series queries)

# PostHog Analytics (frontend)
VITE_PUBLIC_POSTHOG_KEY=phc_...
VITE_PUBLIC_POSTHOG_HOST=https://us.i.posthog.com

# Access Gate (frontend)
VITE_ACCESS_CODE=code1,code2,code3   # Comma-separated codes for different users
```

**OCR:** English-only (`eng`). For Hindi: install `tesseract-lang`, change to `eng+hin` in `ocr_service.py:99`

## Import Structure

**Always use absolute imports:**
```python
from src.core.data_contracts import DocumentTask
from src.parsing_pipeline.modules.triage_service import TriageService
```

**Run as modules:**
```bash
python -m src.module.name
```

## Known Issues

1. **Phase 10a Summary Generation** (Medium): Batch submission fixed, needs end-to-end testing
2. **Series Chat Year Badges** (Low): ChatMessage.tsx doesn't show year badges in series mode yet
3. **Data Folder Organization** (Low): Needs restructure to `data/input/`, `data/intermediate/`, `data/output/`, `data/batch_metadata/`
4. **Data Directory Path Consistency** (Low): Some files use hardcoded `Path("data/processed")` instead of `settings.PROCESSED_DIR`
   - Affected: `src/api/routes/overview.py`, `src/api/routes/summaries.py`, `src/rag_pipeline/indexer.py`, `src/rag_pipeline/rag_service.py`
   - Should add `DATA_DIR` env var support to `src/api/config.py` and update all files to use config
   - Should add `BATCH_JOBS_DIR` to config settings
   - Current setup works in Docker (paths resolve to `/app/data/*`) but lacks configurability

## Future Work

**Planned features (see docs/plans/ for detailed specs):**

1. **RAG Phase 2 & 3 Enhancements** (`docs/plans/rag_phase2_3_plan.md`)
   - Query enhancement with entity extraction, synonym expansion, temporal context
   - Multi-hop reasoning for complex questions spanning multiple sections
   - Advanced reranking with cross-encoder models

2. **PDF Thumbnail Generation** (`docs/plans/THUMBNAIL_GENERATION_PLAN.md`)
   - Automated thumbnail generation for report cards
   - Page preview system for quick navigation
   - Visual asset optimization

## Deployment

- Python 3.11+ (asyncio, Pydantic v2)
- ≥16GB RAM (vision models)
- Qdrant: Docker or Qdrant Cloud
- Batch jobs: 1-2 hour completion

### Docker Production Build

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml build --no-cache
docker compose --env-file .env.production -f docker-compose.prod.yml up
```

**Note:** `--env-file .env.production` is required to pass `VITE_*` variables to the frontend build stage.

**Key files:** `Dockerfile`, `docker-compose.prod.yml`, `Caddyfile`, `.env.production`

**Critical fixes applied (2026-03-04):**
1. **Import map removed** from `frontend/index.html` — was loading React from CDN, conflicting with bundled React
2. **CSS import added** to `frontend/index.tsx` — `import './index.css'` (was only in HTML)
3. **fetchReports URL fix** in `frontend/lib/api.ts` — `new URL()` fails with relative paths; use string concatenation
4. **PDF static mount** at `/api/files` in `src/api/main.py` — frontend expects `/api/files/{filename}.pdf`
5. **X-Frame-Options** in `Caddyfile` — changed `DENY` to `SAMEORIGIN` for iframe PDF viewer

### Pre-Production Hardening (2026-03-04)

#### Rate Limiting
Prevents API bill spikes by limiting LLM-hitting endpoints using slowapi.

**Protected endpoints:** `/api/chat`, `/api/chat/stream`, `/api/series/{id}/query`, `/api/series/{id}/query/stream`
**Default limit:** 30 requests/hour per IP (configurable via `RATE_LIMIT_CHAT`)
**Excluded:** Static data endpoints (`/health`, `/api/reports`, `/api/summaries`, etc.)

**Key files:** `src/api/rate_limit.py`, `src/api/main.py`, `src/api/routes/chat.py`, `src/api/routes/series.py`

**Implementation notes:**
- Uses memory backend (single container); migrate to Redis for horizontal scaling
- Custom IP extraction from `X-Forwarded-For` header (Caddy proxy)
- Returns 429 with JSON error and logs violations
- Rate limit headers (`X-RateLimit-*`) automatically included

#### PostHog Analytics
Tracks user behavior during invite-only testing phase.

**Auto-captured:** Page views, clicks, session duration, scroll depth, device info
**Custom events:**
- `access_granted` / `access_denied` — gate interactions with access code
- `report_viewed` — when user opens a report
- `chat_message_sent` — chat queries with report_id
- `series_chat_sent` — cross-year queries with series_id
- `summary_viewed` — summary tab interactions

**User identification:** Each tester identified by their access code in PostHog

**Key files:** `frontend/lib/posthog.ts`, `frontend/hooks/useChatStream.ts`, `frontend/hooks/useSeriesChat.ts`, `frontend/hooks/useSummaries.ts`

#### Access Gate
Lightweight frontend-only gate for invite-only testing. NOT authentication — just keeps casual visitors out.

**Behavior:**
- First visit: Shows access code prompt
- Correct code: Stores in sessionStorage, identifies user in PostHog
- Wrong code: Shows error, logs `access_denied` event
- Refresh: App loads directly (sessionStorage persists in tab)
- New tab: Gate appears again (sessionStorage is per-tab)

**Multiple codes:** Comma-separated in `VITE_ACCESS_CODE` for different testers (tracked individually in PostHog)

**Key files:** `frontend/components/AccessGate.tsx`, `frontend/index.tsx`


