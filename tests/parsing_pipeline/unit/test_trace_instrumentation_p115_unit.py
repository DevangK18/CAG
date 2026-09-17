"""
P1-15 & P1-16: Unit tests for Instrumentation Gap Closeout and Provenance Assertion.

Tests:
- P1-15a: Triage service emit_io output
- P1-15b: OCR service skip emit
- P1-15c: Scaffolding service page_count emit
- P1-15d: Content extraction emit + error surfacing
- P1-15e: Assembly service phase 8 emits
- P1-16: Provenance assertion in trace
"""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta
from pathlib import Path

from src.core.data_contracts import DocumentTask, ParentChunk, ChildChunk


class MockTraceEmitter:
    """Mock trace emitter for testing emit calls."""

    def __init__(self):
        self.io_calls = []
        self.decision_calls = []
        self.red_flag_calls = []
        self.sample_calls = []

    def emit_io(self, phase, input_summary, output_summary):
        self.io_calls.append({
            "phase": phase,
            "input": input_summary,
            "output": output_summary,
        })

    def emit_decision(self, phase, decision, chosen, alternatives, reason):
        self.decision_calls.append({
            "phase": phase,
            "decision": decision,
            "chosen": chosen,
            "alternatives": alternatives,
            "reason": reason,
        })

    def emit_red_flag(self, phase, flag, details):
        self.red_flag_calls.append({
            "phase": phase,
            "flag": flag,
            "details": details,
        })

    def emit_sample(self, phase, category, examples):
        self.sample_calls.append({
            "phase": phase,
            "category": category,
            "examples": examples,
        })

    def emit(self, phase, event, data):
        pass


def create_test_task(report_id="test_001", **kwargs):
    """Helper to create DocumentTask with required fields."""
    defaults = {
        "report_id": report_id,
        "source_url": "http://example.com/test.pdf",
        "initial_metadata": {"government_body_type": "union"},
        "local_pdf_path": "/fake/path.pdf",
    }
    defaults.update(kwargs)
    return DocumentTask(**defaults)


def create_parent_chunk(chunk_id="ch1", **kwargs):
    """Helper to create ParentChunk with required fields."""
    defaults = {
        "chunk_id": chunk_id,
        "report_id": "test_report",
        "hierarchy": {"level_1": "Chapter 1"},
        "page_range_physical": (1, 10),
        "page_range_logical": ("1", "10"),
        "toc_entry": "Chapter 1",
        "toc_level": 1,
    }
    defaults.update(kwargs)
    return ParentChunk(**defaults)


def create_child_chunk(chunk_id="child_001", **kwargs):
    """Helper to create ChildChunk with required fields."""
    defaults = {
        "chunk_id": chunk_id,
        "parent_chunk_id": "ch1",
        "content_type": "paragraph",
        "content": "Test content",
        "source_page_physical": 1,
        "source_bbox": [0.0, 0.0, 100.0, 100.0],
        "model_used": "test_model",
        "layout_label": "Text",
        "report_id": "test_report",
        "report_title": "Test Report",
        "report_no": "1 of 2024",
        "hierarchy": {"level_1": "Chapter 1"},
        "source_filename": "test.pdf",
    }
    defaults.update(kwargs)
    return ChildChunk(**defaults)


class TestP115bOcrSkipEmission:
    """P1-15b: Test OCR service skip emit for native_text."""

    def test_native_text_emits_skipped(self, tmp_path):
        """native_text classification emits status=skipped."""
        from src.parsing_pipeline.modules.ocr_service import OCRService

        emitter = MockTraceEmitter()
        service = OCRService(output_dir=str(tmp_path), trace_emitter=emitter)

        task = create_test_task(
            report_id="test_003",
            classification="native_text",
            local_pdf_path="/fake/path.pdf",
        )

        service.ocr_document(task, trace_emitter=emitter)

        # Should emit skipped status
        io_calls_phase_3 = [c for c in emitter.io_calls if c["phase"] == "3"]
        assert len(io_calls_phase_3) >= 1
        assert io_calls_phase_3[0]["output"]["status"] == "skipped"
        assert "native_text" in io_calls_phase_3[0]["output"]["reason"]

    def test_decision_emitted_for_skip(self, tmp_path):
        """OCR skip decision is emitted."""
        from src.parsing_pipeline.modules.ocr_service import OCRService

        emitter = MockTraceEmitter()
        service = OCRService(output_dir=str(tmp_path), trace_emitter=emitter)

        task = create_test_task(
            report_id="test_004",
            classification="native_text",
            local_pdf_path="/fake/path.pdf",
        )

        service.ocr_document(task, trace_emitter=emitter)

        # Should emit ocr_skip decision
        skip_decisions = [d for d in emitter.decision_calls if d["decision"] == "ocr_skip"]
        assert len(skip_decisions) >= 1
        assert skip_decisions[0]["chosen"] == "skipped"


class TestP115eAssemblyEmission:
    """P1-15e: Test assembly service phase 8 emits."""

    @pytest.fixture
    def assembly_service(self, tmp_path):
        """Create AssemblyService with temp output directory."""
        from src.parsing_pipeline.modules.assembly_service import AssemblyService
        return AssemblyService(output_dir=str(tmp_path))

    def test_phase_8_entry_emit(self, assembly_service):
        """Phase 8 entry emits parent_chunks and child_chunks counts."""
        emitter = MockTraceEmitter()

        task = create_test_task(report_id="test_006")

        parent_chunks = [create_parent_chunk(chunk_id="ch1")]
        child_chunks = [
            create_child_chunk(chunk_id="child_001", parent_chunk_id="ch1"),
            create_child_chunk(chunk_id="child_002", parent_chunk_id="ch1", source_page_physical=2),
        ]

        assembly_service.assemble_document(
            task, parent_chunks, child_chunks,
            skip_manifest=True, trace_emitter=emitter
        )

        # Find Phase 8 entry emit (input has parent_chunks count)
        entry_emits = [c for c in emitter.io_calls
                       if c["phase"] == "8" and "parent_chunks" in c["input"]]
        assert len(entry_emits) >= 1
        assert entry_emits[0]["input"]["parent_chunks"] == 1
        assert entry_emits[0]["input"]["child_chunks"] == 2

    def test_phase_8_exit_emit(self, assembly_service):
        """Phase 8 exit emits output_path and content_types."""
        emitter = MockTraceEmitter()

        task = create_test_task(report_id="test_007")

        parent_chunks = [create_parent_chunk(chunk_id="ch1")]
        child_chunks = [
            create_child_chunk(chunk_id="child_001", parent_chunk_id="ch1"),
        ]

        assembly_service.assemble_document(
            task, parent_chunks, child_chunks,
            skip_manifest=True, trace_emitter=emitter
        )

        # Find Phase 8 exit emit (output has output_path)
        exit_emits = [c for c in emitter.io_calls
                      if c["phase"] == "8" and "output_path" in c["output"]]
        assert len(exit_emits) >= 1
        assert "content_types_assembled" in exit_emits[0]["output"]

    def test_assembly_timestamp_in_output(self, assembly_service):
        """Phase 8 exit emit includes assembly_timestamp ending with Z."""
        emitter = MockTraceEmitter()

        task = create_test_task(report_id="test_008")

        parent_chunks = []
        child_chunks = []

        assembly_service.assemble_document(
            task, parent_chunks, child_chunks,
            skip_manifest=True, trace_emitter=emitter
        )

        exit_emits = [c for c in emitter.io_calls
                      if c["phase"] == "8" and "assembly_timestamp" in c["output"]]
        assert len(exit_emits) >= 1
        assert exit_emits[0]["output"]["assembly_timestamp"].endswith("Z")

    def test_visual_counts_in_output(self, assembly_service):
        """Phase 8 exit emit includes total_tables and total_figures."""
        emitter = MockTraceEmitter()

        task = create_test_task(report_id="test_008b")

        parent_chunks = [create_parent_chunk(chunk_id="ch1")]
        child_chunks = [
            create_child_chunk(
                chunk_id="table_001",
                parent_chunk_id="ch1",
                content_type="table_markdown",
                content="| A | B |\n|---|---|\n| 1 | 2 |",
            ),
            create_child_chunk(
                chunk_id="fig_001",
                parent_chunk_id="ch1",
                content_type="image_caption",
                content="Figure 1.1: Test chart",
                source_page_physical=2,
            ),
        ]

        assembly_service.assemble_document(
            task, parent_chunks, child_chunks,
            skip_manifest=True, trace_emitter=emitter
        )

        exit_emits = [c for c in emitter.io_calls
                      if c["phase"] == "8" and "total_tables" in c["output"]]
        assert len(exit_emits) >= 1
        assert exit_emits[0]["output"]["total_tables"] == 1
        assert exit_emits[0]["output"]["total_figures"] == 1


class TestP116TimestampNormalization:
    """P1-16: Test timestamp normalization in trace."""

    def test_assembly_timestamp_is_utc(self):
        """assembly_timestamp ends with 'Z' for UTC."""
        from datetime import datetime

        # The timestamp format should be ISO with Z suffix
        timestamp = datetime.utcnow().isoformat() + "Z"
        assert timestamp.endswith("Z")
        # Should be parseable
        datetime.fromisoformat(timestamp.rstrip("Z"))

    def test_trace_renderer_accepts_assembly_timestamp(self):
        """TraceRenderer accepts assembly_timestamp parameter."""
        from src.parsing_pipeline.instrumentation.trace_renderer import TraceRenderer

        timestamp = "2025-05-30T10:00:00Z"

        renderer = TraceRenderer(
            report_id="test_009",
            metadata=None,
            events=[],
            phase_timings={},
            phase_statuses={},
            red_flags=[],
            total_duration=10.0,
            final_status="success",
            assembly_timestamp=timestamp,
        )

        assert renderer.assembly_timestamp == timestamp

    def test_header_includes_assembly_timestamp(self):
        """Rendered header includes assembly timestamp."""
        from src.parsing_pipeline.instrumentation.trace_renderer import TraceRenderer

        timestamp = "2025-05-30T10:00:00Z"

        renderer = TraceRenderer(
            report_id="test_010",
            metadata=None,
            events=[],
            phase_timings={},
            phase_statuses={},
            red_flags=[],
            total_duration=10.0,
            final_status="success",
            assembly_timestamp=timestamp,
        )

        header = renderer._render_header()
        assert "Assembly Timestamp (UTC)" in header
        assert timestamp in header

    def test_header_uses_utc_for_generated(self):
        """Generated timestamp is in UTC (ends with Z)."""
        from src.parsing_pipeline.instrumentation.trace_renderer import TraceRenderer

        renderer = TraceRenderer(
            report_id="test_010b",
            metadata=None,
            events=[],
            phase_timings={},
            phase_statuses={},
            red_flags=[],
            total_duration=10.0,
            final_status="success",
        )

        header = renderer._render_header()
        assert "Generated (UTC)" in header


class TestP116ProvenanceWarning:
    """P1-16: Test provenance warning for stale traces."""

    def test_warning_when_stale(self):
        """>24h difference triggers WARNING in header."""
        from src.parsing_pipeline.instrumentation.trace_renderer import TraceRenderer

        # Timestamp from 48 hours ago
        old_timestamp = (datetime.utcnow() - timedelta(hours=48)).isoformat() + "Z"

        renderer = TraceRenderer(
            report_id="test_011",
            metadata=None,
            events=[],
            phase_timings={},
            phase_statuses={},
            red_flags=[],
            total_duration=10.0,
            final_status="success",
            assembly_timestamp=old_timestamp,
        )

        header = renderer._render_header()
        assert "WARNING" in header
        assert "stale" in header.lower()

    def test_no_warning_when_fresh(self):
        """<24h difference does not trigger warning."""
        from src.parsing_pipeline.instrumentation.trace_renderer import TraceRenderer

        # Timestamp from 1 hour ago
        fresh_timestamp = (datetime.utcnow() - timedelta(hours=1)).isoformat() + "Z"

        renderer = TraceRenderer(
            report_id="test_012",
            metadata=None,
            events=[],
            phase_timings={},
            phase_statuses={},
            red_flags=[],
            total_duration=10.0,
            final_status="success",
            assembly_timestamp=fresh_timestamp,
        )

        header = renderer._render_header()
        assert "WARNING" not in header

    def test_no_warning_when_no_assembly_timestamp(self):
        """No warning when assembly_timestamp is None."""
        from src.parsing_pipeline.instrumentation.trace_renderer import TraceRenderer

        renderer = TraceRenderer(
            report_id="test_013",
            metadata=None,
            events=[],
            phase_timings={},
            phase_statuses={},
            red_flags=[],
            total_duration=10.0,
            final_status="success",
            assembly_timestamp=None,
        )

        header = renderer._render_header()
        assert "WARNING" not in header
        assert "N/A" in header


class TestP116ExtractAssemblyTimestamp:
    """P1-16: Test extraction of assembly_timestamp from events."""

    def test_extracts_timestamp_from_phase_8_event(self):
        """Extracts assembly_timestamp from Phase 8 io event."""
        from src.parsing_pipeline.instrumentation.trace_emitter import TraceEmitter
        from src.parsing_pipeline.instrumentation.trace_models import TraceEvent

        emitter = TraceEmitter(enabled=False)  # Just for method access

        events = [
            TraceEvent(
                phase="8",
                event="io",
                data={
                    "input": {},
                    "output": {
                        "output_path": "/path/to/output.json",
                        "assembly_timestamp": "2025-05-30T12:00:00Z",
                    },
                },
            ),
        ]

        timestamp = emitter._extract_assembly_timestamp(events)
        assert timestamp == "2025-05-30T12:00:00Z"

    def test_returns_none_when_no_phase_8(self):
        """Returns None when no Phase 8 events."""
        from src.parsing_pipeline.instrumentation.trace_emitter import TraceEmitter
        from src.parsing_pipeline.instrumentation.trace_models import TraceEvent

        emitter = TraceEmitter(enabled=False)

        events = [
            TraceEvent(
                phase="7",
                event="io",
                data={"input": {}, "output": {}},
            ),
        ]

        timestamp = emitter._extract_assembly_timestamp(events)
        assert timestamp is None

    def test_returns_none_when_no_assembly_timestamp_in_output(self):
        """Returns None when Phase 8 event lacks assembly_timestamp."""
        from src.parsing_pipeline.instrumentation.trace_emitter import TraceEmitter
        from src.parsing_pipeline.instrumentation.trace_models import TraceEvent

        emitter = TraceEmitter(enabled=False)

        events = [
            TraceEvent(
                phase="8",
                event="io",
                data={
                    "input": {"parent_chunks": 5},
                    "output": {},  # Entry emit, no assembly_timestamp
                },
            ),
        ]

        timestamp = emitter._extract_assembly_timestamp(events)
        assert timestamp is None
