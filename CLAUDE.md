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
| Chat/RAG | gemini-3.5-flash | $0.50 / $3.00 |
| Batch Summaries | gemini-3.5-flash | $0.50 / $3.00 |
| TOC Validation | gemini-3.6-flash | $1.50 / $7.50 |
| Embeddings | text-embedding-005 | $0.00625 |

### Claude Batch Mode (Optional)

```bash
USE_CLAUDE_BATCH=true           # Use Claude for batch summaries
ANTHROPIC_API_KEY=...           # Required for Claude
```

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

- **TOC Extraction:** Phase 4 bucketing → Phase 5.5 reconciliation → Phase 5.7 LLM validation
- **Table Extraction:** pdfplumber → Docling TableFormer → Gemini fallback (0.911 TEDS)
- **Semantic Enrichment:** Finding classification, severity tiers, 87+ regex patterns
- **RAG:** Hybrid dense+BM25 search, Cohere reranking, parent-child chunking
- **API:** 48 endpoints, SSE streaming, hierarchical summaries

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
