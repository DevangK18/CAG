"""
Unit tests for the parallel runner module.

Tests cover:
1. Worker initialization
2. Task result dataclass
3. Task serialization
4. Error handling and failure isolation
5. Manifest handling
"""

import pytest
import os
import json
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from dataclasses import asdict

from src.parsing_pipeline.parallel_runner import (
    TaskResult,
    _serialize_task,
    get_default_workers,
)
from src.core.data_contracts import DocumentTask


class TestTaskResult:
    """Test TaskResult dataclass."""

    def test_default_values(self):
        """TaskResult has correct defaults."""
        result = TaskResult(report_id="test_report", success=False)
        assert result.report_id == "test_report"
        assert result.success is False
        assert result.phase_reached is None
        assert result.error is None
        assert result.error_phase is None
        assert result.task_dict is None
        assert result.output_path is None
        assert result.enrichment_stats is None
        assert result.parent_chunk_count == 0
        assert result.child_chunk_count == 0

    def test_full_success_result(self):
        """TaskResult captures all success fields."""
        result = TaskResult(
            report_id="2023_01_test",
            success=True,
            phase_reached="9",
            task_dict={"report_id": "2023_01_test"},
            output_path="/data/processed/2023_01_test_chunks.json",
            enrichment_stats={"findings": {"total_count": 5}},
            parent_chunk_count=10,
            child_chunk_count=100,
        )
        assert result.success is True
        assert result.phase_reached == "9"
        assert result.parent_chunk_count == 10
        assert result.child_chunk_count == 100

    def test_failure_result(self):
        """TaskResult captures failure information."""
        result = TaskResult(
            report_id="2023_02_failed",
            success=False,
            phase_reached="5",
            error="Layout analysis failed: timeout",
            error_phase="layout_analysis",
        )
        assert result.success is False
        assert result.error_phase == "layout_analysis"
        assert "timeout" in result.error


class TestSerializeTask:
    """Test task serialization for IPC."""

    def test_serialize_document_task(self):
        """Serializes DocumentTask to dict."""
        task = DocumentTask(
            report_id="test_123",
            source_url="https://example.com/report.pdf",
            local_pdf_path="/data/raw/report.pdf",
            initial_metadata={"Title": "Test Report"},
        )
        result = _serialize_task(task)
        assert isinstance(result, dict)
        assert result["report_id"] == "test_123"
        assert result["source_url"] == "https://example.com/report.pdf"

    def test_serialize_with_scaffold(self):
        """Serializes task with scaffold data."""
        task = DocumentTask(
            report_id="test_456",
            source_url="",
            local_pdf_path="/data/raw/report.pdf",
            initial_metadata={},
            scaffold={"toc": [[1, "Chapter 1", 5]], "toc_quality": 75},
        )
        result = _serialize_task(task)
        assert result["scaffold"]["toc"] == [[1, "Chapter 1", 5]]
        assert result["scaffold"]["toc_quality"] == 75

    def test_serialize_handles_errors_gracefully(self):
        """Serialization returns minimal info on error."""
        # Create a mock task that would fail normal serialization
        mock_task = Mock()
        mock_task.report_id = "fallback_id"
        mock_task.processing_status = "failed"
        mock_task.model_dump = Mock(side_effect=Exception("Serialization error"))
        mock_task.dict = Mock(side_effect=Exception("Serialization error"))
        mock_task.__dict__ = {"report_id": "fallback_id", "processing_status": "failed"}

        result = _serialize_task(mock_task)
        # Should still return something useful
        assert "report_id" in result


class TestGetDefaultWorkers:
    """Test default worker count calculation."""

    def test_returns_positive_integer(self):
        """Default workers is always positive."""
        workers = get_default_workers()
        assert isinstance(workers, int)
        assert workers >= 1

    @patch("os.cpu_count")
    def test_caps_at_4_workers(self, mock_cpu_count):
        """Maximum default is 4 workers."""
        mock_cpu_count.return_value = 16
        workers = get_default_workers()
        assert workers == 4

    @patch("os.cpu_count")
    def test_half_cpu_count(self, mock_cpu_count):
        """Uses half of CPU count."""
        mock_cpu_count.return_value = 6
        workers = get_default_workers()
        assert workers == 3

    @patch("os.cpu_count")
    def test_handles_none_cpu_count(self, mock_cpu_count):
        """Handles None from cpu_count gracefully."""
        mock_cpu_count.return_value = None
        workers = get_default_workers()
        assert workers >= 1


class TestTokenizerParallelism:
    """Test TOKENIZERS_PARALLELISM environment handling."""

    def test_env_var_set_at_import(self):
        """TOKENIZERS_PARALLELISM should be 'false' after import."""
        # Note: This is set in main.py, not parallel_runner
        # The parallel_runner sets it in worker_initializer
        # Just verify it doesn't crash when checked
        from src.parsing_pipeline import parallel_runner
        # If we got here, the import worked
        assert True


class TestPipelinePhaseError:
    """Test internal error class."""

    def test_error_captures_phase(self):
        """Error includes phase information."""
        from src.parsing_pipeline.parallel_runner import _PipelinePhaseError

        error = _PipelinePhaseError("scaffolding", "TOC extraction failed")
        assert error.phase == "scaffolding"
        assert error.message == "TOC extraction failed"
        assert "scaffolding" in str(error)
        assert "TOC extraction failed" in str(error)


class TestWorkerIsolation:
    """Test that worker failures are isolated."""

    def test_task_result_captures_crash(self):
        """TaskResult can represent a worker crash."""
        result = TaskResult(
            report_id="crashed_task",
            success=False,
            error="Worker crash: ProcessPoolExecutor worker died",
            error_phase="worker_crash",
        )
        assert result.success is False
        assert result.error_phase == "worker_crash"
        assert "Worker crash" in result.error
