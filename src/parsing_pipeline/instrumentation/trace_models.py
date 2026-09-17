"""
Trace Models for Pipeline Instrumentation.

Contains data classes for trace events and metadata.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import time


@dataclass
class TraceEvent:
    """A single trace event recorded during pipeline execution."""

    phase: str
    """Phase identifier (e.g., '1', '4', '5.5', '10b')."""

    event: str
    """Event type (e.g., 'decision', 'io', 'sample', 'fallback', 'red_flag')."""

    data: Dict[str, Any]
    """Event-specific payload."""

    ts: float = field(default_factory=time.time)
    """Unix timestamp when event was emitted."""


@dataclass
class PhaseResult:
    """Summary of a phase's execution for the trace report."""

    phase: str
    """Phase identifier."""

    status: str
    """'success', 'partial', 'failed', 'skipped'."""

    duration_seconds: float
    """Wall-clock duration."""

    events: List[TraceEvent] = field(default_factory=list)
    """All events emitted during this phase."""


@dataclass
class RedFlag:
    """An anomaly detected during processing that warrants attention."""

    phase: str
    """Phase where anomaly was detected."""

    flag: str
    """Short description of the anomaly."""

    details: Dict[str, Any]
    """Additional context about the anomaly."""


@dataclass
class ReportMetadata:
    """Metadata about the report being traced."""

    report_id: str
    tier: str  # 'union', 'state', 'local_body'
    source_pdf_path: str
    page_count: int = 0
    file_size_bytes: int = 0
    state_name: Optional[str] = None

    def file_size_mb(self) -> float:
        """Return file size in megabytes."""
        return self.file_size_bytes / (1024 * 1024)


@dataclass
class ReportContext:
    """Per-report trace collection state.

    Each report processed in a pipeline run gets its own ReportContext,
    allowing multi-report batches to produce independent trace files.

    Memory note: Per-report event buffers are released on finalize.
    Production runs of 159 reports with --trace would hold ~159 buffers;
    for typical traces of 8-20 reports this is trivial. --trace is
    intended for debugging, not production.
    """

    report_id: str
    """The report's unique identifier."""

    metadata: Optional["ReportMetadata"]
    """Report metadata (tier, path, page count, etc.)."""

    events: List[TraceEvent] = field(default_factory=list)
    """All trace events for this report."""

    phase_timings: Dict[str, float] = field(default_factory=dict)
    """Duration in seconds for each phase."""

    phase_statuses: Dict[str, str] = field(default_factory=dict)
    """Final status ('success', 'partial', 'failed', 'skipped') for each phase."""

    red_flags: List[RedFlag] = field(default_factory=list)
    """Anomalies detected during processing."""

    start_time: float = field(default_factory=time.perf_counter)
    """When trace collection started for this report."""

    current_phase: Optional[str] = None
    """Currently executing phase (for phase_timer context manager)."""
