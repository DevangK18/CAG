# Unified `main.py` Redesign — v3 Implementation Plan

## File Structure

```
src/parsing_pipeline/
├── main.py              ← CLI + PipelineOrchestrator + progress helper (~550 lines)
├── pipeline_state.py    ← PipelineState dataclass (~40 lines)
└── modules/             ← unchanged
```

Delete `run_pipeline_quick.py` when done.

---

## 1. Create `pipeline_state.py`

Single dataclass holding all intermediate results between phases:

```python
@dataclass
class PipelineState:
    tasks: list = field(default_factory=list)
    triaged_native: list = field(default_factory=list)
    triaged_scanned: list = field(default_factory=list)
    ocred_successful: list = field(default_factory=list)
    successful_triaged: list = field(default_factory=list)  # native + ocred, input to phase 4+
    scaffold_complete: list = field(default_factory=list)
    layout_complete: list = field(default_factory=list)
    content_complete: list = field(default_factory=list)
    chunking_complete: list = field(default_factory=list)
    assembly_complete: list = field(default_factory=list)
    enrichment_complete: list = field(default_factory=list)
    chunk_files: list[Path] = field(default_factory=list)

    # Failure tracking — keyed by phase name, value is list of (task, error_msg)
    failed: dict[str, list] = field(default_factory=lambda: defaultdict(list))
```

---

## 2. Rewrite `main.py`

### CLI (bottom of file)

```bash
# Full pipeline (default — all phases)
python main.py manifest.xlsx

# Skip specific phases
python main.py manifest.xlsx --skip 10a
python main.py manifest.xlsx --skip 10b 10c
python main.py manifest.xlsx --skip 5.5 5.7

# Quiet mode
python main.py manifest.xlsx --quiet

# Filter to specific reports
python main.py manifest.xlsx --reports 2025_04_CAG_Report_XYZ 2025_05_CAG_Report_ABC
```

argparse setup:
- `manifest_path` — positional arg
- `--skip` — nargs="*", choices from phase numbers: `["5.5", "5.7", "10a", "10b", "10c"]` (only optional/skippable phases)
- `--quiet` — store_true
- `--reports` — nargs="*", optional list of report_ids to filter

### PipelineOrchestrator class

```python
class PipelineOrchestrator:
    def __init__(self, manifest_path, skip_phases, quiet, report_filter):
        self.manifest_path = manifest_path
        self.skip = set(skip_phases or [])
        self.quiet = quiet
        self.report_filter = report_filter
        self.state = PipelineState()
```

#### `async run(self)` — explicit phase calls, no registry

```python
async def run(self):
    await self._phases_1_to_3()        # smart caching built in
    self._phase_scaffolding()           # 4
    self._phase_layout()                # 5
    if "5.5" not in self.skip:
        self._phase_toc_reconciliation()
    if "5.7" not in self.skip:
        self._phase_llm_toc_validation()
    self._phase_content_extraction()    # 6
    self._phase_chunking()              # 7
    self._phase_hierarchy_enrichment()  # 7.5
    self._phase_assembly()              # 8
    self._phase_semantic_enrichment()   # 9
    if "10a" not in self.skip:
        self._phase_overview_summary()
    if "10b" not in self.skip:
        await self._phase_visual_extraction()
    if "10c" not in self.skip:
        self._phase_visual_postprocess()
    self._print_summary()
```

#### Smart Phases 1-3: `_phases_1_to_3()`

Logic:
1. Run manifest ingestion to get the full task list (this is cheap — just parses the Excel)
2. Apply `--reports` filter if provided
3. For each task, check cached state:
   - PDF exists at `data/raw/{filename}` → download done
   - `data/raw/.cache/{report_id}_triage.json` exists → triage done (contains `{"classification": "native_text"|"scanned"}`)
   - If scanned: `data/raw/.cache/{report_id}_ocr.json` exists → OCR done
4. Split into `cached_tasks` (all checks pass) and `new_tasks` (need processing)
5. Run phases 1-3 only for `new_tasks`
6. For `cached_tasks`, reconstruct the task objects from the cache markers (load classification from triage JSON, set appropriate status)
7. Merge both into `self.state.successful_triaged`

Cache marker format (written by the orchestrator, not the services):
```json
// data/raw/.cache/{report_id}_triage.json
{"classification": "native_text", "timestamp": "2025-02-26T10:30:00"}

// data/raw/.cache/{report_id}_ocr.json  
{"status": "ocr_complete", "timestamp": "2025-02-26T10:31:00"}
```

The orchestrator writes these after each service succeeds. Services stay unchanged. Cache files go in `data/raw/.cache/` to keep things tidy.

Output when all cached:
```
PHASES 1-3: MANIFEST / TRIAGE / OCR
────────────────────────────────────
✓ 12/12 reports cached (skipping download/triage/OCR)
```

Output for mixed:
```
PHASES 1-3: MANIFEST / TRIAGE / OCR
────────────────────────────────────
✓ 10/12 reports cached
  [1/2] Downloading 2025_11_CAG_Report_New...
  [2/2] Downloading 2025_12_CAG_Report_New2...
✓ 2 new: 1 native, 1 scanned
✓ OCR: 1/1 successful
✓ 12 reports ready for Phase 4
```

#### Each phase method pattern

Every `_phase_*()` method follows the same structure:

```python
def _phase_scaffolding(self):
    self._phase_header("4", "DOCUMENT SCAFFOLDING")
    service = ScaffoldingService()
    
    for i, task in enumerate(self.state.successful_triaged, 1):
        self._log(f"  [{i:2d}/{len(self.state.successful_triaged)}] {task.report_id}")
        result = service.build_scaffold(task)
        
        if result.processing_status in ("scaffold_complete", "scaffold_partial"):
            self.state.scaffold_complete.append(result)
            toc = len(result.scaffold.get('toc', [])) if result.scaffold else 0
            self._log(f"             COMPLETE: {toc} TOC entries")
        else:
            self.state.failed["scaffolding"].append((result, result.error_log[-1] if result.error_log else "Unknown"))
            self._log(f"             FAILED: {result.error_log[-1] if result.error_log else 'Unknown'}")
    
    self._phase_result("4", "Scaffolding", len(self.state.scaffold_complete), len(self.state.successful_triaged))
```

Extract each phase's logic directly from current `main.py`. Keep the same service calls, status checks, and error handling. Just restructure into methods that read/write `self.state`.

#### Phase 6 progress bar

Phase 6 (content extraction) is the only phase that needs intra-document progress. Add an optional `progress_callback` to `ContentExtractionService.extract_content()`:

```python
def _phase_content_extraction(self):
    self._phase_header("6", "CONTENT EXTRACTION")
    service = ContentExtractionService()
    
    for i, task in enumerate(self.state.layout_complete, 1):
        self._log(f"  [{i:2d}/{len(self.state.layout_complete)}] {task.report_id}")
        
        def on_progress(current, total):
            print_progress(current, total, f"processing {current}/{total} blocks")
        
        result = service.extract_content(task, progress_callback=on_progress)
        
        if result.processing_status in (...):
            # clear progress bar line and print completion
            ...
```

The `progress_callback` change to ContentExtractionService: find where it currently prints the block-level spam (likely a loop over blocks calling `print()`), and replace with `if progress_callback: progress_callback(i, total)`.

#### Logging helpers

```python
def _log(self, msg, verbose_only=False):
    """Print unless quiet mode suppresses it."""
    if verbose_only and self.quiet:
        return
    if self.quiet:
        return  # quiet mode only shows phase results
    print(msg)

def _phase_header(self, number, name):
    if not self.quiet:
        print(f"\n\nPHASE {number}: {name}")
        print("-" * 40)

def _phase_result(self, number, name, success, total):
    """Always prints, even in quiet mode."""
    pct = f"({success/total*100:.1f}%)" if total > 0 else ""
    if self.quiet:
        print(f"✓ Phase {number} ({name}): {success}/{total} {pct}")
    else:
        print(f"\n{name} Results:")
        print(f"  Successful: {success}/{total} {pct}")
        if self.state.failed.get(name.lower()):
            print(f"  Failed:")
            for task, err in self.state.failed[name.lower()]:
                print(f"    {task.report_id}: {err}")
```

#### `_print_summary()`

Keep the same comprehensive summary from current `main.py`: per-phase success rates, corpus enrichment totals (findings, recommendations, monetary), ministry breakdown, phase 10 status messages, and the final success/failure evaluation. All of this prints in both modes (it's the payoff).

### Progress bar helper (bottom of main.py)

```python
def print_progress(current, total, info=""):
    """In-place progress bar with info text."""
    if total == 0:
        return
    pct = current / total
    width = 30
    filled = int(width * pct)
    bar = "█" * filled + "░" * (width - filled)
    print(f"\r  {bar}  {pct:>4.0%}  {info}", end="", flush=True)

def clear_progress(message=""):
    """Replace progress bar with completion message."""
    print(f"\r  ✓ {message}{' ' * 40}")
```

---

## 3. Modify `ContentExtractionService`

Single change: add `progress_callback: Optional[Callable[[int, int], None]] = None` parameter to `extract_content()`. 

Find the loop that currently prints per-block progress (the `processing X/Y blocks` spam) and replace:
```python
# Before (current)
print(f"processing {i}/{total} blocks ({i/total*100:.0f}%)")

# After
if progress_callback:
    progress_callback(i, total)
```

This is backward-compatible — existing callers that don't pass the callback get no output (which is fine since the orchestrator now owns the display).

---

## 4. Write cache markers after phases 1-3

In `_phases_1_to_3()`, after each service call succeeds, write the cache marker:

```python
# After triage succeeds
cache_dir = Path("data/raw/.cache")
cache_dir.mkdir(exist_ok=True)
with open(cache_dir / f"{task.report_id}_triage.json", "w") as f:
    json.dump({"classification": result.classification, "timestamp": datetime.now().isoformat()}, f)

# After OCR succeeds  
with open(cache_dir / f"{task.report_id}_ocr.json", "w") as f:
    json.dump({"status": "ocr_complete", "timestamp": datetime.now().isoformat()}, f)
```

For cache reads, `_check_cached_state()` needs to reconstruct a task object from the cache. The key info needed is:
- `task.report_id` — from manifest
- `task.local_pdf_path` — `data/raw/{filename}`  
- `task.classification` — from `_triage.json`
- `task.processing_status` — set to `"triage_complete"` or `"ocr_complete"` based on classification

Check what fields your task dataclass requires for Phase 4 input and make sure the cache reconstruction provides them. You may need to also cache `task.scaffold` or other fields if triage/OCR services populate them — inspect what `ScaffoldingService.build_scaffold()` reads from the task.

---

## Implementation Order

1. **`pipeline_state.py`** — trivial, do first
2. **`main.py` skeleton** — CLI, PipelineOrchestrator class, `run()`, logging helpers, progress helper
3. **Phase methods 4-9** — extract from current main.py line by line into methods. This is mechanical.
4. **Phase 10a/b/c methods** — extract from current main.py
5. **`_phases_1_to_3()` with caching** — the only new logic. Build `_check_cached_state()`, cache write after triage/OCR, cache read to reconstruct tasks
6. **ContentExtractionService progress_callback** — find the print spam, replace with callback
7. **`_print_summary()`** — extract from current main.py
8. **Delete `run_pipeline_quick.py`**
9. **Test** — run on a previously-processed manifest to verify cache hits, then on a new report to verify full flow
