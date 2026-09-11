"""
DAG Orchestrator for the CAG AI-Powered Parsing Pipeline.

This is the entry point for running the document parsing pipeline.
Implements Phases 1-10: Manifest → Triage → OCR → Scaffolding → Layout →
Content Extraction → Chunking → Assembly → Semantic Enrichment → Overview & Summary.

## CLI Usage

    python -m src.parsing_pipeline.main "manifest.xlsx"

## Available Flags

    manifest_path       Required. Path to Excel manifest file
    --skip              Skip optional phases. Choices: 5.5, 5.7, 10a, 10b, 10c
    --quiet             Only show phase results, not per-document progress
    --reports           Filter to specific report IDs (space-separated)
    --trace             Enable trace instrumentation (implies --workers 1)

## Examples

    # Full pipeline (all phases)
    python -m src.parsing_pipeline.main "Newtest.xlsx"

    # Skip specific phases
    python -m src.parsing_pipeline.main "Newtest.xlsx" --skip 10a 10b 10c
    python -m src.parsing_pipeline.main "Newtest.xlsx" --skip 5.5 5.7

    # Quiet mode (less output)
    python -m src.parsing_pipeline.main "Newtest.xlsx" --quiet

    # Filter to specific reports
    python -m src.parsing_pipeline.main "manifest.xlsx" --reports 2025_04_Report_A 2025_05_Report_B

    # Combined flags
    python -m src.parsing_pipeline.main "Newtest.xlsx" --skip 10a 10b 10c --quiet --reports Report_A

## Phase Reference

    5.5     TOC Reconciliation (fuses heuristic + Docling detections)
    5.7     LLM TOC Validation (Claude Haiku for low-quality TOCs)
    10a     Overview & Summary Generation (Claude Batch API)
    10b     Visual Extraction (Gemini for tables/charts)
    10c     Visual Post-Processing

## Key Features

- Smart caching for phases 1-3 (avoids re-processing downloaded/triaged/OCR'd reports)
- AI-powered content extraction with intelligent fallbacks
- V2 Table extraction: pdfplumber (native) → Docling TableFormer (scanned) → Gemini 2.5 Flash (fallback)
- V2 Visual extraction: Gemini 2.5 Flash vision for charts and tables
- Dead letter queue for debugging extraction failures
- Comprehensive error logging and observability
- PHASE 9: Semantic enrichment for cross-report analytics
- PHASE 10: Overview & Summary generation via Claude Batch API
- INTELLIGENT TOC: Hierarchy enrichment for flat TOC structures

## Phase 1 Enhancements (P0 Tasks)

- P0-1: Structured Table Extraction (queryable JSON from markdown tables)
- P0-2: Hierarchy Concentration Fix (Y-coordinate aware parent assignment)
- P0-3: Multi-Page Table Stitching (automatic fragment detection and merging)
"""

import os

# DISABLING TOKENIZERS PARALLELISM
# Must be set before transformers/tokenizers are imported
os.environ["TOKENIZERS_PARALLELISM"] = "false"

import asyncio
import sys
import json
import logging
import logging.handlers
from pathlib import Path
from datetime import datetime
from typing import List

# Import services from modules
from src.parsing_pipeline.modules.manifest_ingestion_service import (
    ManifestIngestionService,
)
from src.parsing_pipeline.modules.triage_service import TriageService
from src.parsing_pipeline.modules.ocr_service import OCRService
from src.parsing_pipeline.modules.scaffolding_service import ScaffoldingService
from src.parsing_pipeline.modules.layout_analysis_service import LayoutAnalysisService
from src.parsing_pipeline.modules.content_extraction_service import (
    ContentExtractionService,
)
from src.parsing_pipeline.modules.chunking_service import ChunkingService
from src.parsing_pipeline.modules.assembly_service import (
    AssemblyService,
    propagate_semantic_enrichment_to_chunks,
)
from src.parsing_pipeline.modules.validation_service import ValidationService
from src.parsing_pipeline.modules.semantic_enrichment_service import (
    SemanticEnrichmentService,
)
from src.parsing_pipeline.modules.hierarchy_enricher import (
    HierarchyEnricher,
    should_enrich_hierarchy,
)
from src.parsing_pipeline.modules.toc_reconciliation_service import (
    TOCReconciliationService,
)
from src.parsing_pipeline.modules.toc_llm_validator import TOCLLMValidator

# Import pipeline state management
from src.parsing_pipeline.pipeline_state import PipelineState

# Import data contracts for Pydantic conversion
from src.core.data_contracts import ParentChunk, ChildChunk, DocumentTask

# Import instrumentation
from src.parsing_pipeline.instrumentation import ReportMetadata


# ═══════════════════════════════════════════════════════════════════════════
# PROGRESS BAR HELPERS
# ═══════════════════════════════════════════════════════════════════════════


def print_progress(current: int, total: int, info: str = ""):
    """Print in-place progress bar with info text."""
    if total == 0:
        return
    pct = current / total
    width = 30
    filled = int(width * pct)
    bar = "█" * filled + "░" * (width - filled)
    print(f"\r  {bar}  {pct:>4.0%}  {info}", end="", flush=True)


def clear_progress(message: str = ""):
    """Replace progress bar with completion message."""
    print(f"\r  ✓ {message}{' ' * 60}")  # 60 spaces to clear line


# ═══════════════════════════════════════════════════════════════════════════
# PIPELINE ORCHESTRATOR
# ═══════════════════════════════════════════════════════════════════════════


class PipelineOrchestrator:
    """Orchestrates the 10-phase parsing pipeline with smart caching and progress tracking."""

    def __init__(
        self,
        manifest_path: str,
        skip_phases: list = None,
        quiet: bool = False,
        report_filter: list = None,
        workers: int = 1,
        trace: bool = False,
    ):
        self.manifest_path = manifest_path
        self.skip = set(skip_phases or [])
        self.quiet = quiet
        self.report_filter = report_filter
        self.workers = workers
        self.trace = trace
        self.state = PipelineState()

        # Setup trace emitter if enabled
        if trace:
            from src.parsing_pipeline.instrumentation import TraceEmitter, get_noop_emitter
            from src.parsing_pipeline.config import get_config

            config = get_config()
            self.state.trace_emitter = TraceEmitter(
                enabled=True,
                output_dir=config.instrumentation.output_dir,
                sample_count=config.instrumentation.sample_count,
                incremental_flush=config.instrumentation.incremental_flush,
            )
        else:
            # Use a no-op emitter (avoids None checks throughout the codebase)
            from src.parsing_pipeline.instrumentation import get_noop_emitter
            self.state.trace_emitter = get_noop_emitter()

        # Cache directory
        self.cache_dir = Path("data/raw/.cache")
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    async def run(self):
        """Run the complete pipeline with phase skipping support."""
        self._print_header()

        # Phases 1-3 with smart caching
        await self._phases_1_to_3()

        if not self.state.successful_triaged:
            self._log(
                "No documents ready for processing. Pipeline terminating.", force=True
            )
            return

        # Phases 4-9: Either parallel or sequential based on --workers flag
        if self.workers > 1:
            # Parallel execution across multiple processes
            self._run_phases_4_to_9_parallel()
        else:
            # Sequential execution (default, byte-identical output)
            self._run_phases_4_to_9_sequential()

        # Phase 10a: Overview & Summary (optional)
        if "10a" not in self.skip:
            self._phase_overview_summary()

        # Phase 10b: Visual Extraction (optional)
        if "10b" not in self.skip:
            await self._phase_visual_extraction()

        # Phase 10c: Visual Post-processing (optional)
        if "10c" not in self.skip:
            self._phase_visual_postprocess()

        # Finalize all traces after last enabled phase
        self._finalize_all_traces()

        # Print comprehensive summary
        self._print_summary()

    # ═══════════════════════════════════════════════════════════════════════
    # PHASES 1-3: SMART CACHING
    # ═══════════════════════════════════════════════════════════════════════

    async def _phases_1_to_3(self):
        """Smart phases 1-3: Only process what's not already cached."""
        self._phase_header("1-3", "MANIFEST / TRIAGE / OCR")

        # Phase 1: Run manifest ingestion (cheap - just Excel parsing)
        manifest_service = ManifestIngestionService(raw_data_dir="data/raw")

        try:
            all_tasks = await manifest_service.process_manifest(self.manifest_path)
        except Exception as e:
            self._log(f"Critical error in manifest ingestion: {e}", force=True)
            return

        # Apply report filter if provided
        if self.report_filter:
            all_tasks = [t for t in all_tasks if t.report_id in self.report_filter]
            self._log(
                f"Filtered to {len(all_tasks)} reports: {', '.join(self.report_filter)}"
            )

        # Start trace for each task after tier detection is available
        # NOTE (Fix 1, Round 5): Multi-report batches now work correctly with per-report contexts.
        emitter = self.state.trace_emitter
        for task in all_tasks:
            if emitter.enabled:
                pdf_path = Path(task.local_pdf_path)
                file_size = pdf_path.stat().st_size if pdf_path.exists() else 0

                # Fix 2: Get actual page count from PDF (initial_metadata doesn't have it)
                page_count = 0
                if pdf_path.exists() and file_size > 0:
                    try:
                        import fitz  # PyMuPDF
                        with fitz.open(str(pdf_path)) as doc:
                            page_count = doc.page_count
                    except Exception:
                        pass  # Fall back to 0 if PDF can't be opened

                metadata = ReportMetadata(
                    report_id=task.report_id,
                    tier=task.initial_metadata.get("government_body_type", "union"),
                    source_pdf_path=str(pdf_path),
                    page_count=page_count,
                    file_size_bytes=file_size,
                    state_name=task.initial_metadata.get("state_name"),
                )
                emitter.start_report(task.report_id, metadata)

                # Emit Phase 1 events (manifest ingestion)
                with emitter.phase_timer("1"):
                    emitter.emit_decision(
                        "1",
                        "tier_detection",
                        task.initial_metadata.get("government_body_type", "union"),
                        ["union", "state", "local_body"],
                        f"Detected from manifest filename pattern",
                    )

                    # File resolution decision
                    pdf_resolved = pdf_path.exists() and file_size > 0
                    download_failed = task.processing_status == "failed_download"
                    if download_failed:
                        emitter.emit_decision(
                            "1",
                            "file_resolution",
                            "download_failed",
                            ["local_found", "downloaded", "download_failed"],
                            f"Failed to download from {task.source_url[:50] if task.source_url else 'unknown'}",
                        )
                        emitter.emit_red_flag(
                            "1",
                            "PDF download failed",
                            {"report_id": task.report_id, "url": task.source_url},
                        )
                    elif pdf_resolved:
                        # Check if this was a pre-existing file (no download)
                        emitter.emit_decision(
                            "1",
                            "file_resolution",
                            "local_found",
                            ["local_found", "downloaded", "download_failed"],
                            f"PDF found at {str(pdf_path)[-50:]}",
                        )

                    emitter.emit_io(
                        "1",
                        {"manifest_row": task.initial_metadata.get("SL NO", "unknown")},
                        {
                            "report_id": task.report_id,
                            "pdf_path": str(pdf_path),
                            "file_size_mb": round(file_size / (1024 * 1024), 2),
                            "pdf_exists": pdf_resolved,
                        },
                    )
                    if task.initial_metadata.get("state_name"):
                        emitter.emit_decision(
                            "1",
                            "state_code_mapping",
                            task.initial_metadata.get("state_name"),
                            [],
                            "Mapped from State Name column",
                        )
                    emitter.set_phase_status("1", "success" if pdf_resolved else "failed")

        # Split into cached and new tasks
        cached_tasks = []
        new_tasks = []

        for task in all_tasks:
            cache_status = self._check_cached_state(task)
            if cache_status:
                # Reconstruct from cache
                cached_task = self._reconstruct_from_cache(task, cache_status)
                cached_tasks.append(cached_task)

                # Emit retrospective Phase 2-3 events for cached tasks
                if emitter.enabled:
                    with emitter.phase_timer("2"):
                        emitter.emit_decision(
                            "2",
                            "classification",
                            cached_task.classification or "native_text",
                            ["native_text", "scanned"],
                            "Reconstructed from cache",
                        )
                        emitter.set_phase_status("2", "success")

                    if cached_task.classification == "scanned":
                        with emitter.phase_timer("3"):
                            if cached_task.ocred_pdf_path:
                                emitter.emit_io(
                                    "3",
                                    {"input_pdf": cached_task.local_pdf_path},
                                    {"ocred_pdf": cached_task.ocred_pdf_path},
                                )
                                emitter.set_phase_status("3", "success")
                            else:
                                emitter.emit_error("3", "OCR cache incomplete")
                                emitter.set_phase_status("3", "failed")
            else:
                new_tasks.append(task)

        # Report cache hits
        if cached_tasks:
            self._log(
                f"✓ {len(cached_tasks)}/{len(all_tasks)} reports cached (skipping download/triage/OCR)"
            )

        # Process new tasks through phases 1-3
        if new_tasks:
            self._log(f"Processing {len(new_tasks)} new reports...")
            await self._process_new_tasks(new_tasks)

        # Merge cached and new into successful_triaged
        self.state.successful_triaged = cached_tasks + self.state.successful_triaged
        self.state.tasks = all_tasks

        # Summary
        total_ready = len(self.state.successful_triaged)
        failed_count = len(all_tasks) - total_ready

        if failed_count > 0:
            self._log(
                f"✓ {total_ready}/{len(all_tasks)} reports ready for Phase 4 ({failed_count} failed)"
            )
        else:
            self._log(f"✓ {total_ready}/{len(all_tasks)} reports ready for Phase 4")

    def _check_cached_state(self, task: DocumentTask) -> dict:
        """Check if task is fully cached. Returns cache status dict or None."""
        # Check 1: PDF exists
        pdf_path = Path(task.local_pdf_path)
        if not pdf_path.exists():
            return None

        # Check 2: Triage cache exists
        triage_cache = self.cache_dir / f"{task.report_id}_triage.json"
        if not triage_cache.exists():
            return None

        try:
            with open(triage_cache) as f:
                triage_data = json.load(f)
        except Exception:
            return None

        classification = triage_data.get("classification")

        # Check 3: If scanned, OCR cache must exist
        if classification == "scanned":
            ocr_cache = self.cache_dir / f"{task.report_id}_ocr.json"
            if not ocr_cache.exists():
                return None
            try:
                with open(ocr_cache) as f:
                    ocr_data = json.load(f)
                return {"triage": triage_data, "ocr": ocr_data}
            except Exception:
                return None

        return {"triage": triage_data}

    def _reconstruct_from_cache(
        self, task: DocumentTask, cache_status: dict
    ) -> DocumentTask:
        """Reconstruct a task from cache markers."""
        triage_data = cache_status["triage"]
        classification = triage_data["classification"]

        # Set classification and status
        task.classification = classification

        if classification == "scanned":
            # Check if OCR'd PDF exists - use the correct path pattern
            # OCR service saves to: data/processed/ocred/{report_id}_ocred.pdf
            ocr_output_dir = Path("data/processed/ocred")
            ocred_path = ocr_output_dir / f"{task.report_id}_ocred.pdf"
            if ocred_path.exists():
                task.ocred_pdf_path = str(ocred_path)
            task.processing_status = "ocr_complete"
        else:
            task.processing_status = "triage_complete"

        return task

    async def _process_new_tasks(self, new_tasks: list):
        """Process new tasks through phases 2-3 (triage and OCR)."""
        emitter = self.state.trace_emitter

        # Phase 2: Triage
        triage_service = TriageService(trace_emitter=emitter)
        triaged_native = []
        triaged_scanned = []

        for i, task in enumerate(new_tasks, 1):
            self._log(f"  [{i}/{len(new_tasks)}] Triaging {task.report_id}")

            with emitter.phase_timer("2"):
                # Service now emits detailed classification decisions internally
                result = triage_service.triage_document(task, trace_emitter=emitter)

                if result.classification == "native_text":
                    triaged_native.append(result)
                    self._write_triage_cache(result)
                    emitter.set_phase_status("2", "success")
                elif result.classification == "scanned":
                    triaged_scanned.append(result)
                    self._write_triage_cache(result)
                    emitter.set_phase_status("2", "success")
                else:
                    self.state.failed["triage"].append(
                        (result, result.error_log[-1] if result.error_log else "Unknown")
                    )
                    emitter.emit_error("2", result.error_log[-1] if result.error_log else "Unknown")
                    emitter.set_phase_status("2", "failed")

        self._log(
            f"✓ Triage: {len(triaged_native)} native, {len(triaged_scanned)} scanned"
        )

        # Phase 3: OCR (if needed)
        ocred_successful = []
        if triaged_scanned:
            ocr_service = OCRService(trace_emitter=emitter)
            for i, task in enumerate(triaged_scanned, 1):
                self._log(f"  [{i}/{len(triaged_scanned)}] OCR {task.report_id}")

                with emitter.phase_timer("3"):
                    # Service now emits detailed OCR events internally
                    result = ocr_service.ocr_document(task, trace_emitter=emitter)

                    if result.processing_status == "ocr_complete":
                        ocred_successful.append(result)
                        self._write_ocr_cache(result)
                        emitter.set_phase_status("3", "success")
                    else:
                        self.state.failed["ocr"].append(
                            (
                                result,
                                result.error_log[-1] if result.error_log else "Unknown",
                            )
                        )
                        emitter.emit_error("3", result.error_log[-1] if result.error_log else "Unknown")
                        emitter.set_phase_status("3", "failed")

            self._log(
                f"✓ OCR: {len(ocred_successful)}/{len(triaged_scanned)} successful"
            )

            # Red flag for high OCR failure rate
            ocr_failure_rate = 1 - (len(ocred_successful) / len(triaged_scanned)) if triaged_scanned else 0
            if ocr_failure_rate > 0.20:  # More than 20% failure
                emitter.emit_red_flag(
                    "3",
                    f"High OCR failure rate: {ocr_failure_rate*100:.1f}%",
                    {
                        "failed_count": len(triaged_scanned) - len(ocred_successful),
                        "total_scanned": len(triaged_scanned),
                    },
                )

        # Update state
        self.state.triaged_native = triaged_native
        self.state.triaged_scanned = triaged_scanned
        self.state.ocred_successful = ocred_successful
        self.state.successful_triaged.extend(triaged_native + ocred_successful)

    def _write_triage_cache(self, task: DocumentTask):
        """Write triage cache marker."""
        cache_file = self.cache_dir / f"{task.report_id}_triage.json"
        with open(cache_file, "w") as f:
            json.dump(
                {
                    "classification": task.classification,
                    "timestamp": datetime.now().isoformat(),
                },
                f,
            )

    def _write_ocr_cache(self, task: DocumentTask):
        """Write OCR cache marker."""
        cache_file = self.cache_dir / f"{task.report_id}_ocr.json"
        with open(cache_file, "w") as f:
            json.dump(
                {"status": "ocr_complete", "timestamp": datetime.now().isoformat()}, f
            )

    # ═══════════════════════════════════════════════════════════════════════
    # PHASE 4: SCAFFOLDING
    # ═══════════════════════════════════════════════════════════════════════
    # PHASES 4-9: PARALLEL OR SEQUENTIAL DISPATCH
    # ═══════════════════════════════════════════════════════════════════════

    def _run_phases_4_to_9_parallel(self):
        """Run phases 4-9 in parallel using ProcessPoolExecutor."""
        from src.parsing_pipeline.parallel_runner import run_parallel

        self._log(f"\n{'='*60}", force=True)
        self._log(f"PARALLEL MODE: {self.workers} workers", force=True)
        self._log(f"{'='*60}", force=True)

        # Run parallel execution
        parallel_state = run_parallel(
            tasks=self.state.successful_triaged,
            skip_phases=self.skip,
            quiet=self.quiet,
            workers=self.workers,
            output_dir="data/processed",
        )

        # Merge parallel state into our state
        self.state.scaffold_complete = parallel_state.scaffold_complete
        self.state.layout_complete = parallel_state.layout_complete
        self.state.content_complete = parallel_state.content_complete
        self.state.chunking_complete = parallel_state.chunking_complete
        self.state.assembly_complete = parallel_state.assembly_complete
        self.state.enrichment_complete = parallel_state.enrichment_complete

        # Merge failures
        for phase, failures in parallel_state.failed.items():
            self.state.failed[phase].extend(failures)

    def _run_phases_4_to_9_sequential(self):
        """Run phases 4-9 sequentially (default behavior)."""
        # Phase 4: Scaffolding
        self._phase_scaffolding()

        # Phase 5: Layout Analysis
        self._phase_layout()

        # Phase 5.5: TOC Reconciliation (optional)
        if "5.5" not in self.skip:
            self._phase_toc_reconciliation()

        # Phase 5.7: LLM TOC Validation (optional)
        if "5.7" not in self.skip:
            self._phase_llm_toc_validation()

        # Phase 6: Content Extraction
        self._phase_content_extraction()

        # Phase 7: Chunking
        self._phase_chunking()

        # Phase 7.5: Hierarchy Enrichment
        self._phase_hierarchy_enrichment()

        # Phase 8: Assembly
        self._phase_assembly()

        # Phase 9: Semantic Enrichment
        self._phase_semantic_enrichment()

    # ═══════════════════════════════════════════════════════════════════════
    # PHASE 4: SCAFFOLDING
    # ═══════════════════════════════════════════════════════════════════════

    def _phase_scaffolding(self):
        """Phase 4: Document Scaffolding."""
        self._phase_header("4", "DOCUMENT SCAFFOLDING")
        service = ScaffoldingService()
        emitter = self.state.trace_emitter

        for i, task in enumerate(self.state.successful_triaged, 1):
            # Switch to this report's trace context (Fix 1: per-report isolation)
            emitter.set_current_report(task.report_id)

            self._log(
                f"  [{i:2d}/{len(self.state.successful_triaged)}] Scaffolding {task.report_id}"
            )

            # Note: start_report() and Phase 1-3 events are now emitted in _phases_1_to_3
            # This was moved in Fix 2 to capture Phase 1-3 events in real-time
            result = service.build_scaffold(task, trace_emitter=emitter)

            if result.processing_status in ("scaffold_complete", "scaffold_partial"):
                self.state.scaffold_complete.append(result)
                toc = len(result.scaffold.get("toc", [])) if result.scaffold else 0
                self._log(f"             ✓ {toc} TOC entries")
            else:
                self.state.failed["scaffolding"].append(
                    (result, result.error_log[-1] if result.error_log else "Unknown")
                )
                self._log(
                    f"             ✗ FAILED: {result.error_log[-1] if result.error_log else 'Unknown'}"
                )

        self._phase_result(
            "4",
            "Scaffolding",
            len(self.state.scaffold_complete),
            len(self.state.successful_triaged),
        )

    # ═══════════════════════════════════════════════════════════════════════
    # PHASE 5: LAYOUT ANALYSIS
    # ═══════════════════════════════════════════════════════════════════════

    def _phase_layout(self):
        """Phase 5: Layout Analysis."""
        self._phase_header("5", "LAYOUT ANALYSIS")
        service = LayoutAnalysisService()
        emitter = self.state.trace_emitter

        for i, task in enumerate(self.state.scaffold_complete, 1):
            # Switch to this report's trace context (Fix 1: per-report isolation)
            emitter.set_current_report(task.report_id)

            self._log(
                f"  [{i:2d}/{len(self.state.scaffold_complete)}] Layout analysis {task.report_id}"
            )
            result = service.analyze_layout(task, trace_emitter=emitter)

            if result.processing_status == "layout_complete":
                self.state.layout_complete.append(result)
                page_count = len(result.layout) if result.layout else 0
                self._log(f"             ✓ {page_count} pages analyzed")
            else:
                self.state.failed["layout_analysis"].append(
                    (result, result.error_log[-1] if result.error_log else "Unknown")
                )
                self._log(
                    f"             ✗ FAILED: {result.error_log[-1] if result.error_log else 'Unknown'}"
                )

        self._phase_result(
            "5",
            "Layout Analysis",
            len(self.state.layout_complete),
            len(self.state.scaffold_complete),
        )

    # ═══════════════════════════════════════════════════════════════════════
    # PHASE 5.5: TOC RECONCILIATION
    # ═══════════════════════════════════════════════════════════════════════

    def _phase_toc_reconciliation(self):
        """Phase 5.5: TOC Reconciliation."""
        self._phase_header("5.5", "TOC RECONCILIATION")
        emitter = self.state.trace_emitter
        service = TOCReconciliationService(trace_emitter=emitter)
        reconciled_count = 0

        self._log(
            f"Reconciling TOC with Docling headers for {len(self.state.layout_complete)} documents..."
        )

        for i, task in enumerate(self.state.layout_complete, 1):
            # Switch to this report's trace context (Fix 1: per-report isolation)
            emitter.set_current_report(task.report_id)

            prev_toc_count = len(task.scaffold.get("toc", [])) if task.scaffold else 0
            prev_quality = task.scaffold.get("toc_quality", 0) if task.scaffold else 0

            with emitter.phase_timer("5.5"):
                result = service.reconcile(task, trace_emitter=emitter)
                new_toc_count = (
                    len(result.scaffold.get("toc", [])) if result.scaffold else 0
                )
                new_quality = (
                    result.scaffold.get("toc_quality", 0) if result.scaffold else 0
                )

                # Emit Phase 5.5 trace data
                emitter.emit_io(
                    "5.5",
                    {"toc_entries": prev_toc_count, "toc_quality": prev_quality},
                    {"toc_entries": new_toc_count, "toc_quality": new_quality},
                )

                if new_toc_count != prev_toc_count or new_quality != prev_quality:
                    reconciled_count += 1
                    strategy = task.scaffold.get("reconciliation_strategy", "unknown")
                    emitter.emit_decision(
                        "5.5",
                        "reconciliation_strategy",
                        strategy,
                        ["supplement", "merge", "replace", "none"],
                        f"Quality {prev_quality} → {new_quality}",
                    )
                    self._log(
                        f"  [{i:2d}/{len(self.state.layout_complete)}] {task.report_id}: "
                        f"{prev_toc_count} → {new_toc_count} TOC entries, "
                        f"quality {prev_quality} → {new_quality}"
                    )

                emitter.set_phase_status("5.5", "success")

        self._log(
            f"✓ Reconciliation: {reconciled_count}/{len(self.state.layout_complete)} documents updated",
            force=True,
        )

    # ═══════════════════════════════════════════════════════════════════════
    # PHASE 5.7: LLM TOC VALIDATION
    # ═══════════════════════════════════════════════════════════════════════

    def _phase_llm_toc_validation(self):
        """Phase 5.7: LLM TOC Validation (low-quality TOCs only)."""
        self._phase_header("5.7", "LLM TOC VALIDATION (LOW-QUALITY ONLY)")
        emitter = self.state.trace_emitter

        # Check if GOOGLE_API_KEY is available (for Gemini LLM validation)
        if os.environ.get("GOOGLE_API_KEY"):
            llm_validator = TOCLLMValidator(trace_emitter=emitter)
            llm_validated_count = 0
            llm_skipped_count = 0

            for i, task in enumerate(self.state.layout_complete, 1):
                # Switch to this report's trace context (Fix 1: per-report isolation)
                emitter.set_current_report(task.report_id)

                with emitter.phase_timer("5.7"):
                    if llm_validator.should_validate(task, trace_emitter=emitter):
                        prev_quality = task.scaffold.get("toc_quality", 0) if task.scaffold else 0
                        prev_entries = len(task.scaffold.get("toc", [])) if task.scaffold else 0

                        self._log(
                            f"  [{i:2d}/{len(self.state.layout_complete)}] LLM validating {task.report_id}"
                        )
                        task.scaffold = llm_validator.validate_toc(task, trace_emitter=emitter)
                        llm_validated_count += 1

                        new_quality = task.scaffold.get("toc_quality", 0) if task.scaffold else 0
                        new_entries = len(task.scaffold.get("toc", [])) if task.scaffold else 0

                        emitter.emit_io(
                            "5.7",
                            {"toc_entries": prev_entries, "quality": prev_quality},
                            {"toc_entries": new_entries, "quality": new_quality},
                        )
                        emitter.emit_decision(
                            "5.7",
                            "llm_validation",
                            "validated",
                            ["validated", "skipped"],
                            f"Quality below threshold",
                        )
                        emitter.set_phase_status("5.7", "success")
                    else:
                        llm_skipped_count += 1
                        emitter.emit_decision(
                            "5.7",
                            "llm_validation",
                            "skipped",
                            ["validated", "skipped"],
                            f"Quality above threshold or disabled",
                        )
                        emitter.set_phase_status("5.7", "skipped")

            self._log(
                f"✓ LLM Validation: {llm_validated_count} validated, {llm_skipped_count} skipped",
                force=True,
            )
        else:
            self._log("⚠ SKIPPED: GOOGLE_API_KEY not set", force=True)
            self._log(
                "  Set GOOGLE_API_KEY to enable Gemini LLM validation for low-quality TOCs"
            )
            # Emit skipped status for all reports
            for task in self.state.layout_complete:
                # Switch to this report's trace context (Fix 1: per-report isolation)
                emitter.set_current_report(task.report_id)

                emitter.emit_decision(
                    "5.7",
                    "llm_validation",
                    "skipped",
                    ["validated", "skipped"],
                    "GOOGLE_API_KEY not set",
                )
                emitter.set_phase_status("5.7", "skipped")

    # ═══════════════════════════════════════════════════════════════════════
    # PHASE 6: CONTENT EXTRACTION
    # ═══════════════════════════════════════════════════════════════════════

    def _phase_content_extraction(self):
        """Phase 6: Content Extraction with progress bar."""
        self._phase_header("6", "CONTENT EXTRACTION (AI-POWERED)")
        service = ContentExtractionService()
        emitter = self.state.trace_emitter

        self._log(
            f"Extracting content from {len(self.state.layout_complete)} documents using AI vision models..."
        )

        for i, task in enumerate(self.state.layout_complete, 1):
            # Switch to this report's trace context (Fix 1: per-report isolation)
            emitter.set_current_report(task.report_id)

            self._log(
                f"  [{i:2d}/{len(self.state.layout_complete)}] Content extraction {task.report_id}"
            )

            # Define progress callback (closure is safe - called synchronously within this iteration)
            def on_progress(current, total):
                if not self.quiet:
                    print_progress(current, total, f"{current}/{total} blocks")

            layout_block_count = sum(len(b) for b in (task.layout or {}).values())

            with emitter.phase_timer("6"):
                # Extract with progress callback and trace emitter for per-table instrumentation
                result = service.extract_content(
                    task,
                    progress_callback=on_progress if not self.quiet else None,
                    trace_emitter=emitter,
                )

                # Clear progress bar if shown
                if not self.quiet:
                    clear_progress()

                if result.processing_status in (
                    "completed_content_extraction",
                    "partial_content_extraction",
                ):
                    self.state.content_complete.append(result)
                    content_count = (
                        len(result.extracted_content) if result.extracted_content else 0
                    )
                    tables = sum(
                        1
                        for c in (result.extracted_content or [])
                        if c.content_type in ("table", "table_markdown") or
                           (c.content_type == "image_caption" and c.layout_label == "Table")
                    )
                    figures = sum(
                        1
                        for c in (result.extracted_content or [])
                        if c.content_type == "figure"
                    )
                    self._log(
                        f"             ✓ {content_count} blocks ({tables} tables, {figures} figures)"
                    )

                    # Emit Phase 6 trace data
                    emitter.emit_io(
                        "6",
                        {"layout_blocks": layout_block_count},
                        {"content_blocks": content_count, "tables": tables, "figures": figures},
                    )
                    emitter.set_phase_status(
                        "6",
                        "success" if result.processing_status == "completed_content_extraction" else "partial"
                    )
                else:
                    self.state.failed["content_extraction"].append(
                        (result, result.error_log[-1] if result.error_log else "Unknown")
                    )
                    self._log(
                        f"             ✗ FAILED: {result.error_log[-1] if result.error_log else 'Unknown'}"
                    )
                    emitter.emit_error("6", result.error_log[-1] if result.error_log else "Unknown")
                    emitter.set_phase_status("6", "failed")

        self._phase_result(
            "6",
            "Content Extraction",
            len(self.state.content_complete),
            len(self.state.layout_complete),
        )

        # Show extraction statistics
        if self.state.content_complete:
            total_content = sum(
                len(t.extracted_content) if t.extracted_content else 0
                for t in self.state.content_complete
            )
            total_tables = sum(
                sum(1 for c in (t.extracted_content or []) if c.content_type == "table")
                for t in self.state.content_complete
            )
            total_figures = sum(
                sum(
                    1 for c in (t.extracted_content or []) if c.content_type == "figure"
                )
                for t in self.state.content_complete
            )
            self._log(f"\nTotal extracted across corpus:")
            self._log(f"  Content blocks: {total_content}")
            self._log(f"  Tables: {total_tables}")
            self._log(f"  Figures: {total_figures}")

    # ═══════════════════════════════════════════════════════════════════════
    # PHASE 7: CHUNKING
    # ═══════════════════════════════════════════════════════════════════════

    def _phase_chunking(self):
        """Phase 7: Document Chunking."""
        self._phase_header("7", "DOCUMENT CHUNKING")
        emitter = self.state.trace_emitter
        service = ChunkingService(trace_emitter=emitter)

        self._log(
            f"Creating semantic chunks for {len(self.state.content_complete)} documents..."
        )

        for i, task in enumerate(self.state.content_complete, 1):
            # Switch to this report's trace context (Fix 1: per-report isolation)
            emitter.set_current_report(task.report_id)

            self._log(
                f"  [{i:2d}/{len(self.state.content_complete)}] Chunking {task.report_id}"
            )
            content_count = len(task.extracted_content) if task.extracted_content else 0

            with emitter.phase_timer("7"):
                try:
                    parent_chunks, child_chunks = service.chunk_document(task, trace_emitter=emitter)

                    # Update task with chunks
                    task.parent_chunks = parent_chunks
                    task.child_chunks = child_chunks
                    task.processing_status = "chunking_complete"

                    self.state.chunking_complete.append(task)
                    parent_count = len(parent_chunks) if parent_chunks else 0
                    child_count = len(child_chunks) if child_chunks else 0
                    self._log(
                        f"             ✓ {parent_count} parent chunks, {child_count} child chunks"
                    )

                    # Emit Phase 7 trace data
                    emitter.emit_io(
                        "7",
                        {"content_blocks": content_count, "toc_entries": len(task.scaffold.get("toc", [])) if task.scaffold else 0},
                        {"parent_chunks": parent_count, "child_chunks": child_count},
                    )

                    # Red flag for low parent count (poor TOC/section detection)
                    if parent_count == 0 and child_count > 10:
                        emitter.emit_red_flag(
                            "7",
                            "No parent chunks created",
                            {
                                "child_count": child_count,
                                "report_id": task.report_id,
                                "toc_entries": len(task.scaffold.get("toc", [])) if task.scaffold else 0,
                            },
                        )
                    elif parent_count > 0 and child_count / parent_count > 50:
                        emitter.emit_red_flag(
                            "7",
                            f"Very high child-to-parent ratio ({child_count}/{parent_count})",
                            {"ratio": round(child_count / parent_count, 1)},
                        )

                    emitter.set_phase_status("7", "success")

                except Exception as e:
                    task.processing_status = "failed_chunking"
                    task.error_log.append(f"Chunking error: {str(e)}")
                    self.state.failed["chunking"].append((task, str(e)))
                    self._log(f"             ✗ FAILED: {str(e)}")
                    emitter.emit_error("7", str(e))
                    emitter.set_phase_status("7", "failed")

        self._phase_result(
            "7",
            "Chunking",
            len(self.state.chunking_complete),
            len(self.state.content_complete),
        )

        # Show chunking statistics
        if self.state.chunking_complete:
            total_parent = sum(
                len(t.parent_chunks) if t.parent_chunks else 0
                for t in self.state.chunking_complete
            )
            total_child = sum(
                len(t.child_chunks) if t.child_chunks else 0
                for t in self.state.chunking_complete
            )
            self._log(f"\nTotal chunks created across corpus:")
            self._log(f"  Parent chunks: {total_parent}")
            self._log(f"  Child chunks: {total_child}")

    # ═══════════════════════════════════════════════════════════════════════
    # PHASE 7.5: HIERARCHY ENRICHMENT
    # ═══════════════════════════════════════════════════════════════════════

    def _phase_hierarchy_enrichment(self):
        """Phase 7.5: Intelligent Hierarchy Enrichment."""
        self._phase_header("7.5", "INTELLIGENT HIERARCHY ENRICHMENT")
        emitter = self.state.trace_emitter
        enricher = HierarchyEnricher(trace_emitter=emitter)
        enriched_count = 0
        skipped_count = 0

        self._log(
            f"Checking hierarchy quality for {len(self.state.chunking_complete)} documents..."
        )

        for i, task in enumerate(self.state.chunking_complete, 1):
            # Switch to this report's trace context (Fix 1: per-report isolation)
            emitter.set_current_report(task.report_id)

            with emitter.phase_timer("7.5"):
                if task.parent_chunks and task.child_chunks:
                    should_enrich, reason = should_enrich_hierarchy(
                        task.parent_chunks, task.child_chunks
                    )

                    prev_parents = len(task.parent_chunks)
                    prev_children = len(task.child_chunks)

                    if should_enrich:
                        self._log(
                            f"  [{i:2d}/{len(self.state.chunking_complete)}] Enriching {task.report_id}"
                        )
                        self._log(f"             Reason: {reason}")

                        # Check for concentration red flag
                        if "concentration" in reason.lower():
                            emitter.emit_red_flag(
                                "7.5",
                                "Hierarchy concentration detected",
                                {"reason": reason, "report_id": task.report_id},
                            )

                        try:
                            enriched_parents, enriched_children = enricher.enrich_hierarchy(
                                parent_chunks=task.parent_chunks,
                                child_chunks=task.child_chunks,
                                report_id=task.report_id,
                                aggressive=False,
                                trace_emitter=emitter,
                            )
                            task.parent_chunks = enriched_parents
                            task.child_chunks = enriched_children
                            enriched_count += 1
                            self._log(
                                f"             ✓ {len(enriched_parents)} parents, {len(enriched_children)} children"
                            )

                            emitter.emit_io(
                                "7.5",
                                {"parents": prev_parents, "children": prev_children},
                                {"parents": len(enriched_parents), "children": len(enriched_children)},
                            )
                            emitter.emit_decision(
                                "7.5",
                                "enrichment",
                                "enriched",
                                ["enriched", "skipped"],
                                reason,
                            )
                            emitter.set_phase_status("7.5", "success")

                        except Exception as e:
                            self._log(f"             ⚠ Enrichment failed: {e}")
                            skipped_count += 1
                            emitter.emit_error("7.5", str(e))
                            emitter.set_phase_status("7.5", "partial")
                    else:
                        skipped_count += 1
                        emitter.emit_decision(
                            "7.5",
                            "enrichment",
                            "skipped",
                            ["enriched", "skipped"],
                            "Hierarchy quality acceptable",
                        )
                        emitter.set_phase_status("7.5", "skipped")
                else:
                    # Fix 4: Explain why Phase 7.5 was skipped
                    skipped_count += 1
                    parent_count = len(task.parent_chunks) if task.parent_chunks else 0
                    child_count = len(task.child_chunks) if task.child_chunks else 0
                    emitter.emit_decision(
                        "7.5",
                        "enrichment",
                        "skipped",
                        ["enriched", "skipped"],
                        f"No chunks to enrich (parents={parent_count}, children={child_count})",
                    )
                    emitter.set_phase_status("7.5", "skipped")

        self._log(
            f"\n✓ Hierarchy Enrichment: {enriched_count} enriched, {skipped_count} skipped",
            force=True,
        )

    # ═══════════════════════════════════════════════════════════════════════
    # PHASE 8: ASSEMBLY
    # ═══════════════════════════════════════════════════════════════════════

    def _phase_assembly(self):
        """Phase 8: Document Assembly & Output."""
        self._phase_header("8", "DOCUMENT ASSEMBLY & OUTPUT")
        emitter = self.state.trace_emitter
        assembly_service = AssemblyService(output_dir="data/processed", trace_emitter=emitter)

        self._log(
            f"Assembling final JSON outputs for {len(self.state.chunking_complete)} documents..."
        )

        for i, task in enumerate(self.state.chunking_complete, 1):
            # Switch to this report's trace context (Fix 1: per-report isolation)
            emitter.set_current_report(task.report_id)

            self._log(
                f"  [{i:2d}/{len(self.state.chunking_complete)}] Assembling {task.report_id}"
            )

            with emitter.phase_timer("8"):
                try:
                    # Convert chunks to Pydantic models
                    parent_chunks = [
                        ParentChunk(**pc) if isinstance(pc, dict) else pc
                        for pc in (task.parent_chunks or [])
                    ]
                    child_chunks = [
                        ChildChunk(**cc) if isinstance(cc, dict) else cc
                        for cc in (task.child_chunks or [])
                    ]

                    # Assemble document
                    output_path = assembly_service.assemble_document(
                        task=task,
                        parent_chunks=parent_chunks,
                        child_chunks=child_chunks,
                        trace_emitter=emitter,
                    )

                    task.assembled_output_path = output_path
                    task.processing_status = "assembly_complete"

                    self._log(
                        f"             ✓ {len(parent_chunks)} parents, {len(child_chunks)} children → {Path(output_path).name}"
                    )

                    # Emit Phase 8 trace data
                    emitter.emit_io(
                        "8",
                        {"parent_chunks": len(parent_chunks), "child_chunks": len(child_chunks)},
                        {"output_path": output_path},
                    )
                    emitter.set_phase_status("8", "success")

                    self.state.assembly_complete.append(task)

                except Exception as e:
                    task.processing_status = "failed_assembly"
                    task.error_log.append(f"Assembly error: {str(e)}")
                    self.state.failed["assembly"].append((task, str(e)))
                    self._log(f"             ✗ FAILED: {str(e)}")
                    emitter.emit_error("8", str(e))
                    emitter.set_phase_status("8", "failed")

        self._phase_result(
            "8",
            "Assembly",
            len(self.state.assembly_complete),
            len(self.state.chunking_complete),
        )

        # Show corpus statistics
        if self.state.assembly_complete:
            corpus_stats = assembly_service.get_corpus_stats()
            self._log("\nCorpus Statistics:")
            self._log(f"  Total reports assembled: {corpus_stats['total_reports']}")
            self._log(f"  Total parent chunks: {corpus_stats['total_parent_chunks']}")
            self._log(f"  Total child chunks: {corpus_stats['total_child_chunks']}")

    # ═══════════════════════════════════════════════════════════════════════
    # PHASE 9: SEMANTIC ENRICHMENT
    # ═══════════════════════════════════════════════════════════════════════

    def _phase_semantic_enrichment(self):
        """Phase 9: Semantic Enrichment."""
        self._phase_header("9", "SEMANTIC ENRICHMENT")
        service = SemanticEnrichmentService()
        validation_service = ValidationService()
        emitter = self.state.trace_emitter

        self._log(
            "Extracting findings, recommendations, and entities for cross-report analytics..."
        )

        for i, task in enumerate(self.state.assembly_complete, 1):
            # Switch to this report's trace context (Fix 1: per-report isolation)
            emitter.set_current_report(task.report_id)

            self._log(
                f"  [{i:2d}/{len(self.state.assembly_complete)}] Enriching {task.report_id}"
            )
            try:
                # Load assembled JSON
                with open(task.assembled_output_path, "r", encoding="utf-8") as f:
                    assembled_data = json.load(f)

                # Run enrichment
                enrichment = service.enrich_document(
                    report_id=assembled_data["report_metadata"]["report_id"],
                    report_metadata=assembled_data["report_metadata"],
                    parent_chunks=assembled_data["parent_chunks"],
                    child_chunks=assembled_data["child_chunks"],
                    trace_emitter=emitter,
                )

                # Add enrichment to data
                assembled_data["semantic_enrichment"] = enrichment.model_dump()

                # Propagate semantic enrichment to child chunks for Qdrant indexing
                # This ensures finding_type, severity, is_recommendation, etc. are
                # available at chunk level for filtered retrieval
                findings_count, recs_count, entities_count = propagate_semantic_enrichment_to_chunks(
                    assembled_data["child_chunks"],
                    assembled_data["semantic_enrichment"],
                )

                # Save enriched output (overwrite the original)
                with open(task.assembled_output_path, "w", encoding="utf-8") as f:
                    json.dump(assembled_data, f, indent=2, ensure_ascii=False)

                # Store enrichment stats for summary
                stats = enrichment.statistics
                task.enrichment_stats = stats

                self._log(
                    f"             ✓ {stats['findings']['total_count']} findings, "
                    f"{stats['recommendations']['total_count']} recommendations, "
                    f"₹{stats['findings']['total_monetary_crore']:,.2f} crore"
                )

                self.state.enrichment_complete.append(task)

            except Exception as e:
                task.processing_status = "failed_enrichment"
                task.error_log.append(f"Enrichment error: {str(e)}")
                self.state.failed["enrichment"].append((task, str(e)))
                self._log(f"             ✗ FAILED: {str(e)}")
                emitter.emit_error("9", str(e))
                emitter.set_phase_status("9", "failed")

        self._phase_result(
            "9",
            "Semantic Enrichment",
            len(self.state.enrichment_complete),
            len(self.state.assembly_complete),
        )

        # Comprehensive validation
        if self.state.enrichment_complete:
            self._log(
                "\n  Running comprehensive validation (including Phase 4 features)..."
            )
            validation_summary = {
                "total_validated": 0,
                "avg_score": 0,
                "p4_features": {
                    "footnotes_found": 0,
                    "boxes_detected": 0,
                    "exec_summaries_parsed": 0,
                    "visual_assets_registered": 0,
                },
            }

            for task in self.state.enrichment_complete[
                :3
            ]:  # Validate first 3 as sample
                try:
                    with open(task.assembled_output_path, "r", encoding="utf-8") as f:
                        report_data = json.load(f)

                    validation_result = validation_service.validate_report(
                        report_data=report_data,
                        enrichment_data=report_data.get("semantic_enrichment"),
                    )

                    validation_summary["total_validated"] += 1
                    validation_summary["avg_score"] += validation_result.get(
                        "overall_score", 0
                    )

                    # Track P4 features
                    if report_data.get("footnote_index"):
                        validation_summary["p4_features"]["footnotes_found"] += 1
                    if report_data.get("semantic_enrichment", {}).get("box_elements"):
                        validation_summary["p4_features"]["boxes_detected"] += 1
                    if report_data.get("semantic_enrichment", {}).get(
                        "executive_summary_index"
                    ):
                        validation_summary["p4_features"]["exec_summaries_parsed"] += 1
                    if report_data.get("visual_asset_registry"):
                        validation_summary["p4_features"][
                            "visual_assets_registered"
                        ] += 1

                except Exception as e:
                    self._log(f"    ⚠ Validation failed for {task.report_id}: {e}")

            if validation_summary["total_validated"] > 0:
                avg = (
                    validation_summary["avg_score"]
                    / validation_summary["total_validated"]
                )
                self._log(f"  Sample validation score: {avg:.1f}/100 (RAG readiness)")
                self._log(f"  Phase 4 features detected:")
                self._log(
                    f"    • Footnotes: {validation_summary['p4_features']['footnotes_found']}/{validation_summary['total_validated']} reports"
                )
                self._log(
                    f"    • Box elements: {validation_summary['p4_features']['boxes_detected']}/{validation_summary['total_validated']} reports"
                )
                self._log(
                    f"    • Executive summaries: {validation_summary['p4_features']['exec_summaries_parsed']}/{validation_summary['total_validated']} reports"
                )
                self._log(
                    f"    • Visual registries: {validation_summary['p4_features']['visual_assets_registered']}/{validation_summary['total_validated']} reports"
                )

    # ═══════════════════════════════════════════════════════════════════════
    # PHASE 10a: OVERVIEW & SUMMARY GENERATION
    # ═══════════════════════════════════════════════════════════════════════

    def _phase_overview_summary(self):
        """Phase 10a: Overview & Summary Generation (Batch API)."""
        self._phase_header("10a", "OVERVIEW & SUMMARY GENERATION")

        if self.state.enrichment_complete:
            try:
                # Import batch service (will fail gracefully if not installed)
                from src.batch_pipeline.batch_service import BatchService

                # Get JSON files for successfully enriched reports
                json_files = [
                    Path(task.assembled_output_path)
                    for task in self.state.enrichment_complete
                    if task.assembled_output_path
                    and Path(task.assembled_output_path).exists()
                ]

                if json_files:
                    self._log(
                        f"Submitting {len(json_files)} reports for Phase 10a processing..."
                    )
                    self._log(
                        "  (Overview extraction + 5 summary variants via Claude Batch API)"
                    )

                    emitter = self.state.trace_emitter
                    service = BatchService(trace_emitter=emitter)

                    # Submit batches (async - returns immediately)
                    overview_batch_id = service.submit_overview_batch(json_files)
                    summary_batch_id = service.submit_summary_batch(json_files)

                    # Create job tracker
                    report_ids = [f.stem.replace("_chunks", "") for f in json_files]
                    phase10_tracker_path = service.create_job_tracker(
                        overview_batch_id=overview_batch_id,
                        summary_batch_id=summary_batch_id,
                        report_ids=report_ids,
                    )

                    self.state.phase10a_submitted = True

                    self._log(f"\n✅ Phase 10a batch jobs submitted!", force=True)
                    self._log(f"   Overview Batch: {overview_batch_id}")
                    self._log(f"   Summary Batch:  {summary_batch_id}")
                    self._log(f"   Job Tracker:    {phase10_tracker_path}")
                else:
                    self._log("No JSON files found for Phase 10a processing.")

            except ImportError:
                self._log(
                    "⚠️  batch_pipeline module not found. Phase 10a skipped.", force=True
                )
                self._log("   To enable Overview & Summary generation:")
                self._log("   1. Copy batch_pipeline/ to services/batch_pipeline/")
                self._log("   2. Ensure google-genai package is installed")
            except Exception as e:
                self._log(f"⚠️  Phase 10a submission failed: {str(e)}", force=True)
                self._log("   Pipeline completed through Phase 9.")
        else:
            self._log("No reports completed enrichment. Skipping Phase 10a.")

    # ═══════════════════════════════════════════════════════════════════════
    # PHASE 10b: VISUAL EXTRACTION
    # ═══════════════════════════════════════════════════════════════════════

    def _validate_phase_10b_completion(self, chunk_files: List[Path]) -> bool:
        """
        P1-14a: Verify Phase 10b hydration completed successfully.

        Checks that image_caption chunks have been hydrated with descriptions
        rather than containing raw file paths.

        Args:
            chunk_files: List of chunk JSON files to validate

        Returns:
            True if all image_caption chunks are hydrated, False otherwise
        """
        emitter = self.state.trace_emitter
        incomplete_total = 0
        sample_incomplete = []

        for chunk_file in chunk_files:
            try:
                with open(chunk_file, "r", encoding="utf-8") as f:
                    data = json.load(f)

                child_chunks = data.get("child_chunks", [])
                for chunk in child_chunks:
                    if chunk.get("content_type") == "image_caption":
                        content = chunk.get("content", "")
                        # Check if content is still a file path (not hydrated)
                        if content.startswith("data/extraction_images/") or content.startswith("/"):
                            incomplete_total += 1
                            if len(sample_incomplete) < 3:
                                sample_incomplete.append(chunk.get("chunk_id", "unknown"))

            except Exception as e:
                self._log(f"  Warning: Could not validate {chunk_file.name}: {e}")
                continue

        if incomplete_total > 0:
            self._log(
                f"⚠️  P1-14a: {incomplete_total} image_caption chunks still have file paths (not hydrated)",
                force=True,
            )
            if emitter:
                emitter.emit_red_flag(
                    phase="10b",
                    flag="image_captions_not_hydrated",
                    details={
                        "count": incomplete_total,
                        "sample": sample_incomplete,
                    },
                )
            return False

        self._log(f"  ✓ P1-14a: All image_caption chunks hydrated successfully")
        return True

    async def _phase_visual_extraction(self):
        """Phase 10b: Visual Extraction via Gemini (Tables + Charts)."""
        self._phase_header("10b", "VISUAL EXTRACTION (Gemini)")

        if self.state.enrichment_complete:
            try:
                from src.batch_pipeline.enrichment.gemini_visual_extractor import (
                    GeminiVisualExtractor,
                )

                # Find all chunk files for visual extraction
                chunk_files = [
                    Path(task.assembled_output_path)
                    for task in self.state.enrichment_complete
                    if task.assembled_output_path
                    and Path(task.assembled_output_path).exists()
                ]

                if chunk_files:
                    self._log(
                        f"Submitting {len(chunk_files)} reports for visual extraction..."
                    )
                    emitter = self.state.trace_emitter
                    gemini_extractor = GeminiVisualExtractor(trace_emitter=emitter)
                    job_id = await gemini_extractor.submit_visual_extraction_job(
                        json_files=chunk_files,
                        pdf_dir="data/raw",
                        skip_existing=True,
                        trace_emitter=emitter,
                    )
                    self.state.phase10b_completed = True
                    self.state.chunk_files = chunk_files

                    # P1-14a: Validate hydration completion
                    self._validate_phase_10b_completion(chunk_files)

                    self._log(f"✅ Phase 10b complete: {job_id}", force=True)
                else:
                    self._log("No chunk files found for visual extraction.")
                    # Trace: No files to process
                    emitter = self.state.trace_emitter
                    if emitter:
                        emitter.emit_io("10b", {"chunk_files": 0}, {"skipped": True})
                        emitter.set_phase_status("10b", "skipped")

            except ImportError as e:
                self._log(f"⚠️  Gemini extraction not available: {e}", force=True)
                self._log("   Install: pip install google-genai")
                self._log("   Set GOOGLE_API_KEY in .env")
            except Exception as e:
                self._log(f"⚠️  Phase 10b failed: {e}", force=True)
                import traceback

                traceback.print_exc()
        else:
            self._log("No reports completed enrichment. Skipping Phase 10b.")

    # ═══════════════════════════════════════════════════════════════════════
    # PHASE 10c: VISUAL POST-PROCESSING
    # ═══════════════════════════════════════════════════════════════════════

    def _phase_visual_postprocess(self):
        """Phase 10c: Visual Post-Processing."""
        self._phase_header("10c", "VISUAL POST-PROCESSING")

        # Populate chunk_files from enrichment_complete if not already set by Phase 10b
        if not self.state.chunk_files and self.state.enrichment_complete:
            self.state.chunk_files = [
                Path(task.assembled_output_path)
                for task in self.state.enrichment_complete
                if task.assembled_output_path
                and Path(task.assembled_output_path).exists()
            ]

        if self.state.chunk_files:
            try:
                from src.batch_pipeline.enrichment.visual_post_processor import (
                    VisualPostProcessor,
                )

                emitter = self.state.trace_emitter
                processor = VisualPostProcessor(trace_emitter=emitter)
                stats = processor.process_all(self.state.chunk_files, trace_emitter=emitter)

                self.state.phase10c_completed = True

                self._log(f"✅ Post-processing complete:", force=True)
                self._log(f"   Tables processed: {stats.get('tables_processed', 0)}")
                self._log(
                    f"   TOC tables filtered: {stats.get('tables_filtered_toc', 0)}"
                )
                self._log(f"   Tables hydrated: {stats.get('tables_hydrated', 0)}")
                self._log(f"   Charts hydrated: {stats.get('charts_hydrated', 0)}")
                self._log(f"   Titles enriched: {stats.get('titles_enriched', 0)}")

            except Exception as e:
                self._log(f"⚠️  Phase 10c failed: {e}", force=True)
                emitter = self.state.trace_emitter
                if emitter:
                    emitter.emit_error("10c", str(e))
                    emitter.set_phase_status("10c", "failed")
                import traceback

                traceback.print_exc()
        else:
            self._log("No chunk files available from Phase 10b. Skipping Phase 10c.")
            # Trace: Phase 10c skipped
            emitter = self.state.trace_emitter
            if emitter:
                emitter.emit_io("10c", {"chunk_files": 0}, {"skipped": True})
                emitter.set_phase_status("10c", "skipped")

    # ═══════════════════════════════════════════════════════════════════════
    # TRACE FINALIZATION
    # ═══════════════════════════════════════════════════════════════════════

    def _finalize_all_traces(self):
        """Finalize ALL report traces after the last enabled phase completes.

        This must be called AFTER all enabled phases complete, not in Phase 9,
        because Phases 10b and 10c run after Phase 9 and their events would be lost.

        Fix 1 (Round 5): Now uses per-report contexts, so each report in a multi-report
        batch gets its own isolated trace file. finalize_all_reports() iterates through
        all report contexts and writes each to disk.
        """
        emitter = self.state.trace_emitter
        if not emitter.enabled:
            return

        # Determine final status based on which phases completed
        if self.state.phase10c_completed:
            final_status = "phase_10c_complete"
        elif self.state.phase10b_completed:
            final_status = "phase_10b_complete"
        elif self.state.phase10a_submitted:
            final_status = "phase_10a_submitted"
        elif self.state.enrichment_complete:
            final_status = "enrichment_complete"
        else:
            final_status = "incomplete"

        # Finalize ALL report contexts (Fix 1: per-report isolation)
        trace_paths = emitter.finalize_all_reports(final_status)
        for trace_path in trace_paths:
            self._log(f"✓ Trace finalized: {trace_path}", force=True)

        if not trace_paths:
            self._log("No trace files generated (no reports processed with --trace)", force=True)

    # ═══════════════════════════════════════════════════════════════════════
    # SUMMARY & LOGGING HELPERS
    # ═══════════════════════════════════════════════════════════════════════

    def _print_summary(self):
        """Print comprehensive pipeline summary."""
        print("\n" + "=" * 60)
        print("PIPELINE EXECUTION SUMMARY")
        print("=" * 60)

        # Phase-by-phase success rates
        total_tasks = len(self.state.tasks) if self.state.tasks else 0

        if total_tasks > 0:
            success_triaged = len(self.state.successful_triaged)
            print(
                f"Phases 1-3 (Ingestion/Triage/OCR): {success_triaged}/{total_tasks} "
                f"({success_triaged / total_tasks * 100:.1f}%)"
            )
        else:
            print(f"Phases 1-3 (Ingestion/Triage/OCR): No tasks to process")

        if self.state.successful_triaged:
            scaffold_count = len(self.state.scaffold_complete)
            print(
                f"Phase 4 (Scaffolding): {scaffold_count}/{len(self.state.successful_triaged)} "
                f"({scaffold_count / len(self.state.successful_triaged) * 100:.1f}%)"
            )

        if self.state.scaffold_complete:
            layout_count = len(self.state.layout_complete)
            print(
                f"Phase 5 (Layout): {layout_count}/{len(self.state.scaffold_complete)} "
                f"({layout_count / len(self.state.scaffold_complete) * 100:.1f}%)"
            )

        if self.state.layout_complete:
            content_count = len(self.state.content_complete)
            print(
                f"Phase 6 (Content): {content_count}/{len(self.state.layout_complete)} "
                f"({content_count / len(self.state.layout_complete) * 100:.1f}%)"
            )

        if self.state.content_complete:
            chunking_count = len(self.state.chunking_complete)
            print(
                f"Phase 7 (Chunking): {chunking_count}/{len(self.state.content_complete)} "
                f"({chunking_count / len(self.state.content_complete) * 100:.1f}%)"
            )

        if self.state.chunking_complete:
            assembly_count = len(self.state.assembly_complete)
            print(
                f"Phase 8 (Assembly): {assembly_count}/{len(self.state.chunking_complete)} "
                f"({assembly_count / len(self.state.chunking_complete) * 100:.1f}%)"
            )

        if self.state.assembly_complete:
            enrichment_count = len(self.state.enrichment_complete)
            print(
                f"Phase 9 (Enrichment): {enrichment_count}/{len(self.state.assembly_complete)} "
                f"({enrichment_count / len(self.state.assembly_complete) * 100:.1f}%)"
            )

        # Corpus enrichment totals
        if self.state.enrichment_complete:
            total_findings = sum(
                t.enrichment_stats["findings"]["total_count"]
                for t in self.state.enrichment_complete
                if hasattr(t, "enrichment_stats") and t.enrichment_stats
            )
            total_recommendations = sum(
                t.enrichment_stats["recommendations"]["total_count"]
                for t in self.state.enrichment_complete
                if hasattr(t, "enrichment_stats") and t.enrichment_stats
            )
            total_monetary = sum(
                t.enrichment_stats["findings"]["total_monetary_crore"]
                for t in self.state.enrichment_complete
                if hasattr(t, "enrichment_stats") and t.enrichment_stats
            )

            print(f"\n📊 CORPUS ENRICHMENT TOTALS:")
            print(f"   • {total_findings} findings extracted")
            print(f"   • {total_recommendations} recommendations extracted")
            print(f"   • ₹{total_monetary:,.2f} crore in monetary values identified")

            # Show findings by ministry
            print(f"\n📈 FINDINGS BY MINISTRY:")
            ministry_findings = {}
            for task in self.state.enrichment_complete:
                if hasattr(task, "enrichment_stats") and task.enrichment_stats:
                    ministry = task.enrichment_stats["report_info"]["ministry"]
                    count = task.enrichment_stats["findings"]["total_count"]
                    amount = task.enrichment_stats["findings"]["total_monetary_crore"]
                    if ministry not in ministry_findings:
                        ministry_findings[ministry] = {"count": 0, "amount": 0}
                    ministry_findings[ministry]["count"] += count
                    ministry_findings[ministry]["amount"] += amount

            for ministry, data in sorted(
                ministry_findings.items(), key=lambda x: -x[1]["amount"]
            ):
                print(
                    f"   {ministry}: {data['count']} findings, ₹{data['amount']:,.2f} crore"
                )

        # Phase 10 status
        print("")  # Blank line before phase 10 status
        if self.state.phase10a_submitted:
            print("Phase 10a (Overview & Summary): SUBMITTED (processing async)")
        elif "10a" in self.skip:
            print("Phase 10a (Overview & Summary): SKIPPED")
        else:
            print("Phase 10a (Overview & Summary): NOT RUN")

        if self.state.phase10b_completed:
            print("Phase 10b (Visual Extraction): COMPLETE")
        elif "10b" in self.skip:
            print("Phase 10b (Visual Extraction): SKIPPED")
        else:
            print("Phase 10b (Visual Extraction): NOT RUN")

        if self.state.phase10c_completed:
            print("Phase 10c (Visual Post-Processing): COMPLETE")
        elif "10c" in self.skip:
            print("Phase 10c (Visual Post-Processing): SKIPPED")
        else:
            print("Phase 10c (Visual Post-Processing): NOT RUN")

        # Final success evaluation
        final_success = (
            self.state.successful_triaged
            and len(self.state.scaffold_complete) == len(self.state.successful_triaged)
            and len(self.state.layout_complete) == len(self.state.scaffold_complete)
            and len(self.state.content_complete) == len(self.state.layout_complete)
            and len(self.state.chunking_complete) == len(self.state.content_complete)
            and len(self.state.assembly_complete) == len(self.state.chunking_complete)
            and len(self.state.enrichment_complete) == len(self.state.assembly_complete)
        )

        if final_success:
            print("\n🎉 FULL PIPELINE COMPLETE! End-to-end processing successful!")
            print(
                "✅ Ready for RAG system: Vector Store ingestion can proceed with enriched JSONs"
            )
        else:
            # Collect issues
            issues_found = []
            for phase_name, failures in self.state.failed.items():
                if failures:
                    issues_found.append(f"{phase_name} ({len(failures)} failed)")

            if issues_found:
                print(f"\n⚠️  Pipeline completed with issues: {', '.join(issues_found)}")
            else:
                print("\n⚠️  Pipeline completed with partial success")

    def _log(self, msg: str, force: bool = False):
        """Print message unless quiet mode suppresses it."""
        if force or not self.quiet:
            print(msg)

    def _phase_header(self, number: str, name: str):
        """Print phase header."""
        if not self.quiet:
            print(f"\n\nPHASE {number}: {name}")
            print("-" * 40)

    def _phase_result(self, number: str, name: str, success: int, total: int):
        """Print phase result (always printed, even in quiet mode)."""
        if total == 0:
            status = "No input"
            pct = ""
        else:
            pct = f"({success / total * 100:.1f}%)" if total > 0 else ""
            status = f"{success}/{total} {pct}"

        if self.quiet:
            # Compact format for quiet mode
            icon = "✓" if success == total else "⚠"
            print(f"{icon} Phase {number} ({name}): {status}")
        else:
            # Verbose format
            print(f"\n{name} Results:")
            print(f"  Successful: {status}")

            # Show failures if any
            phase_key = name.lower().replace(" ", "_").replace("&", "and")
            if self.state.failed.get(phase_key):
                print(f"  Failed: {len(self.state.failed[phase_key])}")
                for task, err in self.state.failed[phase_key][:3]:  # Show first 3
                    print(f"    • {task.report_id}: {err}")

    def _print_header(self):
        """Print pipeline header."""
        print("=" * 60)
        print("CAG PARSING PIPELINE - FULL PIPELINE WITH SEMANTIC ENRICHMENT")
        print("=" * 60)
        print(f"Manifest: {self.manifest_path}")
        if self.skip:
            print(f"Skipping phases: {', '.join(sorted(self.skip))}")
        if self.report_filter:
            print(f"Report filter: {len(self.report_filter)} reports")
        if self.workers > 1:
            print(f"Mode: PARALLEL ({self.workers} workers for phases 4-9)")
        if self.trace:
            print(f"Mode: TRACE (emitting markdown traces to {self.state.trace_emitter.output_dir})")
        if self.quiet:
            print("Mode: QUIET (per-document progress suppressed)")
        print()


# ═══════════════════════════════════════════════════════════════════════════
# CLI ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════


def setup_logging(debug: bool = False):
    """
    Configure root logger with console and rotating file handlers.

    Args:
        debug: If True, set all loggers to DEBUG level. Otherwise, WARNING for noisy libs.
    """
    # Create logs directory
    logs_dir = Path("logs")
    logs_dir.mkdir(parents=True, exist_ok=True)

    # Generate log filename with date
    log_filename = logs_dir / f"parsing_pipeline_{datetime.now().strftime('%Y%m%d')}.log"

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG if debug else logging.INFO)

    # Remove existing handlers to avoid duplicates
    root_logger.handlers.clear()

    # Console handler (stdout)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter(
        '%(asctime)s | %(name)s | %(levelname)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)

    # Rotating file handler (10MB per file, keep 5 backups)
    file_handler = logging.handlers.RotatingFileHandler(
        log_filename,
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter(
        '%(asctime)s | %(name)s | %(levelname)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(file_formatter)
    root_logger.addHandler(file_handler)

    # Suppress noisy third-party loggers unless debug mode
    if not debug:
        logging.getLogger('docling').setLevel(logging.WARNING)
        logging.getLogger('urllib3').setLevel(logging.WARNING)
        logging.getLogger('pdfminer').setLevel(logging.WARNING)
        logging.getLogger('PIL').setLevel(logging.WARNING)
        logging.getLogger('httpx').setLevel(logging.WARNING)
        logging.getLogger('asyncio').setLevel(logging.WARNING)

    root_logger.info(f"Logging configured: console (INFO) + file ({log_filename}, DEBUG)")


async def main():
    """Main entry point with CLI argument parsing."""
    import argparse

    parser = argparse.ArgumentParser(
        description="CAG Parsing Pipeline - Process audit reports through 10 phases",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Full pipeline (all phases)
  python -m src.parsing_pipeline.main "Newtest.xlsx"

  # Skip specific phases
  python -m src.parsing_pipeline.main "Newtest.xlsx" --skip 10a 10b 10c
  python -m src.parsing_pipeline.main "Newtest.xlsx" --skip 5.5 5.7

  # Quiet mode (less output)
  python -m src.parsing_pipeline.main "Newtest.xlsx" --quiet

  # Filter to specific reports
  python -m src.parsing_pipeline.main "manifest.xlsx" --reports 2025_04_Report_A 2025_05_Report_B
        """,
    )
    parser.add_argument("manifest_path", type=str, help="Path to Excel manifest file")
    parser.add_argument(
        "--skip",
        nargs="*",
        choices=["5.5", "5.7", "10a", "10b", "10c"],
        default=[],
        help="Skip optional phases (space-separated)",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Quiet mode - only show phase results, not per-document progress",
    )
    parser.add_argument(
        "--reports",
        nargs="*",
        default=None,
        help="Filter to specific report IDs (space-separated)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging for all loggers including third-party libraries",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        metavar="N",
        help="Number of parallel workers for phases 4-9 (default: 1 = sequential). "
             "Recommended: min(cpu_count/2, 4) due to ~2-4GB memory per worker.",
    )
    parser.add_argument(
        "--trace",
        action="store_true",
        help="Enable trace instrumentation. Emits detailed per-report markdown traces "
             "documenting decisions, fallbacks, and I/O. Implies --workers 1.",
    )

    args = parser.parse_args()

    # Handle --trace flag constraints
    if args.trace and args.workers > 1:
        print(f"Note: --trace requires sequential execution. Overriding --workers {args.workers} to 1.")
        args.workers = 1

    # Setup logging (must be done early, before any loggers are used)
    setup_logging(debug=args.debug)

    # Validate manifest path
    manifest_file = Path(args.manifest_path)
    if not manifest_file.exists():
        # Try default location
        default_manifest = Path("CAG Main Docs CCDT.xlsx")
        if default_manifest.exists():
            print(f"Using default manifest: {default_manifest}")
            manifest_path = str(default_manifest.resolve())
        else:
            print(f"Error: Manifest file not found: {args.manifest_path}")
            return
    else:
        manifest_path = str(manifest_file.resolve())

    # Run orchestrator
    orchestrator = PipelineOrchestrator(
        manifest_path=manifest_path,
        skip_phases=args.skip,
        quiet=args.quiet,
        report_filter=args.reports,
        workers=args.workers,
        trace=args.trace,
    )
    await orchestrator.run()


if __name__ == "__main__":
    asyncio.run(main())
