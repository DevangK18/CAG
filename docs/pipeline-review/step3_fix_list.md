# Step 3: Ranked fix list (for approval)

Built from:
- Step 1 (output audit, 49 issues);
- the Step 2 agent reviews: A 23, B 30, C 38, D 25;
- the three main-session deep dives, measured against 6 hand-labelled gold reports.

Every issue ID in those reports maps to one work package (WP) in the index at the end, so
nothing is dropped. The detail for each ID (`file:line`, evidence, fix sketch) is in its source
report.

**Status: FINAL DRAFT, awaiting approval.** All 4 agent reports and the deep dives are merged.
Nothing has been implemented.

## The headline picture

1. **Two critical bugs corrupt what users see.**
   - State and local summaries are invented because the prompts never contain the report
     (D-10a-01, an f-string bug, verified).
   - Phase 7.5 duplicates parents and invents a 1,645-child "Corporation" section in BR
     (B-7.5-01).
2. **Findings extraction misses about 70% of real findings. It is not over-extracting.**
   - Against 899 hand-labelled findings in 6 reports, precision is about 95% and recall
     19–35% (68% for the ATIR).
   - The LLM "validator" makes it worse: 26 of the 33 findings it removed were real.
   - Recommendations miss whole styles: ATIR 0/11, `2) MoES may…`, passive "may be ensured".
   - These are all a Phase 9 design problem, not a tuning problem.
3. **Money figures are unreliable.**
   - "₹1.5 lakh crore" is read as ₹1.5 lakh.
   - "24.53 lakh candidates" is read as money.
   - `million`/`billion` are 10× too large.
   - Finding totals sum nested amounts.
   - The entity graph reads paise as rupees (100× too large).
   - The best regex method picks the right impact amount only 56% of the time.
4. **Document structure is the upstream root of many symptoms.** The TOC quality score measures
   shape, not content (A-TQ-01), so:
   - merger-junk bookmarks win;
   - the printed contents parser breaks on state/local layouts;
   - Phase 5.5 promotes recommendation boxes and ₹-sentences to headings;
   - chunks are attached to the wrong parent (B-7-01).
5. **Runs lie about success, and stale data resurrects.**
   - Exit code is always 0 (C-R-01).
   - Failed reports keep old output (C-R-02).
   - GCS deletions come back because the VM rsync has no `-d` (C-R-11).

## Decisions needed from you

| # | Decision | Recommendation |
|---|----------|----------------|
| D1 | Phase 9: replace regex-first extraction with **per-section LLM extraction with grounding**, keeping regex as a cross-check (WP-9A) | **Yes.** No regex tuning closes a 70% recall gap. About 10–25 Vertex calls per report, gated on the gold scorer |
| D2 | Stop the LLM validator from deleting findings **now** (a config-only change), before WP-9A lands | **Yes** |
| D3 | `run-parsing.yml` changes: `rsync -d` on sync-down, a real exit status, `skip_phases` parsing (WP-R1). You asked to keep this workflow as-is | Needed for correctness. Minimal, reviewed diff only, shown to you before commit. Mirror it in `run-parsing-gpu.yml` |
| D4 | After fixes, **re-run all union reports** (the current union output predates 2026-09-25 fixes) and regenerate the 6 state/local summaries | Yes, once WP-0 and WP-S land; the GPU VM makes it about 6 h |
| D5 | Your pending GCS cleanup: also clean `cag-parsing-vm:/var/tmp/cag/data/` or it comes back (C-R-11) | Do it after WP-R1, or I give you the exact VM commands |
| D6 | Manifest data fixes (yours): 2025_18 report no.; HP rows with no report no.; state/local manifests lack Department/Audit Category columns | Your call. WP-1 infers ATIR from the title regardless |

## Work packages (in implementation order)

### WP-0: Critical, small, do first
| Fix | IDs | Where | Effort |
|---|---|---|---|
| Escape `{input}` in the 10 state/local summary templates (or stop mixing f-strings with `.format`); add a test that every tier's rendered prompt contains the report data | D-10a-01, P10a-01 | `batch_pipeline/prompts/summary_variants.py:449,515,683,774,969,1067,1263,1345,1550,1658`, `:364` | S |
| Phase 7.5: detect each section once (the narrowest parent wins), unique IDs, no invented L1s; post-sync touches only enriched children | B-7.5-01/02/03, P7-01 | `hierarchy_enricher.py` (see B report) | M |
| LLM validator: never drop on INVALID; store the verdict; count UNCERTAIN/failed as `unverified` (interim for D2) | llm_validation §1–8, P9-14 (part) | `semantic_enrichment_service.py:657-688`, `enrichment_patterns.yaml:337-341` | S |
| Heuristic TOC `self.logger`, which should be the module `logger` | A-4-05 | `scaffolding_service.py:1109` | S |
| Recommendation prompt/validator dead code | llm_validation §1 | `llm_validator.py` | S (folded into WP-9A) |

### WP-R1: Run integrity (workflow + orchestration)
| Fix | IDs | Where | Effort |
|---|---|---|---|
| Exit non-zero when any selected report fails or 0 reports match; `final_success` includes Phases 1–3 and 10; the workflow maps the exit code to status | C-R-01, A-1-01, P1-03, D hand-off | `main.py:193-197,1856-1864,2082,2100`; `run-parsing.yml:325-330` | S–M |
| On failure, move the old `*_chunks.json` aside (`.stale`), and have the indexer skip non-completed manifest entries | C-R-02, P1-04 | `assembly_service.py:957-979`; `indexer.py:81-83` | S |
| Mark "completed" only after the last requested phase | C-R-03 | `assembly_service.py:292` | S |
| Sync-down with `-d` (or wipe the VM copy); keep the upload without `-d` | C-R-11 | `run-parsing.yml:190-191`, GPU workflow equivalent | S |
| `skip_phases` comma parsing | C-R-06 | `run-parsing.yml:28,291`; `main.py:2025` | S |
| Per-run log file name (run ID and tier); stop rotation mid-run | C-R-05, pre-audit list | `main.py:1955,1975` | S |
| Shard `processed/manifest.json` per tier (or per report) with tier, run ID and path | C-R-04, P8-04 | `manifest_ingestion_service`, `assembly_service`, indexer | M |
| Keep red flags in production output (`processing_stats.red_flags`) | C-X-01 | `trace_emitter.py:293` | S |
| Upload the dead-letter-queue folder with the run | B hand-off | `run-parsing.yml:237-242` | S |
| Replace the "RAG readiness" score with checks for the real defects (preflight metrics) | C-8-10 | `validation_service.py` | M |

### WP-1: Ingestion, OCR, report type
| Fix | IDs | Where | Effort |
|---|---|---|---|
| OCR timeout scales with page count; reuse an existing complete output; `output_type: pdf`; log failures at ERROR | A-3-01/02, P1-01/02 | `ocr_service.py:113-116,166-178,213-228`; `parsing_config.yaml:35-41` | S |
| ATIR detection from title/cover; call `detect_report_type(task)` so ATIR/state profiles apply (fix the key `Title`) | A-1-03, C-9-02, P1-05 | `manifest_ingestion_service.py:151-174,671-679`; `report_type_profiles.py:223-264`; `main.py:1269`; `parallel_runner.py:275` | M |
| Apply the `--reports` filter before resolve/download; key the triage cache by PDF hash; minor defects | A-1-02/04/05/06, C-R-10, P1-06/07 | `main.py:240-249,399-454` | S |
| Infer department/subtype for state/local where the manifest lacks them (LLM overview fallback) | C-8-02, D hand-off | `assembly_service.py:337-346` | M |

### WP-S: Document structure (TOC → parents → chunks)
| Fix | IDs | Where | Effort |
|---|---|---|---|
| **A content-aware TOC quality score**: printed-contents verification rate, junk titles (`Binder1.pdf`, `Blank Page`), chapter coverage, heading-likeness | A-TQ-01, A-5.5-02 | `toc_quality.py`; `toc_reconciliation_service.py:69-70,229-272` | M |
| Source order: a verified printed contents beats bookmarks; reject merger-junk bookmarks | A-4-02, C-8-09, P4-02 | `scaffolding_service.py:476-483,734-825` | M |
| Printed-contents parser: 3-column Title \| Para \| Page layout, running headers, centred cells; "N \| P a g e" page numbers | A-4-01, A-4-03, P4-01 | `printed_toc_parser.py:24-38,98-172` | M |
| Phase 5.5 supplement: heading test (numbering, length, no ₹/sentence punctuation, font-style), no recommendation boxes; dedupe by chapter number; order by (page, y) | A-5.5-01/03/04/05, P5.5-01, P4-03 | `toc_reconciliation_service.py:48-57,473-775` | M |
| Heuristic TOC: multi-line banners, table rows, 100-page cap | A-4-04, A-4-07 | `scaffolding_service.py:1112-1430` | M |
| Phase 5.7: redesign as a keep/drop/relevel reviewer with the correct page offset, or delete | A-5.7-01/02, P5.7-01 | `toc_llm_validator.py` | M (or S to delete) |
| **Logical page = printed page number** (detected per page), not physical+1 | A-4-06, P8-03 | `scaffolding_service.py:1436-1451`; chunking accepts `None` | M |
| **Wrong-parent root cause:** heading positions are matched to TOC entries by title only, with no page check. Match on (title, page) and assign children in reading order. B measured wrong parents falling from 10–57% to about 0–7% | B-7-01, B-7-02, A-5.5-04, P7-02 | `toc_reconciliation_service.py:649-668`; `chunking_service.py:541-567,580,821-882` | M |
| Parent chunks carry tier, category, department, subtype | B-7-03, C-8-01, P8-01 | `chunking_service.py:582-640` | S |
| Fragment/heading-only parents; tiny caption/source/unit children merged into neighbours; stale parent counts | B-7-05, C-8-05, P7-03/04/05 | chunking, assembly | S–M |

### WP-6: Extraction fidelity (text and tables)
| Fix | IDs | Where | Effort |
|---|---|---|---|
| Keep Docling labels (footnote, caption, list item) instead of flattening to "Text"; link footnotes to their markers | B-5-01, B-6-19, P6-12 | `layout_analysis_service`, `content_extraction_service` | M |
| Garbage filter: exempt tables from the whitespace-ratio rule; stop dropping 148 "(₹ in crore)" unit lines, source lines, captions, chapter titles and repeated real headings (including "Recommendations" after the 2nd occurrence) | B-6-04, B-6-16, P6-02 (the GPU p.145 case) | `chunk_filter_service.py:37-45,150-174` | S |
| Sideways text on portrait pages is extracted reversed (129 pages in 5 reports); the text fix is demonstrated, the table fix is to derotate before pdfplumber | B-6-05, P6-01 | `text_extractor.py:146-213`; `pdfplumber_table_extractor.py:189-194` | M |
| Rupee from the "Rupee Foradian" backtick; year-range hyphen rejoin; curly-quote bug | B-6-06/07/08, P6-11 | `text_repair.py` | S |
| Tables: header-row heuristic, leading caption row, repeated first row, 1-row fragments, dropped page on merge, `(₹ in crore)` unit applied, `source_chunk_id` "temp" | B-6-09/10/11/12, B-7-04, B-6-01, P6-02/03 | `structured_table_extractor`, `multi_page_table_handler` | M |
| Table captions/numbers stored on the table chunk; registry caption | C-8-06, P6-04 | assembly, extraction | S |
| Vector-chart values kept in searchable text; chart values from 10b into text | B-6-18, D-10c-03, P6-05 | extraction; `visual_post_processor.py:523` | M |
| Images: real subtype classification (caption present), photos/banners not sent to the chart prompt, no local path as chunk text | B-6-14/15, D-10b-03/04, P6-06/07 | extraction; `gemini_visual_extractor.py:749-756,884-892` | M |
| Counters, M2-DLQ noise, ERROR-level fallbacks, layout confidence no-op, first-provenance-only | B-6-17, C-R-08, B-6-02/03, B-5-02/03, P6-08/09/10 | various | S |

### WP-9A: Findings and recommendations (redesign; decision D1)
| Fix | IDs | Where | Effort |
|---|---|---|---|
| **Per-section LLM extraction**: verbatim spans, grounded back to chunk text, with type, impact-amount span, addressee, rec number, exec-summary/chapter dedup. Regex candidates kept as a logged cross-check | P9-01/02/03/13, extractor_precision_recall, llm_validation "Revised" | new module plus `semantic_enrichment_service` | L |
| Interim regex fixes, until 9A lands or as a fallback: remove period/table-reference `NON_FINDING` prefixes; exclude replies/rebuttals; recommendation patterns for `N)`, roman numerals, passive "may be …", "The Department may …"; case-sensitive acronym subjects; cue-to-list-item association across chunks | extractor_precision_recall | `finding_extractor.py:202-240`; `recommendation_extractor.py` | M |
| Severity from the primary impact amount; amount-only dedup replaced | P9-04, C-9-11 | `finding_extractor.py:796-801`; `semantic_enrichment_service.py:764-870` | S |
| **Gate:** `score_gold.py` on the 6 gold reports: finding recall ≥ 80% at precision ≥ 90%, recommendation recall ≥ 90%, impact-amount match ≥ 80% | — | `docs/pipeline-review/step2/deep-dives/scripts/score_gold.py` → `tests/` | S |

### WP-M: Money
| Fix | IDs | Where | Effort |
|---|---|---|---|
| One-pass tokenizer: currency prefix with word boundary, compound units (lakh crore, thousand crore), ranges, no quantity nouns, exact-span dedup, correct million/billion | monetary M1–M8, P9-05 | `monetary_processor.py:85-94,264-272,317-326` | M |
| The primary impact amount comes from WP-9A (or `_identify_primary` as fallback); drop or rename the summed `total_amount_inr` | M9–M12, M15 | `finding_extractor.py:796`; `assembly_service.py:1103-1104` | S |
| **Paise/rupee naming**: `_paise` / `_crore` fields; fix the entity graph 100× error | M13, M14 | `data_contracts.py:351,366`; `entity_graph/mention_indexer.py:257` | S |
| Table cells: apply the "(₹ in crore)" unit; today `normalized_value` is off by 10⁷ | B-6-11 | `structured_table_extractor.py:44-53,662-678` | S |
| Unit tests from the harness plus gold-label amounts | — | `tests/` | S |

### WP-9B: Other Phase 9 linkers
| Fix | IDs | Where | Effort |
|---|---|---|---|
| Annexure links: resolve to the right appendix (147/254 are wrong today); fall back to appendix chunks when there are no appendix parents | C-9-03, P9-09 | `annexure_linker.py:50-120` | M |
| Evidence links: real content types and keys, "Appendix" recognised, paragraph resolution | C-9-01, P9-06 | `evidence_linker.py:343-462`; `semantic_enrichment_service.py:747-749` | M |
| Cross-references: skip the table's own caption, "Chapter-N" and Roman numerals, statute refs, paragraph lists | C-9-04, P9-08 | `cross_reference_resolver.py` | M |
| Exec-summary citations: standalone citation chunks, "&"/"to" ranges, "Paras" plural, the whole exec-summary subtree | C-9-05, P9-07 | `executive_summary_parser.py` | S–M |
| Previous-audit refs: word boundaries, exclude self | C-9-06, P9-10 | `temporal_extractor.py:40-44` | S |
| `audit_period`: single-year and "FY" forms; overview-LLM fallback | C-9-07, P9-15 | `temporal_extractor.py:14-27` | S |
| Section classification: after WP-S, classify from the TOC plus content; confidence semantics | C-9-08, P9-11 | `section_classifier.py` | M |
| Entities: acronym pattern, aliases, deterministic order | C-9-09, P9-12 | `entity_extractor.py` | S |
| Load or delete the dead YAML sections, so nobody tunes dead config | C-9-10 | `enrichment_patterns.yaml`, `pattern_loader.py` | S |
| Finding↔recommendation linking beyond ±5 pages | C-9-12 | `semantic_enrichment_service.py:711-726` | S |
| `section_type` propagation key; no enrichment fields in table `structured_data`; `extraction_confidence` key | C-8-07/08 | `assembly_service.py:257,1055-1141` | S |

### WP-L: Gemini throughput (shared rate limiter)
| Fix | IDs | Where | Effort |
|---|---|---|---|
| One adaptive limiter with a shared cool-down across phases (and VMs via GCS/lock or a per-VM budget); phase deadlines; bounded concurrency for Phases 9, 10a and 10b; retries report `unverified` rather than silently passing | P9-14, D-10b-01, X-02, C design | `src/core/gemini_client.py:81-123` + callers | M |
| Retry lost 10a variants and 10b charts; never overwrite a complete file with a partial one; unwrap single-element list JSON | D-10a-02, D-10b-02, P10a-02, P10b-02 | `batch_service.py:294-300,597-644`; `gemini_visual_extractor.py` | S |
| Token and cost recording for Phase 10 | D-M-04 | `gemini_client.py` | S |

### WP-10: Summaries and visuals quality
| Fix | IDs | Where | Effort |
|---|---|---|---|
| Chapter summaries see the whole chapter subtree; deeper parents summarised; no duplicate/fragment parents (after WP-S) | D-10a-03/04, P10a-03 | `batch_service.py:1205-1274,1441-1466` | M |
| Overview merge by exact report ID and run, never fuzzy | D-10a-05 | `merge_utils.py:16-61` | S |
| Summary input: findings ranked by the correct impact amount, real key tables, exec summary included; remove example numbers from prompts; add a grounding check (numbers must appear in the source) | D-10a-06/07/08 | `summary_variants.py:180-335` | M |
| Merge hierarchical summaries into parent `content_summary`; indexer path for summaries | C-8-04, D hand-off | assembly / indexer | S |
| 10b/10c: table re-extraction branch; TOC-table filter (75% false positives); no confidence overwrite; recorded model name | D-10b-05/06, D-10c-01/02 | `gemini_visual_extractor.py:680-720`; `visual_post_processor.py:277-330` | M |
| Correct `pdf_dir` per tier | D hand-off | `main.py:1583` | S |

### WP-X: Dead code and config hygiene (last)
| Fix | IDs |
|---|---|
| Delete or quarantine: `gcs_integration.py`, `pdfmux_router.py`, `toc_table_parser.py`, `excel_analysis.py`, the non-Vertex `batch_pipeline/enrichment/*` (about 3,000 lines, D-X-01), `Phase10Service`, `_archived_v1` | C-X-02, B-6-13, A report, D-X-01, D-10a-09 |
| Config: keys never read, reads outside the loader, the duplicate `llm_validation` names, env overrides for list/dict fields | C-C-01/02/03, A-4-07 |
| The parallel `--workers` path: fix the divergence or remove it | C-R-07 |
| The `cu121` line in `Dockerfile.parsing` (no-op); GPU start retries 6→15 | pre-audit list |

## Verification plan for every WP
1. Unit tests for each fix.
2. Run the pipeline locally or on the GPU VM on the 6 gold reports plus CG_2025_01 (OCR) and
   HP_2019, then:
   - run `preflight_check.py`;
   - run `score_gold.py` (the Phase 9 gate);
   - run the Step 1 metrics scripts (`step1/scripts/`) to show each Step 1 issue is gone.
3. Compare before and after in `implementation_log.md`.

## Suggested batching into PRs

| PR | WPs | Why grouped |
|---|---|---|
| 1 | WP-0 + WP-R1 | Small, high value, unblocks trusting runs |
| 2 | WP-M + WP-1 | |
| 3 | WP-S | The largest structural change; re-run gold reports after |
| 4 | WP-6 | |
| 5 | WP-L then WP-9A | The limiter first, because 9A needs it |
| 6 | WP-9B + WP-10 | |
| 7 | WP-X | |

Then: re-run union (D4).

## Index: every issue → work package

| Source | IDs → WP |
|---|---|
| Step 1 | P1-01/02 → WP-1; P1-03/04 → WP-R1; P1-05/06/07 → WP-1; P1-08 → D6 (yours); P4-01/02/03, P5.5-01/02, P5.7-01 → WP-S; P6-00 → D4; P6-01/02/03/04/05/06/07/08/09/10/11/12 → WP-6; P7-01 → WP-0; P7-02/03/04/05 → WP-S; P8-01 → WP-S; P8-02 → WP-1; P8-03 → WP-S; P8-04 → WP-R1; P9-01/02/03/04/13 → WP-9A; P9-05 → WP-M; P9-06–P9-12, P9-15 → WP-9B; P9-14 → WP-L; P10a-01 → WP-0; P10a-02, P10b-01/02 → WP-L; P10a-03, P10c-01 → WP-10; X-01 → verification tooling; X-02 → WP-L |
| Agent A | A-3-* → WP-1; A-1-* → WP-1 (A-1-01 → WP-R1); A-4-05 → WP-0; A-4-*, A-TQ-01, A-5.5-*, A-5.7-* → WP-S |
| Agent B | B-7.5-* → WP-0; B-7-* → WP-S (B-7-04 → WP-6); B-5-*, B-6-* → WP-6 (B-6-13 → WP-X) |
| Agent C | C-R-* → WP-R1 (C-R-07 → WP-X, C-R-08 → WP-6, C-R-10 → WP-1); C-8-01 → WP-S; C-8-02 → WP-1; C-8-03/05 → WP-R1/WP-S; C-8-04 → WP-10; C-8-06 → WP-6; C-8-07/08/09 → WP-9B/WP-S; C-8-10, C-X-01 → WP-R1; C-9-* → WP-9B (C-9-02 → WP-1, C-9-11 → WP-9A); C-C-*, C-X-02 → WP-X |
| Agent D | D-10a-01 → WP-0; D-10a-02, D-10b-01/02, D-M-04 → WP-L; D-10a-03–08 → WP-10; D-10b-03/04 → WP-6; D-10b-05/06, D-10c-* → WP-10; D-10a-09, D-X-01 → WP-X; D-M-01/02/03 → WP-L/WP-X (see D report) |
| Deep dives | llm_validation → WP-0 (interim) + WP-9A; monetary M1–M17 → WP-M; extractor_precision_recall → WP-9A |
| Pre-audit list | all items are covered by the IDs above; GPU items → WP-X |
