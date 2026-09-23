"""
Pipeline State Management

This module defines the PipelineState dataclass that holds all intermediate
results between pipeline phases. Used by the PipelineOrchestrator to track
progress and manage the flow between phases.
"""

from dataclasses import dataclass, field
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from src.parsing_pipeline.instrumentation import TraceEmitter


@dataclass
class PipelineState:
    """Holds all intermediate results between pipeline phases."""

    # Phase 1: All tasks from manifest
    tasks: list = field(default_factory=list)

    # Phase 2: Triage results
    triaged_native: list = field(default_factory=list)
    triaged_scanned: list = field(default_factory=list)

    # Phase 3: OCR results
    ocred_successful: list = field(default_factory=list)

    # Combined input to Phase 4+ (native + ocred)
    successful_triaged: list = field(default_factory=list)

    # Phase 4: Scaffolding
    scaffold_complete: list = field(default_factory=list)

    # Phase 5: Layout Analysis
    layout_complete: list = field(default_factory=list)

    # Phase 6: Content Extraction
    content_complete: list = field(default_factory=list)

    # Phase 7: Chunking
    chunking_complete: list = field(default_factory=list)

    # Phase 8: Assembly
    assembly_complete: list = field(default_factory=list)

    # Phase 9: Semantic Enrichment
    enrichment_complete: list = field(default_factory=list)

    # Phase 10b: Chunk files for visual extraction
    chunk_files: list = field(default_factory=list)

    # Phase 10 tracking flags
    phase10a_submitted: bool = False
    phase10a_completed: bool = False
    phase10b_completed: bool = False
    phase10c_completed: bool = False

    # Failure tracking - keyed by phase name, value is list of (task, error_msg)
    failed: dict = field(default_factory=lambda: defaultdict(list))

    # Trace instrumentation emitter (None when tracing disabled)
    trace_emitter: Optional["TraceEmitter"] = None
