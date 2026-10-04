# Consumer inventory: output fields (before PR 2)

Read-only Explore agent, 2026-10-04, `fix/01-critical-fixes` at b12a993.
Paths are relative to the repo root.

Unit reminder:
- 1e9 converts paise to crore. This is correct for `normalized_inr`, `total_amount_inr` and `monetary_value`, which hold paise.
- 1e7 converts rupees to crore. It is wrong for these fields.

## 1. Money fields

| file:line | role | use | unit | risk |
|---|---|---|---|---|
| `src/core/data_contracts.py:351,366-375` | schema | `normalized_inr`, `total_amount_inr` (sum), `monetary_value` (max), `monetary_value_crore` | paise / paise / paise / crore | The `_inr` names are misleading |
| `src/parsing_pipeline/modules/enrichment/monetary_processor.py:44,310-335` | produces | `normalize_to_paise` | paise | the root of everything below |
| `src/parsing_pipeline/modules/enrichment/finding_extractor.py:796,824-831,851-855,1019-1047` | produces / consumes | sum, max, `/1e9`, severity from the sum | paise→crore | severity is silently wrong if the unit changes |
| `src/parsing_pipeline/modules/semantic_enrichment_service.py:797-800,887-908,917-922,957-969` | produces stats | headline = distinct `monetary_value`; raw / exec / dup totals from the sum | paise→crore | feeds the overview and frontend |
| `src/parsing_pipeline/modules/assembly_service.py:1103-1104` | produces chunk `structured_data` | `total_amount_crore` = **max**; `total_amount_inr` = **sum** | crore / paise | the name clashes with the Qdrant field (next row) |
| `src/rag_pipeline/embedding_service.py:510-512` | produces Qdrant `total_amount_crore` | `total_amount_inr / 1e9` (**sum**) | paise→crore | **HIGH**: a rename or unit change silently corrupts filters, LLM tags and citations |
| `src/rag_pipeline/qdrant_service.py:173,508` | consumes | FLOAT index, `RetrievedChunk` | crore | None on rename |
| `src/rag_pipeline/models.py:39,59,73-74,215,239,260-261,317` | consumes | LLM tag "Amount: ₹X crore", citations | crore | the LLM sees a sum labelled as the finding amount |
| `src/rag_pipeline/rag_service.py:2118`, `retrieval_service.py:964`, `cli.py:54,190-191` | consumes | citations, snippet, range filter | crore | pass-through / filter |
| `src/api/services/streaming_wrapper.py:148,179`, `search_service.py:503`, `api/models.py:85,416` | consumes | API citations and search | crore | pass-through |
| `src/entity_graph/mention_indexer.py:27-42,274` | consumes | `finding_amount_crore()` | correct (fixed in PR 1) | the `amount_crore` fallback is dead |
| `src/entity_graph/models.py:78`, `entity_service.py:256-270,432`, `api/routes/entities.py:95-102` | consumes `EntityMention.amount_crore` | filter, sort, output | crore | the DB must be re-indexed after the fix |
| `src/batch_pipeline/process_results.py:117,126` | produces overview `findings_list[].amount_crore` | `monetary_value / 1e9` | paise→crore | **HIGH** |
| `src/api/routes/overview.py:206-210` | consumes | min/max filter | crore | — |
| `src/batch_pipeline/prompts/summary_variants.py:211,225,234` | consumes | prompt text, sort | crore | low |
| `src/api/services/report_service.py:286-290` | consumes `semantic.monetary_statistics.total_amount_crore` | `monetary_impact` string | crore | **EXISTING BUG**: no producer writes `monetary_statistics`, so it is always None, and the frontend shows N/A |
| `frontend/hooks/useReports.ts:15,120`, `frontend/index.tsx:555-590` | consumes `monetary_impact` | parses "₹X crore"; `index.tsx:585` does `/10000` and labels it "L Cr" | crore | **EXISTING BUG**: 1 lakh crore = 100,000 crore, so the figure is 10× too large |
| `frontend/index.tsx:703,897`, `lib/api.ts:34,229-238,725`, `types.ts:113,169-178,436`, `components/Entity/EntityFindingsTab.tsx:222-226`, `utils.ts:194` | consumes | display | crore | — |
| `scripts/pipeline/extract_other_findings.py:51-60,135` | consumes `total_amount_inr` | `/1e7` as "Cr" | **rupees (wrong)** | **EXISTING BUG**: 100× too large |
| `scripts/utils/verify_monetary_fixes.py:102-163` | consumes | `/1e9` | correct | — |
| `scripts/evaluation/run_baseline_diagnostics*.py`, `scripts/debug/probe_amounts.py` | consumes | counts / debug | — | low |

## 2. `content_type`

- **Allowed values:** a Pydantic `Literal` at `data_contracts.py:99-107,200-208`: `paragraph`, `table_markdown`, `image_caption`, `chart_data_path`, `list`, `header`, `footnote`.
- **A new value** (e.g. `list_item`) is a hard ValidationError until the Literal is extended. Once extended, every consumer handles it silently.
- **Producers:**
  - `text_extractor.py:110-130`: header, list or paragraph. The footnote label maps to paragraph.
  - `content_extraction_service.py`: :433/:754 table, :663 footnote, :809 image_caption, :915 paragraph.
  - `pdfplumber_table_extractor.py:142`.
  - `chunking_service.py:975` embeds the type in the chunk ID.
  - The Qdrant-only types `chapter_summary` and `section_summary` come from `indexer.py:242,265` and `hierarchical_retriever.py:318,341`.

| file:line | effect of a new or renamed value | risk |
|---|---|---|
| `src/parsing_pipeline/modules/enrichment/finding_extractor.py:749` | only `paragraph` and `list` can become findings, so `list_item` and `footnote` never do | **high** |
| `src/batch_pipeline/prompts/summary_variants.py:286,324`; `overview_extraction.py:389-390` | header, list, footnote and list_item are dropped from the summary and overview input | medium |
| `src/api/services/asset_service.py:348-364,553` | only paragraph and header are scanned for Figure/Table titles | medium |
| `src/rag_pipeline/retrieval_service.py:172-220` | the neighbour chunk-ID regex `_(\w+)_(\d+)$` breaks on a hyphenated type | medium |
| `src/parsing_pipeline/modules/chunk_filter_service.py:38-45,100,156,182` | no `MIN_LENGTH` entry for footnote; `list_item` escapes the garbage filter | medium |
| `src/parsing_pipeline/modules/chunking_service.py:231,332,351,368` | `list_item` takes the non-paragraph path | medium |
| `src/parsing_pipeline/modules/assembly_service.py:248,575,667,756,790` | the footnote index is built only from `footnote` | medium |
| `semantic_enrichment_service.py:748`, `evidence_linker.py:345`, `main.py:896-947` | compare against `"table"` and `"figure"`, which are never produced, so the evidence linker gets 0 tables and the stats are always 0 | **existing bug** |
| `recommendation_extractor.py:286,421`, `contextual_caption_service.py`, `hierarchy_enricher.py:528-551`, `executive_summary_parser.py:137-143`, `cross_reference_resolver.py:85`, `validation_service.py:361,435-461,750` | allow/deny lists include or exclude new values silently; `validation_service` compares against a never-produced `"page_number"` | low–medium |
| `embedding_service.py:731-741,781,838`, `qdrant_service.py:163,505`, `batch_pipeline/enrichment/*`, `scripts/evaluation/*` | pass-through or silently skipped | low |

## 3. Pages: `source_page_logical` / `source_page_physical`

**No API or frontend consumer displays a true logical page.** `page_range_logical` has no consumer outside the parsing pipeline.

| file:line | use | issue |
|---|---|---|
| `src/rag_pipeline/embedding_service.py:841-842` | payload `page_logical=str(...)` | a None value is stored as the string "None" |
| `src/rag_pipeline/models.py:150-152,165,211`; `rag_service.py:2114`; `corrective_rag.py:435-437` | citation page = physical+1 | the 1-based conversion happens here |
| `src/api/services/streaming_wrapper.py:133-144,168-176` | sets `page_logical=str(page)` **and** `page_physical=page` (page is already +1) | the "logical" page is fake; the comment at `api/models.py:81` says 0-based |
| `frontend/index.tsx:428`, `stores/appStore.ts:321` | `targetPage = page_physical + 1` | **EXISTING BUG**: a citation opens the next page |
| `frontend/lib/citationUtils.ts:132-136,184-188` | mixed lookups | works by accident |
| `src/rag_pipeline/retrieval_service.py:797,808,835,960`; `api/services/search_service.py:500`; `frontend/components/Home/SearchResultRow.tsx:349` | `FindingSnippet.page = physical` with no +1, shown as "p.N" | **off by one** (the other direction) |
| `src/entity_graph/mention_indexer.py:199,282,325,353`; `entity_service.py:429`; `frontend/components/Entity/EntityMentionsTab.tsx:72-73,175`; `EntityFindingsTab.tsx:96,221` | 0-based page passed to `openHomePdf` (1-based, `HomePDFPanel.tsx:56`) | **off by one**; page 0 doesn't navigate at all |
| `src/api/services/asset_service.py:356-412,479,557` | +1 | correct |
| `src/batch_pipeline/process_results.py:109-110,130` → `frontend/index.tsx:417,846` | overview `page_start` is 0-based | likely off by one (not fully verified) |
| `src/batch_pipeline/prompts/overview_extraction.py:197,405`; `summary_variants.py:292` | "p.{page}" given to the LLM, 0-based | the generated summaries cite pages off by one |

## 4. `processed/manifest.json`

- **Writers:** `assembly_service.py:67-86,906-1007` (load–modify–write; `output_file` is a basename with no tier), several `AssemblyService` instances in `main.py:578,1167,1712-1724` and `parallel_runner.py:492-511`. Each caches the manifest, so the last writer wins.
- **Upload:** `gcs_integration.py:185-210`, which is dead code.
- **Defined but never read:** `src/api/config.py:83-87` (`MANIFEST_PATH`) and `src/api/gcs_sync.py:231-244`.
- **Do NOT use the manifest:** `report_service.py:222`, `report_registry.py:257`, `mention_indexer.py:427` and `asset_service.py:296-301`. They glob `**/*_chunks.json`. The indexer reads it since PR 1, to skip unfinished reports.
- **Expects a per-tier manifest:** `scripts/migration/migrate_union_data.py:198-211,247-299` expects `processed/union/manifest.json`, so today it finds nothing.
- **Test:** `tests/parsing_pipeline/unit/test_run_quality_fixes_unit.py:90-104`.

**Sharding is low risk for consumers.** The real problems are the basename-only `output_file` and lost writes between instances.

## New issues found (not in the Step 1/2 lists)

| ID | Issue | Where |
|---|---|---|
| N-01 | A citation opens the page after the cited one (+1 applied twice) | `streaming_wrapper.py:143-144` + `frontend/index.tsx:428`, `stores/appStore.ts:321` |
| N-02 | Search snippets and entity mentions/findings show 0-based pages as 1-based; page 0 doesn't navigate | `retrieval_service.py:960`, `mention_indexer.py`, `EntityMentionsTab.tsx`, `EntityFindingsTab.tsx` |
| N-03 | Report `monetary_impact` is always N/A (it reads `monetary_statistics`, which doesn't exist) | `src/api/services/report_service.py:286-290` |
| N-04 | The "L Cr" display divides by 10,000, but 1 lakh crore = 100,000 crore | `frontend/index.tsx:585` |
| N-05 | `extract_other_findings.py` treats paise as rupees (100×) | `scripts/pipeline/extract_other_findings.py:51-60` |
| N-06 | The Qdrant `total_amount_crore` holds the sum, while chunk `structured_data.total_amount_crore` holds the max | `embedding_service.py:510-512` vs `assembly_service.py:1103-1104` |
| N-07 | Summary and overview prompts cite 0-based pages | `overview_extraction.py:197,405`, `summary_variants.py:292` |
