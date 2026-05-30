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

## Pipeline Configuration

All pipeline thresholds are centralized in `parsing_config.yaml`. Key settings:
- **Triage:** `text_threshold: 150` chars/page for native_text vs scanned classification
- **Layout:** `confidence_threshold: 0.65`, TableFormer mode: ACCURATE
- **TOC Reconciliation:** `similarity_threshold: 0.65`, quality tiers at 70/40
- **LLM Validation:** Claude Haiku for low-quality TOCs (<50 score)
- **Canonical monetary unit:** Paise (1e9 paise = ₹1 crore). All `normalized_inr` fields store integer paise.

## Known Issues

1. Phase 10a summary generation needs end-to-end testing
2. Some files use hardcoded `Path("data/processed")` instead of config
3. Series chat doesn't show year badges yet

## Status

Fully operational multi-tier system: 97% TOC accuracy, 95% citation match rate. Home UI full-stack implementation completed.

**P0 Bug Fixes:** ✅ COMPLETED (188 tests)
**P1 Enhancements:** ✅ COMPLETED (113 tests + 10 skipped)
**P2 Polish Items:** 🔜 NEXT (Plan approved, Revision 2)

**Total tests:** 300+ passing

**Next up:** P2 Implementation — 5 data quality polish items (9-14 hours total)

## Completed: P0 Bug Fixes

**Plan:** `docs/plans/CAG_P0_PLAN.md` (Revision 2, approved for implementation)

**9 P0 bugs in 3 phases (26-30 days total):**

**Phase 1 - Foundational Data Quality:**
- P0-01: Monetary extraction (Indian comma grouping, dedup, year rejection, explicit-total preference)
- P0-06: Deterministic report ID generation (zero-padding)

**Phase 2 - Hierarchy & Table Integrity:**
- P0-05: Triage misclassification (blank-page skipping, median instead of mean)
- P0-03: Multi-page table merger (chain iteration, tier-3 fallback, DLQ)
- P0-02: Phase 5.5 TOC validation (empty-TOC handling, noise rejection)
- P0-04: Chapter L1 promotion guardrails (orphan-section detection)

**Phase 3 - Semantic Enrichment:**
- P0-07: Finding-type classifier ("Audit observed..." umbrella pattern, tier gates)
- P0-08: Recommendation extraction (list-after-cue pattern)
- P0-09: Section classifier taxonomy expansion

**Key files for P0 work:**
- `src/parsing_pipeline/modules/enrichment/monetary_processor.py` (P0-01)
- `src/parsing_pipeline/modules/enrichment/finding_extractor.py` (P0-01, P0-07)
- `src/parsing_pipeline/modules/toc_reconciliation_service.py` (P0-02, P0-04)
- `src/parsing_pipeline/modules/multi_page_table_handler.py` (P0-03)
- `src/parsing_pipeline/modules/triage_service.py` (P0-05)
- `src/parsing_pipeline/modules/manifest_ingestion_service.py` (P0-06)
- `src/parsing_pipeline/modules/enrichment/recommendation_extractor.py` (P0-08)
- `src/parsing_pipeline/modules/enrichment/section_classifier.py` (P0-09)

---

## P0 Implementation Progress

**Plan document:** `docs/plans/CAG_P0_PLAN.md` (Revision 2)

### ✅ Phase 1 COMPLETED (2026-05-30)

#### P0-01: Monetary Extraction Overhaul
**Files modified:**
- `src/parsing_pipeline/modules/enrichment/monetary_processor.py`
- `src/parsing_pipeline/modules/enrichment/finding_extractor.py`
- `src/parsing_pipeline/modules/semantic_enrichment_service.py`

**Changes:**
1. ✅ Year rejection pattern (e.g., "Rs 2003") - verified working
2. ✅ Amount-based deduplication with 5% tolerance
3. ✅ Explicit-total preference heuristic - new `extract_monetary_values_with_preference()` method
4. ✅ Populate `monetary_value` (singular) and `monetary_value_crore` fields in findings
5. ✅ Sanity-check red flag for implausible totals (tier-specific: Union ₹5L cr, State ₹1L cr, Local ₹10K cr)

**Tests:** `tests/parsing_pipeline/unit/test_monetary_processor_unit.py` (21 tests passing)

#### P0-06: Deterministic Report ID Generation
**Files modified:**
- `src/parsing_pipeline/modules/manifest_ingestion_service.py`
- `scripts/canonicalize_report_ids.py` (new migration script)

**Changes:**
1. ✅ Zero-padding normalization (`num_part.zfill(2)` - "4" → "04")
2. ✅ Format validation via `_validate_report_id_format()` method
3. ✅ Legacy format fallback via `_check_legacy_report_id()` method
4. ✅ Migration script for renaming legacy files to canonical format

**Tests:** P0-06 tests in `tests/parsing_pipeline/unit/test_manifest_ingestion_unit.py` (7 tests passing)

### ✅ Phase 2 COMPLETED (2026-05-30)

#### P0-05: Triage Misclassification
**File modified:** `src/parsing_pipeline/modules/triage_service.py`

**Changes:**
1. ✅ Skip blank pages (<20 chars) in sampling via `skip_blank_pages` option
2. ✅ Use median instead of mean via `use_median` option (robust to outliers)
3. ✅ Widen borderline band from 0.7-1.3 to 0.4-1.5 (`BORDERLINE_BAND_LOW/HIGH`)
4. ✅ Sample from mid-document (pages 10-20) via `sample_mid_document` option
5. ✅ All new options enabled by default, can be disabled for backward compat

**Tests:** `tests/parsing_pipeline/unit/test_triage_service_unit.py` (25 tests passing)

#### P0-03: Multi-page Table Merger
**File modified:** `src/parsing_pipeline/modules/multi_page_table_handler.py`

**Changes:**
1. ✅ Increase gap tolerance from 2 to 3 pages (`MAX_PAGE_GAP = 3`)
2. ✅ Add missing-page detection via `_detect_missing_pages()` method
3. ✅ Add DLQ red flag `multi_page_table_page_lost` for missing pages
4. ✅ Statistics tracking for `missing_pages_detected` and `dlq_entries`

**Tests:** `tests/parsing_pipeline/unit/test_multi_page_table_handler_unit.py` (32 tests passing)

#### P0-02: Phase 5.5 TOC Validation
**File modified:** `src/parsing_pipeline/modules/toc_reconciliation_service.py`

**Changes:**
1. ✅ Empty-TOC explicit handling (separate branch in reconcile logic)
2. ✅ Noise rejection patterns (`NOISE_PATTERNS`) for paragraph refs, source citations, page numbers
3. ✅ Quality cap at 85 (`QUALITY_CAP`) for Phase 5.7 eligibility
4. ✅ Parent deduplication via `_deduplicate_parents()` method

**Tests:** P0-02 tests in `tests/parsing_pipeline/unit/test_toc_reconciliation_unit.py` (15 tests)

#### P0-04: Chapter L1 Promotion Guardrails
**File modified:** `src/parsing_pipeline/modules/toc_reconciliation_service.py`

**Changes:**
1. ✅ Chapter pattern promotion to L1 via `_promote_chapters_to_l1()` method
2. ✅ Patterns: Chapter/Annexure/Appendix (Arabic/Roman numerals)
3. ✅ L1 count sanity check (`MAX_L1_COUNT = 15`) with red flag
4. ✅ Orphan section detection via `_detect_orphan_sections()` method

**Tests:** P0-04 tests in `tests/parsing_pipeline/unit/test_toc_reconciliation_unit.py` (11 tests)

### ✅ Phase 3 COMPLETED (2026-05-30)

**Pre-Phase 3 Baseline (Step 6.5):**
- Finding 'other' ratio: 47.1%
- Section 'other' ratio: 90.5%

#### P0-07: Finding-type Classifier Pattern Expansion
**File modified:** `src/parsing_pipeline/modules/enrichment/finding_extractor.py`

**Changes:**
1. ✅ Umbrella pattern detection ("Audit observed/noticed/found that...") with deficiency keyword extraction
2. ✅ `DEFICIENCY_TO_TYPE_MAP` mapping 30+ deficiency keywords to finding types
3. ✅ Tier-specific taxonomy gates (`TIER_ALLOWED_TYPES`) for Union/State/Local
4. ✅ Non-finding rejection patterns (`NON_FINDING_PATTERNS`) for Brief Snapshot, footnotes, captions
5. ✅ Additional patterns for NON_COMPLIANCE, PERFORMANCE_SHORTFALL, SYSTEM_DEFICIENCY

**Tests:** `tests/parsing_pipeline/unit/test_finding_extractor_p07_unit.py` (26 tests passing)

#### P0-08: Recommendation Extraction Enhancements
**File modified:** `src/parsing_pipeline/modules/enrichment/recommendation_extractor.py`

**Changes:**
1. ✅ List-after-cue pattern ("We recommend that:\n1. ...") via `_extract_list_after_cue()` method
2. ✅ Verb rejection patterns (`VERB_REJECTION_PATTERNS`) for PAC/Guideline citations
3. ✅ Enhanced addressee extraction patterns (`ADDRESSEE_PATTERNS`)
4. ✅ `_is_verb_false_positive()` method to filter PAC observations and rule citations

**Tests:** `tests/parsing_pipeline/unit/test_recommendation_extractor_p08_unit.py` (20 tests passing)

#### P0-09: Section Classifier Taxonomy Expansion
**Files modified:**
- `src/parsing_pipeline/modules/enrichment/section_classifier.py`
- `src/core/data_contracts.py`
- `src/parsing_pipeline/modules/semantic_enrichment_service.py`

**Changes:**
1. ✅ Expanded `SectionType` enum with 14 new types: financial_management, employment, execution, planning, capacity_building, grievance_redressal, impact, monitoring_evaluation, compliance_review, performance_audit, infrastructure, service_delivery, regulatory, environment
2. ✅ Added 70+ patterns for new section types in `SECTION_TYPE_PATTERNS`
3. ✅ Added `section_other_ratio_high` red flag (>70%) in semantic_enrichment_service

**Tests:** `tests/parsing_pipeline/unit/test_section_classifier_p09_unit.py` (32 tests passing)

**Post-Phase 3 Results:**
- Section 'other' ratio: 63.3% (target <70% ✅ achieved)
- Finding 'other' ratio: requires re-processing pipeline (target <40%)

### Verification Gates

Post-Phase 3 metrics:
- `monetary_total_crore` within 10% of ground-truth
- Finding precision ≥85% on labeled sample
- No noise parents (`^\\(Paragraph`, `^\\(Source:`)
- Multi-page tables have continuous `source_pages` or missing pages in DLQ
- Section 'other' ratio <70% ✅
- Finding 'other' ratio <40% (pending re-processing)

---

## P1 Implementation Progress

**Plan document:** `docs/P1_IMPLEMENTATION_PLAN.md` (Revision 2)

**Note:** P1-13 was DROPPED (expected behavior, not a bug per plan analysis).

### ✅ Phase A COMPLETED (2026-05-30)

#### P1-10: Entity Extraction Filters
**File modified:** `src/parsing_pipeline/modules/enrichment/entity_extractor.py`

**Changes:**
1. ✅ Stuttered text rejection (tokenizer artifacts like "MaharashtraMaharashtra")
2. ✅ State name filtering (imported STATE_CODES from manifest_ingestion_service)
3. ✅ Job title pattern rejection (Block Education Officer, Chartered Accountant, etc.)
4. ✅ Document section pattern rejection (Chapter, Annexure, Appendix patterns)

**Tests:** `tests/parsing_pipeline/unit/test_entity_extractor_p110_unit.py` (32 tests)

#### P1-12: Year Extraction Fix
**File modified:** `src/parsing_pipeline/modules/assembly_service.py`

**Changes:**
1. ✅ Report No year extraction preferred over publication date
2. ✅ Conflict detection and logging when sources disagree
3. ✅ Red flag emission for year conflicts

**Tests:** `tests/parsing_pipeline/unit/test_assembly_service_p112_unit.py` (14 tests)

#### P1-14a: Hydration Validation
**File modified:** `src/parsing_pipeline/main.py`

**Changes:**
1. ✅ `_validate_phase_10b_completion()` method to verify Phase 10b hydration
2. ✅ Checks image_caption chunks for file paths vs descriptions

**Tests:** `tests/parsing_pipeline/unit/test_hydration_validation_p114a_unit.py` (9 tests)

### ✅ Phase B COMPLETED (2026-05-30)

#### P1-14b: Extraction Method Population
**Files modified:**
- `src/parsing_pipeline/extractors/pdfplumber_table_extractor.py`
- `src/parsing_pipeline/modules/content_extraction_service.py`
- `src/batch_pipeline/enrichment/gemini_visual_extractor.py`

**Changes:**
1. ✅ `extraction_method` field added to pdfplumber results (e.g., "pdfplumber-lines_strict")
2. ✅ `extraction_confidence` field populated from table extraction
3. ✅ Docling TableFormer sets extraction_method in content_extraction_service
4. ✅ Gemini visual extractor sets extraction_method when updating chunks

**Tests:** `tests/parsing_pipeline/unit/test_extraction_method_p114b_unit.py` (10 tests)

#### P1-14c: Visual Asset Registry Structure
**Files modified:**
- `src/core/data_contracts.py`
- `src/parsing_pipeline/modules/assembly_service.py`

**Changes:**
1. ✅ `VisualAssetRegistry` Pydantic model with total_tables, total_figures
2. ✅ `tables_by_section` and `figures_by_section` groupings by parent_chunk_id
3. ✅ `extraction_stats` aggregation by extraction_method
4. ✅ Updated `_build_visual_asset_registry()` method

**Tests:** `tests/parsing_pipeline/unit/test_visual_asset_registry_p114c_unit.py` (12 tests)

### ✅ Phase C COMPLETED (2026-05-30)

#### P1-15: Instrumentation Gap Closeout
**Files modified:**
- `src/parsing_pipeline/modules/triage_service.py` (P1-15a)
- `src/parsing_pipeline/modules/ocr_service.py` (P1-15b)
- `src/parsing_pipeline/modules/scaffolding_service.py` (P1-15c)
- `src/parsing_pipeline/modules/content_extraction_service.py` (P1-15d)
- `src/parsing_pipeline/modules/assembly_service.py` (P1-15e)

**Changes:**
1. ✅ P1-15a: Triage emit_io with output_data (classification, avg_chars, ratio)
2. ✅ P1-15b: OCR skip emit for native_text classification
3. ✅ P1-15c: Scaffolding page_count emit at phase entry
4. ✅ P1-15d: Content extraction emit with visual counts and error surfacing
5. ✅ P1-15e: Assembly Phase 8 entry/exit emits with content_types and visual counts

#### P1-16: Provenance Assertion in Trace
**Files modified:**
- `src/parsing_pipeline/instrumentation/trace_renderer.py`
- `src/parsing_pipeline/instrumentation/trace_emitter.py`
- `src/parsing_pipeline/modules/assembly_service.py`

**Changes:**
1. ✅ `assembly_timestamp` parameter added to TraceRenderer
2. ✅ Header shows Generated (UTC) and Assembly Timestamp (UTC)
3. ✅ Provenance WARNING if timestamps diverge >24 hours (stale JSON detection)
4. ✅ `_extract_assembly_timestamp()` method in trace_emitter

**Tests:** `tests/parsing_pipeline/unit/test_trace_instrumentation_p115_unit.py` (16 tests)

### ✅ Phase D COMPLETED (2026-05-30)

#### P1-11: Page Rotation Handling
**Files modified:**
- `src/parsing_pipeline/extractors/text_extractor.py`
- `src/parsing_pipeline/modules/content_extraction_service.py`

**Changes:**
1. ✅ `_get_page_rotation()` method for rotation detection (0, 90, 180, 270)
2. ✅ `_extract_text_with_rotation_handling()` for proper extraction on rotated pages
3. ✅ 90°/270° pages use dict-based extraction for correct reading order
4. ✅ Rotation tracking in `structured_data.page_rotation`
5. ✅ Red flag `rotated_page_detected` emission in content_extraction_service

**Tests:** `tests/parsing_pipeline/unit/test_text_extractor_rotation_p111_unit.py` (4 tests + 10 skipped without PyMuPDF)

### P1 Test Summary

**Total: 113 passed, 10 skipped**

| Phase | Items | Tests |
|-------|-------|-------|
| A | P1-10, P1-12, P1-14a | 55 |
| B | P1-14b, P1-14c | 22 |
| C | P1-15, P1-16 | 16 |
| D | P1-11 | 4 (+10 skipped) |

**Key files for P1 work:**
- `src/parsing_pipeline/modules/enrichment/entity_extractor.py` (P1-10)
- `src/parsing_pipeline/modules/assembly_service.py` (P1-12, P1-14c, P1-15e, P1-16)
- `src/parsing_pipeline/main.py` (P1-14a)
- `src/parsing_pipeline/extractors/pdfplumber_table_extractor.py` (P1-14b)
- `src/parsing_pipeline/extractors/text_extractor.py` (P1-11)
- `src/parsing_pipeline/instrumentation/trace_renderer.py` (P1-16)
- `src/parsing_pipeline/instrumentation/trace_emitter.py` (P1-16)

---

## P2: Data Quality Polish — NEXT

**Plan document:** `P2_IMPLEMENTATION_PLAN.md` (Revision 2, approved)

**5 items targeting data quality improvements (9-14 hours total):**

| Item | Description | Effort | Risk |
|------|-------------|--------|------|
| P2-20 | footnote_index type fix (dict not list) | 1h | Low |
| P2-18 | Blank-page extraction pre-check | 1-2h | Low |
| P2-21 | Temporal extraction guards (report_year bounds, FY end-year fix) | 2-3h | Low |
| P2-17 | OCR header normalization (Roman numerals: ITI→III, IT→II) | 3-4h | Low |
| P2-19 | Empty-parent cleanup (conservative artifact patterns only) | 2-3h | **Medium** |

**Implementation Order:** P2-20 → P2-18 → P2-21 → P2-17 → P2-19

**Key design decisions (Revision 2):**
1. **P2-19:** Dropped unsafe diagnostic patterns (`^\d`, `^[a-z]`) that would delete legitimate parents like "1.1 Introduction". Now uses only explicit artifact patterns (`^\d+_[A-Z]`, `^Blank\s+Page$`, etc.).
2. **P2-17:** Fixed layering issue — normalization applies to BOTH text_extractor.py (child content) AND toc_reconciliation_service.py (parent toc_entry from Docling). Fixed regex bug conflating IT→II vs ITI→III.

**Key files for P2 work:**
- `src/parsing_pipeline/modules/assembly_service.py` (P2-19, P2-20)
- `src/parsing_pipeline/modules/content_extraction_service.py` (P2-18)
- `src/parsing_pipeline/modules/enrichment/temporal_extractor.py` (P2-21)
- `src/parsing_pipeline/modules/semantic_enrichment_service.py` (P2-21)
- `src/parsing_pipeline/modules/ocr_normalizer.py` (P2-17, NEW)
- `src/parsing_pipeline/extractors/text_extractor.py` (P2-17)
- `src/parsing_pipeline/modules/toc_reconciliation_service.py` (P2-17, P2-19)