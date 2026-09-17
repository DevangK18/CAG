"""
Unit tests for P0-2: Hierarchy Concentration Fix with Y-coordinate awareness.

Tests the fix for the 92.3% concentration bug where all content on a page
was assigned to a single parent section, even when multiple sections
started on that page.

The fix uses Y-coordinates to determine which section content belongs to:
- Content must be at or below the section heading's Y-position
- Multiple sections on the same page are now correctly distinguished
"""

import pytest
from typing import List
from collections import Counter

from src.core.data_contracts import DocumentTask, ExtractedContent, ParentChunk
from src.parsing_pipeline.modules.chunking_service import ChunkingService


class TestHierarchyConcentrationFix:
    """Test suite for Y-coordinate aware parent assignment."""

    @pytest.fixture
    def chunking_service(self):
        """Create ChunkingService instance."""
        return ChunkingService()

    @pytest.fixture
    def sample_task_with_y_positions(self):
        """
        Create a sample task simulating a page with multiple sections.

        Page 15 contains:
          - End of "3.1.2 Budget Allocation" (y: 0-200)
          - Start of "3.1.3 Implementation" (y: 200-800)
        """
        task = DocumentTask(
            report_id="test_report_001",
            source_url="https://example.com/test.pdf",
            local_pdf_path="/tmp/test.pdf",
            initial_metadata={"Title": "Test Report", "Report No": "001/2024"},
        )

        # Scaffold with TOC and heading Y-positions
        task.scaffold = {
            "toc": [
                [2, "3.1.2 Budget Allocation", 14],  # Starts on page 14
                [2, "3.1.3 Implementation", 15],     # Starts on page 15 at y=200
                [2, "3.1.4 Monitoring", 16],         # Starts on page 16
            ],
            "page_map": {14: "14", 15: "15", 16: "16"},
            # P0-2: Heading Y-positions
            "heading_positions": {
                "14_3.1.2 Budget Allocation": 100.0,
                "15_3.1.3 Implementation": 200.0,    # Section starts at y=200 on page 15
                "16_3.1.4 Monitoring": 100.0,
            },
        }

        # Extracted content on page 15 at different Y-positions
        task.extracted_content = [
            # Content at top of page 15 (y=50-150) → should belong to 3.1.2
            ExtractedContent(
                content_type="paragraph",
                content="Budget allocation continued from previous page.",
                source_page_physical=15,
                source_bbox=[72, 50, 523, 150],  # y0=50, y1=150
                model_used="test",
                layout_label="Text",
            ),
            # Content at middle of page 15 (y=250-350) → should belong to 3.1.3
            ExtractedContent(
                content_type="paragraph",
                content="Implementation started on this page.",
                source_page_physical=15,
                source_bbox=[72, 250, 523, 350],  # y0=250, y1=350
                model_used="test",
                layout_label="Text",
            ),
            # Content at bottom of page 15 (y=400-500) → should belong to 3.1.3
            ExtractedContent(
                content_type="paragraph",
                content="More implementation details.",
                source_page_physical=15,
                source_bbox=[72, 400, 523, 500],  # y0=400, y1=500
                model_used="test",
                layout_label="Text",
            ),
        ]

        return task

    def test_y_coordinate_aware_assignment(self, chunking_service, sample_task_with_y_positions):
        """
        Test that content is correctly assigned based on Y-coordinates.

        Without fix: All 3 chunks would be assigned to "3.1.2 Budget Allocation"
        With fix: First chunk → 3.1.2, next two chunks → 3.1.3
        """
        parent_chunks, child_chunks = chunking_service.chunk_document(sample_task_with_y_positions)

        assert len(parent_chunks) == 3
        assert len(child_chunks) == 3

        # Find parent chunk IDs
        budget_parent = next(p for p in parent_chunks if "Budget Allocation" in p.toc_entry)
        implementation_parent = next(p for p in parent_chunks if "Implementation" in p.toc_entry)

        # Check assignments
        child_by_content = {c.content[:20]: c for c in child_chunks}

        # First chunk (y=50, before section 3.1.3 starts) → Budget Allocation
        budget_child = child_by_content["Budget allocation co"]  # Fixed: first 20 chars
        assert budget_child.parent_chunk_id == budget_parent.chunk_id

        # Second chunk (y=250, after section 3.1.3 starts at y=200) → Implementation
        impl_child_1 = child_by_content["Implementation start"]  # Fixed: first 20 chars
        assert impl_child_1.parent_chunk_id == implementation_parent.chunk_id

        # Third chunk (y=400, well within section 3.1.3) → Implementation
        impl_child_2 = child_by_content["More implementation "]  # Fixed: first 20 chars
        assert impl_child_2.parent_chunk_id == implementation_parent.chunk_id

    def test_no_high_concentration(self, chunking_service, sample_task_with_y_positions):
        """
        Test that no single parent gets an excessive share of children.

        The fix should prevent the 92.3% concentration issue.
        """
        parent_chunks, child_chunks = chunking_service.chunk_document(sample_task_with_y_positions)

        # Count children per parent
        parent_counts = Counter(c.parent_chunk_id for c in child_chunks)

        # Calculate maximum concentration
        max_children = max(parent_counts.values())
        total_children = len(child_chunks)
        max_concentration = (max_children / total_children) * 100

        # Assert no parent has more than 67% of children (2 out of 3 is acceptable)
        assert max_concentration <= 67, f"Concentration too high: {max_concentration:.1f}%"

    def test_y_position_stored_in_parent_chunks(self, chunking_service, sample_task_with_y_positions):
        """Test that parent chunks have start_y_position populated."""
        parent_chunks, _ = chunking_service.chunk_document(sample_task_with_y_positions)

        # Check that Y-positions were captured
        impl_parent = next(p for p in parent_chunks if "Implementation" in p.toc_entry)
        assert impl_parent.start_y_position is not None
        assert impl_parent.start_y_position == 200.0

    def test_fallback_when_no_y_position(self, chunking_service):
        """
        Test that assignment works even without Y-position data (embedded TOC case).

        Should fall back to original logic without breaking.
        """
        task = DocumentTask(
            report_id="test_report_002",
            source_url="https://example.com/test2.pdf",
            local_pdf_path="/tmp/test2.pdf",
            initial_metadata={"Title": "Test Report 2", "Report No": "002/2024"},
        )

        # Scaffold WITHOUT heading_positions (e.g., from embedded TOC)
        task.scaffold = {
            "toc": [
                [1, "Chapter 1", 5],
                [1, "Chapter 2", 10],
            ],
            "page_map": {5: "5", 10: "10"},
            "heading_positions": {},  # Empty - no Y-positions available
        }

        task.extracted_content = [
            ExtractedContent(
                content_type="paragraph",
                content="Content in chapter 1.",
                source_page_physical=7,
                source_bbox=[72, 100, 523, 200],
                model_used="test",
                layout_label="Text",
            ),
        ]

        # Should not raise exception, should fall back gracefully
        parent_chunks, child_chunks = chunking_service.chunk_document(task)

        assert len(parent_chunks) == 2
        assert len(child_chunks) == 1
        assert child_chunks[0].parent_chunk_id == parent_chunks[0].chunk_id

    def test_multiple_sections_same_page_different_y(self, chunking_service):
        """
        Test complex scenario with 3 sections starting on the same page.

        Page 10 contains:
          - Section A (y: 0-200)
          - Section B (y: 200-400)
          - Section C (y: 400-800)
        """
        task = DocumentTask(
            report_id="test_report_003",
            source_url="https://example.com/test3.pdf",
            local_pdf_path="/tmp/test3.pdf",
            initial_metadata={"Title": "Test Report 3", "Report No": "003/2024"},
        )

        task.scaffold = {
            "toc": [
                [2, "Section A", 10],
                [2, "Section B", 10],
                [2, "Section C", 10],
            ],
            "page_map": {10: "10"},
            "heading_positions": {
                "10_Section A": 50.0,
                "10_Section B": 250.0,
                "10_Section C": 450.0,
            },
        }

        task.extracted_content = [
            # Content in Section A (y=100)
            ExtractedContent(
                content_type="paragraph",
                content="A content",
                source_page_physical=10,
                source_bbox=[72, 100, 523, 150],
                model_used="test",
                layout_label="Text",
            ),
            # Content in Section B (y=300)
            ExtractedContent(
                content_type="paragraph",
                content="B content",
                source_page_physical=10,
                source_bbox=[72, 300, 523, 350],
                model_used="test",
                layout_label="Text",
            ),
            # Content in Section C (y=500)
            ExtractedContent(
                content_type="paragraph",
                content="C content",
                source_page_physical=10,
                source_bbox=[72, 500, 523, 550],
                model_used="test",
                layout_label="Text",
            ),
        ]

        parent_chunks, child_chunks = chunking_service.chunk_document(task)

        assert len(parent_chunks) == 3
        assert len(child_chunks) == 3

        # Get parent IDs
        parent_a = next(p for p in parent_chunks if "Section A" in p.toc_entry)
        parent_b = next(p for p in parent_chunks if "Section B" in p.toc_entry)
        parent_c = next(p for p in parent_chunks if "Section C" in p.toc_entry)

        # Check each child is assigned to correct parent
        child_by_content = {c.content: c for c in child_chunks}

        assert child_by_content["A content"].parent_chunk_id == parent_a.chunk_id
        assert child_by_content["B content"].parent_chunk_id == parent_b.chunk_id
        assert child_by_content["C content"].parent_chunk_id == parent_c.chunk_id

    def test_boundary_case_content_at_heading(self, chunking_service):
        """
        Test boundary case where content Y-position equals heading Y-position.

        Should be assigned to the section (at or below).
        """
        task = DocumentTask(
            report_id="test_report_004",
            source_url="https://example.com/test4.pdf",
            local_pdf_path="/tmp/test4.pdf",
            initial_metadata={"Title": "Test Report 4", "Report No": "004/2024"},
        )

        task.scaffold = {
            "toc": [
                [1, "Section 1", 5],
                [1, "Section 2", 5],  # Starts on same page at y=200
            ],
            "page_map": {5: "5"},
            "heading_positions": {
                "5_Section 1": 100.0,
                "5_Section 2": 200.0,
            },
        }

        task.extracted_content = [
            # Content exactly at Section 2 heading Y-position
            ExtractedContent(
                content_type="paragraph",
                content="Content at boundary",
                source_page_physical=5,
                source_bbox=[72, 200, 523, 250],  # y0 = 200, same as heading
                model_used="test",
                layout_label="Text",
            ),
        ]

        parent_chunks, child_chunks = chunking_service.chunk_document(task)

        # Content at y=200 should belong to Section 2 (starts at y=200)
        section2_parent = next(p for p in parent_chunks if "Section 2" in p.toc_entry)
        assert child_chunks[0].parent_chunk_id == section2_parent.chunk_id


class TestBackwardCompatibility:
    """Test that the fix doesn't break existing functionality."""

    @pytest.fixture
    def chunking_service(self):
        """Create ChunkingService instance."""
        return ChunkingService()

    def test_single_section_per_page_still_works(self, chunking_service):
        """Test normal case with one section per page (no Y-position needed)."""
        task = DocumentTask(
            report_id="test_report_005",
            source_url="https://example.com/test5.pdf",
            local_pdf_path="/tmp/test5.pdf",
            initial_metadata={"Title": "Test Report 5", "Report No": "005/2024"},
        )

        task.scaffold = {
            "toc": [
                [1, "Chapter 1", 5],
                [1, "Chapter 2", 10],
                [1, "Chapter 3", 15],
            ],
            "page_map": {5: "5", 10: "10", 15: "15"},
            "heading_positions": {
                "5_Chapter 1": 100.0,
                "10_Chapter 2": 100.0,
                "15_Chapter 3": 100.0,
            },
        }

        task.extracted_content = [
            ExtractedContent(
                content_type="paragraph",
                content="Content in chapter 1",
                source_page_physical=7,
                source_bbox=[72, 100, 523, 200],
                model_used="test",
                layout_label="Text",
            ),
            ExtractedContent(
                content_type="paragraph",
                content="Content in chapter 2",
                source_page_physical=12,
                source_bbox=[72, 100, 523, 200],
                model_used="test",
                layout_label="Text",
            ),
        ]

        parent_chunks, child_chunks = chunking_service.chunk_document(task)

        assert len(parent_chunks) == 3
        assert len(child_chunks) == 2

        # Verify correct assignment
        ch1_parent = next(p for p in parent_chunks if "Chapter 1" in p.toc_entry)
        ch2_parent = next(p for p in parent_chunks if "Chapter 2" in p.toc_entry)

        assert child_chunks[0].parent_chunk_id == ch1_parent.chunk_id
        assert child_chunks[1].parent_chunk_id == ch2_parent.chunk_id
