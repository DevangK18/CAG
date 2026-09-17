"""
Parallel Runner for the CAG Parsing Pipeline.

Executes phases 4-9 in parallel across multiple processes using ProcessPoolExecutor.
Each worker processes a complete DocumentTask through all phases, avoiding cross-process
serialization of intermediate state.

Design principles:
1. Per-task parallelism: Each task runs through phases 4-9 as one unit
2. Expensive model loading once per worker via initializer
3. Manifest writes deferred to main process (no locking needed)
4. Failure isolation: One task crash doesn't affect others

Usage:
    from src.parsing_pipeline.parallel_runner import run_parallel

    state = run_parallel(
        tasks=triaged_tasks,
        skip_phases={"5.7"},
        quiet=False,
        workers=4,
    )
"""

import os
import sys
import json
import logging
import traceback
from pathlib import Path
from datetime import datetime
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Set, Tuple

# Import pipeline state
from src.parsing_pipeline.pipeline_state import PipelineState

# Import data contracts
from src.core.data_contracts import DocumentTask, ParentChunk, ChildChunk

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# WORKER GLOBALS - Initialized once per worker process
# ═══════════════════════════════════════════════════════════════════════════════

_scaffolding_service = None
_layout_service = None
_toc_reconciliation_service = None
_toc_llm_validator = None
_content_extraction_service = None
_chunking_service = None
_hierarchy_enricher = None
_assembly_service = None
_semantic_enrichment_service = None
_worker_initialized = False


def _worker_initializer(output_dir: str = "data/processed"):
    """
    Initialize worker process with pre-loaded services.

    Called once per worker at process start. Loads expensive models (Docling ~2GB)
    into process memory so they're reused across all tasks assigned to this worker.

    Args:
        output_dir: Output directory for assembly service
    """
    global _scaffolding_service, _layout_service, _toc_reconciliation_service
    global _toc_llm_validator, _content_extraction_service, _chunking_service
    global _hierarchy_enricher, _assembly_service, _semantic_enrichment_service
    global _worker_initialized

    # Critical: Set tokenizer parallelism before any imports
    # Children don't reliably inherit env on all platforms
    os.environ["TOKENIZERS_PARALLELISM"] = "false"

    # Import services here to ensure TOKENIZERS_PARALLELISM is set first
    from src.parsing_pipeline.modules.scaffolding_service import ScaffoldingService
    from src.parsing_pipeline.modules.layout_analysis_service import LayoutAnalysisService
    from src.parsing_pipeline.modules.toc_reconciliation_service import TOCReconciliationService
    from src.parsing_pipeline.modules.toc_llm_validator import TOCLLMValidator
    from src.parsing_pipeline.modules.content_extraction_service import ContentExtractionService
    from src.parsing_pipeline.modules.chunking_service import ChunkingService
    from src.parsing_pipeline.modules.hierarchy_enricher import HierarchyEnricher
    from src.parsing_pipeline.modules.assembly_service import AssemblyService
    from src.parsing_pipeline.modules.semantic_enrichment_service import SemanticEnrichmentService

    # Initialize all services
    _scaffolding_service = ScaffoldingService()
    _layout_service = LayoutAnalysisService()  # Loads Docling ~2GB
    _toc_reconciliation_service = TOCReconciliationService()
    _toc_llm_validator = TOCLLMValidator() if os.environ.get("GOOGLE_API_KEY") else None
    _content_extraction_service = ContentExtractionService()
    _chunking_service = ChunkingService()
    _hierarchy_enricher = HierarchyEnricher()
    _assembly_service = AssemblyService(output_dir=output_dir)
    _semantic_enrichment_service = SemanticEnrichmentService()

    _worker_initialized = True

    # Log worker startup
    pid = os.getpid()
    logger.info(f"Worker {pid} initialized with all services")


# ═══════════════════════════════════════════════════════════════════════════════
# TASK RESULT DATACLASS
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class TaskResult:
    """Result of processing a single task through phases 4-9."""
    report_id: str
    success: bool
    phase_reached: Optional[str] = None
    error: Optional[str] = None
    error_phase: Optional[str] = None
    task_dict: Optional[Dict[str, Any]] = None
    output_path: Optional[str] = None
    enrichment_stats: Optional[Dict[str, Any]] = None

    # Chunk counts for manifest update
    parent_chunk_count: int = 0
    child_chunk_count: int = 0


# ═══════════════════════════════════════════════════════════════════════════════
# SINGLE-TASK PROCESSOR (Runs in worker process)
# ═══════════════════════════════════════════════════════════════════════════════

def _process_task_phases_4_to_9(
    task_dict: Dict[str, Any],
    skip_phases: Set[str],
) -> Dict[str, Any]:
    """
    Process a single DocumentTask through phases 4-9.

    This function runs in a worker process. It uses the pre-initialized services
    from _worker_initializer() to avoid reloading models for each task.

    Args:
        task_dict: Serialized DocumentTask (dict form for pickling)
        skip_phases: Set of phase identifiers to skip (e.g., {"5.5", "5.7"})

    Returns:
        Dict with result fields (serializable for IPC)
    """
    global _scaffolding_service, _layout_service, _toc_reconciliation_service
    global _toc_llm_validator, _content_extraction_service, _chunking_service
    global _hierarchy_enricher, _assembly_service, _semantic_enrichment_service

    # Reconstruct DocumentTask from dict
    task = DocumentTask(**task_dict)

    result = {
        "report_id": task.report_id,
        "success": False,
        "phase_reached": None,
        "error": None,
        "error_phase": None,
        "task_dict": None,
        "output_path": None,
        "enrichment_stats": None,
        "parent_chunk_count": 0,
        "child_chunk_count": 0,
    }

    try:
        # ─────────────────────────────────────────────────────────────────────
        # PHASE 4: SCAFFOLDING
        # ─────────────────────────────────────────────────────────────────────
        task = _scaffolding_service.build_scaffold(task)
        if task.processing_status not in ("scaffold_complete", "scaffold_partial"):
            error_msg = task.error_log[-1] if task.error_log else "Scaffolding failed"
            raise _PipelinePhaseError("scaffolding", error_msg)
        result["phase_reached"] = "4"

        # ─────────────────────────────────────────────────────────────────────
        # PHASE 5: LAYOUT ANALYSIS
        # ─────────────────────────────────────────────────────────────────────
        task = _layout_service.analyze_layout(task)
        if task.processing_status != "layout_complete":
            error_msg = task.error_log[-1] if task.error_log else "Layout analysis failed"
            raise _PipelinePhaseError("layout_analysis", error_msg)
        result["phase_reached"] = "5"

        # ─────────────────────────────────────────────────────────────────────
        # PHASE 5.5: TOC RECONCILIATION (optional)
        # ─────────────────────────────────────────────────────────────────────
        if "5.5" not in skip_phases:
            task = _toc_reconciliation_service.reconcile(task)
            result["phase_reached"] = "5.5"

        # ─────────────────────────────────────────────────────────────────────
        # PHASE 5.7: LLM TOC VALIDATION (optional)
        # ─────────────────────────────────────────────────────────────────────
        if "5.7" not in skip_phases and _toc_llm_validator:
            if _toc_llm_validator.should_validate(task):
                task.scaffold = _toc_llm_validator.validate_toc(task)
            result["phase_reached"] = "5.7"

        # ─────────────────────────────────────────────────────────────────────
        # PHASE 6: CONTENT EXTRACTION
        # ─────────────────────────────────────────────────────────────────────
        # No progress callback in parallel mode (would interleave output)
        task = _content_extraction_service.extract_content(task, progress_callback=None)
        if task.processing_status not in ("completed_content_extraction", "partial_content_extraction"):
            error_msg = task.error_log[-1] if task.error_log else "Content extraction failed"
            raise _PipelinePhaseError("content_extraction", error_msg)
        result["phase_reached"] = "6"

        # ─────────────────────────────────────────────────────────────────────
        # PHASE 7: CHUNKING
        # ─────────────────────────────────────────────────────────────────────
        parent_chunks, child_chunks = _chunking_service.chunk_document(task)
        task.parent_chunks = parent_chunks
        task.child_chunks = child_chunks
        task.processing_status = "chunking_complete"
        result["phase_reached"] = "7"

        # ─────────────────────────────────────────────────────────────────────
        # PHASE 7.5: HIERARCHY ENRICHMENT
        # ─────────────────────────────────────────────────────────────────────
        from src.parsing_pipeline.modules.hierarchy_enricher import should_enrich_hierarchy

        if task.parent_chunks and task.child_chunks:
            should_enrich, reason = should_enrich_hierarchy(task.parent_chunks, task.child_chunks)
            if should_enrich:
                enriched_parents, enriched_children = _hierarchy_enricher.enrich_hierarchy(
                    parent_chunks=task.parent_chunks,
                    child_chunks=task.child_chunks,
                    report_id=task.report_id,
                    aggressive=False,
                )
                task.parent_chunks = enriched_parents
                task.child_chunks = enriched_children
        result["phase_reached"] = "7.5"

        # ─────────────────────────────────────────────────────────────────────
        # PHASE 8: ASSEMBLY (skip manifest update - done in main process)
        # ─────────────────────────────────────────────────────────────────────
        # Convert chunks to Pydantic models if needed
        parent_chunks_pydantic = [
            ParentChunk(**pc) if isinstance(pc, dict) else pc
            for pc in (task.parent_chunks or [])
        ]
        child_chunks_pydantic = [
            ChildChunk(**cc) if isinstance(cc, dict) else cc
            for cc in (task.child_chunks or [])
        ]

        # Assemble document WITHOUT updating manifest (skip_manifest=True)
        output_path = _assembly_service.assemble_document(
            task=task,
            parent_chunks=parent_chunks_pydantic,
            child_chunks=child_chunks_pydantic,
            skip_manifest=True,  # Critical: defer to main process
        )
        task.assembled_output_path = output_path
        task.processing_status = "assembly_complete"
        result["output_path"] = output_path
        result["parent_chunk_count"] = len(parent_chunks_pydantic)
        result["child_chunk_count"] = len(child_chunks_pydantic)
        result["phase_reached"] = "8"

        # ─────────────────────────────────────────────────────────────────────
        # PHASE 9: SEMANTIC ENRICHMENT
        # ─────────────────────────────────────────────────────────────────────
        with open(task.assembled_output_path, "r", encoding="utf-8") as f:
            assembled_data = json.load(f)

        enrichment = _semantic_enrichment_service.enrich_document(
            report_id=assembled_data["report_metadata"]["report_id"],
            report_metadata=assembled_data["report_metadata"],
            parent_chunks=assembled_data["parent_chunks"],
            child_chunks=assembled_data["child_chunks"],
        )

        # Add enrichment to data
        assembled_data["semantic_enrichment"] = enrichment.model_dump()

        # Save enriched output (overwrite)
        with open(task.assembled_output_path, "w", encoding="utf-8") as f:
            json.dump(assembled_data, f, indent=2, ensure_ascii=False)

        # Store enrichment stats
        stats = enrichment.statistics
        task.enrichment_stats = stats
        result["enrichment_stats"] = stats
        result["phase_reached"] = "9"

        # ─────────────────────────────────────────────────────────────────────
        # SUCCESS
        # ─────────────────────────────────────────────────────────────────────
        result["success"] = True
        result["task_dict"] = _serialize_task(task)

    except _PipelinePhaseError as e:
        result["error"] = str(e.message)
        result["error_phase"] = e.phase
        result["task_dict"] = _serialize_task(task)

    except Exception as e:
        result["error"] = f"{type(e).__name__}: {str(e)}"
        result["error_phase"] = result.get("phase_reached") or "unknown"
        result["task_dict"] = _serialize_task(task)
        # Log full traceback for debugging
        logger.error(f"Task {task.report_id} failed: {traceback.format_exc()}")

    return result


class _PipelinePhaseError(Exception):
    """Internal exception for phase failures with phase tracking."""
    def __init__(self, phase: str, message: str):
        self.phase = phase
        self.message = message
        super().__init__(f"Phase {phase}: {message}")


def _serialize_task(task: DocumentTask) -> Dict[str, Any]:
    """
    Serialize DocumentTask to dict for IPC.

    Handles non-serializable fields gracefully.
    """
    try:
        # Use Pydantic's model_dump if available
        if hasattr(task, "model_dump"):
            return task.model_dump()
        elif hasattr(task, "dict"):
            return task.dict()
        else:
            # Fallback: convert dataclass-like object
            return {k: v for k, v in task.__dict__.items() if not k.startswith("_")}
    except Exception:
        # Last resort: return minimal info
        return {
            "report_id": getattr(task, "report_id", "unknown"),
            "processing_status": getattr(task, "processing_status", "unknown"),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN PARALLEL RUNNER
# ═══════════════════════════════════════════════════════════════════════════════

def run_parallel(
    tasks: List[DocumentTask],
    skip_phases: Set[str],
    quiet: bool = False,
    workers: int = 4,
    output_dir: str = "data/processed",
) -> PipelineState:
    """
    Run phases 4-9 in parallel across multiple worker processes.

    Args:
        tasks: List of DocumentTask objects that have completed phases 1-3
        skip_phases: Set of phase identifiers to skip (e.g., {"5.5", "5.7"})
        quiet: If True, suppress per-task progress output
        workers: Number of worker processes (default: 4)
        output_dir: Output directory for assembled JSONs

    Returns:
        PipelineState with all results populated
    """
    state = PipelineState()
    state.successful_triaged = list(tasks)  # Copy input tasks

    if not tasks:
        logger.warning("No tasks to process")
        return state

    total_tasks = len(tasks)
    completed = 0
    failed = 0
    in_flight = 0

    # Progress display helper
    def update_progress():
        if not quiet:
            msg = f"\rPhase 4-9: {completed}/{total_tasks} done, {in_flight} in flight, {failed} failed"
            print(msg + " " * 10, end="", flush=True)

    print(f"\n{'='*60}")
    print(f"PARALLEL EXECUTION: {workers} workers, {total_tasks} tasks")
    print(f"{'='*60}\n")

    # Serialize tasks for worker processes
    task_dicts = []
    for task in tasks:
        if hasattr(task, "model_dump"):
            task_dicts.append(task.model_dump())
        elif hasattr(task, "dict"):
            task_dicts.append(task.dict())
        else:
            task_dicts.append(task.__dict__.copy())

    # Track results by report_id for manifest update
    results_by_id: Dict[str, Dict[str, Any]] = {}

    # Create process pool with initializer
    with ProcessPoolExecutor(
        max_workers=workers,
        initializer=_worker_initializer,
        initargs=(output_dir,),
    ) as executor:
        # Submit all tasks
        future_to_task = {
            executor.submit(_process_task_phases_4_to_9, task_dict, skip_phases): task_dict
            for task_dict in task_dicts
        }
        in_flight = len(future_to_task)
        update_progress()

        # Collect results as they complete
        for future in as_completed(future_to_task):
            original_task_dict = future_to_task[future]
            report_id = original_task_dict.get("report_id", "unknown")
            in_flight -= 1

            try:
                result = future.result()
                results_by_id[result["report_id"]] = result

                if result["success"]:
                    completed += 1

                    # Reconstruct task and populate state lists
                    if result["task_dict"]:
                        try:
                            completed_task = DocumentTask(**result["task_dict"])
                            completed_task.enrichment_stats = result.get("enrichment_stats")

                            # Populate all intermediate state lists
                            state.scaffold_complete.append(completed_task)
                            state.layout_complete.append(completed_task)
                            state.content_complete.append(completed_task)
                            state.chunking_complete.append(completed_task)
                            state.assembly_complete.append(completed_task)
                            state.enrichment_complete.append(completed_task)
                        except Exception as e:
                            logger.warning(f"Could not reconstruct task {report_id}: {e}")

                    if not quiet:
                        print(f"\r✓ {report_id}: completed through phase 9" + " " * 30)
                else:
                    failed += 1
                    error_phase = result.get("error_phase", "unknown")
                    error_msg = result.get("error", "Unknown error")

                    # Try to reconstruct partial task for failure tracking
                    try:
                        partial_task = DocumentTask(**result["task_dict"]) if result["task_dict"] else DocumentTask(report_id=report_id)
                    except Exception:
                        partial_task = DocumentTask(report_id=report_id, local_pdf_path="")

                    state.failed[error_phase].append((partial_task, error_msg))

                    if not quiet:
                        print(f"\r✗ {report_id}: failed at phase {error_phase}: {error_msg[:50]}" + " " * 10)

            except Exception as e:
                # Worker process crashed
                failed += 1
                error_msg = f"Worker crash: {str(e)}"

                try:
                    partial_task = DocumentTask(**original_task_dict)
                except Exception:
                    partial_task = DocumentTask(report_id=report_id, local_pdf_path="")

                state.failed["worker_crash"].append((partial_task, error_msg))

                if not quiet:
                    print(f"\r✗ {report_id}: worker crashed: {str(e)[:50]}" + " " * 10)

            update_progress()

    # Clear progress line
    if not quiet:
        print("\r" + " " * 80)

    # ─────────────────────────────────────────────────────────────────────────
    # UPDATE MANIFEST (single-threaded, after all workers complete)
    # ─────────────────────────────────────────────────────────────────────────
    if state.enrichment_complete:
        print(f"\nUpdating manifest with {len(state.enrichment_complete)} completed reports...")

        from src.parsing_pipeline.modules.assembly_service import AssemblyService
        manifest_service = AssemblyService(output_dir=output_dir)

        for task in state.enrichment_complete:
            report_id = task.report_id
            result = results_by_id.get(report_id, {})

            if result.get("output_path"):
                # Create placeholder chunks for manifest update
                # (we don't need actual chunk data, just counts)
                parent_count = result.get("parent_chunk_count", 0)
                child_count = result.get("child_chunk_count", 0)

                manifest_service._update_manifest(
                    report_id=report_id,
                    parent_chunks=[None] * parent_count,  # Placeholder for count
                    child_chunks=[None] * child_count,
                    output_path=Path(result["output_path"]),
                )

        print(f"✓ Manifest updated")

    # ─────────────────────────────────────────────────────────────────────────
    # SUMMARY
    # ─────────────────────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"PARALLEL EXECUTION COMPLETE")
    print(f"{'='*60}")
    print(f"  Successful: {completed}/{total_tasks}")
    print(f"  Failed:     {failed}/{total_tasks}")

    if state.failed:
        print(f"\n  Failures by phase:")
        for phase, failures in state.failed.items():
            if failures:
                print(f"    {phase}: {len(failures)}")

    return state


def get_default_workers() -> int:
    """
    Calculate default worker count based on system resources.

    Conservative default: min(cpu_count // 2, 4)
    Each worker uses ~2-4GB for Docling model.
    """
    cpu_count = os.cpu_count() or 4
    return min(cpu_count // 2, 4)
