"""
Per-report work for one phase, shared by the sequential path and --workers.

Each function does one report's work for one phase and nothing else: the
orchestrator keeps the bookkeeping (state, logs, manifests, trace events) and
calls these functions either in its own process or in worker processes. There
is no second implementation of a phase.

Every call builds its services afresh, so nothing carries over from one report
to the next, whichever process runs it. Worker processes are started with
"spawn": the parent holds Docling and CUDA, which do not survive a fork. This
module imports the services lazily so a worker does not load Docling.
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# One report, one phase
# ═══════════════════════════════════════════════════════════════════════════


def ocr_report(task, emitter):
    """Phase 3."""
    from src.parsing_pipeline.modules.ocr_service import OCRService

    return OCRService(trace_emitter=emitter).ocr_document(task, trace_emitter=emitter)


def scaffold_report(task, emitter):
    """Phase 4."""
    from src.parsing_pipeline.modules.scaffolding_service import ScaffoldingService

    return ScaffoldingService().build_scaffold(task, trace_emitter=emitter)


def extract_report(task, emitter, progress_callback=None):
    """Phase 6."""
    from src.parsing_pipeline.modules.content_extraction_service import (
        ContentExtractionService,
    )

    return ContentExtractionService().extract_content(
        task, progress_callback=progress_callback, trace_emitter=emitter
    )


def chunk_report(task, emitter):
    """Phase 7. Returns the task with its parent and child chunks."""
    from src.parsing_pipeline.modules.chunking_service import ChunkingService

    parent_chunks, child_chunks = ChunkingService(trace_emitter=emitter).chunk_document(
        task, trace_emitter=emitter
    )
    task.parent_chunks = parent_chunks
    task.child_chunks = child_chunks
    task.processing_status = "chunking_complete"
    return task


def enrich_hierarchy_report(task, emitter, aggressive: bool):
    """Phase 7.5. Returns (parents, children, outcome of the enricher's safety valve)."""
    from src.parsing_pipeline.modules.hierarchy_enricher import HierarchyEnricher

    enricher = HierarchyEnricher(trace_emitter=emitter)
    parents, children = enricher.enrich_hierarchy(
        parent_chunks=task.parent_chunks,
        child_chunks=task.child_chunks,
        report_id=task.report_id,
        aggressive=aggressive,
        trace_emitter=emitter,
    )
    return parents, children, enricher.last_outcome


def assemble_report(task, emitter, run_id: str):
    """
    Phase 8: write the working file. Returns (path, parent count, child count).

    The tier manifest is updated by the orchestrator, one report at a time, so
    workers never write the same manifest file.
    """
    from src.core.data_contracts import ChildChunk, ParentChunk
    from src.parsing_pipeline.modules.assembly_service import AssemblyService

    parent_chunks = [
        ParentChunk(**pc) if isinstance(pc, dict) else pc
        for pc in (task.parent_chunks or [])
    ]
    child_chunks = [
        ChildChunk(**cc) if isinstance(cc, dict) else cc
        for cc in (task.child_chunks or [])
    ]
    service = AssemblyService(
        output_dir="data/processed", trace_emitter=emitter, run_id=run_id
    )
    output_path = service.assemble_document(
        task=task,
        parent_chunks=parent_chunks,
        child_chunks=child_chunks,
        trace_emitter=emitter,
        skip_manifest=True,
    )
    parents, children = service.last_counts
    return output_path, parents, children


def enrich_report(
    task,
    emitter,
    run_id: str,
    phases_completed: List[str],
    pdf_for_checks: Optional[str],
):
    """
    Phase 9: enrich the working file, run the preflight checks and write the final
    *_chunks.json. Returns a dict for the orchestrator's manifest and log lines.
    """
    import json
    import os
    from pathlib import Path

    from src.parsing_pipeline.modules.assembly_service import (
        AssemblyService,
        propagate_semantic_enrichment_to_chunks,
    )
    from src.parsing_pipeline.modules.semantic_enrichment_service import (
        SemanticEnrichmentService,
    )
    from src.parsing_pipeline.modules.validation_service import run_quality_checks
    from src.parsing_pipeline.quality import summarize as summarize_quality

    with open(task.assembled_output_path, "r", encoding="utf-8") as f:
        assembled_data = json.load(f)

    enrichment = SemanticEnrichmentService().enrich_document(
        report_id=assembled_data["report_metadata"]["report_id"],
        report_metadata=assembled_data["report_metadata"],
        parent_chunks=assembled_data["parent_chunks"],
        child_chunks=assembled_data["child_chunks"],
        task=task,  # report type (ATIR, state_*) comes from the manifest metadata
        trace_emitter=emitter,
    )
    assembled_data["semantic_enrichment"] = enrichment.model_dump()

    # finding_type, severity, is_recommendation etc. at chunk level for filtered retrieval
    propagate_semantic_enrichment_to_chunks(
        assembled_data["child_chunks"], assembled_data["semantic_enrichment"]
    )

    # Red flags from phases 1-9 travel with the output (tracing or not)
    assembled_data.setdefault("processing_stats", {})["red_flags"] = (
        emitter.get_red_flags(task.report_id)
    )

    metadata = assembled_data["report_metadata"]
    metadata["processing_status"] = "enriched"
    metadata["phases_completed"] = phases_completed
    metadata["pipeline_run_id"] = run_id
    assembled_data["processing_stats"]["processing_status"] = "enriched"

    # Preflight checks on the final output; never raises
    quality = run_quality_checks(assembled_data, pdf_for_checks)
    assembled_data["processing_stats"]["quality"] = quality

    # Write the working file, then rename it to the final *_chunks.json:
    # a run stopped mid-write never leaves a partial final file
    working_path = Path(task.assembled_output_path)
    final_path = AssemblyService.final_output_path(working_path)
    with open(working_path, "w", encoding="utf-8") as f:
        json.dump(assembled_data, f, indent=2, ensure_ascii=False)
    os.replace(working_path, final_path)

    return {
        "final_path": str(final_path),
        "tier": metadata.get("government_body_type", "union"),
        "parent_chunks": len(assembled_data["parent_chunks"]),
        "child_chunks": len(assembled_data["child_chunks"]),
        "quality_summary": summarize_quality(quality),
        "statistics": enrichment.statistics,
    }


# ═══════════════════════════════════════════════════════════════════════════
# Running a function in a worker process
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class WorkerResult:
    """What a worker sends back: the function's value or its error, plus red flags."""

    value: Any = None
    error: Optional[str] = None
    red_flags: List[dict] = field(default_factory=list)
    seconds: float = 0.0


def run_in_worker(
    fn: Callable, task, args: tuple, prior_red_flags: Optional[List[dict]] = None
) -> WorkerResult:
    """
    Run fn(task, emitter, *args) in a worker process.

    The worker has its own disabled trace emitter for this report, seeded with the
    report's red flags so far (Phase 9 writes them into the output). The red flags
    raised here go back to the orchestrator. Errors come back as text: not every
    exception can be pickled, and the orchestrator handles them as it would its own.
    """
    from src.parsing_pipeline.instrumentation import TraceEmitter

    emitter = TraceEmitter(enabled=False)
    emitter.set_current_report(task.report_id)
    prior = list(prior_red_flags or [])
    emitter.add_red_flags(task.report_id, prior)

    started = time.monotonic()
    result = WorkerResult()
    try:
        result.value = fn(task, emitter, *args)
    except Exception as e:
        logger.exception(
            f"[{task.report_id}] {getattr(fn, '__name__', fn)} failed in a worker"
        )
        result.error = str(e)
    result.red_flags = emitter.get_red_flags(task.report_id)[len(prior) :]
    result.seconds = time.monotonic() - started
    return result


class WorkerError(Exception):
    """A report's error from a worker process, raised again in the orchestrator."""


def init_worker(log_file: Optional[str], debug: bool) -> None:
    """Worker start-up: log to the run's log file and the console, like the orchestrator."""
    from src.parsing_pipeline.log_setup import configure_logging

    configure_logging(log_file, debug)
