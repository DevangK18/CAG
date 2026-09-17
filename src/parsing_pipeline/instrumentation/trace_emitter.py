"""
Trace Emitter for Pipeline Instrumentation.

The TraceEmitter is the core class for collecting trace events during pipeline execution.
It's designed for zero overhead when disabled - all methods check `self.enabled` as the
first operation and return immediately if tracing is off.

Architecture (Fix 1 - Round 5):
    The emitter uses a per-report context dict to handle multi-report batches correctly.
    Each report gets its own ReportContext with isolated events, timings, and red flags.
    This prevents event contamination where one trace file would contain events from
    multiple reports.

    Memory note: Per-report event buffers are released on finalize. Production runs of
    159 reports with --trace would hold ~159 buffers; for typical traces of 8-20 reports
    this is trivial. --trace is intended for debugging, not production.

Usage:
    emitter = TraceEmitter(enabled=True, output_dir="logs/traces")

    # For each report in a batch:
    emitter.start_report(report_id, metadata)

    # In phase loops, switch context before emitting:
    emitter.set_current_report(report_id)
    with emitter.phase_timer("4"):
        emitter.emit_decision("4", "bookmark_quality", "accept", ["reject"], "score 0.82 > threshold 0.6")

    # At pipeline end, finalize all reports:
    paths = emitter.finalize_all_reports("enrichment_complete")
"""

import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional

from .trace_models import PhaseResult, RedFlag, ReportContext, ReportMetadata, TraceEvent


class TraceEmitter:
    """
    Per-report trace emitter with isolated event buffers. Zero overhead when disabled.

    Each report processed in a pipeline run gets its own ReportContext via start_report().
    Phase loops call set_current_report() to switch which context receives events.
    At pipeline end, finalize_all_reports() writes each report's trace file.
    """

    def __init__(
        self,
        enabled: bool = False,
        output_dir: str = "logs/traces",
        sample_count: int = 5,
        incremental_flush: bool = False,
    ):
        """
        Initialize the TraceEmitter.

        Args:
            enabled: Master switch. If False, all methods are no-ops.
            output_dir: Directory for trace markdown files.
            sample_count: Maximum number of samples to collect per category.
            incremental_flush: If True, flush events to disk after each phase.
        """
        self.enabled = enabled
        self.output_dir = Path(output_dir)
        self.sample_count = sample_count
        self.incremental_flush = incremental_flush

        # Per-report context storage (Fix 1: isolated buffers per report)
        self._report_contexts: Dict[str, ReportContext] = {}
        self._current_report_id: Optional[str] = None

        # Legacy attributes for backward compatibility with noop emitter checks
        self.report_id: Optional[str] = None

    def start_report(self, report_id: str, metadata: ReportMetadata) -> None:
        """
        Initialize trace collection for a new report.

        Creates a new ReportContext for this report and sets it as current.
        Does NOT clobber existing contexts for other reports in the batch.

        Args:
            report_id: The report's unique identifier.
            metadata: Report metadata (tier, path, page count, etc.).
        """
        if not self.enabled:
            return

        # Create fresh context for this report
        self._report_contexts[report_id] = ReportContext(
            report_id=report_id,
            metadata=metadata,
            events=[],
            phase_timings={},
            phase_statuses={},
            red_flags=[],
            start_time=time.perf_counter(),
            current_phase=None,
        )
        self._current_report_id = report_id
        self.report_id = report_id  # Legacy compatibility

        # Ensure output directory exists
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def set_current_report(self, report_id: str) -> None:
        """
        Switch to an existing report's context.

        Called at the start of each per-report loop iteration in Phases 4+
        to ensure events are routed to the correct report's buffer.

        Args:
            report_id: The report to switch to (must have called start_report first).
        """
        if not self.enabled:
            return

        if report_id in self._report_contexts:
            self._current_report_id = report_id
            self.report_id = report_id  # Legacy compatibility

    def _get_current_context(self) -> Optional[ReportContext]:
        """Get the current report's context, or None if not set."""
        if not self._current_report_id:
            return None
        return self._report_contexts.get(self._current_report_id)

    def emit(self, phase: str, event: str, data: Dict[str, Any]) -> None:
        """
        Emit a generic trace event.

        Args:
            phase: Phase identifier (e.g., '1', '4', '5.5').
            event: Event type name.
            data: Event-specific payload.
        """
        if not self.enabled:
            return

        ctx = self._get_current_context()
        if not ctx:
            return

        ctx.events.append(
            TraceEvent(phase=phase, event=event, data=data, ts=time.time())
        )

    def emit_decision(
        self,
        phase: str,
        decision: str,
        chosen: str,
        alternatives: List[str],
        reason: str,
    ) -> None:
        """
        Emit a decision point with alternatives considered.

        Args:
            phase: Phase identifier.
            decision: Name of the decision (e.g., 'bookmark_quality', 'tier_selection').
            chosen: The option that was selected.
            alternatives: Other options that were available.
            reason: Why this option was chosen.
        """
        if not self.enabled:
            return

        ctx = self._get_current_context()
        if not ctx:
            return

        ctx.events.append(
            TraceEvent(
                phase=phase,
                event="decision",
                data={
                    "decision": decision,
                    "chosen": chosen,
                    "alternatives": alternatives,
                    "reason": reason,
                },
                ts=time.time(),
            )
        )

    def emit_io(
        self, phase: str, input_summary: Dict[str, Any], output_summary: Dict[str, Any]
    ) -> None:
        """
        Emit phase input/output summary.

        Args:
            phase: Phase identifier.
            input_summary: Summary of phase inputs.
            output_summary: Summary of phase outputs.
        """
        if not self.enabled:
            return

        ctx = self._get_current_context()
        if not ctx:
            return

        ctx.events.append(
            TraceEvent(
                phase=phase,
                event="io",
                data={"input": input_summary, "output": output_summary},
                ts=time.time(),
            )
        )

    def emit_sample(
        self, phase: str, category: str, examples: List[Dict[str, Any]]
    ) -> None:
        """
        Emit sample data for inspection (e.g., rejected TOC entries).

        Automatically limits to self.sample_count examples.

        Args:
            phase: Phase identifier.
            category: Sample category (e.g., 'accepted_toc', 'rejected_entities').
            examples: List of example items.
        """
        if not self.enabled:
            return

        ctx = self._get_current_context()
        if not ctx:
            return

        # Limit to sample_count
        limited_examples = examples[: self.sample_count]

        ctx.events.append(
            TraceEvent(
                phase=phase,
                event="sample",
                data={"category": category, "examples": limited_examples},
                ts=time.time(),
            )
        )

    def emit_fallback(
        self, phase: str, primary: str, fell_back_to: str, trigger: str
    ) -> None:
        """
        Emit when a fallback mechanism activated.

        Args:
            phase: Phase identifier.
            primary: The primary mechanism that failed.
            fell_back_to: The fallback mechanism used.
            trigger: What caused the fallback (e.g., 'pdfplumber returned None').
        """
        if not self.enabled:
            return

        ctx = self._get_current_context()
        if not ctx:
            return

        ctx.events.append(
            TraceEvent(
                phase=phase,
                event="fallback",
                data={
                    "primary": primary,
                    "fell_back_to": fell_back_to,
                    "trigger": trigger,
                },
                ts=time.time(),
            )
        )

    def emit_red_flag(self, phase: str, flag: str, details: Dict[str, Any]) -> None:
        """
        Emit an anomaly that should appear in the Red Flags section.

        These are critical issues that warrant attention during trace review.

        Args:
            phase: Phase identifier.
            flag: Short description of the anomaly.
            details: Additional context (must include actual data, not just messages).
        """
        if not self.enabled:
            return

        ctx = self._get_current_context()
        if not ctx:
            return

        ctx.red_flags.append(RedFlag(phase=phase, flag=flag, details=details))
        ctx.events.append(
            TraceEvent(
                phase=phase,
                event="red_flag",
                data={"flag": flag, **details},
                ts=time.time(),
            )
        )

    def emit_error(self, phase: str, error: str, details: Dict[str, Any] = None) -> None:
        """
        Emit an error that occurred during processing.

        Args:
            phase: Phase identifier.
            error: Error message.
            details: Additional context.
        """
        if not self.enabled:
            return

        ctx = self._get_current_context()
        if not ctx:
            return

        ctx.events.append(
            TraceEvent(
                phase=phase,
                event="error",
                data={"error": error, **(details or {})},
                ts=time.time(),
            )
        )

    @contextmanager
    def phase_timer(self, phase: str) -> Generator[None, None, None]:
        """
        Context manager to time a phase.

        Usage:
            with emitter.phase_timer("4"):
                # Phase 4 code

        Args:
            phase: Phase identifier.
        """
        if not self.enabled:
            yield
            return

        ctx = self._get_current_context()
        if not ctx:
            yield
            return

        ctx.current_phase = phase
        start = time.perf_counter()
        try:
            yield
        finally:
            duration = time.perf_counter() - start
            ctx.phase_timings[phase] = duration
            ctx.current_phase = None

            # Incremental flush if enabled
            if self.incremental_flush:
                self._flush_phase(phase)

    def set_phase_status(self, phase: str, status: str) -> None:
        """
        Set the final status for a phase.

        Args:
            phase: Phase identifier.
            status: 'success', 'partial', 'failed', 'skipped'.
        """
        if not self.enabled:
            return

        ctx = self._get_current_context()
        if ctx:
            ctx.phase_statuses[phase] = status

    def get_phase_results(self) -> List[PhaseResult]:
        """
        Build PhaseResult objects from current report's collected data.

        Returns:
            List of PhaseResult for all phases with timing data.
        """
        if not self.enabled:
            return []

        ctx = self._get_current_context()
        if not ctx:
            return []

        results = []
        for phase, duration in sorted(
            ctx.phase_timings.items(), key=lambda x: self._phase_sort_key(x[0])
        ):
            phase_events = [e for e in ctx.events if e.phase == phase]
            status = ctx.phase_statuses.get(phase, "success")
            results.append(
                PhaseResult(
                    phase=phase,
                    status=status,
                    duration_seconds=duration,
                    events=phase_events,
                )
            )
        return results

    def finalize_report(self, final_status: str) -> Optional[Path]:
        """
        Write markdown trace file for the CURRENT report and remove its context.

        Args:
            final_status: The final processing status of the report.

        Returns:
            Path to the generated trace file, or None if tracing disabled.
        """
        if not self.enabled:
            return None

        if not self._current_report_id:
            return None

        ctx = self._report_contexts.pop(self._current_report_id, None)
        if not ctx:
            return None

        # Import renderer here to avoid circular imports
        from .trace_renderer import TraceRenderer

        total_duration = time.perf_counter() - ctx.start_time

        # P1-16: Extract assembly_timestamp from Phase 8 events
        assembly_timestamp = self._extract_assembly_timestamp(ctx.events)

        renderer = TraceRenderer(
            report_id=ctx.report_id,
            metadata=ctx.metadata,
            events=ctx.events,
            phase_timings=ctx.phase_timings,
            phase_statuses=ctx.phase_statuses,
            red_flags=ctx.red_flags,
            total_duration=total_duration,
            final_status=final_status,
            assembly_timestamp=assembly_timestamp,  # P1-16
        )

        return renderer.render_to_file(self.output_dir)

    def finalize_all_reports(self, final_status: str) -> List[Path]:
        """
        Finalize ALL remaining reports at pipeline end.

        Iterates through all report contexts and writes each to its own trace file.
        Use this at pipeline end instead of finalize_report() for multi-report batches.

        Args:
            final_status: The final processing status to apply to all reports.

        Returns:
            List of paths to generated trace files.
        """
        if not self.enabled:
            return []

        paths = []
        # Iterate over a copy of keys since we're modifying the dict
        for report_id in list(self._report_contexts.keys()):
            self._current_report_id = report_id
            self.report_id = report_id
            path = self.finalize_report(final_status)
            if path:
                paths.append(path)

        return paths

    def all_report_ids(self) -> List[str]:
        """Return list of all report IDs that have active contexts."""
        return list(self._report_contexts.keys())

    def _flush_phase(self, phase: str) -> None:
        """
        Incrementally flush events for a phase to disk.

        Used when incremental_flush is enabled for crash protection.
        """
        ctx = self._get_current_context()
        if not ctx:
            return

        # Create a partial trace file in tier-specific subdirectory
        tier = ctx.metadata.tier if ctx.metadata else "unknown"
        tier_dir = self.output_dir / tier
        tier_dir.mkdir(parents=True, exist_ok=True)
        partial_path = tier_dir / f"{ctx.report_id}_partial.md"

        # Append phase events to partial file
        with open(partial_path, "a", encoding="utf-8") as f:
            f.write(f"\n## Phase {phase} (incremental)\n")
            for event in ctx.events:
                if event.phase == phase:
                    f.write(f"- {event.event}: {event.data}\n")

    def _extract_assembly_timestamp(self, events: List) -> Optional[str]:
        """
        P1-16: Extract assembly_timestamp from Phase 8 io events.

        Looks for output_data containing assembly_timestamp in Phase 8 events.

        Args:
            events: List of TraceEvent objects

        Returns:
            Assembly timestamp string (ISO format with Z suffix) or None
        """
        for event in events:
            if event.phase == "8" and event.event == "io":
                output_data = event.data.get("output", {})
                # Extract assembly_timestamp from Phase 8 exit emit
                if "assembly_timestamp" in output_data:
                    return output_data["assembly_timestamp"]
        return None

    @staticmethod
    def _phase_sort_key(phase: str) -> tuple:
        """
        Sort key for phase identifiers.

        Handles numeric phases (1, 2, 3) and sub-phases (5.5, 5.7, 10b, 10c).
        """
        # Handle special phases
        if phase == "10a":
            return (10, 0.1)
        elif phase == "10b":
            return (10, 0.2)
        elif phase == "10c":
            return (10, 0.3)

        try:
            return (float(phase), 0)
        except ValueError:
            return (999, 0)  # Unknown phases at end


# Global no-op emitter for when tracing is disabled
_NOOP_EMITTER: Optional[TraceEmitter] = None


def get_noop_emitter() -> TraceEmitter:
    """
    Get a shared no-op TraceEmitter instance.

    This can be used as a default when tracing is disabled,
    avoiding the need for None checks throughout the codebase.
    """
    global _NOOP_EMITTER
    if _NOOP_EMITTER is None:
        _NOOP_EMITTER = TraceEmitter(enabled=False)
    return _NOOP_EMITTER
