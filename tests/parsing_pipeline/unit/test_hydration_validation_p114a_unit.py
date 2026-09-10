"""
P1-14a: Unit tests for Hydration Validation.

Tests:
- Detection of unhydrated image_caption chunks (still contain file paths)
- Passing validation when all chunks are hydrated
- Red flag emission for incomplete hydration
"""

import pytest
import json
from pathlib import Path
from unittest.mock import MagicMock, patch


class MockTraceEmitter:
    """Mock trace emitter for testing."""

    def __init__(self):
        self.red_flags = []

    def emit_red_flag(self, phase, flag, details):
        self.red_flags.append({
            "phase": phase,
            "flag": flag,
            "details": details,
        })


class MockPipelineState:
    """Mock pipeline state."""

    def __init__(self):
        self.trace_emitter = MockTraceEmitter()


class MockOrchestrator:
    """Minimal mock of PipelineOrchestrator for testing validation method."""

    def __init__(self):
        self.state = MockPipelineState()
        self.quiet = False
        self.logs = []

    def _log(self, msg, force=False):
        self.logs.append(msg)

    def _validate_phase_10b_completion(self, chunk_files):
        """
        P1-14a: Verify Phase 10b hydration completed successfully.
        (Copied from main.py for isolated testing)
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
                f"P1-14a: {incomplete_total} image_caption chunks still have file paths (not hydrated)",
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

        self._log(f"  P1-14a: All image_caption chunks hydrated successfully")
        return True


@pytest.fixture
def orchestrator():
    """Create mock orchestrator."""
    return MockOrchestrator()


@pytest.fixture
def temp_chunk_dir(tmp_path):
    """Create temporary directory for chunk files."""
    return tmp_path


class TestHydrationValidation:
    """P1-14a: Test hydration validation."""

    def test_detects_unhydrated_image_captions(self, orchestrator, temp_chunk_dir):
        """File paths in content -> validation fails."""
        # Create a chunk file with unhydrated image captions
        chunk_file = temp_chunk_dir / "test_report_chunks.json"
        chunk_data = {
            "child_chunks": [
                {
                    "chunk_id": "chunk_001",
                    "content_type": "image_caption",
                    "content": "data/extraction_images/page_5_figure_1.png",  # Not hydrated
                },
                {
                    "chunk_id": "chunk_002",
                    "content_type": "paragraph",
                    "content": "This is a normal paragraph.",
                },
                {
                    "chunk_id": "chunk_003",
                    "content_type": "image_caption",
                    "content": "data/extraction_images/page_10_chart_2.png",  # Not hydrated
                },
            ]
        }
        with open(chunk_file, "w") as f:
            json.dump(chunk_data, f)

        result = orchestrator._validate_phase_10b_completion([chunk_file])

        assert result is False
        assert len(orchestrator.state.trace_emitter.red_flags) == 1
        assert orchestrator.state.trace_emitter.red_flags[0]["flag"] == "image_captions_not_hydrated"
        assert orchestrator.state.trace_emitter.red_flags[0]["details"]["count"] == 2

    def test_passes_when_hydrated(self, orchestrator, temp_chunk_dir):
        """Gemini descriptions in content -> validation passes."""
        # Create a chunk file with hydrated image captions
        chunk_file = temp_chunk_dir / "test_report_chunks.json"
        chunk_data = {
            "child_chunks": [
                {
                    "chunk_id": "chunk_001",
                    "content_type": "image_caption",
                    "content": "This chart shows the trend of GST collections from 2020-2024.",
                },
                {
                    "chunk_id": "chunk_002",
                    "content_type": "paragraph",
                    "content": "This is a normal paragraph.",
                },
                {
                    "chunk_id": "chunk_003",
                    "content_type": "image_caption",
                    "content": "A bar graph depicting district-wise allocation of funds.",
                },
            ]
        }
        with open(chunk_file, "w") as f:
            json.dump(chunk_data, f)

        result = orchestrator._validate_phase_10b_completion([chunk_file])

        assert result is True
        assert len(orchestrator.state.trace_emitter.red_flags) == 0

    def test_handles_mixed_content(self, orchestrator, temp_chunk_dir):
        """Mix of hydrated and unhydrated -> validation fails."""
        chunk_file = temp_chunk_dir / "test_report_chunks.json"
        chunk_data = {
            "child_chunks": [
                {
                    "chunk_id": "chunk_001",
                    "content_type": "image_caption",
                    "content": "This is a properly hydrated description.",  # Hydrated
                },
                {
                    "chunk_id": "chunk_002",
                    "content_type": "image_caption",
                    "content": "data/extraction_images/missing_description.png",  # Not hydrated
                },
            ]
        }
        with open(chunk_file, "w") as f:
            json.dump(chunk_data, f)

        result = orchestrator._validate_phase_10b_completion([chunk_file])

        assert result is False
        assert orchestrator.state.trace_emitter.red_flags[0]["details"]["count"] == 1

    def test_handles_no_image_captions(self, orchestrator, temp_chunk_dir):
        """No image_caption chunks -> validation passes."""
        chunk_file = temp_chunk_dir / "test_report_chunks.json"
        chunk_data = {
            "child_chunks": [
                {
                    "chunk_id": "chunk_001",
                    "content_type": "paragraph",
                    "content": "Just text content.",
                },
                {
                    "chunk_id": "chunk_002",
                    "content_type": "table_markdown",
                    "content": "| A | B |\n|---|---|\n| 1 | 2 |",
                },
            ]
        }
        with open(chunk_file, "w") as f:
            json.dump(chunk_data, f)

        result = orchestrator._validate_phase_10b_completion([chunk_file])

        assert result is True

    def test_multiple_chunk_files(self, orchestrator, temp_chunk_dir):
        """Multiple files with some unhydrated -> fails with total count."""
        chunk_file1 = temp_chunk_dir / "report1_chunks.json"
        chunk_file2 = temp_chunk_dir / "report2_chunks.json"

        chunk_data1 = {
            "child_chunks": [
                {
                    "chunk_id": "r1_chunk_001",
                    "content_type": "image_caption",
                    "content": "data/extraction_images/r1_image.png",  # Not hydrated
                },
            ]
        }
        chunk_data2 = {
            "child_chunks": [
                {
                    "chunk_id": "r2_chunk_001",
                    "content_type": "image_caption",
                    "content": "data/extraction_images/r2_image.png",  # Not hydrated
                },
                {
                    "chunk_id": "r2_chunk_002",
                    "content_type": "image_caption",
                    "content": "This one is hydrated.",  # Hydrated
                },
            ]
        }

        with open(chunk_file1, "w") as f:
            json.dump(chunk_data1, f)
        with open(chunk_file2, "w") as f:
            json.dump(chunk_data2, f)

        result = orchestrator._validate_phase_10b_completion([chunk_file1, chunk_file2])

        assert result is False
        assert orchestrator.state.trace_emitter.red_flags[0]["details"]["count"] == 2

    def test_handles_empty_child_chunks(self, orchestrator, temp_chunk_dir):
        """Empty child_chunks array -> validation passes."""
        chunk_file = temp_chunk_dir / "empty_chunks.json"
        chunk_data = {"child_chunks": []}
        with open(chunk_file, "w") as f:
            json.dump(chunk_data, f)

        result = orchestrator._validate_phase_10b_completion([chunk_file])

        assert result is True

    def test_handles_absolute_path(self, orchestrator, temp_chunk_dir):
        """Absolute paths also detected as unhydrated."""
        chunk_file = temp_chunk_dir / "test_chunks.json"
        chunk_data = {
            "child_chunks": [
                {
                    "chunk_id": "chunk_001",
                    "content_type": "image_caption",
                    "content": "/Users/dev/Projects/CAG/data/extraction_images/image.png",
                },
            ]
        }
        with open(chunk_file, "w") as f:
            json.dump(chunk_data, f)

        result = orchestrator._validate_phase_10b_completion([chunk_file])

        assert result is False


class TestRedFlagEmission:
    """P1-14a: Test red flag emission details."""

    def test_red_flag_includes_sample_chunks(self, orchestrator, temp_chunk_dir):
        """Red flag includes sample of unhydrated chunk IDs."""
        chunk_file = temp_chunk_dir / "test_chunks.json"
        chunk_data = {
            "child_chunks": [
                {"chunk_id": f"chunk_{i:03d}", "content_type": "image_caption", "content": f"data/extraction_images/img{i}.png"}
                for i in range(5)
            ]
        }
        with open(chunk_file, "w") as f:
            json.dump(chunk_data, f)

        orchestrator._validate_phase_10b_completion([chunk_file])

        red_flag = orchestrator.state.trace_emitter.red_flags[0]
        assert red_flag["details"]["count"] == 5
        # Should only include first 3 as sample
        assert len(red_flag["details"]["sample"]) == 3
        assert red_flag["details"]["sample"][0] == "chunk_000"

    def test_red_flag_phase_is_10b(self, orchestrator, temp_chunk_dir):
        """Red flag correctly attributes to phase 10b."""
        chunk_file = temp_chunk_dir / "test_chunks.json"
        chunk_data = {
            "child_chunks": [
                {"chunk_id": "chunk_001", "content_type": "image_caption", "content": "data/extraction_images/img.png"}
            ]
        }
        with open(chunk_file, "w") as f:
            json.dump(chunk_data, f)

        orchestrator._validate_phase_10b_completion([chunk_file])

        red_flag = orchestrator.state.trace_emitter.red_flags[0]
        assert red_flag["phase"] == "10b"
        assert red_flag["flag"] == "image_captions_not_hydrated"
