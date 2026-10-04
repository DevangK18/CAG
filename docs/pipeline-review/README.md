# Parsing pipeline review (2026-09)

Full review of the parsing pipeline (Phases 1–10). It combines an audit of real output with
a code review phase by phase, and produces one ranked fix list for approval before
implementation.

## Process

| Step | What | Who | Status | Output |
|------|------|-----|--------|--------|
| 1 | Output audit: every JSON and every page of every PDF vs output, plus run logs, across all tiers | Subagent (read-only) | Done 2026-09-26 | `step1/step1_findings.md` (49 issues), `step1/scorecard.md`, `step1/step1_metrics.json` |
| 2a | Code review, Phases 1–5.7 (manifest, triage, OCR, scaffolding, TOC) | Agent A (read-only) | Done (23 issues) | `step2/agents/A_phases_1-5.7.md` |
| 2b | Code review, Phases 5–7.5 (layout, extraction, tables, chunking, hierarchy) | Agent B (read-only) | Done (30 issues) | `step2/agents/B_phases_5-7.5.md` |
| 2c | Code review, Phase 8, Phase 9 (excluding deep dives), orchestration and cross-cutting | Agent C (read-only) | Done (38 issues) | `step2/agents/C_phases_8-9_orchestration.md` |
| 2d | Code review, Phase 10 (`src/batch_pipeline`) | Agent D (read-only) | Done | `step2/agents/D_phase_10.md` |
| 2e | Deep dive: LLM validation of findings and recommendations | Main session | Done | `step2/deep-dives/llm_validation.md` |
| 2f | Deep dive: monetary parsing | Main session | Done | `step2/deep-dives/monetary.md` |
| 2g | Deep dive: precision and recall of pattern-based extractors | Main session | Done (6 reports) | `step2/deep-dives/extractor_precision_recall.md` |
| 2h | Hand-labelled answer key: findings and recommendations for 6 reports (guide: `gold-labels/LABELING_GUIDE.md`) | Main session labels 2025_38; 5 blind labelling agents do 2025_08, OD_2025_05, JH_2025_02, BR_2024_03, HP_2022; main session adjudicates every pipeline/gold mismatch | Labels done (6/6); adjudication pending | `gold-labels/*.json`, `gold-labels/ADJUDICATION_LOG.md` |
| 3 | Merged, ranked fix list: Step 1 + Step 2, each item traced to phase and `file:line` | Main session | Final draft; awaiting user approval | `step3_fix_list.md` |
| 4 | Implementation of approved fixes | TBD after approval | Pending | commits + `implementation_log.md` |

## Runs audited

| Tier | Reports | Run | Code version |
|------|---------|-----|--------------|
| Union | 19 | 35994256570 | Before 2026-09-25 fixes |
| Union (GPU test) | 2025_08 | 36194014772 | After fixes (`gpu-test/`) |
| State | OD_2025_05, JH_2025_02 | 36167161942 | After fixes |
| Local | BR_2024_03, KA_2022_06, HP_2022, HP_2019 (CG_2025_01 failed at OCR) | 36191270703 | After fixes |

Code reviewed: branch `feature/gcp-migration` at 782d9d0.

## How the Step 2 work is split

The four agents own disjoint files. The main session owns the deep dives, so no two workers
review the same code:

- **Agent A:** `manifest_ingestion_service.py`, `triage_service.py`, `ocr_service.py`,
  `ocr_normalizer.py`, `scaffolding_service.py`, `printed_toc_parser.py`, `toc_table_parser.py`,
  `toc_quality.py`, `toc_reconciliation_service.py` (including the Phase 5.5 heading promotion),
  `toc_llm_validator.py`, `report_type_profiles.py`, `excel_analysis.py`.
- **Agent B:**
  - `layout_analysis_service.py`, `content_extraction_service.py`;
  - `extractors/` (`text_extractor`, `text_repair`, `pdfmux_router`, `pdfplumber_table_extractor`);
  - `structured_table_extractor.py`, `multi_page_table_handler.py`;
  - `chunking_service.py`, `chunk_filter_service.py`, `hierarchy_enricher.py`;
  - `enrichment/contextual_caption_service.py`.
- **Agent C:**
  - Phase 8: `assembly_service.py`, `validation_service.py`.
  - Phase 9 orchestration: `semantic_enrichment_service.py`, excluding `_validate_findings_with_llm`.
  - Phase 9 modules: `evidence_linker.py`, and in `enrichment/`: `section_classifier`,
    `cross_reference_resolver`, `annexure_linker`, `executive_summary_parser`, `entity_extractor`,
    `temporal_extractor`, `pattern_loader`.
  - Orchestration and cross-cutting: `main.py`, `parallel_runner.py`, `pipeline_state.py`,
    `config.py`, `instrumentation/`, `gcs_integration.py`.
- **Agent D:** all of `src/batch_pipeline/` (Phases 10a/10b/10c, prompts, batch service, result
  processing, merge).
- **Main session (deep dives):**
  - `enrichment/finding_extractor.py`, `recommendation_extractor.py`, `llm_validator.py`,
    `monetary_processor.py`, `box_element_extractor.py`;
  - `semantic_patterns.py`, `config/enrichment_patterns.yaml`;
  - `semantic_enrichment_service._validate_findings_with_llm`;
  - measuring precision and recall of every Phase 9 extractor against the answer key.

## Work log

- **2026-09-26:**
  - Step 1 completed (49 issues, 2 critical).
  - Step 2 kicked off with the four agents above, working in parallel.
  - First code facts, found in the main session while planning:
    - Recommendations are never LLM-validated: a prompt exists at `llm_validator.py:110`, but it
      has no request builder and no call site.
    - Only findings with confidence in [0.5, 0.7) are validated
      (`enrichment_patterns.yaml:333-334`). Findings outside that band pass unchecked, both those
      at 0.7 or above and those below 0.5. The validator's docstring says below 0.5 means
      "rejected", but `semantic_enrichment_service.py:657-660` keeps them. Across the 26 outputs,
      559 of 1,234 findings (45%) are below 0.5 and 324 (26%) are at 0.7 or above, so 72% never
      see the LLM (`step2/deep-dives/llm_validation.md`).
    - A failed validation call keeps the finding (fail-open). `validate_single` turns every API
      error into UNCERTAIN (`llm_validator.py:270-276`), and the service counts UNCERTAIN as valid.
      In the union run, 31 findings in 6 reports failed after about 5 minutes of retries each and
      were kept and counted as "validated": 2025_16 11/16, 2023_11 6/7, 2025_18 4/4,
      2025_03 2/2, 2024_01 2/2, 2023_20 3/30.
    - Validation is one sequential call per finding.
    - (Correction: an earlier note here said "318/645 calls failed". That figure counts retry
      warnings, not findings. The per-finding figure is the one above.)
  - Labelling set up:
    - The guide is written.
    - Five labelling agents started. They are general-purpose agents with no session context, so
      they are blind to the pipeline code and output.
    - Why agents: about 280k words of PDF across 6 reports is too much for one context without
      repeated compaction.
    - Quality control: the main session labels 2025_38 itself for calibration and re-reads the PDF
      for every item where gold and pipeline disagree before any metric is computed.
    - Caveat: the main session has read the extractor code, so its own 2025_38 labels are not
      pattern-blind. It does not open 2025_38's pipeline output until labelling is finished.
  - About 10 minutes after launch, all 9 agents (4 reviewers and 5 labellers) stopped on the
    account usage limit. Only the report skeletons had been written. After the reset, all 9 were
    resumed with their context kept, and told to save after each phase or ~20 pages. If the limit
    hits again, they are resumed the same way after the next reset.
  - Agent D finished (report: 759 lines). Critical root cause for P10a-01, **verified
    independently by the main session**:
    - The state and local prompt builders in `summary_variants.py` are f-strings containing
      `{input}`, so Python substitutes the built-in `input` function at definition time.
    - Rebuilding all 5 variants × 3 tiers confirms it: state and local prompts contain
      `<built-in function input>` in place of the report data, while union prompts keep the
      placeholder.
    - Agent D also confirmed that no LLM finding or recommendation extraction runs in production.
      `batch_pipeline/enrichment/enrichment_service.py` is CLI-only, crashes on start, and is
      non-Vertex.
  - The HP_2022 labels are done: 139 findings (10 borderline) and 12 recommendations (1
    borderline), all 142 pages read.
  - The usage limit hit a second time, after the agents had saved partial progress:
    - 2025_08 saved through p.119;
    - BR had read pp.0-35;
    - JH had its chapters done;
    - OD had reached about p.95;
    - Agent A had gathered its Phase 4-5.7 evidence.
  - All 7 unfinished agents (A, B, C and 4 labellers) were resumed on 2026-09-27 after the reset.
  - Gold labels finished for four reports:

    | Report | Findings (borderline) | Recs (borderline) | Labeller |
    |--------|----------------------|-------------------|----------|
    | 2025_38 | 94 | 22 | Main session, all 90 pages; source in `gold-labels/src_2025_38/` |
    | 2025_08 | 140 (11) | 36 (3) | Agent, 158 pages |
    | JH_2025_02 | 134 (24) | 7 | Agent, 168 pages |
    | HP_2022 | 139 (10) | 12 (1) | Agent |

    OD_2025_05 and BR_2024_03 are still being labelled.
  - Labeller conventions worth knowing when scoring:
    - Annexure and table narratives are excluded. This matters for 2025_08 (annexure "Audit
      observations" columns) and JH (Tables 4.15-4.17).
    - Advice sentences inside audit rebuttals are labelled as borderline recommendations
      (2025_38, 2025_08).
    - Chapter "Summing up" / conclusion paragraphs are labelled with `location` = conclusion.
  - Agent A finished with 23 issues. Its core point: the TOC quality score measures only shape,
    so junk TOCs score 85-100 and nothing reacts.
    - Main session spot-check A-4-05: confirmed. `ScaffoldingService` has no `self.logger`; only
      `TOCRejectionLogger` defines one. So `scaffolding_service.py:1109` would raise an
      AttributeError inside the except block.
    - Hand-off to the main session: `enrich_document` is called without `task=`, so
      `detect_report_type` never runs. The ATIR and state profiles for Phase 9 finding patterns
      are never used.
  - The first gold scores are in (`step2/deep-dives/gold_scores.json`):
    - Findings precision is about 93-97%, but recall is only 19-31% (68% for the HP_2022 ATIR).
      The main cause is under-extraction, not over-extraction.
    - JH: the LLM validator removed 11 candidates, and 10 of them were real findings.
  - More labels finished:
    - OD_2025_05: 245 findings, 50 recs.
    - BR_2024_03: 257 findings, 45 recs.
  - All 6 gold reports are scored:
    - Findings precision is about 95%, recall 19-35% (68% for the ATIR).
    - The LLM validator removed 33 findings, 26 of them real.
    - Impact amounts: the best regex method matches gold in 56% of cases.
  - Agent C finished (38 issues). Main session spot-check C-R-11: **confirmed**.
    - `run-parsing.yml:190-191` syncs `gs://…/raw/` and `processed/` onto the VM without `-d`,
      and uploads back without `-d`.
    - So anything deleted in GCS persists on the VM disk and is re-uploaded on the next run.
    - The user's pending GCS cleanup must also be applied to `cag-parsing-vm:/var/tmp/cag/data/`
      (or the workflow gets `-d`).
  - Agent C reverses Step 1 on annexure links: HP_2022 and KA were "fine" in count only, but 147
    of 254 "resolved" links point at the wrong appendix (C-9-03).
  - Adjudication done (`gold-labels/ADJUDICATION_LOG.md`):
    - Pipeline findings with no gold match: 10 of 14 are true false positives, and 7 of those
      are management replies.
    - LLM rejections: 26/33 were real findings.
    - Sampled misses: about 90%+ are real findings, so the recall conclusion is robust.
  - Step 3 fix list drafted (`step3_fix_list.md`), awaiting Agent B's final report.
  - Agent B finished (30 issues).
    - B-7.5-01 (critical) was reproduced exactly: 639 parents, 329 unique IDs, 1,645 children
      under "Corporation".
    - Main-session spot-check B-6-04: **confirmed**. The whitespace-ratio rule in
      `chunk_filter_service.py:168-173` has no table exemption, so padded Docling markdown tables
      are dropped.
  - Step 3 fix list finalised with B's items. **Step 2 is complete.**
