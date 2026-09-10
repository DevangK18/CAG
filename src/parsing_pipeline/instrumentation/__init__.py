"""
Pipeline Trace Instrumentation Module.

This module provides observability into the CAG parsing pipeline by emitting
detailed trace events at each phase. Traces are rendered to Markdown files
for human review and debugging.

Usage:
    from src.parsing_pipeline.instrumentation import TraceEmitter, get_noop_emitter

    # Create enabled emitter
    emitter = TraceEmitter(enabled=True, output_dir="logs/traces")

    # Or get a no-op emitter for when tracing is disabled
    emitter = get_noop_emitter()

Key Features:
- Zero overhead when disabled (all methods check enabled flag first)
- Per-report trace files with Red Flags auto-collection
- Decision point, I/O, sample, and fallback event types
- Phase timing with context manager
- Incremental flush option for crash protection

See docs/guides/PARSING_PIPELINE.md for full documentation.
"""

from .trace_emitter import TraceEmitter, get_noop_emitter
from .trace_models import PhaseResult, RedFlag, ReportContext, ReportMetadata, TraceEvent
from .trace_renderer import TraceRenderer

__all__ = [
    "TraceEmitter",
    "get_noop_emitter",
    "TraceEvent",
    "PhaseResult",
    "RedFlag",
    "ReportContext",
    "ReportMetadata",
    "TraceRenderer",
]
