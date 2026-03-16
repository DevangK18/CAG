# main.py — Fix Plan (8 Issues)

Apply all fixes to `src/parsing_pipeline/main.py` unless noted otherwise.

---

## Bug 1: Phase 10c can't run independently of 10b

**Problem**: `_phase_visual_postprocess` relies on `self.state.chunk_files` which only gets populated inside `_phase_visual_extraction`. If 10b is skipped (or was run in a previous pipeline execution), 10c silently does nothing.

**Fix**: At the top of `_phase_visual_postprocess`, before the `if self.state.chunk_files:` check, add fallback population:

```python
# Populate chunk_files from enrichment_complete if not already set by Phase 10b
if not self.state.chunk_files and self.state.enrichment_complete:
    self.state.chunk_files = [
        Path(task.assembled_output_path)
        for task in self.state.enrichment_complete
        if task.assembled_output_path and Path(task.assembled_output_path).exists()
    ]
```

Also remove the `return phase10b_completed` from `_phase_visual_extraction` — it's unused by the caller.

---

## Bug 2: ManifestIngestionService downloads inside process_manifest

**Problem**: `_phases_1_to_3` calls `manifest_service.process_manifest(self.manifest_path)` for ALL reports, but this method both parses the Excel AND downloads PDFs. So cached reports still get re-downloaded.

**Fix**: Inspect `ManifestIngestionService.process_manifest()` to understand its behavior. There are two likely scenarios:

**Scenario A** — The service already skips downloading if the PDF exists on disk (check for something like `if pdf_path.exists(): skip`). If so, the current code is fine and no fix needed. Just add a comment in `_phases_1_to_3` noting this.

**Scenario B** — The service always downloads. In this case, refactor `_phases_1_to_3` to:
1. Call a manifest-parse-only method (or add one to `ManifestIngestionService`) that returns task objects with metadata from the Excel without downloading
2. Run `_check_cached_state` on each task  
3. Only call the download method for tasks that aren't cached

If Scenario B and you can't easily split the service, the simplest fix is: add an `existing_files: set[str]` parameter to `process_manifest` that tells it which report_ids to skip downloading for. The service checks this set before each download.

**Action for Claude Code**: Read `ManifestIngestionService.process_manifest()` first. If it already skips existing PDFs, just add a clarifying comment. If not, implement the split.

---

## Bug 3: _reconstruct_from_cache may have incomplete task fields

**Problem**: `_reconstruct_from_cache` assumes `task.local_pdf_path` is already set on the task object. But if `process_manifest` only sets this field during/after download, cached tasks reconstructed before downloading would have the wrong path.

**Fix**: Again depends on Bug 2 investigation. If `process_manifest` sets `local_pdf_path` during Excel parsing (before download), this is fine. If it only sets it after download, then `_reconstruct_from_cache` needs to explicitly set it:

```python
def _reconstruct_from_cache(self, task, cache_status):
    triage_data = cache_status["triage"]
    classification = triage_data["classification"]
    
    task.classification = classification
    
    # Ensure local_pdf_path is set (may not be if manifest service didn't download)
    if not task.local_pdf_path or not Path(task.local_pdf_path).exists():
        # Reconstruct expected path from report metadata
        expected_path = Path("data/raw") / f"{task.report_id}.pdf"
        if expected_path.exists():
            task.local_pdf_path = str(expected_path)
    
    if classification == "scanned":
        ocred_path = task.local_pdf_path.replace(".pdf", "_ocred.pdf")
        if Path(ocred_path).exists():
            task.ocred_pdf_path = ocred_path
        task.processing_status = "ocr_complete"
    else:
        task.processing_status = "triage_complete"
    
    return task
```

**Action for Claude Code**: Check how `local_pdf_path` is populated in `ManifestIngestionService` and `DocumentTask`. If it's set from Excel parsing, no fix needed. If set only after download, apply the fix above (adjust the path pattern to match your actual file naming convention — check `data/raw/` to see how PDFs are named).

---

## Bug 4: clear_progress missing ✓ prefix

**Problem**: `clear_progress` prints the message without a checkmark, inconsistent with the rest of the output style.

**Fix**: Change line 78:
```python
# Before
print(f"\r  {message}{' ' * 60}")

# After  
print(f"\r  ✓ {message}{' ' * 60}")
```

---

## Nit 5: Dead ValidationService instantiation in _phase_assembly

**Problem**: Line 604 creates `validation_service = ValidationService()` but never uses it. Validation happens in `_phase_semantic_enrichment`.

**Fix**: Remove `validation_service = ValidationService()` from `_phase_assembly` (line 604).

---

## Nit 6: Phases 5.5, 5.7, 7.5 invisible in --quiet mode

**Problem**: These phases use `self._log()` for their summary lines, which gets suppressed in quiet mode. Unlike phases 4-9 which call `_phase_result` (always prints), these three phases print nothing in quiet mode.

**Fix**: Add `force=True` to the summary lines in each of these three methods:

In `_phase_toc_reconciliation`:
```python
self._log(f"✓ Reconciliation: {reconciled_count}/{len(self.state.layout_complete)} documents updated", force=True)
```

In `_phase_llm_toc_validation`:
```python
self._log(f"✓ LLM Validation: {llm_validated_count} validated, {llm_skipped_count} skipped", force=True)
```
And the SKIPPED message already has `force=True`, that's fine.

In `_phase_hierarchy_enrichment`:
```python
self._log(f"\n✓ Hierarchy Enrichment: {enriched_count} enriched, {skipped_count} skipped", force=True)
```

---

## Nit 7: _print_summary missing Phase 10 status

**Problem**: The final summary only covers phases 1-9. The old main.py printed batch job IDs, async status, and instructions for checking/processing results.

**Fix**: Add phase 10 status to `_print_summary`, after the enrichment section and before the final success evaluation. Insert this block:

```python
# Phase 10 status
phase10_notes = []

if "10a" not in self.skip:
    # Check if batch was submitted (look for the log pattern or add a state flag)
    phase10_notes.append("10a (Overview & Summary): SUBMITTED (async)")
elif "10a" in self.skip:
    phase10_notes.append("10a (Overview & Summary): SKIPPED")

if "10b" not in self.skip and self.state.chunk_files:
    phase10_notes.append("10b (Visual Extraction): COMPLETE")
elif "10b" in self.skip:
    phase10_notes.append("10b (Visual Extraction): SKIPPED")

if "10c" not in self.skip and self.state.chunk_files:
    phase10_notes.append("10c (Visual Post-Processing): COMPLETE")
elif "10c" in self.skip:
    phase10_notes.append("10c (Visual Post-Processing): SKIPPED")

if phase10_notes:
    for note in phase10_notes:
        print(f"Phase {note}")
```

To make this more accurate, add three boolean flags to `PipelineState`:

```python
# Phase 10 tracking
phase10a_submitted: bool = False
phase10b_completed: bool = False  
phase10c_completed: bool = False
```

Set `self.state.phase10a_submitted = True` after successful batch submission in `_phase_overview_summary`. Set `self.state.phase10b_completed = True` after successful extraction in `_phase_visual_extraction` (replacing the local `phase10b_completed` variable). Set `self.state.phase10c_completed = True` after successful post-processing in `_phase_visual_postprocess`. Then use these flags in the summary instead of inferring from skip/chunk_files.

---

## Nit 8: Document the progress callback closure behavior

**Problem**: The `on_progress` closure inside the Phase 6 loop captures `self.quiet` which is fine, but it's worth a brief comment since closures in loops are a common Python gotcha.

**Fix**: This is actually a non-issue since `on_progress` only references `self.quiet` (stable) and is called synchronously within the same iteration. No code change needed. Just add a one-line comment if you want:

```python
# progress_callback is called synchronously within this iteration, no closure issue
def on_progress(current, total):
    if not self.quiet:
        print_progress(current, total, f"{current}/{total} blocks")
```

---

## Summary of file changes

| File | Change |
|---|---|
| `src/parsing_pipeline/main.py` | Fixes 1, 4, 5, 6, 7, 8. Bug 2 and 3 depend on reading ManifestIngestionService first. |
| `src/parsing_pipeline/pipeline_state.py` | Add `phase10a_submitted`, `phase10b_completed`, `phase10c_completed` booleans (Nit 7) |
| `src/parsing_pipeline/modules/manifest_ingestion_service.py` | Possibly refactor if Bug 2 Scenario B applies |
| `src/parsing_pipeline/modules/content_extraction_service.py` | Already needs `progress_callback` parameter (from original plan, not a fix) |
