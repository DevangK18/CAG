# CLAUDE.md

## Project Overview

CAG Interactive Gateway: AI-powered system for querying India's public audit reports. Parses PDFs into structured JSON, enriches with semantic metadata, provides RAG-powered Q&A.

**Multi-tier support:** Union, State, and Local Body reports with tier-specific metadata.

## Architecture

- **Parsing Pipeline** (`src/parsing_pipeline/`): 10-phase pipeline with TOC extraction, semantic enrichment, hierarchical chunking
- **RAG Pipeline** (`src/rag_pipeline/`): Hybrid search (dense + BM25), parent-child chunking, reranking, SSE streaming
- **Batch Pipeline** (`src/batch_pipeline/`): Claude/OpenAI Batch API, Gemini visual extraction
- **API** (`src/api/`): FastAPI with `/reports`, `/chat`, `/series` endpoints
- **Frontend** (`frontend/`): React + TypeScript, Zustand, react-pdf, ReactMarkdown

## Commands

```bash
# Setup
poetry install && cp .env.example .env
cd frontend && npm install

# Parsing Pipeline
python -m src.parsing_pipeline.main "CAG_Union_Reports.xlsx"
python -m src.parsing_pipeline.main "CAG_State_Reports.xlsx"
python run_pipeline_quick.py "Manifest.xlsx" --phase10a --phase10b

# RAG Pipeline
docker run -p 6333:6333 qdrant/qdrant
python -m src.rag_pipeline.indexer --input-dir data/processed --recreate
poetry run python scripts/index_and_migrate_qdrant.py --all

# API/Frontend
uvicorn src.api.main:app --reload --port 8000
cd frontend && npm run dev

# Testing
pytest --cov=src

# Code Quality Analysis
npx truecourse dashboard  # AI-powered codebase analysis (architecture, security, bugs, performance)
```

## Multi-Tier Architecture

**Tier Detection:** Filename-based (`CAG_Union_Reports.xlsx`, `CAG_State_Reports.xlsx`, `CAG_Local_Body_Reports.xlsx`) or `Government Body Type` column override.

**Tier-Specific Fields:**
- `government_body_type`: "union" | "state" | "local_body"
- `state_name`: For State/Local reports (null for Union)
- `audit_category`: "compliance" | "performance" | "financial" | "revenue" | "commercial" | "atir"

**Report ID Formats:**
- Union: `{year}_{serial}_{title}`
- State: `{ST}_{year}_{no}_{title}`
- Local ATIR: `{ST}_ATIR_{year}_{title}`

**Directory Structure:**
```
data/raw/{union,state,local_body}/      # PDFs by tier
data/processed/{union,state,local_body}/ # JSON outputs by tier
```

## Key Implementation Details

### Table/Chart Extraction
3-tier strategy: pdfplumber → Docling TableFormer → Gemini Vision fallback

### TOC Extraction
Phase 4 (quantile bucketing) → Phase 5.5 (reconciliation) → Phase 5.7 (LLM validation). Result: 97%+ accuracy.

### Semantic Enrichment
Algorithmic entity extraction, finding classification, recommendation parsing. 87+ regex patterns for State/Local report language (GST/ITC, PRI/ULB terminology). Finding types: loss_of_revenue, accounting_irregularity, performance_shortfall, procedural_lapse, system_deficiency, fraud_misappropriation, wasteful_expenditure.

**Tier-Specific Severity Thresholds (Rs crore):**
- Union: critical=100, high=10, medium=1
- State: critical=50, high=5, medium=0.5
- Local: critical=10, high=1, medium=0.1

### Chat & Citations
ReactMarkdown rendering, 95%+ citation match rate, correct PDF page navigation.

## Directory Structure

```
src/
├── parsing_pipeline/modules/   # scaffolding, toc, chunking, semantic enrichment
├── rag_pipeline/              # indexer, embedding, qdrant, retrieval
├── batch_pipeline/            # batch API, Gemini visual extraction
├── api/routes/                # reports, chat, series endpoints
└── core/                      # config, data_contracts

frontend/
├── components/                # ReportCard, ChatMessage, PDFViewer, HowItWorks
├── hooks/                     # useReports, useChatStream, useFetchFilters
└── lib/                       # api, citationUtils, posthog

scripts/
├── index_and_migrate_qdrant.py  # Multi-tier Qdrant migration
└── migrate_union_data.py        # Backfill Union tier metadata
```

## Configuration

```bash
OPENAI_API_KEY=...        # Embeddings + Batch API
ANTHROPIC_API_KEY=...     # Claude LLM + Batch API
COHERE_API_KEY=...        # Reranking
GOOGLE_API_KEY=...        # Gemini visual extraction
QDRANT_URL=http://localhost:6333
RATE_LIMIT_CHAT=30/hour   # LLM endpoint rate limiting

# Frontend
VITE_PUBLIC_POSTHOG_KEY=phc_...
VITE_ACCESS_CODE=code1,code2,code3
```

## Deployment

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml build --no-cache
docker compose --env-file .env.production -f docker-compose.prod.yml up
```

Requirements: Python 3.11+, ≥16GB RAM, Qdrant (Docker or Cloud)

**Production features:** Rate limiting (slowapi, 30/hour on chat endpoints), PostHog analytics, Access gate (sessionStorage-based).

## Import Structure

Always use absolute imports and run as modules:
```python
from src.core.data_contracts import DocumentTask
python -m src.module.name
```

## Known Issues

1. Phase 10a summary generation needs end-to-end testing
2. Some files use hardcoded `Path("data/processed")` instead of config
3. Series chat doesn't show year badges yet

## Status

Fully operational multi-tier system: 97% TOC accuracy, 95% citation match rate, <5% "other" findings for State/Local reports, 188+ tests passing.

## Current TODO (Completed) for Home UI Full stack implementation

Files : "01_frontend_implementation_plan.md" and "02_frontend_implementation_plan.md"

1. Phase BE Types (Pydantic Response Models) and FE Types (Typescript types) Completed
2. Phase BE-0 (Foundational Changes) and BE-A (Stub Routes) : To be completed next session