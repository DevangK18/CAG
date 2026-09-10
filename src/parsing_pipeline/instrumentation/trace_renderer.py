"""
Trace Renderer for Pipeline Instrumentation.

Converts collected trace events into a structured Markdown report.
"""

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .trace_models import RedFlag, ReportMetadata, TraceEvent


class TraceRenderer:
    """Renders trace events into a Markdown report."""

    def __init__(
        self,
        report_id: str,
        metadata: Optional[ReportMetadata],
        events: List[TraceEvent],
        phase_timings: Dict[str, float],
        phase_statuses: Dict[str, str],
        red_flags: List[RedFlag],
        total_duration: float,
        final_status: str,
        assembly_timestamp: Optional[str] = None,  # P1-16: Add assembly timestamp
    ):
        self.report_id = report_id
        self.metadata = metadata
        self.events = events
        self.phase_timings = phase_timings
        self.phase_statuses = phase_statuses
        self.red_flags = red_flags
        self.total_duration = total_duration
        self.final_status = final_status
        self.assembly_timestamp = assembly_timestamp  # P1-16

    def render_to_file(self, output_dir: Path) -> Path:
        """
        Render the trace to a Markdown file.

        Args:
            output_dir: Base directory for trace files. Files are written to
                        tier-specific subdirectories (union/state/local_body).

        Returns:
            Path to the generated file.
        """
        # Determine tier-specific subdirectory
        tier = self.metadata.tier if self.metadata else "unknown"
        tier_dir = output_dir / tier
        tier_dir.mkdir(parents=True, exist_ok=True)

        # Generate filename with date
        date_str = datetime.now().strftime("%Y%m%d")
        filename = f"{self.report_id}_trace_{date_str}.md"
        output_path = tier_dir / filename

        content = self._render_markdown()

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(content)

        return output_path

    def _render_markdown(self) -> str:
        """Generate the full Markdown content."""
        sections = [
            self._render_header(),
            self._render_red_flags(),
            self._render_pass_fail_summary(),
        ]

        # Group events by phase
        phases = self._get_ordered_phases()
        for phase in phases:
            sections.append(self._render_phase(phase))

        return "\n".join(sections)

    def _render_header(self) -> str:
        """Render the report header."""
        tier = self.metadata.tier if self.metadata else "unknown"
        pages = self.metadata.page_count if self.metadata else 0
        duration_str = self._format_duration(self.total_duration)
        # P1-16: Use UTC for generated timestamp
        generated_utc = datetime.utcnow().isoformat() + "Z"

        header = f"""# Pipeline Trace: {self.report_id}

**Generated (UTC)**: {generated_utc}
**Assembly Timestamp (UTC)**: {self.assembly_timestamp or "N/A"}
**Tier**: {tier} | **Pages**: {pages} | **Total Duration**: {duration_str}
**Final Status**: {self.final_status}
"""

        # P1-16: Provenance warning if timestamps diverge significantly
        if self.assembly_timestamp:
            try:
                assembly_dt = datetime.fromisoformat(self.assembly_timestamp.rstrip("Z"))
                generated_dt = datetime.utcnow()
                hours_diff = abs((generated_dt - assembly_dt).total_seconds()) / 3600
                if hours_diff > 24:
                    header += f"\n**WARNING**: Trace generated {hours_diff:.1f}h after assembly — JSON may be stale\n"
            except ValueError:
                pass  # Invalid timestamp format

        if self.metadata:
            header += f"""
**Source PDF**: `{self.metadata.source_pdf_path}`
**File Size**: {self.metadata.file_size_mb():.2f} MB
"""
            if self.metadata.state_name:
                header += f"**State**: {self.metadata.state_name}\n"

        return header

    def _render_red_flags(self) -> str:
        """Render the Red Flags section."""
        if not self.red_flags:
            return """
---

## Red Flags

_No anomalies detected._
"""

        lines = [
            "",
            "---",
            "",
            "## Red Flags",
            "",
            "| Phase | Flag | Details |",
            "|-------|------|---------|",
        ]

        for flag in self.red_flags:
            details_str = self._format_details(flag.details)
            lines.append(f"| {flag.phase} | {flag.flag} | {details_str} |")

        return "\n".join(lines)

    def _render_pass_fail_summary(self) -> str:
        """Render the Pass/Fail Summary table."""
        lines = [
            "",
            "---",
            "",
            "## Pass/Fail Summary",
            "",
            "| Phase | Status | Duration |",
            "|-------|--------|----------|",
        ]

        phases = self._get_ordered_phases()
        for phase in phases:
            status = self.phase_statuses.get(phase, "success")
            duration = self.phase_timings.get(phase, 0)
            status_icon = self._status_icon(status)
            duration_str = self._format_duration(duration)
            lines.append(f"| {phase} | {status_icon} {status} | {duration_str} |")

        return "\n".join(lines)

    def _render_phase(self, phase: str) -> str:
        """Render a single phase section."""
        phase_events = [e for e in self.events if e.phase == phase]
        status = self.phase_statuses.get(phase, "success")
        duration = self.phase_timings.get(phase, 0)

        # Get phase name
        phase_name = self._get_phase_name(phase)

        lines = [
            "",
            "---",
            "",
            f"## Phase {phase}: {phase_name}",
            "",
        ]

        # Extract I/O events
        io_events = [e for e in phase_events if e.event == "io"]
        if io_events:
            lines.extend(self._render_io_section(io_events))

        # Extract decision events
        decision_events = [e for e in phase_events if e.event == "decision"]
        if decision_events:
            lines.extend(self._render_decisions_section(decision_events))

        # Extract fallback events
        fallback_events = [e for e in phase_events if e.event == "fallback"]
        if fallback_events:
            lines.extend(self._render_fallbacks_section(fallback_events))

        # Extract sample events
        sample_events = [e for e in phase_events if e.event == "sample"]
        if sample_events:
            lines.extend(self._render_samples_section(sample_events))

        # Extract error events
        error_events = [e for e in phase_events if e.event == "error"]
        if error_events:
            lines.extend(self._render_errors_section(error_events))

        # Extract red flag events (already in summary, but show context)
        red_flag_events = [e for e in phase_events if e.event == "red_flag"]
        if red_flag_events:
            lines.extend(self._render_red_flag_details(red_flag_events))

        # Extract generic events
        generic_events = [
            e
            for e in phase_events
            if e.event not in ("io", "decision", "fallback", "sample", "error", "red_flag")
        ]
        if generic_events:
            lines.extend(self._render_generic_events(generic_events))

        # Duration
        lines.extend(
            [
                "",
                "### Duration",
                "",
                f"{self._format_duration(duration)}",
            ]
        )

        return "\n".join(lines)

    def _render_io_section(self, events: List[TraceEvent]) -> List[str]:
        """Render Input/Output section."""
        lines = ["### Input", ""]

        for event in events:
            input_data = event.data.get("input", {})
            for key, value in input_data.items():
                lines.append(f"- **{key}**: {self._format_value(value)}")

        lines.extend(["", "### Output", ""])

        for event in events:
            output_data = event.data.get("output", {})
            for key, value in output_data.items():
                lines.append(f"- **{key}**: {self._format_value(value)}")

        return lines

    def _render_decisions_section(self, events: List[TraceEvent]) -> List[str]:
        """Render Mechanism & Decisions section."""
        lines = ["", "### Mechanism & Decisions", ""]

        for event in events:
            data = event.data
            decision = data.get("decision", "unknown")
            chosen = data.get("chosen", "unknown")
            reason = data.get("reason", "")
            alternatives = data.get("alternatives", [])

            lines.append(f"- **{decision}**: `{chosen}`")
            if reason:
                lines.append(f"  - Reason: {reason}")
            if alternatives:
                lines.append(f"  - Alternatives: {', '.join(alternatives)}")

        return lines

    def _render_fallbacks_section(self, events: List[TraceEvent]) -> List[str]:
        """Render Fallbacks section."""
        lines = ["", "### Fallbacks Fired", ""]

        for event in events:
            data = event.data
            primary = data.get("primary", "unknown")
            fell_back_to = data.get("fell_back_to", "unknown")
            trigger = data.get("trigger", "unknown")

            lines.append(f"- **{primary}** → **{fell_back_to}**")
            lines.append(f"  - Trigger: {trigger}")

        return lines

    def _render_samples_section(self, events: List[TraceEvent]) -> List[str]:
        """Render Samples section."""
        lines = ["", "### Samples", ""]

        for event in events:
            category = event.data.get("category", "unknown")
            examples = event.data.get("examples", [])

            lines.append(f"**{category}** ({len(examples)} samples):")
            lines.append("")

            if examples and isinstance(examples[0], dict):
                # Table format
                if examples:
                    headers = list(examples[0].keys())
                    lines.append("| " + " | ".join(headers) + " |")
                    lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
                    for ex in examples:
                        row = [str(ex.get(h, ""))[:50] for h in headers]
                        lines.append("| " + " | ".join(row) + " |")
            else:
                # List format
                for ex in examples:
                    lines.append(f"- {ex}")

            lines.append("")

        return lines

    def _render_errors_section(self, events: List[TraceEvent]) -> List[str]:
        """Render Errors section."""
        lines = ["", "### Errors", ""]

        for event in events:
            error = event.data.get("error", "unknown error")
            details = {k: v for k, v in event.data.items() if k != "error"}

            lines.append(f"- **Error**: {error}")
            if details:
                for key, value in details.items():
                    lines.append(f"  - {key}: {value}")

        return lines

    def _render_red_flag_details(self, events: List[TraceEvent]) -> List[str]:
        """Render Red Flag details inline."""
        lines = ["", "### Anomalies Detected", ""]

        for event in events:
            flag = event.data.get("flag", "unknown")
            details = {k: v for k, v in event.data.items() if k != "flag"}

            lines.append(f"- **{flag}**")
            for key, value in details.items():
                lines.append(f"  - {key}: {value}")

        return lines

    def _render_generic_events(self, events: List[TraceEvent]) -> List[str]:
        """Render generic events not covered by other sections."""
        lines = ["", "### Other Events", ""]

        for event in events:
            lines.append(f"- **{event.event}**: {self._format_details(event.data)}")

        return lines

    def _get_ordered_phases(self) -> List[str]:
        """Get phases in execution order."""
        # Collect all phases from events and timings
        phases = set(self.phase_timings.keys())
        for event in self.events:
            phases.add(event.phase)

        # Sort by phase number
        return sorted(phases, key=self._phase_sort_key)

    @staticmethod
    def _phase_sort_key(phase: str) -> tuple:
        """Sort key for phase identifiers."""
        if phase == "10a":
            return (10, 0.1)
        elif phase == "10b":
            return (10, 0.2)
        elif phase == "10c":
            return (10, 0.3)
        elif phase == "7.5":
            return (7, 0.5)

        try:
            return (float(phase), 0)
        except ValueError:
            return (999, 0)

    @staticmethod
    def _get_phase_name(phase: str) -> str:
        """Get human-readable phase name."""
        names = {
            "1": "Manifest Ingestion",
            "2": "Document Triage",
            "3": "OCR Processing",
            "4": "Document Scaffolding",
            "5": "Layout Analysis",
            "5.5": "TOC Reconciliation",
            "5.7": "LLM TOC Validation",
            "6": "Content Extraction",
            "7": "Hierarchical Chunking",
            "7.5": "Hierarchy Enrichment",
            "8": "Document Assembly",
            "9": "Semantic Enrichment",
            "10a": "Overview & Summary Generation",
            "10b": "Visual Extraction (Gemini)",
            "10c": "Visual Post-Processing",
        }
        return names.get(phase, "Unknown")

    @staticmethod
    def _status_icon(status: str) -> str:
        """Get status icon."""
        icons = {
            "success": "\u2713",  # checkmark
            "partial": "\u26A0",  # warning
            "failed": "\u2717",  # X
            "skipped": "\u2014",  # em dash
        }
        return icons.get(status, "?")

    @staticmethod
    def _format_duration(seconds: float) -> str:
        """Format duration for display."""
        if seconds < 60:
            return f"{seconds:.1f}s"
        elif seconds < 3600:
            minutes = int(seconds // 60)
            secs = seconds % 60
            return f"{minutes}m {secs:.0f}s"
        else:
            hours = int(seconds // 3600)
            minutes = int((seconds % 3600) // 60)
            return f"{hours}h {minutes}m"

    @staticmethod
    def _format_value(value: Any) -> str:
        """Format a value for display."""
        if isinstance(value, (list, tuple)):
            if len(value) > 5:
                return f"[{len(value)} items]"
            return str(value)
        elif isinstance(value, dict):
            if len(value) > 5:
                return f"{{{len(value)} keys}}"
            return str(value)
        elif isinstance(value, float):
            return f"{value:.2f}"
        return str(value)

    @staticmethod
    def _format_details(details: Dict[str, Any]) -> str:
        """Format details dict for inline display."""
        if not details:
            return ""
        parts = []
        for key, value in details.items():
            if isinstance(value, float):
                parts.append(f"{key}={value:.2f}")
            elif isinstance(value, (list, tuple)) and len(value) > 3:
                parts.append(f"{key}=[{len(value)} items]")
            else:
                val_str = str(value)
                if len(val_str) > 50:
                    val_str = val_str[:47] + "..."
                parts.append(f"{key}={val_str}")
        return ", ".join(parts)
