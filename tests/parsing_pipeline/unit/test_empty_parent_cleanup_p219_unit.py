"""
P2-19: Unit tests for empty-parent cleanup.

Tests for removal of assembly artifact parents with 0 children,
while PRESERVING legitimate parents like "1.1 Introduction".

CRITICAL: Safety tests verify no legitimate parents are deleted.
"""

import pytest
from unittest.mock import Mock
from src.parsing_pipeline.modules.assembly_service import AssemblyService
from src.core.data_contracts import ParentChunk, ChildChunk


@pytest.fixture
def assembly_service(tmp_path):
    """Create an AssemblyService with temp output directory."""
    return AssemblyService(output_dir=str(tmp_path))


def make_parent(chunk_id: str, toc_entry: str) -> ParentChunk:
    """Helper to create a ParentChunk."""
    return ParentChunk(
        chunk_id=chunk_id,
        report_id="test_report",
        toc_entry=toc_entry,
        toc_level=1,
        hierarchy={"L1": toc_entry},
        page_range_physical=(1, 10),
        page_range_logical=("1", "10"),
    )


def make_child(chunk_id: str, parent_id: str) -> ChildChunk:
    """Helper to create a ChildChunk."""
    return ChildChunk(
        chunk_id=chunk_id,
        parent_chunk_id=parent_id,
        report_id="test_report",
        report_title="Test Report",
        report_no="1 of 2023",
        content_type="paragraph",
        content="Test content",
        source_page_physical=1,
        source_bbox=[0.0, 0.0, 100.0, 100.0],
        source_filename="test.pdf",
        model_used="test",
        layout_label="Text",
        hierarchy={"L1": "Test"},
    )


class TestEmptyParentCleanupP219:
    """P2-19: Test empty-parent cleanup with artifact patterns."""

    def test_blank_page_parent_removed(self, assembly_service):
        """P2-19: Parent 'Blank Page' with 0 children should be removed."""
        parents = [
            make_parent("p1", "Chapter 1"),
            make_parent("p2", "Blank Page"),
        ]
        children = [make_child("c1", "p1")]  # Only Chapter 1 has children

        result = assembly_service._cleanup_empty_parents(parents, children)

        assert len(result) == 1
        assert result[0].toc_entry == "Chapter 1"

    def test_file_merger_label_removed(self, assembly_service):
        """P2-19: Parent '15_Separator' with 0 children should be removed."""
        parents = [
            make_parent("p1", "Executive Summary"),
            make_parent("p2", "15_Separator"),
            make_parent("p3", "01_Cover"),
        ]
        children = [make_child("c1", "p1")]

        result = assembly_service._cleanup_empty_parents(parents, children)

        assert len(result) == 1
        assert result[0].toc_entry == "Executive Summary"

    def test_state_code_prefix_removed(self, assembly_service):
        """P2-19: Parent 'WBOCW_123' with 0 children should be removed."""
        parents = [
            make_parent("p1", "Chapter 2"),
            make_parent("p2", "WBOCW_123"),
            make_parent("p3", "MH_456"),
        ]
        children = [make_child("c1", "p1")]

        result = assembly_service._cleanup_empty_parents(parents, children)

        assert len(result) == 1
        assert result[0].toc_entry == "Chapter 2"

    def test_chapter_parent_preserved(self, assembly_service):
        """P2-19: 'Chapter 1' with children should be preserved."""
        parents = [make_parent("p1", "Chapter 1")]
        children = [make_child("c1", "p1"), make_child("c2", "p1")]

        result = assembly_service._cleanup_empty_parents(parents, children)

        assert len(result) == 1
        assert result[0].toc_entry == "Chapter 1"

    def test_empty_non_artifact_preserved(self, assembly_service):
        """P2-19: 'Executive Summary' with 0 children should be PRESERVED."""
        parents = [make_parent("p1", "Executive Summary")]
        children = []  # No children

        result = assembly_service._cleanup_empty_parents(parents, children)

        # Should be preserved - not an artifact pattern
        assert len(result) == 1
        assert result[0].toc_entry == "Executive Summary"


class TestSafetyTestsP219:
    """P2-19 CRITICAL: Safety tests for legitimate parent preservation."""

    def test_numbered_section_preserved(self, assembly_service):
        """P2-19 SAFETY: '1.1 Introduction' with 0 children MUST be PRESERVED."""
        parents = [make_parent("p1", "1.1 Introduction")]
        children = []

        result = assembly_service._cleanup_empty_parents(parents, children)

        # CRITICAL: Must NOT be deleted - this is legitimate content
        assert len(result) == 1
        assert result[0].toc_entry == "1.1 Introduction"

    def test_numbered_parent_with_zero_children_preserved(self, assembly_service):
        """P2-19 SAFETY: '3 Results' with 0 children MUST be PRESERVED."""
        parents = [make_parent("p1", "3 Results")]
        children = []

        result = assembly_service._cleanup_empty_parents(parents, children)

        # CRITICAL: Must NOT be deleted
        assert len(result) == 1
        assert result[0].toc_entry == "3 Results"

    def test_lowercase_section_preserved(self, assembly_service):
        """P2-19 SAFETY: 'section A' with 0 children MUST be PRESERVED."""
        parents = [make_parent("p1", "section A")]
        children = []

        result = assembly_service._cleanup_empty_parents(parents, children)

        # CRITICAL: Must NOT be deleted
        assert len(result) == 1
        assert result[0].toc_entry == "section A"


class TestEdgeCasesP219:
    """P2-19: Edge case tests."""

    def test_multiple_artifact_parents_removed(self, assembly_service):
        """P2-19: Multiple artifact parents should be removed in one pass."""
        parents = [
            make_parent("p1", "Chapter 1"),
            make_parent("p2", "Blank Page"),
            make_parent("p3", "01_Cover"),
            make_parent("p4", "Chapter 2"),
            make_parent("p5", "Separator"),
            make_parent("p6", "99"),  # Just a number
        ]
        children = [
            make_child("c1", "p1"),
            make_child("c2", "p4"),
        ]

        result = assembly_service._cleanup_empty_parents(parents, children)

        # Only Chapter 1 and Chapter 2 should remain
        toc_entries = [p.toc_entry for p in result]
        assert len(result) == 2
        assert "Chapter 1" in toc_entries
        assert "Chapter 2" in toc_entries

    def test_artifact_with_children_preserved(self, assembly_service):
        """P2-19: '01_Cover' WITH children should be preserved."""
        parents = [make_parent("p1", "01_Cover")]
        children = [make_child("c1", "p1")]  # Has a child

        result = assembly_service._cleanup_empty_parents(parents, children)

        # Should be preserved because it has children
        assert len(result) == 1
        assert result[0].toc_entry == "01_Cover"

    def test_trace_emitted_on_cleanup(self, assembly_service):
        """P2-19: Trace should be emitted when cleaning up parents."""
        parents = [
            make_parent("p1", "Chapter 1"),
            make_parent("p2", "Blank Page"),
        ]
        children = [make_child("c1", "p1")]

        mock_emitter = Mock()

        result = assembly_service._cleanup_empty_parents(
            parents, children, trace_emitter=mock_emitter
        )

        # Verify trace was emitted
        mock_emitter.emit_sample.assert_called_once()
        mock_emitter.emit.assert_called_once()

    def test_empty_parents_list(self, assembly_service):
        """P2-19: Empty parents list should return empty."""
        result = assembly_service._cleanup_empty_parents([], [])

        assert result == []

    def test_all_parents_have_children(self, assembly_service):
        """P2-19: When all parents have children, none are removed."""
        parents = [
            make_parent("p1", "Chapter 1"),
            make_parent("p2", "Chapter 2"),
        ]
        children = [
            make_child("c1", "p1"),
            make_child("c2", "p2"),
        ]

        result = assembly_service._cleanup_empty_parents(parents, children)

        assert len(result) == 2


class TestIsAssemblyArtifactP219:
    """P2-19: Test the _is_assembly_artifact pattern matcher."""

    def test_file_merger_pattern(self, assembly_service):
        """P2-19: '01_Cover' should match artifact pattern."""
        assert assembly_service._is_assembly_artifact("01_Cover") is True
        assert assembly_service._is_assembly_artifact("15_Separator") is True

    def test_state_code_pattern(self, assembly_service):
        """P2-19: 'WBOCW_123' should match artifact pattern."""
        assert assembly_service._is_assembly_artifact("WBOCW_123") is True
        assert assembly_service._is_assembly_artifact("MH_456") is True

    def test_blank_page_pattern(self, assembly_service):
        """P2-19: 'Blank Page' should match artifact pattern."""
        assert assembly_service._is_assembly_artifact("Blank Page") is True
        assert assembly_service._is_assembly_artifact("blank page") is True

    def test_legitimate_titles_not_matched(self, assembly_service):
        """P2-19: Legitimate titles should NOT match artifact patterns."""
        # These should NOT be matched
        assert assembly_service._is_assembly_artifact("1.1 Introduction") is False
        assert assembly_service._is_assembly_artifact("Chapter 1") is False
        assert assembly_service._is_assembly_artifact("Executive Summary") is False
        assert assembly_service._is_assembly_artifact("3 Results") is False
        assert assembly_service._is_assembly_artifact("section A") is False

    def test_empty_and_none(self, assembly_service):
        """P2-19: Empty and None inputs should return False."""
        assert assembly_service._is_assembly_artifact("") is False
        assert assembly_service._is_assembly_artifact(None) is False
