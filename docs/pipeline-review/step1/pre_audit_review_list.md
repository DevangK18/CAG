# Full-review list (collected during state/local runs, 2026-09-25)

## Phase 1-3 (manifest / triage / OCR)
- OCR timeout fixed at 600 s (parsing_config.yaml ocr.timeout) -> CG_2025_01 (129 pp, text drawn as vector outlines) killed at 600 s on e2-standard-4. Scale by page count like Docling.
- OCR failures are silent: ocr_service.py:166-178 only appends to task.error_log; nothing logged at ERROR.
- OCR output_type "pdfa" adds slow/fragile Ghostscript PDF/A step; "pdf" is enough.
- Filter matching 0 reports exits 0 -> workflow + VM status "success" for an empty run. Should exit non-zero.
- Ingestion downloads every manifest row before --reports filter is applied.
- ATIR not detected for local manifest (no "Audit Category" column) -> IDs HP_2019_Annual_... instead of {ST}_ATIR_{year}_...
- (fixed 922c0ac/782d9d0) tier from filename; raw dir chosen before column override.

## Phase 4 / 5.5 (TOC)
- HP_2019: printed TOC verified 35% -> rejected -> heuristic 21 entries. Check quality in output.
- HP_2022_ATI: printed TOC verify 18% (bookmarks used, 26 entries) - check offsets.

- Phase 5.5 supplementing: HP_2022 26 -> 291 entries (+305 Docling headers), HP_2019 21 -> 170, KA_2022_06 22 -> 122. Likely table titles/bold lead-ins promoted to headings -> tiny sections.
- Phase 5.5 reconciled quality is 85 for every report (BR 91->85, KA 63->85, HP22 70->85, HP19 100->85): looks like a constant, so "keep Phase 4 if reconciled scores lower" is not a real comparison.

## Phase 6-7 (extraction / chunking)
- Parent fragmentation: BR_2024_03 639 parents / 1719 children despite 58-entry printed TOC kept (Phase 7.5 sub-parents?); HP_2022 291/957, HP_2019 170/530 (~3 children per parent).
- Phase 6 summary "0 figures" always: main.py:899 counts content_type=="figure"; figures are "image_caption".
- M2-DLQ noise: multi_page_table_handler.py:305-334 flags every non-table page between any two tables <=5 pages apart -> dozens of false dlq_entries.
- Tier-3 fallbacks logged at ERROR ("pdfplumber + Docling failed, saving for Gemini") - normal path, wrong level.

## Phase 9 (semantic enrichment)
- Recommendations: OD_2025_05 structural=0 numbered=0 verb=36 (performance audit has recommendation boxes).
- Evidence links: 0 for both state reports.
- Exec summary citations resolved: 0% for both.
- Cross-references resolved 8-12%; annexure links OD 7/15.
- LLM validation sequential: 32 calls = 18 min with 429s; union Phase 9 = 200 min (35% of run).
- Findings/sections typed "other" (from earlier union audit).

- Evidence links = 0 in ALL 6 state+local reports; exec-summary citations 0% in all 5 with a summary -> systematic bug, not data.
- ATIR reports (HP_2022, HP_2019): 0 recommendations, even verb=0 -> extractor doesn't cover ATIR wording ("suggestions", "department should").
- ATIR reports typed "compliance" in Phase 9 (no ATIR detection upstream).
- Annexure links: BR_2024_03 0/23 resolved (vs HP_2022 29/29) -> BR-specific format mismatch.

## Phase 10 (Gemini)
- 10b charts processed one at a time; 76 charts = 92 min (52% of state run). Parallelise within quota.
- 10b: Gemini sometimes returns a JSON list -> "Top-level value is not an object" -> wasted re-request; unwrap single-element list.

## Infra / parallel runs
- processed/manifest.json shared across tiers, last writer wins -> blocks parallel tier VMs.
- Daily log file name shared (parsing_pipeline_YYYYMMDD.log).
- GPUS_ALL_REGIONS quota = 1 -> only one GPU VM project-wide.
- GCS cleanup pending (user): 8 local PDFs in raw/union/, 10 state PDFs in raw/union/ to move to raw/state/.
- GPU workflow (run-parsing-gpu.yml on main + feature/gpu-vm): VM start retry 6 -> ~15 (L4 stockouts frequent in us-central1-a/b).
- Gemini Vertex quota shared across VMs/runs: parallel VMs slow each other's Phase 9/10 until calls are parallelised with a shared limiter.
- Dockerfile.parsing cu121 torch line is a no-op (poetry already installs torch 2.10.0+cu128).
- Agent worktree to remove later: .claude/worktrees/agent-a210edd736865373f
