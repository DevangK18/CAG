# Agent C: Phase 8, Phase 9 (excluding the deep dives), orchestration and cross-cutting

Status: COMPLETE (2026-09-27). 38 issues plus the P9-14 concurrency design. The ranked list is at the end.

Scope and limits follow `AGENT_BRIEF.md`. Scratch scripts live in
`<scratchpad>/step2/C/`, where
`<scratchpad>` = `/private/tmp/claude-501/-Users-dev-Projects-CAG/5b128fa5-8434-46e2-a3c3-a9695a9cdf81/scratchpad`.

## Work log

**Files read in full:**
- `main.py` (2100)
- `parallel_runner.py` (542)
- `pipeline_state.py` (66)
- `.github/workflows/run-parsing.yml` (409, read-only)
- `assembly_service.py` (1150)
- `semantic_enrichment_service.py` (1104), except `_validate_findings_with_llm`, which the main session owns
- `evidence_linker.py` (521)
- `enrichment/cross_reference_resolver.py` (164)
- `enrichment/annexure_linker.py` (140)
- `enrichment/executive_summary_parser.py` (214)
- `core/data_contracts.py` lines 140–290 (ParentChunk/ChildChunk)
- `report_type_profiles.py` lines 203–330 (read only for the call-site question; the file is Agent A's)
- `enrichment/section_classifier.py` (339)
- `enrichment/entity_extractor.py` (304)
- `enrichment/temporal_extractor.py` (255)
- `enrichment/pattern_loader.py` (267)
- `validation_service.py` (1045)
- `config.py` (559)
- `parsing_config.yaml` (305)
- `instrumentation/__init__.py` (40)
- `instrumentation/trace_emitter.py` (565, all of the emit and finalize paths)
- `gcs_integration.py` (283; only its structure and importers checked, since it's dead)
- `src/core/gemini_client.py` (135, for P9-14)
- `llm_validator.py` lines 200–280 (client and call interface only, for P9-14; the logic is the main session's)
- Not read in full: `instrumentation/trace_models.py` (111) and `trace_renderer.py` (460). They're used only with `--trace`, which production never passes, and the defects found are in the emitter gating.

**Logs checked:**
- `gcs/runs/*/pipeline.log`, `gcs/runs-gpu/*/pipeline.log`
- `gcs/logs/parsing_pipeline_2026092{0,3,4,5}.log`
- `gcs/processed/manifest.json`
- Manifests `State_Examples.xlsx` and `Local_Examples.xlsx` (columns)

**Scripts run** (all in `<scratchpad>/step2/C/`):

| Script | Purpose | Result |
|---|---|---|
| `evidence_probe.py` | Counts references in finding text; reruns `EvidenceLinker` with `table_markdown` chunks | Evidence links stay 0 even with the right table input: the resolver is broken too (C-9-01) |
| `annexure_link_correctness.py` (+ `.out`) | For every *resolved* annexure link, checks whether the target parent carries the same appendix number | 254 resolved, only **107 correct (42%)** (C-9-03) |
| `xref_probe.py` (+ `.out`) | Cross-refs by type and resolution; counts table "refs" that are the table's own caption | Table refs resolve 0/1,164 across 26 outputs; 39–51% of them are the table's own caption line (C-9-04) |
| `section_probe.py` (+ `.out`) | Section classification distribution by report | "other" 40–97% of sections; `is_low_confidence` never set (C-9-08) |
| `entity_probe.py` (+ `.out`) | Attributes each entity to the pattern that produced it | The acronym pattern produces most "schemes" noise (C-9-09) |
| `temporal_probe.py` (+ `.out`) | Audit-period phrasing where the period is null; previous-ref quality | Single-FY and "FY" phrasing missed; 28/72 junk and 18/72 self refs (C-9-06, C-9-07) |
| `validation_probe.py` (+ `.out`) | Reruns `ValidationService` on all 26 outputs | Every report scores ≥ 84; latent footnote crash reproduced (C-8-10) |
| `dedup_probe.py` (+ `.out`) | Checks amount-based duplicate flags against text | 33/35 flagged "duplicates" have unrelated text (C-9-11) |
| `xref_examples.out` | Examples of statutory FPs, unresolved chapter refs and list para refs | C-9-04 |
| config field grep | Every `config.py` dataclass field grepped for reads | 6 unread keys (C-C-01) |
| `esi_probe.py` (+ `.out`) | Reruns `ExecutiveSummaryParser`; compares citation strings present on exec-summary pages with those extracted | e.g. 2023_11: 54 present, 0 extracted; GPU 2025_08: 4 present, 0 extracted (C-9-05) |

---

## Orchestration and run level (main.py, parallel_runner.py, pipeline_state.py, workflow)

### Data flow

1. `main()` (`main.py:2001-2096`) parses args, calls `setup_logging()` and runs
   `PipelineOrchestrator.run()` (`main.py:186-225`).
2. `_phases_1_to_3()` (`:231-397`). The report filter is an exact `report_id` match (`:246`). Cached
   tasks are split out using `data/raw/.cache/{report_id}_triage.json` (`:399-431`).
3. Phases 4–9 run sequentially. The CPU workflow never passes `--workers`, so production always uses
   the sequential path (`:593-622`).
4. 10a (`:1393`), 10b (`:1557`) and 10c (`:1618`).
5. `_record_failures_in_manifest()` (`:1713`), `_finalize_all_traces()` and `_print_summary()`
   (`:1727`).
6. The process always exits 0 (`asyncio.run(main())`, `:2100`).
7. In the workflow, `run_pipeline.sh` runs `docker run …` with `set -e`. `run_detached.sh` maps
   RC 0 to status `success` (`run-parsing.yml:319-330`). The job polls that status.

### Does it run? (evidence)

- **Sequential path:** always. Every run log shows `PHASE n:` headers; none shows `PARALLEL MODE`.
- **`_record_failures_in_manifest`:** runs. The local log has `Manifest: marked 1 failed report(s)`
  (`runs/36191270703/pipeline.log:1950`). The union run predates it (commit 3f29988).
- **Final evaluation:**
  - The union run printed `⚠️ Pipeline completed with issues: layout_analysis (1 failed)` (`:7766`), yet the status was `success`.
  - The local run printed `🎉 FULL PIPELINE COMPLETE!` (`:1975`) with 4/5 reports, and the status was `success`.

### Issues

#### C-R-01 · high · The pipeline never exits non-zero, so every partial or empty run is recorded as "success"
- **Location:**
  - `main.py:2100`: `asyncio.run(main())`; `main()` returns None.
  - `main.py:2082-2083`: a missing manifest just `return`s.
  - `main.py:193-197`: no triaged documents, so `return`.
  - `main.py:1855-1881`: `final_success` is only printed.
  - `run-parsing.yml:325-330`: `RC -eq 0`, so `FINAL="success"`.
- **Root cause.** The exit code carries no information. Beyond that, `final_success` (`:1856-1864`) compares each phase with `successful_triaged`, not with `len(self.state.tasks)`:
  - A report that fails in Phases 1–3 (CG at OCR) or at download is invisible to the check. That's why the local run says "FULL PIPELINE COMPLETE" with 4/5.
  - Phase 10 failures never enter `state.failed`. `_phase_overview_summary` and `_phase_visual_extraction` catch `Exception` and only print (`:1492-1494`, `:1606-1610`). Per-variant and per-chart 429 losses are never counted at all (see Agent D).
- **Explains Step 1:** P1-03, and the 0-report "success" (pre-audit list item).
- **Evidence:** runs 35994256570 and 36191270703 both have status `success`. The log lines are quoted above.
- **Fix proposal:**
  1. `main()` returns `orchestrator.exit_code` and the entry point calls `sys.exit(asyncio.run(main()))`.
  2. Define exit codes:
     - 0: all tasks reached Phase 9 and every enabled Phase 10 step recorded 0 losses.
     - 3: partial (some reports or phases failed).
     - 4: nothing processed. This covers a filter matching 0 reports and a missing manifest.
     - 1: crash.
  3. Record 10a/10b/10c losses in `state.failed["10a"]` and the others. BatchService and the visual extractor must return counts of lost items.
  4. In the workflow, map `RC=3` to status `partial` and treat it as a failure in the polling `case` (or `::warning`), without masking it.
  5. Write a machine-readable `run_summary.json`, uploaded next to `status`, with per-report and per-phase outcomes.
- **Risk / effort:** `set -e` in `run_pipeline.sh` would skip the upload step on a non-zero exit, so partial output would never reach GCS. Wrap the docker run as `docker run … || PIPE_RC=$?`, still upload, and `exit $PIPE_RC` at the end. Effort M. The workflow is the user's "proven" file, so it needs sign-off.
- **Confidence:** verified by reading, plus log evidence.

#### C-R-02 · high · A report that fails in a later run keeps its old `*_chunks.json`, and the indexer ingests it regardless of the manifest
- **Location:**
  - `run-parsing.yml:229-230`: `rsync gs://…/processed/` pulls every earlier output down.
  - `run-parsing.yml:278`: `rsync` up, without `-d`.
  - `assembly_service.py:957-979`: `mark_failed` sets `stale_output` but leaves the file.
  - `src/rag_pipeline/indexer.py:81-83`: globs `**/*_chunks.json` and never reads `manifest.json`.
- **Root cause.** Output files are never deleted, renamed or versioned per run. Before 3f29988 the manifest didn't even record the failure; `_update_manifest` alone just left the old `completed` entry. The pipeline now records `status: failed, stale_output: true`, but nothing downstream reads it.
- **Explains Step 1:** P1-04. In the current manifest, 2025_06 is still `completed`, last_updated 09-19. That entry was written before commit 3f29988.
- **Evidence:** `gcs/processed/manifest.json`, entry `2025_06…`: `status: completed`, `last_updated 2026-09-19T22:45`. The run log records a Docling timeout for it on 09-24.
- **Fix proposal:**
  - (a) In `mark_failed`, when `stale_output` is set, move `{tier}/{id}_chunks.json` and `_overview.json` to `processed/_stale/{tier}/` (upload with `rsync -d` for that folder only, or `gsutil mv`). Alternatively add a run-scoped `data/processed/{tier}/{id}_chunks.json.failed` marker.
  - (b) The indexer and `api/gcs_sync.py` read `manifest.json` and skip anything not `completed`.
  - (c) Add `pipeline_run_id` and `code_version` (git SHA passed as a build arg) to `report_metadata` and to the manifest entry. Then a stale file is identifiable from its content.
- **Risk / effort:** S–M. Moving files in GCS from the workflow needs care: the upload has no `-d` because deletes are dangerous.
- **Confidence:** verified.

#### C-R-03 · medium · The manifest marks a report "completed" at Phase 8, before Phase 9 and Phase 10 have run
- **Location:** `assembly_service.py:292-293` (`_update_manifest` inside `assemble_document`, status `completed`) and `main.py:1202`.
- **Root cause:** The completion status is written by Phase 8. Consequences:
  - A crash in Phase 9 or 10 leaves `completed`. Only exceptions caught into `state.failed["enrichment"]` are re-marked.
  - A Phase 10 failure never marks anything.
  - If the process is killed by the workflow's `max_hours` timeout, every report that got past Phase 8 says `completed`, even without enrichment.
- **Explains Step 1:** latent (not triggered, since every run finished).
- **Fix proposal:** Write the manifest per phase (`phase_reached`, `phases_failed[]`) and set `completed` only after the last enabled phase. Record `enriched: bool` and `phase10: {overview, summaries, visual}` flags.
- **Risk / effort:** S.
- **Confidence:** verified by reading.

#### C-R-04 · medium · `processed/manifest.json` is one file shared across tiers and VMs, and the last writer wins
- **Location:**
  - `assembly_service.py:68-69` (path `data/processed/manifest.json`);
  - `run-parsing.yml:230`, which downloads it at run start;
  - `run-parsing.yml:278`, which uploads it at run end.
- **Root cause:** Each run downloads the manifest when it starts and uploads its own copy at the end. Two VMs running in parallel (the planned per-tier VMs) each upload a copy that lacks the other's entries, so the entries of whichever finishes first are lost.
- **Explains Step 1:** P8-04 (shared) and X-02-adjacent.
- **Stale header:**
  - `generation_timestamp` is set only when the file is created (`assembly_service.py:81`). `_save_manifest` updates `last_updated` (`:990`), so the header is misleading by design rather than stale. The file does have `last_updated 2026-09-26T01:15`.
  - The entries carry no tier, no path directory (`output_file` is a bare name, `:938`) and no run ID. A consumer can't locate a file or tell which run produced it.
- **Fix proposal:**
  - Shard the manifest by tier: `processed/{tier}/manifest.json`. Better still, write one small file per report, `processed/{tier}/{report_id}.status.json`, and let the index be derived.
  - Add `government_body_type`, `output_path` relative to `processed/`, `run_id` and `code_version`.
  - Rename `generation_timestamp` to `created_at`.
  - Upload with a GCS generation precondition (`gsutil cp -x-goog-if-generation-match`), or just rely on the per-report status files.
- **Risk / effort:** M. The API side reads `manifest.json` (`src/api/config.py`, `src/api/gcs_sync.py`); hand-off to whoever owns the API.
- **Confidence:** verified.

#### C-R-05 · medium · One daily log file is shared by every run on the VM and every tier, rotation cuts long runs, and the upload overwrites other VMs' logs
- **Location:**
  - `main.py:1955`: `logs/parsing_pipeline_{YYYYMMDD}.log`, dated at process start.
  - `main.py:1975-1980`: `RotatingFileHandler(10 MB, backupCount=5)`.
  - `run-parsing.yml:285`: `gsutil cp /workspace/logs/*.log gs://…/logs/`.
- **Root cause:**
  - `WORK_DIR=/var/tmp/cag` persists on the VM, so all runs on the same date append to one file.
  - `gs://…/logs/parsing_pipeline_20260925.log` holds three runs: the state run (17:47), the empty local run (21:09) and the local run (21:50). See `grep "Logging configured"` at lines 1, 885 and 894.
  - A run that crosses midnight keeps logging to the previous day's name.
  - With per-tier VMs, each VM's `cp` overwrites the other VMs' same-day file in GCS.
  - Rotation at 10 MB renames the file to `.log.1`. The union run's DEBUG log (about 1.2 MB/day now) is under the limit, but a 100-report run would rotate, and `*.log` would not upload the `.log.N` backups.
- **Explains Step 1:** the "shared log file" item from the pre-audit list.
- **Fix proposal:**
  - Name the file `logs/{RUN_ID or timestamp}_{tier}.log` and pass `RUN_ID` through `-e RUN_ID` from the workflow.
  - Drop the rotation, or upload `*.log*`.
  - Upload to `gs://…/runs/{run_id}/pipeline_debug.log`, next to the stdout log that already goes there.
- **Risk / effort:** S.
- **Confidence:** verified (log file contents).

#### C-R-06 · medium · The `skip_phases` input documented as "comma-separated" crashes argparse
- **Location:**
  - `run-parsing.yml:28-29`: description "comma-separated, e.g., 10a,10b,10c".
  - `run-parsing.yml:291-293`: builds `--skip 10a,10b,10c`.
  - `main.py:2025-2031`: `nargs="*", choices=[...]`.
- **Root cause:** `"10a,10b,10c"` is one token that isn't in `choices`, so argparse exits 2 and the status becomes `failed:2` after the image build and VM start (about 15 minutes wasted). Only space-separated input works.
- **Explains Step 1:** latent. The audited runs didn't use skip.
- **Fix proposal:** In `main.py`, accept both forms: `type=lambda s: s.split(",")` with flattening, or `nargs="*"` plus a post-split that validates against the choices. Workflow text is optional.
- **Risk / effort:** S.
- **Confidence:** verified by reading. argparse behaviour is standard.

#### C-R-07 · medium · The parallel path (`--workers > 1`) diverges from the sequential path and would silently produce different, poorer output
- **Location:** `parallel_runner.py:134-313` compared with `main.py:593-1317`.
- **Root cause:** The parallel worker:
  - calls `enrich_hierarchy(aggressive=False)` (`:236`), whereas sequential passes `aggressive=reason in (...)` (`main.py:1101`);
  - never calls `propagate_semantic_enrichment_to_chunks` (compare `main.py:1283-1286`), so child chunks lack the `structured_data.finding_type`, `is_recommendation` and similar fields that Qdrant filters use;
  - does no Phase 9 validation sample;
  - uses no trace emitter;
  - catches a 7.5 failure as a whole-task failure (sequential only logs and keeps the report);
  - the TOC LLM validator (5.7) is skipped in workers when `GOOGLE_CLOUD_PROJECT` is unset, just as in sequential.

  The module docstring promises "byte-identical output" (`main.py:204` comment), which isn't true.
- **Explains Step 1:** latent (production doesn't use `--workers`).
- **Fix proposal:** Make one function, `process_task_4_to_9(task, services, emitter)`, used by both paths, so they can't drift. Or delete the parallel path until it's needed. The per-tier VM plan gives parallelism across VMs instead.
- **Risk / effort:** M.
- **Confidence:** verified by reading.

#### C-R-08 · low · The Phase 6 "figures" counter and the corpus "Tables" counter always print 0
- **Location:**
  - `main.py:899-903`: `content_type == "figure"`. That type doesn't exist; the ChildChunk Literal (`data_contracts.py:200-208`) has `image_caption`.
  - `main.py:941-944`: the corpus total counts `content_type == "table"`, which also doesn't exist (`table_markdown`).
- **Explains Step 1:** P6-08 ("figure count always 0; corpus table total also 0").
- **Fix proposal:**
  - Count figures as `image_caption and layout_label != "Table"`.
  - Count tables as `table_markdown`, or `image_caption` with `layout_label == "Table"`, the same rule as the per-report count at `:893-898`.
- **Risk / effort:** S.
- **Confidence:** verified.

#### C-R-09 · low · The Phase 1 trace always says the tier came from the manifest filename
- **Location:** `main.py:286`: the string `"Detected from manifest filename pattern"` is hard-coded, although tier now comes from the Government Type column (922c0ac).
- **Fix:** Record the actual source, which `manifest_ingestion_service` knows. S.

#### C-R-10 · low · Phase 1–3 cache reuse ignores PDF identity, and the OCR cache path is reconstructed by convention
- **Location:**
  - `main.py:399-431`: cache hit means the PDF exists and `{report_id}_triage.json` exists.
  - `main.py:446-449`: OCR path by name. If the ocred file is missing, `ocred_pdf_path` stays None but status is `ocr_complete`, so Phase 4 falls back to the raw scanned PDF without warning.
- **Explains Step 1:** P1-07 (Agent A owns triage and ingestion; recorded here because the check lives in `main.py`).
- **Fix proposal:**
  - Store `sha256` and `size` of the PDF in the triage cache, and invalidate on mismatch.
  - If `classification == scanned` and the ocred file is missing, drop the cache and re-run OCR, logged at WARNING.
- **Risk / effort:** S.

#### C-R-11 · high · Files deleted or moved in GCS come back on the next run, because the VM keeps its own copy and both syncs run without `-d`
- **Location:**
  - `run-parsing.yml:190`: `WORK_DIR=/var/tmp/cag` sits on the VM's persistent disk. It is not a tmpfs and it survives stop and start.
  - `run-parsing.yml:229-230`: `rsync -r gs://…/raw/` and `…/processed/` are downloaded into it.
  - `run-parsing.yml:278-284`: `rsync -r` from it back up to `raw/`, `processed/`, `batch_jobs/`, `extraction_images/` and the others.
- **Root cause:**
  - Neither direction deletes anything. A file removed from GCS stays in `/var/tmp/cag/data/...` on the VM and is uploaded again at the end of the next run.
  - This applies to the GCS cleanup the user still has to do: the 8 local and 10 state PDFs misplaced in `raw/union/`, and the stale 2025_06 output (C-R-02). After a `gcloud storage mv` or `rm`, the next CPU run puts every one of those files back.
  - It also means `batch_jobs/` output from older code versions is reused. 10b runs with `skip_existing=True` (`main.py:1584`), so charts extracted by old code are never redone. Hand-off to Agent D.
- **Explains Step 1:** It makes P1-04 persistent. It also blocks the pending GCS cleanup ("GCS cleanup pending" in the review list).
- **Evidence:** Verified by reading the workflow. I did not inspect the VM disk; the VM is stopped and read-only rules apply.
- **Fix proposal:**
  - (a) Choose one of these:
    - Treat GCS as the only source of truth. Wipe `${WORK_DIR}/data` at run start (`rm -rf`) before the download sync. This costs a re-download of `raw/` (PDFs, a few GB) and `processed/` each run.
    - Download with `rsync -d`, which makes the VM mirror GCS (that direction is safe).
  - (b) Keep the upload without `-d`.
  - (c) Until this is fixed, do the GCS cleanup *and* delete the same paths under `/var/tmp/cag/data` on `cag-parsing-vm`. Otherwise the cleanup is undone.
  - This touches the "proven" workflow, so it needs user sign-off. The GPU workflow has the same pattern (Agent D or the main session should check).
- **Risk / effort:** S. Wiping the directory means a longer download. Mirroring with `-d` downward is cheaper.
- **Confidence:** Verified by reading.

### Improvements (not bugs)

- **Summary output.** `_print_summary` uses `print`, not the logger, so the final summary isn't in the DEBUG file log. Emit the summary through `logger.info` too.
- **Validation sample.** The Phase 9 "validation" block only validates the first 3 reports (`main.py:1335-1337`), and its score isn't persisted anywhere. Either persist it per report into `processing_stats.validation`, or remove it.
- **Readiness message.** `"Ready for RAG system"` is printed even when Phase 10 failed. It should be tied to the exit code (C-R-01).

### Wired-and-working inventory (orchestration)

| Component / flag | Status | Evidence |
|---|---|---|
| Sequential Phases 4–9 | works | all run logs |
| `--workers` parallel path | never runs (and diverges) | workflow never passes it; C-R-07 |
| `--trace` instrumentation | never runs in production | workflow doesn't pass `--trace`; no-op emitter used |
| `--skip` with commas | runs but broken | C-R-06 |
| `--reports` filter | works; a filter matching 0 reports exits 0 | P1-03 |
| `_record_failures_in_manifest` | works for Phases 1–9; Phase 10 is never recorded | local log `:1950`; C-R-01 |
| `final_success` evaluation | runs but broken (ignores Phase 1–3 and Phase 10 failures) | local log `:1975` |
| Process exit code | fails silently (always 0) | C-R-01 |
| Phase 6/corpus figure and table counters | runs but broken | C-R-08 |
| Phase 9 validation sample (first 3 reports) | runs; result is discarded | `main.py:1335-1387` |
| Daily log file | runs; shared across runs and tiers | C-R-05 |

---

## Phase 8: Assembly (assembly_service.py; validation_service.py below)

### Data flow

`main._phase_assembly` (`main.py:1163-1239`) converts dicts into `ParentChunk`/`ChildChunk`, then
calls `AssemblyService.assemble_document` (`assembly_service.py:167-315`), which does the following in order:
1. `_extract_report_year` (`:88-165`).
2. `_cleanup_empty_parents` (`:388-444`).
3. `_build_report_metadata` (`:317-354`), `_serialize_parent_chunks` (`:356`), `_serialize_child_chunks` (`:446-530`) and `_build_processing_stats` (`:599-647`).
4. `ContextualCaptionService.replace_generic_captions`, which is Agent B's.
5. `TemporalExtractor.annotate_chunk_temporal` on paragraphs.
6. `_compute_chunk_confidence` (`:532-597`).
7. `_build_footnote_index` (`:649`).
8. `_build_visual_asset_registry` (`:710-826`).
9. Write `{tier}/{id}_chunks.json`.
10. `_update_manifest`.

After Phase 9, `propagate_semantic_enrichment_to_chunks` (`:1015-1150`) mutates the children.

### Issues

#### C-8-01 · medium · Parent chunks always get `audit_category: "compliance"`, and no chunk carries `department` or `report_subtype`
- **Location:**
  - `data_contracts.py:185-192`: ParentChunk default `"compliance"`.
  - Parents are built without `audit_category`, `department` or `report_subtype` at `chunking_service.py:582-594` and `:629-640` (Agent B's file). Children set `audit_category` only (`:740-742`).
  - `assembly_service.py:356-368`: dumps the parents as they are.
  - `assembly_service.py:467-518`: children are serialized without `department` or `report_subtype` at all.
- **Root cause:** Tier metadata is copied field by field in several places, and the parent constructor misses three fields.
- **Explains Step 1:** P8-01, and part of P8-02.
- **Evidence:** OD `report_metadata.audit_category = performance`; all 170 parents say `compliance` (Step 1).
- **Fix proposal:** Make assembly the single source of truth. In `assemble_document`, stamp `government_body_type`, `state_name`, `department`, `audit_category` and `report_subtype` from `_build_report_metadata(...)` onto every parent and child dict after serialization, and add `department` and `report_subtype` to the child dict and to `metadata.source`. This fixes it whatever Phase 7 or 7.5 did. Hand-off to Agent B to also pass the fields in `chunking_service`.
- **Risk / effort:** S.
- **Confidence:** verified by reading plus the Step 1 evidence.

#### C-8-02 · medium · `ministry` is "Unknown" and `department` null for every state and local report; `report_subtype` is always null
- **Location:**
  - `assembly_service.py:337`: `"ministry": metadata.get("Department", "Unknown")`.
  - `:344`: `"department": metadata.get("department")`.
  - `manifest_ingestion_service.py:670` and `:683`: `department = safe_get_optional("Department")`, then `Department = department or "Unknown"`. That's Agent A's file.
- **Root cause:** The state and local manifests have no `Department` column. Their columns are `SL NO, Date, Report_No, Original Title, Recommended Title, Government Type, State, State_code, Union Department ("-"), Report Type, Sector, Report PDF`. So `department` is None and `ministry` is "Unknown".
  - The department is often in the title itself, e.g. OD "…School and Mass Education **Department**".
  - `report_subtype` needs a `Report Subtype` column, which no manifest has. `Sector: Local Bodies / Urban Local Bodies` is never used to infer `PRI_ULB`.
- **Explains Step 1:** P8-02 (department/ministry/subtype).
- **Fix proposal:**
  - (a) Agent A: in manifest ingestion, map `Union Department`, treating "-" as null. Infer the department from the title with a regex (`(\w[\w &]+ Department)`, `Ministry of …`). Infer `report_subtype` from Sector or Government Type: Local Bodies gives `PRI_ULB`, and "Public Sector Undertakings" gives `PSE`.
  - (b) Agent D: backfill `department` or `ministry` from the Phase 10a overview LLM output, which already extracts the audited entity, when the manifest has none.
  - (c) Assembly: emit `ministry: null`, not the literal "Unknown". The string "Unknown" becomes a real facet value in the corpus summary ("Unknown: 260 findings").
- **Risk / effort:** S–M.
- **Confidence:** verified (manifest columns printed).

#### C-8-03 · medium · `report_metadata.processing_status` is frozen at "chunking_complete", and no Phase 9 or 10 status is ever written into the chunk file
- **Location:**
  - `main.py:986` sets `chunking_complete`.
  - `assembly_service.py:353` and `:640` serialize `task.processing_status`, which is still `chunking_complete`.
  - `main.py:1202` sets `assembly_complete` only after writing.
  - `main.py:1278-1290`: Phase 9 adds `semantic_enrichment` but never updates `report_metadata.processing_status`.
  - `processing_stats.phase_10b_complete` stays `False` unless 10b flips it (Agent D).
- **Explains Step 1:** P8-02 (status stuck).
- **Fix proposal:**
  - After each phase writes the file, set `report_metadata.processing_status` to one of `assembled`, `enriched`, `phase10_complete`.
  - Add `report_metadata.phases_completed: [...]`.
  - Set `pipeline_run_id` and `code_version` (C-R-02).
- **Risk / effort:** S.
- **Confidence:** verified.

#### C-8-04 · medium · Parent `content_summary` is never filled; there is no merge step for the hierarchical summaries
- **Location:**
  - `chunking_service.py:590` and `:637` set `content_summary=None`.
  - A grep over `src/` finds no other writer of `content_summary`.
  - `batch_jobs/hierarchical/*` holds the summaries keyed by `parent_chunk_id` (Step 1: OD 87/87 match).
- **Root cause:** Phase 10a writes RAPTOR summaries to `batch_jobs/hierarchical/` only. `build_final_overviews` doesn't merge them back into `*_chunks.json`.
  - The indexer globs `**/*_hierarchical.json` separately (`indexer.py:315`), so they may still reach Qdrant if that glob finds them.
  - But the chunk file (and the API that serves parents) never has them.
- **Explains Step 1:** P8-02 (content_summary null).
- **Fix proposal:** In Phase 10a post-processing (Agent D's `process_results.build_final_overviews`), write the `content_summary` of each parent by `parent_chunk_id`. Log unmatched IDs, since P7-01 duplicate IDs make the join ambiguous.
- **Risk / effort:** S. Hand-off to Agent D.
- **Confidence:** verified by grep.

#### C-8-05 · low–medium · The processing stats and the manifest count parents *before* the empty-artifact cleanup
- **Location:**
  - `assembly_service.py:228-229`: `_build_processing_stats(task, parent_chunks, …)` gets the uncleaned list.
  - `:293`: `_update_manifest(task.report_id, parent_chunks, …)`, also uncleaned.
  - `:224`: the file holds `cleaned_parents`.
- **Explains Step 1:** P7-05 ("parent count in stats stale", HP_2022, KA). The manifest has HP_2022 at 291 and KA at 122, while their files hold 286 and 118.
- **Fix:** Pass `cleaned_parents` to both. S. Verified.

#### C-8-06 · medium · The visual-asset registry caption is "Table on page N" for most tables, because only the table's own first line and the parent titles are searched
- **Location:**
  - `assembly_service.py:828-860` (`_extract_table_identity`): matches `Table X.Y` only in the first markdown line or in `hierarchy` values.
  - `:770`: falls back to `f"Table on page {page + 1}"`.
- **Root cause:** Captions in CAG reports sit in the chunk before the table: a paragraph or header saying "Table 3.2: …". That chunk is never looked at.
- **Explains Step 1:** P6-04 (the registry side). Agent B owns caption extraction in Phase 6 and the contextual captions.
- **Fix proposal:**
  - Before building the registry, walk the children in order. For each `table_markdown`, look back at most 2 chunks on the same page, or at the previous page's last chunk, for `^(Table|Statement)\s*(No\.?)?\s*[\d.]+`.
  - Store `table_number` and `caption` on the table chunk itself (`structured_data.caption`). Cross-refs (C-9-04) and evidence links (C-9-01) can then resolve against it.
  - Use `page_logical` in the fallback text.
- **Risk / effort:** S–M.
- **Confidence:** verified by reading. The Step 1 output shows "Table on page N".

#### C-8-07 · low · `extraction_confidence` uses a TOC quality key that doesn't exist, so it always gets the 75 default
- **Location:** `assembly_service.py:257-259` reads `task.scaffold.get("toc_quality_score", 75.0)`. The scaffold stores `toc_quality` (see `main.py:723` and `:731`, which read `toc_quality`).
- **Fix:** Read `toc_quality`. S. Verified by reading. A grep for `toc_quality_score` is still to be confirmed below.

#### C-8-08 · low · `propagate_semantic_enrichment_to_chunks` never propagates `section_type`, and it dumps enrichment fields into table `structured_data`
- **Location:**
  - `assembly_service.py:1055-1059` and `:1077-1081`: read `section.get("parent_chunk_id")`. `SectionClassification` stores the parent under `chunk_id` (`data_contracts.py:480`), so `parent_section_types` is always empty and `sd["section_type"]` is never set. That is dead logic.
  - `:1090-1093`: every child gets `structured_data = {}` (or the existing table structure), and the `finding_type`, `severity` and `total_amount_inr` keys are written *into the table's structured payload*, mixing two schemas.
  - `:1104`: copies `total_amount_inr`, which holds paise (P9-05, the main session's deep dive).
  - `:1133-1141`: entity mentions use raw substring matching (`entity.lower() in content_lower`), so short or noisy entities ("Day Meals", "RD") tag unrelated chunks.
- **Fix:**
  - Use `section.get("chunk_id")`.
  - Put enrichment in `chunk["enrichment"] = {...}`, separate from `structured_data`.
  - Match entities on word boundaries and only for entities of three or more tokens, or those present in the entity dictionary.
- **Risk / effort:** S. Check what the indexer reads from `structured_data` first; hand-off.
- **Confidence:** verified by reading. The key name was verified by running `esi_probe.py`: the `chunk_id` key is populated.

#### C-8-09 · low · `_cleanup_empty_parents` doesn't catch the PDF-merger junk seen in this corpus
- **Location:** `assembly_service.py:39-53`. The patterns cover `01_Cover` and `Blank Page`, but not `Binder1.pdf`, `2 TOC`, `1 Cover pages`, `ATIR 2017-19_HP_English_C…` or `1. Nagarothana Front Page`. The first two are seen in HP_2022 and KA (P4-02).
- **Fix:** This belongs upstream (Agent A, bookmark rejection). As a backstop here, add `\.pdf$`, `^\d+\.?\s+(TOC|Cover|Front Page|Blank Page)` and `^Binder\d*`. S.

## Phase 9 (semantic enrichment, orchestration and non-deep-dive extractors)

### Data flow (`semantic_enrichment_service.enrich_document`, `:128-606`)

1. **Report type** (`:159-165`).
   - With `task`, it uses `report_type_profiles.detect_report_type(task)`.
   - Otherwise it uses `normalize_report_type(report_metadata["report_type"])`.
   - Both callers (`main.py:1269`, `parallel_runner.py:275`) pass no `task`, so the normalize path always runs.
2. `SectionClassifier.classify_sections(parents)`.
3. `FindingExtractor.extract_findings` (main session), then per-finding `EntityExtractor.extract_entities_from_text`, then `_validate_findings_with_llm` (main session).
4. `RecommendationExtractor.extract_all` (main session).
5. `_link_findings_to_recommendations`: same chapter and within 5 pages.
6. `_link_evidence_to_findings`, which calls `EvidenceLinker` (C-9-01).
7. `AnnexureLinker.link_annexures` (C-9-03).
8. `EntityExtractor.extract_entities`.
9. `BoxElementExtractor` (main session).
10. `ExecutiveSummaryParser` (C-9-05).
11. `TemporalExtractor` for the audit period, reference years and previous-audit refs.
12. `CrossReferenceResolver` (C-9-04).
13. `_calculate_statistics`, which includes `_deduplicate_cross_finding_amounts`.
14. Trace emits.

### Issues (so far; Phase 9 is still being written)

#### C-9-01 · medium · Evidence links can never resolve tables, and appendix and paragraph resolution is broken; the "always empty" result is structural
- **Location:**
  - `semantic_enrichment_service.py:747-749`: `tables = [c for c in child_chunks if c.get("content_type") == "table"]`. No child has that type (the Literal is `table_markdown`), so `tables` is always `[]`.
  - `evidence_linker.py:343-365` (`_find_table_by_number`): even with the right input it requires `content_type == "table"` and a `title` or `structured_data.title` key. Chunk dicts have neither.
  - `evidence_linker.py:369-406` (`_find_annexure`): looks only for the word "Annexure" in `metadata.hierarchy` or the first 100 characters of a chunk. State and local reports say **"Appendix"**, and the capture groups (`:73-83`) take `(\d+)`, so "Appendix 2.1" becomes "2". It also returns the *first* chunk mentioning "Annexure N" in its opening, which can be the referencing chunk itself (a self-link) rather than the annexure.
  - `evidence_linker.py:408-462` (`_find_chunk_by_para`): relies on `metadata.paragraph_number`, which is never set. Its fallback joins the *leading integer* of each hierarchy level, so ["2.1 Planning", "2.1.1 Funds"] becomes "2.2" and resolves the wrong paragraph or none.
  - `evidence_linker.py:171-201`: position-based dedup can't dedupe overlapping patterns ("(Annexure 8)" and "Annexure 8" start at different offsets), so links are duplicated. The pre-fix union output shows `['(Annexure 8)', 'Annexure 8', …]`.
  - Page refs (`:280-293`) are "linked" without any resolution.
- **Explains Step 1:** P9-06.
  - All 7 post-fix outputs have 0 links: they use "Appendix", tables never resolve, and paragraph resolution fails.
  - The pre-fix union reports got 0–9 links only from "Annexure"-worded references and occasional paragraph matches.
- **Evidence:** `evidence_probe.py`:
  - Finding texts do contain references: OD table 13, appendix 5, para 4; HP_2022 appendix 27; JH table 10, appendix 6.
  - Rerunning with `table_markdown` chunks still gives `relink=0` for every post-fix report.
- **Fix proposal:** Retire `EvidenceLinker`'s private resolvers and build evidence links from one reference index shared with the cross-reference resolver and the annexure linker:
  1. Build one `ReferenceIndex` per report:
     - `section_no` to parent (with ancestor fallback: 3.2.1.4 → 3.2.1 → 3.2);
     - `table_no` to the `table_markdown` chunk, using the caption look-back from C-8-06;
     - `appendix/annexure id` to a parent *or* to a header or paragraph child whose content starts with `(Appendix|Annexure)[\s\-–]*ID` (BR's `Appendix-5.2` headers);
     - `chapter` in Arabic or Roman to the L1 parent.
  2. `evidence_links(finding)` is all resolved references whose `source_chunk_id == finding.source_chunk_id`, plus references inside the finding text.
  3. Dedupe by `(type, normalized_id)`.
- **Risk / effort:** M. It's one module replacing three.
- **Confidence:** verified by running.

#### C-9-02 · medium · Report-type profiles for ATIR and state reports are dead code; `detect_report_type(task)` is never called
- **Location:**
  - `semantic_enrichment_service.py:159-164`: `task` is optional.
  - `main.py:1269-1275` and `parallel_runner.py:275-280` never pass it.
  - So `normalize_report_type(report_metadata["report_type"])` always runs. It never returns `state_performance` or `state_commercial` (the raw manifest value is just "Performance" or "Compliance"). It returns `atir` only if the Report Type column says so, which it never does.
- **Root cause:** `detect_report_type` (`report_type_profiles.py:203-267`) *does* check `"annual technical inspection" in title` and the state tier, but it's unreachable. Its title lookup key `metadata.get("report_title")` also doesn't exist in `initial_metadata` (the key is `Title`), so the title checks would fail even if it were called. That file is Agent A's; hand-off.
- **Explains Step 1:** P1-05 (ATIR typed "compliance" in Phase 9).
- **Evidence:** every `Detected report type:` log line is one of `financial`, `performance` or `compliance`. HP_2019 and HP_2022 are logged as `compliance`; OD is `performance`, not `state_performance`.
- **Fix proposal:**
  - Pass report-type inputs without `task`: call `detect_report_type_from_metadata(report_metadata, toc_titles)` using `report_title`, `government_body_type` and `audit_category`, which assembly already writes to `report_metadata`.
  - Fix the title key.
  - Upstream, have manifest ingestion set `audit_category="atir"` (Agent A).
- **Risk / effort:** S. Profiles change finding patterns and boosts (main session's scope), so re-measure.
- **Confidence:** verified by reading plus logs.

#### C-9-03 · high · Annexure links: 58% of "resolved" links point at the WRONG appendix, and reports without appendix parents drop every reference
- **Location:**
  - `annexure_linker.py:50-61`: indexes only parents whose `toc_entry` *starts with* Annexure or Appendix. The key is the whole normalized title, e.g. `appendix_2.3_(reference:_paragraph_2.4.4…`.
  - `annexure_linker.py:84-86`: `if not annexure_index: return []`, so when a report has no appendix parents, no references are even recorded. HP_2019 has 11 appendix references in its findings and 0 links.
  - `annexure_linker.py:108-120`: matching is substring-in-either-direction, then a "fuzzy" pass strips trailing digits (`re.sub(r'_?\d+$','',norm_ref)`). The result:
    - `appendix_1.2` becomes `appendix_1.` and matches `appendix_1.1…`;
    - `appendix_1` matches `appendix_15(i)`;
    - `annexure_3` becomes `annexure` and matches the *first* annexure parent of any number;
    - whichever parent comes first in dict order wins.
- **Explains Step 1:** P9-09. Step 1 measured resolution *rate* only; this measures *correctness*. It also reverses Step 1's "HP_2022 29/29, KA 26/27 fine".
- **Evidence:** `annexure_link_correctness.py` / `.out`, across 26 outputs: 254 links marked resolved, **107 point to a parent with the same appendix number**.

| Report | Resolved | Correct |
|---|---|---|
| HP_2022 | 29 | 2 (`Appendix-1` → `Appendix-15(i)`) |
| KA | 26 | 5 (`Appendix 2.1` → `Appendix 2.10`) |
| OD | 7 | 1 (`Appendix 8.1` → `Appendix 8.3`) |
| 2025_16 | 24 | 1 |
| 2023_11 | 24 | 6 |
| 2020_16, 2023_20, 2025_26 | — | 0 (all mapped to a generic `Appendix` or `Annexure` parent) |
| JH | 21/21 | 21 |
| 2023_19 | 14 | 13 |
| 2025_06 | 40 | 38 |

- **Fix proposal:** Exact ID matching.
  - Parse the ID with `(?:Annexure|Appendix)[\s\-–:]*((?:[IVX]+|[A-Z]|\d+)(?:\.\d+)*(?:\s*\([a-z0-9]+\))?)`.
  - Normalize to `appendix:2.1` or `appendix:15(i)`, and treat `Annexure` and `Appendix` as equivalent.
  - Index *both* parents and child header or paragraph chunks that start with an appendix ID, the latter covering BR's `Appendix-5.2` header chunks under `APPENDIX DESCRIPTION`.
  - Resolve by exact key, then by prefix (`15` → `15(i)`) only when that prefix is unique.
  - Otherwise leave it unresolved.
  - Always record unresolved references.
- **Risk / effort:** S.
- **Confidence:** verified by running.

#### C-9-04 · medium · Cross-references: table refs never resolve (0/1,164), up to half the "refs" are the table's own caption, chapter refs fail on "Chapter-N", Roman/Arabic mismatches and statutory "Section/Chapter" refs
- **Location:**
  - `cross_reference_resolver.py:83-100`: the table index is built from `hierarchy` values starting with "Table". Hierarchy values are parent section titles, so tables are never indexed.
  - `:28`: the table pattern has no `\b`, so it also matches `…table 2019` inside words.
  - `:127-162`: it scans every child including the caption chunk "Table 3.2: …", so the caption registers as a reference to itself.
  - `:69-71`: the chapter index needs `Chapter\s+`, so `Chapter-1 Introduction` (OD, JH, HP) is not indexed.
  - `:137-138`: the lookup key is `chapter_3` vs `chapter_iii`, with no Roman↔Arabic normalization.
  - `:22`: `Para(?:graph)?\.?\s*` doesn't accept the plural "Paras 2.1.1, 2.1.2 and 2.3" and captures only the first number of a list.
  - `:24` and `:26`: "Section 2.1 of the Act" or "Chapter VI of GFR" resolve to the report's own section or chapter (false positives). No context guard.
  - No dedupe.
- **Explains Step 1:** P9-08.
- **Evidence:** `xref_probe.py` / `.out`:
  - table refs resolved per report: 0 in 24 reports; 2025_06 2/182 and 2025_20 2/54.
  - share of table refs that are the table's own caption: OD 62/126, JH 94/186, BR 60/127, 2025_06 97/182.
  - chapter refs resolved: OD 12/24, 2020_16 12/22, 2023_20 0/8.
- **Fix proposal:** Use the shared `ReferenceIndex` from C-9-01.
  - Tables are indexed from the caption look-back.
  - Skip matches whose source chunk *is* that table's caption.
  - Use `\b` boundaries.
  - Normalize chapters: strip `[-–:]`, convert Roman to Arabic.
  - Handle list and range expansion ("3.1 to 3.7", "2.1.1, 2.1.2 and 2.3", "&").
  - Add an ancestor fallback for deep paragraph numbers.
  - Reject `Section|Chapter|Rule N of <the|this> (Act|Rules|Manual|Code|GFR)`.
- **Risk / effort:** M, shared with C-9-01.
- **Confidence:** verified by running.

#### C-9-05 · medium · Executive-summary citations: standalone citation chunks are dropped as "sub-headings", "&" separators are unsupported, and the ESI only covers children directly under the exec parent
- **Location:**
  - `executive_summary_parser.py:143-145`: any chunk under 80 characters that doesn't end with "." is treated as a sub-heading and skipped. Docling often emits the citation as its own line, e.g. GPU `child_p011_paragraph_0025` = `(Paras 2.1.1, 2.1.2, 2.2 and 2.3)` (33 chars), so it's never parsed.
  - `:36-50`: separators are only `,` and `and`. `(Paragraphs 3.5.3 & 3.5.4.2)` (2023_20) yields `[]`; `3.1 to 3.7` (2020_16) yields `3.1`, `3.7` only; a trailing period `3.2.` fails the `^\d+(\.\d+)*$` check.
  - `:24-31`: the title patterns are anchored at `^`, so KA's `5.Executive Summary` is missed (ESI null). Only exact child membership counts (`:90-93`): sub-parents inside the exec summary, created by P5.5 promotion, aren't included, so BR `Overview[9,21]` gives an index covering only [21,21].
  - `:207-214`: citations resolve only to parents whose title starts with the exact number. There's no ancestor fallback, and nothing works when parent titles carry prefixes (P4-01).
  - `:158-163`: item typing tests `recommend|should|may consider|ensure` *before* finding cues, so finding sentences containing "ensure" become "recommendation" (Step 1: OD "Article 21-A…").
- **Explains Step 1:** P9-07.
  - 2023_11's 54 citations became *parent titles* (P4/P5.5, Agent A), so they aren't in any child.
  - GPU's 4 are standalone chunks (above).
  - 2020_16 has 5 present and 0 extracted (range and "to" forms, plus the standalone-chunk skip).
- **Evidence:** `esi_probe.py` / `.out`, plus a direct regex test: `(Paragraphs 3.5.3 & 3.5.4.2)` gives `[]`.
- **Fix proposal:**
  - Treat a chunk that is *only* a citation as belonging to the previous item. Append it to the previous item and don't skip it.
  - Add `&` and `to` range expansion. Strip trailing dots.
  - Select exec pages by the exec parent's `page_range_physical` and include every child on those pages.
  - Relax the title pattern to `^\W*\d*\W*(executive summary|overview|highlights)`.
  - Resolve through the shared `ReferenceIndex` with ancestor fallback.
  - Type items with finding cues first, and give "recommendation" only to explicit "recommend" or a Recommendations sub-heading.
- **Risk / effort:** S–M.
- **Confidence:** verified by running.

#### C-9-06 · medium · Previous-audit references: 39% are substring junk and 25% are the report citing itself
- **Location:**
  - `temporal_extractor.py:44`: `(?:ATN|Action\s+Taken\s+Note).*?(\d{4})` has `re.IGNORECASE` (`:51-53`) and no `\b`. So "atn" matches inside Patn**a**, Visakhap**atn**am, R**atn**agiri and Nav**atn**a, and `.*?(\d{4})` then grabs the next 4-digit run anywhere later in the chunk.
  - `:43`: `Report No. N of YYYY` matches the report's own number, which appears on the cover, preface and in footers.
  - `:221-227`: dedup keeps only the *first* ref per year, so a junk ref can hide a genuine one for the same year.
- **Explains Step 1:** P9-10.
- **Evidence:** `temporal_probe.py` / `.out`. Of 72 refs across the 26 outputs, 28 are "atn" substring junk (BR 10/10, GPU 4/5, 2023_07 3/3) and 18 are self-references.
- **Fix proposal:**
  - Use `\bATNs?\b` case-sensitively, or `Action\s+Taken\s+Notes?`, and limit the year search to about 60 chars in the same sentence.
  - Exclude any ref whose `(no, year)` equals the report's own `report_no`.
  - Better patterns for real follow-ups: "Paragraph x.y of the Report No. N of YYYY", "earlier Audit Report (YYYY)", "PAC", "COPU recommendations".
  - Dedupe by `raw_text`, not by year.
- **Risk / effort:** S.
- **Confidence:** Verified by running.

#### C-9-07 · medium · `audit_period` is null for every single-financial-year report and every "FY"-prefixed range
- **Location:** `temporal_extractor.py:14-27`. Every pattern needs two years joined by "to", with the year directly after the keyword.
- **Root cause:** The pattern set misses these real phrasings, all printed by `temporal_probe.py`:
  - `for the year 2022-23` (2025_03, 2025_04, 2025_16, 2025_18: Accounts and FRBM reports);
  - `for the period 2020-21` (2022_29, 2024_13, 2025_14: Direct Taxes);
  - `during FY 2018-19 to FY 2020-21` ("FY" breaks `during\s+(\d{4})`);
  - `during the period 2015-22` (2025_20; the single range covers several years);
  - HP_2019 and HP_2022, which say `during 2016-17`.
  - There is also no start ≤ end check, and the "fallback" pattern (`:26`) can pick up any expenditure trend range. JH got 2019–2024 from a five-year trend table, while the SFAR's audit year is 2023-24.
- **Explains Step 1:** P9-15. All 10 reports with a null period are covered by these phrasings.
- **Fix proposal:**
  - Allow an optional `FY\s*` before each year.
  - Accept a single `(?:for|during)\s+(?:the\s+)?(?:financial\s+)?(?:year|period)\s+(?:FY\s*)?YYYY-YY` as a period of one fiscal year.
  - Accept `YYYY-YY` spans wider than one year (`2015-22`).
  - Rank candidates by section (scope/introduction first), then by keyword strength. Don't take the first hit.
  - Fall back to the overview LLM's `audit_period` (Phase 10a), which Step 1 found correct, e.g. OD "2018-19 to 2022-23". That's a hand-off to Agent D.
- **Risk / effort:** S.
- **Confidence:** Verified by running.

#### C-9-08 · medium · Section classification is a title regex with fixed confidences (0 / 0.7 / 0.9). "Other" is the default for 40–97% of sections, and the low-confidence flag can never fire
- **Location:**
  - `section_classifier.py:61-236`: patterns over `toc_entry` plus ancestor titles.
  - `:306`: confidence is 0.9 if the pattern matches the title, 0.7 if it matches an ancestor.
  - `:313`: `is_low_confidence` only if a match is < 0.5. The only values are 0.7 and 0.9, so it's dead. An unmatched section gets `other` with confidence 0.0 and `is_low_confidence=False`.
- **Root cause:**
  - The taxonomy is mostly topical (employment, infrastructure and so on). Most CAG body sections have topical titles ("2.3 Shortage of teachers") that fit nothing, so they become `other`.
  - The *role* of a section is never inferred from its position: a sub-section of a body chapter is a findings section.
  - `^recommendations` needs the plural at the start, so the recommendation boxes that P5.5 promoted to parents ("Recommendation 3.1 …") become `other`: OD 20, 2025_06 19.
  - `^overview` makes BR's and HP's report-level "Overview" parents exec summaries, which is right. But any "Overview of …" section title is typed exec summary too.
  - Ancestor-context matching at 0.7 spreads a type to every descendant. 2023_11 has 57 parents typed `executive_summary`, including garbage citation titles.
- **Explains Step 1:** P9-11.
- **Evidence:** `section_probe.py` / `.out`:
  - `other`: HP_2022 278/286, HP_2019 162/170, BR 484/639, OD 128/170, GPU 68/120.
  - `low_flag=0` in every report.
  - Of the `other` sections, many sit in body chapters (OD 110, HP_2022 269, 2025_26 99) and many contain "Audit observed/noticed" cues (OD 54, BR 104).
- **Fix proposal:** Two axes.
  - **(a) Role:** preface, exec_summary, introduction, audit_framework, findings, recommendations, conclusion, appendix, front_matter. Derive it from position: which L1 chapter the section is under, and whether it sits between the Introduction chapter and the Conclusion/Appendix. Add title cues (singular `^recommendations?\b`) and content cues ("Audit observed", "Recommendation x.y").
  - **(b) Topic:** keep the current topical patterns as an optional secondary tag.
  - Give real confidences: position plus cue agreement.
  - Send only the truly ambiguous sections to an LLM, batched once per report with all titles in one call.
  - The executive-summary parser and the temporal extractor consume `section_type`, so this also helps C-9-05 and C-9-07.
- **Risk / effort:** M.
- **Confidence:** Verified by running.

#### C-9-09 · low–medium · Entity lists: the "scheme" acronym pattern captures any capitalised phrase before an acronym, and per-finding entity lists are non-deterministic
- **Location:**
  - `entity_extractor.py:40`: `([A-Z][\w\s]{5,55})\s*\([A-Z]{2,8}\)` is filed under `schemes`. It matches every acronym definition: "Head Master (HM)", "Day Meals (MDM)", "Gross Enrolment Ratio (GER)", "Revenue Receipts (RR)", "Class XII from Council of Higher Secondary Education". Because `[\w\s]` crosses lowercase words, a match can start at any capital, e.g. "IF stipulated constitution of a District Level Committee".
  - `:37-38`: patterns 0 and 1 duplicate each other; 1 is a subset of 0. Captures start at any capitalised word, e.g. "There are seven Centrally Sponsored Scheme" and "DLC to monitor the implementation of the Scheme".
  - `:216`: `list(set(entities))[:10]`. Set order depends on the per-process hash seed, so *which* 10 entities a finding keeps changes from run to run. The output is non-deterministic.
  - `:285-304`: substring dedup is O(n²) and case-folded. It merges genuinely different entities that contain one another.
  - The alias normalisation (`enrichment_patterns.yaml: entity_aliases`) is never loaded (C-9-10). So "Ministry of Education, GOI", "Ministry of Education, GoI" and "Ministry of Education" stay as three entries.
- **Explains Step 1:** P9-12.
- **Evidence:** `entity_probe.py` / `.out`. The acronym pattern alone yields OD 94, JH 95 and HP_2022 59 candidates, the large majority of "schemes" (OD 80 final). The samples are mostly not schemes.
- **Fix proposal:**
  - Move the acronym pattern to a separate `acronyms` map (`{"GER": "Gross Enrolment Ratio"}`), which is useful for query expansion. Keep `schemes` to phrases ending in Scheme/Yojana/Mission/Abhiyan/Programme.
  - Anchor matches to a run of capitalised words only: `(?:[A-Z][\w'-]*(?:\s+(?:of|for|and|the)\s+|\s+)){1,7}(?:Scheme|…)`.
  - Sort before truncating.
  - Load `entity_aliases` for canonicalisation.
- **Risk / effort:** S.
- **Confidence:** Verified by running.

#### C-9-10 · high (for the main session's work) · Most of `enrichment_patterns.yaml` is never read: editing its finding, non-finding, section, alias or temporal patterns changes nothing
- **Location:**
  - `pattern_loader.py` getters `get_finding_type_patterns`, `get_non_finding_patterns`, `get_section_patterns`, `get_entity_aliases`, `get_deficiency_to_type_map`, `get_temporal_config` and `reload_patterns` have **no callers** anywhere in `src/` or `scripts/` (grep).
  - The only live reads are `get_confidence_thresholds()`, used for the section threshold and the LLM band, and `get_llm_validation_config()`.
  - So these YAML sections are dead:
    - `finding_types` (`enrichment_patterns.yaml:14-168`);
    - `non_finding_patterns` (`:169-197`);
    - `section_patterns` (`:198-276`);
    - `entity_aliases` (`:277-319`);
    - `temporal` (`:320-329`);
    - `confidence_thresholds.finding_extraction`.
  - The live patterns are hard-coded in `finding_extractor.py`, `semantic_patterns.py` (main session), `section_classifier.py` and `entity_extractor.py`.
- **Explains Step 1:** It's why "87+ regex patterns" in CLAUDE.md and the YAML diverge from behaviour. It's latent for output and critical for anyone tuning.
- **Fix proposal:** Pick one home for patterns.
  - Either wire the YAML into the extractors (`FindingExtractor`, `SectionClassifier`, `EntityExtractor`) with a unit test asserting each YAML key is consumed,
  - or delete the dead YAML sections so nobody tunes them.
  - Log the loaded pattern counts at startup.
- **Risk / effort:** S to delete, M to wire in. Hand-off to the main session, which owns `enrichment_patterns.yaml` and the finding extractor.
- **Confidence:** Verified by grep.

#### C-9-11 · low–medium · Amount-only finding dedup marks unrelated findings as duplicates
- **Location:** `semantic_enrichment_service.py:764-862` (`_deduplicate_cross_finding_amounts`). Two findings are "duplicates" if their `total_amount_inr` is within 1% and they're within 15 pages. Text is never compared. The flag `is_duplicate` persists in the output and excludes the finding from `primary_findings` totals.
- **Explains Step 1:** A side effect adjacent to P9-05. Monetary semantics belong to the main session; the dedup lives here.
- **Evidence:** `dedup_probe.py` / `.out`. 35 findings are marked `is_duplicate` across 26 reports, and **33 have unrelated text** (word Jaccard < 0.3) versus the retained finding in their amount group. Example: 2022_29 "We noticed errors in assessment while giving effect to appellate order…" vs "The AO, while computing tax liability…", both ₹45.49 crore. Direct Taxes reports often repeat round figures.
- **Fix proposal:**
  - Require amount match *and* text similarity (≥ 0.5 Jaccard, or same source paragraph number).
  - Or restrict dedup to exec-summary vs chapter copies (`is_executive_summary`).
- **Risk / effort:** S.
- **Confidence:** Verified by running. The comparison heuristic picks one retained finding per amount group.

#### C-9-12 · low · `_link_findings_to_recommendations` links only within the same chapter and ±5 pages, so recommendations in a closing "Recommendations" chapter or box never link to the findings they address
- **Location:** `semantic_enrichment_service.py:711-726`.
- **Root cause:** It's a proximity heuristic. Recommendations numbered "Recommendation 3.1" or listed in a summary chapter point at paragraphs by number, and the paragraph numbers are ignored.
- **Fix proposal:**
  - Link through `paragraph_citations` and `rec_number` (x.y) to findings whose section number shares the prefix, using the shared `ReferenceIndex` (C-9-01).
  - Then fall back to proximity.
  - Take the top 5 by similarity, not the first 5 in list order.
- **Risk / effort:** S.
- **Confidence:** Verified by reading.

### Phase 9 runtime: P9-14 concurrency and rate-limiter design (concurrency side only)

The main session owns the validator's logic, including the fact that UNCERTAIN on failure counts as valid. This section covers only how calls are scheduled.

**Current behaviour, verified by reading:**
- Phase 9 runs report by report and finding by finding, in a single thread (`main.py:1256`, `semantic_enrichment_service.py:651-683`).
- Each call goes through `generate_with_retry` (`src/core/gemini_client.py:81-123`): up to 8 retries with backoff of 5, 10, 20 and 40 s, then 60 s each, about 5 minutes per call before giving up.
- Vertex serves Gemini through Dynamic Shared Quota, so a 429 is a capacity signal shared with every caller in the project and region, not a per-process limit.
- Each 429 spell stalls the entire serial phase. Step 1's figures:
  - 31 final validation failures, roughly 2.5–3 minutes apart;
  - 318 failed attempts out of 645;
  - Phase 9 took 3 h 20 m on union.
- Phase 10a already uses a `ThreadPoolExecutor` (`batch_service.py:313`) and 10b has its own `_wait_for_rate_limit` (`gemini_visual_extractor.py:276`). So three independent throttles compete for the same DSQ, and the CPU and GPU VMs compete too (X-02).

**Proposed design:**
1. **One process-wide gate in `src/core/gemini_client.py`.** Every Gemini call in Phases 5.7, 9, 10a and 10b goes through it. It has:
   - a bounded concurrency semaphore, starting around 8;
   - AIMD adaptation: after N consecutive successes, add 1 to the limit, up to a cap (e.g. 16); on a 429, halve the limit (minimum 1);
   - a shared cool-down: the first 429 sets `resume_at = now + backoff`, and every worker waits until then, so workers don't each retry blindly into a busy model;
   - per-phase metrics (calls, 429s, time waited), written to `processing_stats` and `run_summary.json`.
2. **Deadlines instead of per-call retry budgets.** Each phase gets a wall-clock budget. When it runs out, the remaining items are recorded as `validation_status: "unverified"` and reported. Semantics are the main session's call; this only records the state. The phase no longer burns about 5 minutes on each failing item.
3. **Parallelism.** Use a `ThreadPoolExecutor` sized by the gate for the per-finding (or per-batch) calls inside a report, and overlap across reports.
   - The orchestrator is phase-major: Phase 5 for all reports, then Phase 6 for all, and so on.
   - Make the LLM-bound phases (9, 10a, 10b) consume a queue fed as each report finishes Phase 8. Then Gemini calls overlap with the next report's Docling (CPU or GPU bound) instead of running after it.
4. **Fewer calls matters more than faster calls.** Batching many validation items into one prompt per chapter or report is the main session's design decision. For concurrency, one call carrying 20 items costs the same quota slot as one call carrying a single item.
5. **Across VMs.** DSQ is project-wide, so per-VM gates can't coordinate exactly. Options, cheapest first:
   - (a) AIMD per process is self-regulating: when another VM consumes capacity, 429s rise and each gate backs off. This is enough for 2–3 VMs.
   - (b) Stagger schedules so the LLM-heavy tails don't overlap, for example tier VMs offset by Phase 5 duration.
   - (c) Use Vertex **batch prediction** for 10a and 10b, which aren't interactive. It has no 429s, and the jobs are asynchronous and cheaper. The latency is minutes to hours, which is acceptable for a nightly corpus build.
   - (d) Provisioned Throughput is a purchase decision; ask the user first (standing rule).
   - A distributed token bucket (GCS generation-match counter or Firestore) is possible but not worth it at this scale.
- **Effort:** M (gate plus executor), L (report-major pipelining).
- **Risk:** Higher concurrency without AIMD would increase 429s. Test with the 18-report union set.

### Wired-and-working inventory (Phase 8 and 9, my modules)

| Component | Status | Evidence |
|---|---|---|
| Assembly write, report year, empty-artifact cleanup | works (cleanup misses junk titles, C-8-09) | outputs |
| Parent tier metadata (`audit_category`, department, subtype) | runs but broken | C-8-01, C-8-02 |
| `processing_status` in report_metadata | runs but broken (frozen) | C-8-03 |
| Parent `content_summary` | never runs (no merge) | C-8-04 |
| Footnote index (`_build_footnote_index`) | never produces output: 0 `footnote` chunks in all 26 outputs (upstream never emits the type; hand-off to B) | `validation_probe` side check |
| Visual asset registry captions | runs but broken (generic captions) | C-8-06 |
| `extraction_confidence` | runs, TOC factor always 75 | C-8-07 |
| `propagate_semantic_enrichment_to_chunks`, `section_type` | dead logic (wrong key) | C-8-08 |
| Report-type profiles (atir, state_*) | dead code in production | C-9-02 |
| Evidence linker | runs, structurally 0 | C-9-01 |
| Annexure linker | runs; 58% of resolved links wrong; silent when no appendix parents | C-9-03 |
| Cross-reference resolver | runs; tables 0% | C-9-04 |
| Executive-summary parser | runs; misses standalone and "&" citations | C-9-05 |
| Temporal: audit period / previous refs | runs but broken | C-9-07 / C-9-06 |
| Section classifier `is_low_confidence` | dead (can never be true) | C-9-08 |
| `enrichment_patterns.yaml` (most sections) | dead config | C-9-10 |
| Finding–recommendation linking | works (proximity only) | C-9-12 |
| Amount dedup | runs but mostly wrong | C-9-11 |
| Phase 9 trace red flags (`monetary_total_implausible`, `finding_other_ratio_high`, `section_other_ratio_high`) | computed, then discarded in production (C-X-01) | `trace_emitter.py:293` |

---

## Phase 8: validation_service.py

#### C-8-10 · medium · The "RAG readiness" score is blind to every failure Step 1 found, and it runs on only the first 3 reports with the result thrown away
- **Location:**
  - `validation_service.py:83-155` and `:472-609`: the score is built from orphan rate, depth, concentration, inversions, TOC false-positive regexes, metadata completeness, garbage chunks, entity noise, and finding and caption issues.
  - `main.py:1335-1387`: `[:3]`, log line only.
- **Evidence:** `validation_probe.py` / `.out`, which reruns it on all 26 outputs:
  - Stale pre-fix 2025_06 (worst in the corpus: number recall 0.64, 120 reversed chunks) scores **92.9 "WORLD-CLASS"**.
  - BR (P7-01 critical: 310 duplicate parents, 611 children outside their parent's pages) scores **89.9 "PRODUCTION"**.
  - OD scores 94.5 WORLD-CLASS, even though its summaries are fabricated (P10a-01).
  - Every report scores ≥ 84.
- **Latent crash:** `_validate_footnotes` (`:894-912`) treats `footnote_index` as a list of dicts, but assembly writes a dict keyed by number (`assembly_service.py:663`). Iterating yields strings, so `f.get` raises `AttributeError: 'str' object has no attribute 'get'` (verified by calling it with `{'1': {...}}`). It's hidden only because no report has footnote chunks. The first report with a footnote makes the sample validation log "⚠ Validation failed".
- **Fix proposal:**
  - Replace the score with hard checks that map to real defects, most available in `scripts/evaluation/preflight_check.py` or cheap to add:
    - duplicate parent IDs;
    - children outside their parent's page range;
    - wrong-parent headers;
    - reversed text;
    - generic table captions;
    - logical page == physical+1 on all pages;
    - summary numbers not in the text (P10a).
  - Run on **every** report. Persist the result into `processing_stats.validation`. Feed failures into the exit code (C-R-01).
  - Fix `_validate_footnotes` to iterate `.values()`.
- **Risk / effort:** M.
- **Confidence:** Verified by running.

---

## Config (config.py vs parsing_config.yaml)

Method: I enumerated every dataclass field in `config.py` and grepped `src/` and `scripts/` for `.field_name` reads outside `config.py`.

#### C-C-01 · low · Config keys that are defined but never read
These keys can be tuned with no effect:
- `scaffolding.embedded_toc_min_entries`
- `scaffolding.toc_rejection_alert_threshold`
- `scaffolding.min_toc_quality_score`
- `chunking.max_parent_chunk_pages`
- `semantic_enrichment.min_monetary_value_for_high_severity`
- `instrumentation.enabled`: only the `--trace` flag switches tracing (`main.py:166`).

`parsing_config.yaml` documents each of them as if it were live. **Fix:** wire them up or delete them. Add a startup warning for YAML keys that don't map to a field: `_apply_yaml_overrides` (`config.py:490-498`) silently drops unknown keys and typos. Effort S.

#### C-C-02 · low · Config read outside the loader, and a name collision
- **Read outside the loader:** `content_extraction.pdfmux` is a nested dict that `config.py` has no field for. `content_extraction_service.py:152-159` reads it by opening the YAML file directly. There are two config paths, and env overrides (`PARSING_*`) don't apply to it.
- **Name collision:** "llm_validation" means Phase 5.7 TOC validation in `parsing_config.yaml:138` and Phase 9 finding validation in `enrichment_patterns.yaml:337`. Both use model `gemini-3.8-flash`, and nothing says which is which.
- **Env override typing:** `_apply_env_overrides` assigns the raw string to List and Dict fields (`config.py:520-531`), which breaks `assembly_bookmark_patterns` or `severity_thresholds` if they are overridden by env.
- **Docstring:** the `ChunkingConfig` docstring for `max_parent_chunk_pages` sits under `max_child_chunk_chars` (`config.py:355-367`); cosmetic.
- **Fix:** Rename the sections (`toc_llm_validation`, `finding_llm_validation`). Add a `pdfmux` dataclass. Parse env values with `yaml.safe_load` for typing. Effort S.

#### C-C-03 · info · Duplicate or conflicting values
- No key is defined with *different* values in `config.py` and `parsing_config.yaml`. The defaults match: I compared all 43 fields.
- There are three pairs worth noting:
  - `layout.table_min_non_empty_cells` and `content_extraction.table_min_non_empty_cells` are the same concept in two places; both are 3, and both are read.
  - The finding confidence threshold exists in both YAMLs: `semantic_enrichment.finding_confidence_threshold`, which is live, and `enrichment_patterns.yaml: confidence_thresholds.finding_extraction`, which is dead.
  - `pattern_loader.get_confidence_thresholds()` has *code* defaults 0.4 and 0.4 (`pattern_loader.py:203-208`), different from the YAML values 0.5 and 0.5. They apply only if the YAML file is missing, which would lower the validation band silently.

---

## Instrumentation and gcs_integration

#### C-X-01 · medium · In production every red flag is computed and then discarded
- **Location:**
  - `trace_emitter.py:293-294` and all `emit_*` methods: `if not self.enabled: return`.
  - Production never passes `--trace` (`run-parsing.yml:260-270`).
  - `main.py:177-180` uses the no-op emitter.
- **Root cause:** The code already detects many of the defects the audit found:
  - `monetary_total_implausible` (P9-05, whose absurd totals of ₹80 lakh crore would trigger it);
  - `finding_other_ratio_high` (P9-03);
  - `section_other_ratio_high` (P9-11);
  - `year_extraction_conflict`;
  - `High OCR failure rate` (P1-01);
  - `No parent chunks created` and `Very high child-to-parent ratio`;
  - `image_captions_not_hydrated` (P6-06).

  None of them reach the logs or the output. `--trace` also forces sequential mode and writes large Markdown traces, so it isn't a production switch.
- **Fix proposal:**
  - Split red flags from tracing: always collect red flags (cheap), write them to `processing_stats.red_flags` per report and to `run_summary.json`, and log each at WARNING.
  - Keep full event traces behind `--trace`.
  - Red flags at "error" severity feed the exit code (C-R-01).
- **Risk / effort:** S.
- **Confidence:** Verified by reading.

#### C-X-02 · low · `gcs_integration.py` (283 lines) is dead code
- **Location:** It has no importers (grep over `src`, `scripts` and `tests`). All GCS I/O happens in the workflow shell.
- **Fix:** Delete it, or use it for per-report status files (C-R-04). The download and upload conventions in it (`raw/{tier}`, `processed/{tier}`) match the workflow's. Effort S.

---

## Pattern table (for the answer key)

These are the regexes in my modules. FP is a false positive observed in the real output; Miss is a real reference the pattern fails on. The probe scripts are in `<scratchpad>/step2/C/`.

| Module:line | Pattern (abridged) | Meant to match | Observed FP (examples) | Observed misses (examples) |
|---|---|---|---|---|
| `evidence_linker.py:61-67` | `Table\s+(\d+(?:\.\d+)*)` ×4 overlapping | Table refs in finding text | None resolve, so no FPs; duplicate matches from overlapping patterns | All resolutions fail (C-9-01) |
| `evidence_linker.py:73-83` | `Annexure[\s-]?([IVX]+\b\|[A-Z]\|\d+)`, `(?:Appendix\|Annex)…(\d+)` | Annexure/appendix refs | Duplicates "(Annexure 8)" and "Annexure 8"; self-link to the referencing chunk | "Appendix 2.1" captured as "2"; resolver only knows "Annexure" (HP_2022 27 refs, 0 links) |
| `evidence_linker.py:89-96` | `Para(?:graph)?\.?\s+(\d+(?:\.\d+)*)` | Paragraph refs | Resolver joins leading integers of hierarchy levels, giving a wrong paragraph | "Paras 2.1.1, 2.1.2" (plural and list) |
| `evidence_linker.py:101-105` | `pages?\s+(\d+…)`, `\(p(?:g)?\.?\s*(\d+)\)` | Page refs | Every "page N" becomes a link without resolution, including table-row text | Logical vs physical page never converted |
| `cross_reference_resolver.py:22` | `Para(?:graph)?\.?\s*(\d+\.\d+(?:\.\d+)?)` | Paragraph refs | "para 6 of Chapter III of RLDA Constitution Rules" (statutory) | "Paras 3.4.1, 3.4.2 and 3.4.3": only the first is captured (26 list refs); single-level "Para 5" |
| `cross_reference_resolver.py:24` | `Section\s*(\d+\.\d+…)` | Report sections | "section 16.1 of the National Highways Authority of India Act, 1988" | Rarely used by CAG ("Paragraph" is standard) |
| `cross_reference_resolver.py:26` | `Chapter\s+([IVXivx]+\|\d+)` | Chapter refs | "Chapter VII (Finance and Budget) of RLDA Constitution Rules"; "chapter VIA of the Income Tax Act" (captures "VI") | Unresolved: "Chapter VI" 12, "Chapter I" 10, "Chapter 3" 7: index needs `Chapter\s+` (misses "Chapter-1") and has no Roman↔Arabic mapping |
| `cross_reference_resolver.py:28` | `Table(?:\s+No\.?)?\s*[-\s]?(\d+(?:\.\d+)?)` (no `\b`) | Table refs | The table's own caption counts as a ref: OD 62/126, JH 94/186, 2025_06 97/182 | All 1,164 unresolved (index built from hierarchy titles) |
| `cross_reference_resolver.py:30-31` | `as (discussed\|mentioned…) (above\|earlier\|in) (Para)? N.N` | Back-references | Duplicates of the `:22` matches | — |
| `annexure_linker.py:17-35` | Context-gated `(Annexure\|Appendix)[\s-]*[A-Z0-9IVX]+[\w-]*(\.\w+)*` (after "in/at/vide/as per/and/(") | Appendix refs | — | A reference at sentence start without a gate word ("Appendix 3.1 shows…"); no refs recorded at all when a report has no appendix parents (HP_2019: 11 in findings, 0 links) |
| `annexure_linker.py:108-120` | Substring and "strip trailing digits" matching | Resolve ref to parent | 147/254 resolved links point at the wrong appendix: `Appendix-1` → `Appendix-15(i)`, `Appendix 2.1` → `Appendix 2.10`, `Annexure 3` → first annexure parent | BR `Appendix-5.2` exists only as header chunks, never indexed |
| `executive_summary_parser.py:24-31` | `^executive\s+summary`, `^highlights?$`, `^summary$`, `^overview$`, `^key\s+findings`… | Exec summary parent | Any "Overview" parent | KA "5.Executive Summary" (numbered prefix) |
| `executive_summary_parser.py:36-50` | `\(Para(graph)?s?\.?\s*([\d.]+(\s*(,\|and)\s*[\d.]+)*)(…Page no. N)?\)` | Citations | — | "(Paragraphs 3.5.3 & 3.5.4.2)" (`&`); "(Paragraph 3.1 to 3.7, 3.10…)" (`to` range); standalone citation chunks skipped as sub-headings (GPU 4/4) |
| `executive_summary_parser.py:159-163` | `recommend\|should\|may\s+consider\|ensure` → recommendation; then finding cues | Item type | Finding sentences containing "ensure" or "should" typed recommendation (OD "Article 21-A…") | — |
| `section_classifier.py:61-236` | Title and ancestor regexes, confidence 0.9/0.7 | Section role/topic | `^overview` catches any "Overview …"; ancestor matching gives descendants the parent's type (2023_11: 57 exec parents) | "Recommendation 3.1" (singular) → other (OD 20); topical body sections → other (OD 110) |
| `entity_extractor.py:37-38` | `(Under )?(the )?([A-Z][\w\s]{2,55}(Scheme\|Programme\|…))` | Schemes | "There are seven Centrally Sponsored Scheme"; "DLC to monitor the implementation of the Scheme"; "Orientation Programme" | Lowercase or ALL-CAPS scheme names |
| `entity_extractor.py:40` | `([A-Z][\w\s]{5,55})\s*\([A-Z]{2,8}\)` → schemes | Scheme + acronym | "Head Master", "Day Meals", "Gross Enrolment Ratio", "Revenue Receipts", "Right to Education", "IF stipulated constitution of a District Level Committee" (OD 94, JH 95 candidates) | — |
| `entity_extractor.py:46-47` | `(Ministry\|Department) of [A-Z]…{0,5}` | Ministries/departments | 2025_04: 74 "ministries" (mostly real: Union Accounts lists them) | Variants not aliased ("…, GOI" / "…, GoI") |
| `entity_extractor.py:79` | `((?:[A-Z][a-z]+\s+){1,5}(Corporation\|Authority\|Board\|Commission\|Council))` | Organisations | "National Council", "State Council", "Municipal Commission" (generic) | Acronym organisations outside the fixed list |
| `temporal_extractor.py:14-27` | `(covering\|during\|from\|for the years) YYYY-YY to YYYY-YY`, `period from Month YYYY to Month YYYY`, bare `YYYY-YY to YYYY-YY` | Audit period | Bare fallback picks trend ranges (JH 2019–2024 for the 2023-24 SFAR) | "for the year 2022-23" (4), "for the period 2020-21" (3), "during FY 2018-19 to FY 2020-21", "during the period 2015-22", "during 2016-17" (HP) |
| `temporal_extractor.py:40-44` | outstanding paras…YYYY; earlier audit…YYYY; `Report No. N of YYYY`; `(ATN\|Action Taken Note).*?(\d{4})` (IGNORECASE, no `\b`) | Previous-audit refs | 28/72 are "atn" inside Patna/Visakhapatnam/Ratnagiri/Navaratna; 18/72 are the report's own number | "Paragraph x of Report No. N" follow-ups are captured only via the Report No pattern |
| `temporal_extractor.py:31-36` | `(\d{4})[-–—](\d{2,4})`, `\b((?:19\|20)\d{2})\b` | Reference years | No `\b` on the range: "2019-205" gives end year 205, skipped by the range check only for the start year | — |
| `assembly_service.py:39-53` | Artifact parent titles (`^\d+_[A-Z]`, `^Blank\s+Page$`, …) | Empty merger-junk parents | — | `Binder1.pdf`, `2 TOC`, `1 Cover pages`, `1. Nagarothana Front Page` |
| `assembly_service.py:844-858` | `(**)?Table\s*([\d.]+)\s*[:\-–]?\s*(.+)` on the table's first line or hierarchy | Table caption | — | The caption line preceding the table (the common case), so "Table on page N" |
| `assembly_service.py:873-879` | Visual-subtype keywords (`location` → map, `structure` → diagram) | Figure subtype | "location" and "structure" in ordinary captions | — |

## Step 1 issue coverage

| Step 1 ID | Explained by |
|---|---|
| P1-03 | C-R-01 |
| P1-04 | C-R-02, C-R-03, C-R-11 |
| P1-05 (Phase 9 typing part) | C-9-02; manifest part → Agent A |
| P1-07 | C-R-10 (check location); Agent A owns the cache writer |
| P6-04 (registry caption) | C-8-06; Phase 6 caption extraction → Agent B |
| P6-08 | C-R-08 |
| P6-12 (footnotes never linked) | Wired-and-working: 0 `footnote` chunks in all outputs (upstream → Agent B); C-8-10 latent crash |
| P7-05 | C-8-05 |
| P8-01 | C-8-01 |
| P8-02 | C-8-02, C-8-03, C-8-04 |
| P8-03 (logical page) | Not explained here: assembly copies `child.source_page_logical` unchanged (`assembly_service.py:479`). The value is produced in Phase 6/7 (Agent B) from the scaffold page map (Agent A). |
| P8-04 | C-R-04 |
| P9-06 | C-9-01 |
| P9-07 | C-9-05 |
| P9-08 | C-9-04 |
| P9-09 | C-9-03 (also reverses Step 1's "HP_2022/KA fine") |
| P9-10 | C-9-06 |
| P9-11 | C-9-08 |
| P9-12 | C-9-09 |
| P9-14 (concurrency side) | Runtime design section above |
| P9-15 | C-9-07 |
| X-01 (preflight blind spots) | C-8-10 (in-pipeline validator equally blind) |
| X-02 | Runtime design section above (cross-VM) |
| Shared log file | C-R-05 |
| GCS cleanup pending | C-R-11 (cleanup would be undone) |
| P9-01/02/03/04/05/13 | Main session (deep dives). Adjacent items: C-9-10 (dead YAML), C-9-11 (dedup), C-8-08 (paise field copied) |

| Step 1 ID | Explained by |
|---|---|
| P1-03 | C-R-01 |
| P1-04 | C-R-02 (plus C-R-03) |
| P1-05 (Phase 9 typing part) | C-9-02 |
| P1-07 | C-R-10 (check location); Agent A owns the cache writer |
| P6-04 (registry caption) | C-8-06 |
| P6-08 | C-R-08 |
| P7-05 | C-8-05 |
| P8-01 | C-8-01 |
| P8-02 | C-8-02, C-8-03, C-8-04 |
| P8-04 | C-R-04 |
| P9-06 | C-9-01 |
| P9-07 | C-9-05 |
| P9-08 | C-9-04 |
| P9-09 | C-9-03 |
| Shared log file | C-R-05 |

## Hand-offs

- **Agent B:** `chunking_service.py:582-594`, `:629-640` and `:740-742` don't pass `audit_category`, `department` or `report_subtype` to ParentChunk and ChildChunk (C-8-01).
- **Agent A:**
  - `manifest_ingestion_service.py:670` and `:683`: the state and local manifests have no `Department` column (only `Union Department`); department and subtype need inferring (C-8-02).
  - `report_type_profiles.detect_report_type` reads `report_title`, but the metadata key is `Title` (C-9-02).
  - ATIR category (P1-05).
  - Bookmark junk as parents (C-8-09).
- **Agent D:**
  - Merge `batch_jobs/hierarchical` summaries into parent `content_summary` (C-8-04).
  - Report Phase 10 per-item losses to the orchestrator so the exit code can reflect them (C-R-01).
  - `main.py:1583` passes `pdf_dir="data/raw"` for every tier. Check that 10b resolves `raw/{tier}/`.
  - `skip_existing=True` (`main.py:1584`) plus the non-deleting VM sync (C-R-11): charts extracted by older code are never redone.
  - Use the overview LLM's `audit_period` and department as fallbacks (C-9-07, C-8-02).
  - The GPU workflow probably shares the C-R-11 sync pattern.
  - Phase 10 rate limiting should use the shared gate (P9-14 design).
- **Agent A (additional):**
  - 2023_11's 54 exec-summary citations "(Paragraph 3.2, Page no. 11)" became parent titles, so the exec-summary parser can't see them (C-9-05).
  - The triage cache writer should store the PDF hash (C-R-10).
- **Agent B (additional):**
  - 0 `footnote` chunks exist in all 26 outputs, so P4-1 capture never fires and `footnote_index` is always empty (P6-12).
  - `source_page_logical` (P8-03) is produced upstream; assembly only copies it (`assembly_service.py:479`).
  - Store `table_number` and `caption` on table chunks, for C-8-06, C-9-01 and C-9-04.
- **API/indexer owner:**
  - `src/rag_pipeline/indexer.py:81-83` globs `**/*_chunks.json` and ignores manifest status, so stale and failed outputs get indexed (C-R-02).
  - `src/api/gcs_sync.py` and `src/api/config.py` read the shared manifest (C-R-04).
- **Main session:**
  - Most of `enrichment_patterns.yaml` is dead (C-9-10).
  - `propagate_semantic_enrichment_to_chunks` copies `total_amount_inr` (paise) into `structured_data` (`assembly_service.py:1104`; P9-05 naming).
  - Amount-only dedup marks unrelated findings as duplicates (C-9-11).
  - `atir` and `state_*` report types never reach the finding extractor (C-9-02). Re-measure after the fix.
  - The pattern table above is for the answer key.
- **User / infra:** Until C-R-11 is fixed, the planned GCS cleanup (misplaced PDFs in `raw/union/`, stale 2025_06) must also be done in `cag-parsing-vm:/var/tmp/cag/data/`, or the next run restores the files.

## Summary (ranked issue list)

| # | ID | Sev | Title | Location |
|---|---|---|---|---|
| 1 | C-R-11 | high | GCS deletes and moves are undone by the VM's persistent copy (non-deleting rsync both ways); blocks the pending cleanup | `run-parsing.yml:190,229-230,278-284` |
| 2 | C-R-01 | high | Always exits 0; `final_success` ignores Phase 1–3 and Phase 10 failures | `main.py:2100,1856-1864,193-197,2082`; `run-parsing.yml:325-330` |
| 3 | C-R-02 | high | Failed reports keep old `*_chunks.json`; the indexer ingests it regardless | `assembly_service.py:957-979`; `indexer.py:81-83` |
| 4 | C-9-03 | high | 147/254 "resolved" annexure links point at the wrong appendix; nothing is recorded when there are no appendix parents | `annexure_linker.py:50-61,84-86,108-120` |
| 5 | C-9-10 | high* | Most of `enrichment_patterns.yaml` is never loaded | `pattern_loader.py` getters with no callers |
| 6 | C-9-01 | medium | Evidence links structurally impossible | `semantic_enrichment_service.py:747-749`; `evidence_linker.py:343-462` |
| 7 | C-9-04 | medium | Cross-refs: tables 0/1,164; captions counted as refs; Chapter-N, Roman/Arabic and statutory FPs | `cross_reference_resolver.py:22-31,69-100` |
| 8 | C-9-05 | medium | Exec-summary citations: standalone chunks skipped; `&` and `to` unsupported; direct-children-only coverage | `executive_summary_parser.py:24-50,90-93,143-145,207-214` |
| 9 | C-9-08 | medium | Section classifier: "other" 40–97%; `is_low_confidence` can never be true | `section_classifier.py:61-339` |
| 10 | C-9-02 | medium | ATIR and state report-type profiles unreachable | `semantic_enrichment_service.py:159-164`; `main.py:1269` |
| 11 | C-8-01 | medium | Parents always `compliance`; department and subtype not on chunks | `chunking_service.py:582-640` (B); `assembly_service.py:356-518` |
| 12 | C-8-02 | medium | ministry "Unknown", department null for state/local | `assembly_service.py:337-346`; `manifest_ingestion_service.py:670,683` (A) |
| 13 | C-8-03 | medium | `processing_status` frozen at `chunking_complete` | `main.py:986,1202`; `assembly_service.py:353` |
| 14 | C-8-04 | medium | Parent `content_summary` never merged | no writer (grep) |
| 15 | C-8-06 | medium | Registry table captions "Table on page N" | `assembly_service.py:770,828-860` |
| 16 | C-8-10 | medium | Validation score blind (stale 2025_06 = 92.9 WORLD-CLASS); latent footnote crash | `validation_service.py:472-609,894-912` |
| 17 | C-X-01 | medium | Red flags discarded in production | `trace_emitter.py:293`; `main.py:177-180` |
| 18 | C-R-03 | medium | Manifest "completed" written at Phase 8 | `assembly_service.py:292-293` |
| 19 | C-R-04 | medium | Shared `manifest.json`, last writer wins; entries lack tier, path and run ID | `assembly_service.py:68,938` |
| 20 | C-R-05 | medium | Shared daily log file, rotation, GCS overwrite | `main.py:1955,1975-1980`; `run-parsing.yml:285` |
| 21 | C-R-06 | medium | Comma-separated `skip_phases` crashes argparse | `run-parsing.yml:28-29,291-293`; `main.py:2025-2031` |
| 22 | C-R-07 | medium | Parallel path diverges from sequential | `parallel_runner.py:134-313` |
| 23 | C-9-06 | medium | Previous-audit refs: 28/72 "atn" junk, 18/72 self-refs | `temporal_extractor.py:40-44,221-227` |
| 24 | C-9-07 | medium | `audit_period` null for single-FY and "FY" phrasing | `temporal_extractor.py:14-27` |
| 25 | P9-14 design | medium | Serial calls with independent 5-minute retries; shared AIMD gate, deadlines, pipelining, batch prediction | `gemini_client.py:81-123`; `main.py:1256` |
| 26 | C-9-09 | low–med | Entity noise (acronym pattern); non-deterministic truncation; aliases unused | `entity_extractor.py:37-40,216` |
| 27 | C-9-11 | low–med | Amount-only dedup: 33/35 unrelated | `semantic_enrichment_service.py:764-862` |
| 28 | C-8-05 | low–med | Stats and manifest count uncleaned parents | `assembly_service.py:228-229,293` |
| 29 | C-8-08 | low | `section_type` never propagated (wrong key); schema mixing | `assembly_service.py:1055-1141` |
| 30 | C-9-12 | low | Finding↔rec linking proximity only | `semantic_enrichment_service.py:711-726` |
| 31 | C-R-08 | low | Figure and corpus-table counters always 0 | `main.py:899-903,941-944` |
| 32 | C-R-10 | low | Cache ignores PDF identity; missing OCR file silently uses the scanned PDF | `main.py:399-454` |
| 33 | C-8-07 | low | `toc_quality_score` key doesn't exist (always 75) | `assembly_service.py:257-259` |
| 34 | C-8-09 | low | Cleanup misses corpus merger junk | `assembly_service.py:39-53` |
| 35 | C-C-01 | low | 6 config keys never read; unknown YAML keys ignored | `config.py:83-103,355,398,410,490-498` |
| 36 | C-C-02 | low | pdfmux read outside the loader; two "llm_validation" sections; env override breaks List/Dict | `content_extraction_service.py:152-159`; `config.py:520-531` |
| 37 | C-R-09 | low | Trace says tier came from the filename | `main.py:286` |
| 38 | C-X-02 | low | `gcs_integration.py` dead | no importers |

\* C-9-10 has no direct output effect. It's high because it misleads anyone tuning the YAML, and it shapes the main session's fix plan.

## Could not verify

- **VM disk contents** (C-R-11): inferred from the workflow, not inspected.
- **`set -e` interaction with a non-zero exit code:** reasoned from the script only; no run has failed yet.
- **`--workers` path** (C-R-07): read only, not executed.
- **Summary merge under P7-01 duplicate parent IDs:** noted, not measured.
- **Dedup probe** (C-9-11): approximate (one comparison target per amount group).
- **P9-14 AIMD design:** a proposal, not load-tested.
