# CLAUDE.md

## Project Overview

CAG Interactive Gateway: AI-powered system for querying India's public audit reports. Parses PDFs into structured JSON, enriches with semantic metadata, provides RAG-powered Q&A.

**Multi-tier support:** Union, State, and Local Body reports with tier-specific metadata.

## Status: COMPLETE

All backend systems implemented, tested, and verified:

| Component | Status | Tests |
|-----------|--------|-------|
| Parsing Pipeline | ✅ Complete | 188 tests (P0) + 113 tests (P1) + 64 tests (P2) |
| RAG Pipeline | ✅ Complete | Hybrid search, reranking, agentic RAG |
| Embedding Service | ✅ Complete | OpenAI text-embedding-3-small |
| API Layer | ✅ Complete | 48 endpoints, full backend value exposed |

**Metrics:** 97% TOC accuracy, 95% citation match rate, 300+ tests passing.

## Architecture

```
src/
├── parsing_pipeline/   # 10-phase PDF→JSON pipeline
├── rag_pipeline/       # Hybrid search, Qdrant, reranking
├── batch_pipeline/     # Claude Batch API, Gemini visual
├── api/                # FastAPI REST + SSE streaming
└── core/               # Config, data contracts

frontend/               # React + TypeScript + Zustand
```

## Commands

```bash
# Setup
poetry install && cp .env.example .env
cd frontend && npm install

# Pipeline
python -m src.parsing_pipeline.main "CAG_Union_Reports.xlsx"
python -m src.rag_pipeline.indexer --input-dir data/processed --recreate

# Run
uvicorn src.api.main:app --reload --port 8000
cd frontend && npm run dev

# Test
pytest --cov=src
```

## Configuration

### Standard Mode (Direct API Keys)
```bash
OPENAI_API_KEY=...        # Embeddings (required)
ANTHROPIC_API_KEY=...     # Claude for batch summaries
COHERE_API_KEY=...        # Reranking
GOOGLE_API_KEY=...        # Gemini for visual extraction
QDRANT_URL=http://localhost:6333
```

### Google Cloud Mode (Vertex AI)
Route all LLM calls through GCP to use cloud credits:
```bash
# Enable Vertex AI routing
USE_VERTEX_AI=true              # Route Claude through Vertex AI Model Garden
USE_VERTEX_EMBEDDINGS=true      # Use Vertex AI text-embedding-005

# GCP Configuration
GOOGLE_CLOUD_PROJECT=your-project-id
VERTEX_AI_REGION=us-central1    # or europe-west4, asia-northeast1

# Still needed (for services not yet on Vertex AI)
COHERE_API_KEY=...              # Reranking
GOOGLE_API_KEY=...              # Gemini parsing pipeline
OPENAI_API_KEY=...              # QueryEnhancer fallback
```

**Cost Comparison (Vertex AI vs Direct):**
- Claude: Same pricing, consolidated GCP billing
- Embeddings: $0.00625/1M tokens (Vertex) vs $0.13/1M (OpenAI) = **20x cheaper**

## Multi-Tier Architecture

**Tiers:** `government_body_type` = "union" | "state" | "local_body"

**Report ID Formats:**
- Union: `{year}_{serial}_{title}`
- State: `{ST}_{year}_{no}_{title}`
- Local: `{ST}_ATIR_{year}_{title}`

**Directory Structure:**
```
data/raw/{union,state,local_body}/      # PDFs
data/processed/{union,state,local_body}/ # JSON
```

## Key Features

- **TOC Extraction:** Phase 4 bucketing → Phase 5.5 reconciliation → Phase 5.7 LLM validation
- **Table Extraction:** pdfmux routing → pdfplumber → Docling TableFormer → Gemini fallback (0.911 TEDS)
- **Semantic Enrichment:** Finding classification, severity tiers, entity extraction, 87+ regex patterns
- **RAG:** Hybrid dense+BM25 search, Cohere reranking, parent-child chunking, SSE streaming
- **API Layer:** Full backend value exposed including SOTA features, hierarchical summaries, semantic filters

## Import Structure

```python
from src.core.data_contracts import DocumentTask
python -m src.module.name
```

## Pipeline Configuration

Centralized in `parsing_config.yaml`:
- Triage: `text_threshold: 150` chars/page
- Layout: `confidence_threshold: 0.65`, TableFormer ACCURATE mode
- TOC: `similarity_threshold: 0.65`, quality tiers 70/40
- Monetary: Canonical unit = paise (1e9 paise = ₹1 crore)

## Deployment

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml up
```

Requirements: Python 3.11+, ≥16GB RAM, Qdrant

## Documentation

- `docs/API_LAYER_ANALYSIS.md` - API layer gap analysis and implementation
- `docs/PIPELINE_INTEGRITY_AUDIT.md` - Pipeline verification
- `docs/guides/PARSING_PIPELINE.md` - Pipeline architecture
