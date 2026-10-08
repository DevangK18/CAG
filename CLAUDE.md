# CLAUDE.md

## Project Overview

CAG Interactive Gateway: AI-powered system for querying India's public audit reports. Parses PDFs into structured JSON, enriches with semantic metadata, provides RAG-powered Q&A.

**Multi-tier support:** Union, State, and Local Body reports with tier-specific metadata.

## Repository Structure

```
CAG/
├── .github/workflows/      # CI/CD (deploy-api, run-parsing, terraform)
├── frontend/               # React + TypeScript + Zustand
├── infra/
│   ├── terraform/          # GCP Infrastructure as Code
│   └── scripts/            # deploy.sh, setup-gcp.sh
├── notebooks/              # Jupyter notebooks
├── scripts/
│   ├── debug/              # Diagnostic scripts
│   ├── evaluation/         # Embedding/RAG evaluation
│   ├── migration/          # Data migration utilities
│   ├── pipeline/           # Pipeline runners
│   └── utils/              # Misc utilities
├── src/
│   ├── api/                # FastAPI REST + SSE streaming
│   ├── batch_pipeline/     # Gemini batch processing
│   ├── core/               # Config, data contracts
│   ├── entity_graph/       # PostgreSQL entity storage
│   ├── observability/      # Cost tracking, logging
│   ├── parsing_pipeline/   # 10-phase PDF→JSON pipeline
│   └── rag_pipeline/       # Hybrid search, Qdrant, reranking
├── tests/                  # pytest test suite
├── Dockerfile              # API container (Cloud Run)
├── Dockerfile.parsing      # Parsing container (Compute Engine)
├── docker-compose.prod.yml # Local production testing
├── parsing_config.yaml     # Pipeline configuration
└── pyproject.toml          # Python dependencies
```

## Commands

```bash
# Setup
poetry install && cp .env.example .env
cd frontend && npm install

# Pipeline
python -m src.parsing_pipeline.main "manifest.xlsx"
python -m src.rag_pipeline.indexer --input-dir data/processed --recreate

# Run locally
uvicorn src.api.main:app --reload --port 8000
cd frontend && npm run dev

# Test
pytest --cov=src

# Deploy (GCP)
cd infra/scripts && ./setup-gcp.sh PROJECT_ID
cd infra/terraform && terraform apply -var-file=environments/prod.tfvars
```

## Configuration

### Google-Native Mode (Default - GCP Credit Billing)

```bash
# GCP Configuration (required)
GOOGLE_CLOUD_PROJECT=your-project-id
GOOGLE_API_KEY=...              # For Gemini API access
VERTEX_AI_REGION=us-central1

# Vertex AI Embeddings (20x cheaper than OpenAI)
USE_VERTEX_EMBEDDINGS=true      # Use text-embedding-005

# External services
COHERE_API_KEY=...              # Reranking
QDRANT_URL=http://localhost:6333

# Cloud Run (set automatically)
DATA_BUCKET=cag-data-xxx        # GCS bucket for data
DATA_DIR=/app/data              # Local data directory
```

**Gemini Models:**
| Component | Model | Cost (input/output per 1M) |
|-----------|-------|---------------------------|
| Chat/RAG | gemini-3.8-flash | $0.75 / $3.75 to 2026-12-31, then $1.50 / $7.50 |
| Overview, 4 summary variants | gemini-3.1-pro-preview | $2.00 / $12.00 (≤200K prompt) |
| Simple summary, chapter/section summaries, Phase 10b visuals, Phase 9 findings and recommendations | gemini-3.8-flash | as Chat/RAG |
| Query enhancement, routing, groundedness, canonicalisation | gemini-3.8-flash | as Chat/RAG |
| Embeddings | text-embedding-005 | $0.00625 |

Phase 10 models and Flash thinking levels are set in `src/core/phase10_models.py`. Every
Gemini call goes through one limiter (`src/core/gemini_limiter.py`), configured under
`gemini:` in `parsing_config.yaml`: a token budget per model (capacity x utilisation over a
60 s window, counted like Google's throughput metric), an in-flight ceiling per model, and a
429 retried alone. Utilisation steps down only while 429s stay high.

**Phase 9 findings and recommendations:** one Flash call per section
(`modules/enrichment/llm_finding_extractor.py`); the model returns chunk numbers, an anchor,
the type and the printed impact amount, and code checks each item against the text
(`llm_items.py`). Regex extractors are the cross-check and the fallback for a failed section.
Calls run in the main process; worker processes do the rest of Phase 9.

**Phase 10a order** (`batch_pipeline/phase10a_runner.py`): overviews at once; summaries
bottom-up over every parent with real text (`summary_tree.py`); the five variants once a
report's chapter summaries and overview are done. Phase 10b runs alongside 10a.

**Promoting a run:** `promote-run.yml` (manual, dry run by default) copies a test prefix into
the production paths; replaced files go to `quarantine/promote-<run id>/`.

## GCP Deployment

**Architecture:**
- **Cloud Run**: API + Frontend (scale-to-zero, $5-20/mo)
- **Compute Engine**: Parsing pipeline (spot instance, $15-25/mo)
- **Cloud Storage**: PDFs and processed JSON
- **Qdrant Cloud**: Vector database (free tier)

**CI/CD Workflows:**
- `deploy-api.yml` - Build and deploy to Cloud Run on push to main
- `run-parsing.yml` - Manual trigger for parsing pipeline
- `terraform.yml` - Infrastructure changes

**Estimated monthly cost:** $25-55 (within $300 GCP credit)

## Multi-Tier Architecture

**Tiers:** `government_body_type` = "union" | "state" | "local_body"

**Report ID Formats:**
- Union: `{year}_{serial}_{title}`
- State: `{ST}_{year}_{no}_{title}`
- Local: `{ST}_ATIR_{year}_{title}`

## Key Features

- **TOC Extraction:** Phase 4 bucketing → Phase 5.5 reconciliation
- **Table Extraction:** pdfplumber → Docling TableFormer → Gemini fallback (0.911 TEDS)
- **Semantic Enrichment:** Gemini findings and recommendations checked against the text, severity tiers, links to tables, appendices and paragraphs
- **RAG:** Hybrid dense+BM25 search, Cohere reranking, parent-child chunking
- **API:** 48 endpoints, SSE streaming, hierarchical summaries

## Import Structure

```python
from src.core.data_contracts import DocumentTask
python -m src.module.name
```

## Git Commit Rules

- **NO** `Co-Authored-By` lines in commits - ever
- Keep commit messages concise and human-like
- Use imperative mood: "Fix bug" not "Fixed bug" or "Fixes bug"
- One-line summary, max 72 characters
- No verbose explanations unless absolutely necessary

## Pipeline Configuration

Centralized in `parsing_config.yaml`:
- Triage: `text_threshold: 150` chars/page
- Layout: Docling labels kept (footnote, caption, list item), TableFormer ACCURATE mode
- TOC: `similarity_threshold: 0.65`, quality tiers 70/40
- Monetary: Canonical unit = paise (1e9 paise = ₹1 crore)
