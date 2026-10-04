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

## Git Commit Rules

- **NO** `Co-Authored-By` lines in commits - ever
- Keep commit messages concise and human-like
- Use imperative mood: "Fix bug" not "Fixed bug" or "Fixes bug"
- One-line summary, max 72 characters
- No verbose explanations unless absolutely necessary

## Git Workflow (pipeline-review fixes)

The fixes in `docs/pipeline-review/step3_fix_list.md` land through one PR per work package.

**Branches**
- Integration branch: `feature/gcp-migration`. Never commit to it directly, never force-push or rewrite it, never push to `main`.
- Per PR: `git switch feature/gcp-migration && git pull`, then `git switch -c fix/<nn>-<short-name>`.
- Never branch one PR branch from another. Parallel PRs rebase onto `feature/gcp-migration` after the earlier one merges.

**Agents and worktrees**
- Agents work in worktrees spawned while the PR branch is checked out (`worktree.baseRef` is `head`).
- List each agent's files before spawning; two agents never edit the same file.
- Main session only: `main.py`, `parallel_runner.py`, `semantic_enrichment_service.py`, `assembly_service.py`, `src/core/data_contracts.py`, `parsing_config.yaml`, `enrichment_patterns.yaml`, `.github/workflows/*`, `docs/pipeline-review/implementation_log.md`.
- Agents commit only in their worktree: no push, PR, merge, workflow dispatch or GCS writes.
- No poetry env per worktree: use the main checkout's interpreter and confirm `import src` resolves to the worktree.

**Integration**
- One commit per fix-list row on the PR branch (`git merge --squash worktree-<name>`).
- Message: `<type>(<phase>): <what changed> [<issue IDs>]`, e.g. `fix(phase10a): escape {input} in summary prompts [D-10a-01]`.
- Keep the PR branch linear; remove each worktree and its branch after integrating.

**Before pushing**
- On the PR branch: unit tests, `score_gold.py`, `preflight_check.py` and the Step 1 scripts for the issues claimed. Log before/after numbers in `implementation_log.md`.

**Pull request**
- Push only the PR branch. `gh pr create --base feature/gcp-migration`, titled `PR <nn>: <work packages> - <summary>`, body = fix IDs (one line each) then before/after numbers.
- Wait for approval; the user squash-merges. Then pull `feature/gcp-migration`, delete the local PR branch, `git worktree prune`, and check no `fix/*` or `worktree-*` branches remain.
- Workflow file changes go in their own PR.

## Pipeline Configuration

Centralized in `parsing_config.yaml`:
- Triage: `text_threshold: 150` chars/page
- Layout: `confidence_threshold: 0.65`, TableFormer ACCURATE mode
- TOC: `similarity_threshold: 0.65`, quality tiers 70/40
- Monetary: Canonical unit = paise (1e9 paise = ₹1 crore)
