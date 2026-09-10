"""
P1-14c: Unit tests for Visual Asset Registry Structure.

Tests:
- VisualAssetRegistry model in data_contracts
- _build_visual_asset_registry method in assembly_service
- tables_by_section and figures_by_section grouping
- extraction_stats aggregation
"""

import pytest
from typing import Dict, List, Any

from src.core.data_contracts import VisualAssetRegistry
from src.parsing_pipeline.modules.assembly_service import AssemblyService


@pytest.fixture
def assembly_service(tmp_path):
    """Create AssemblyService with temp output directory."""
    output_dir = tmp_path / "processed"
    output_dir.mkdir()
    return AssemblyService(output_dir=str(output_dir))


class TestVisualAssetRegistryModel:
    """P1-14c: Test VisualAssetRegistry Pydantic model."""

    def test_model_has_required_fields(self):
        """VisualAssetRegistry should have all P1-14c fields."""
        registry = VisualAssetRegistry()

        assert hasattr(registry, "total_tables")
        assert hasattr(registry, "total_figures")
        assert hasattr(registry, "tables_by_section")
        assert hasattr(registry, "figures_by_section")
        assert hasattr(registry, "extraction_stats")

    def test_default_values(self):
        """Default values should be 0 or empty dicts."""
        registry = VisualAssetRegistry()

        assert registry.total_tables == 0
        assert registry.total_figures == 0
        assert registry.tables_by_section == {}
        assert registry.figures_by_section == {}
        assert registry.extraction_stats == {}

    def test_can_populate_all_fields(self):
        """All fields should accept valid data."""
        registry = VisualAssetRegistry(
            total_tables=42,
            total_figures=15,
            tables_by_section={"chapter_1": ["table_001", "table_002"]},
            figures_by_section={"chapter_2": ["fig_001"]},
            extraction_stats={"pdfplumber-lines_strict": 30, "docling-tableformer": 12},
        )

        assert registry.total_tables == 42
        assert registry.total_figures == 15
        assert len(registry.tables_by_section["chapter_1"]) == 2
        assert registry.extraction_stats["pdfplumber-lines_strict"] == 30


class TestBuildVisualAssetRegistry:
    """P1-14c: Test _build_visual_asset_registry method."""

    def test_counts_tables_correctly(self, assembly_service):
        """Total tables should match table_markdown chunk count."""
        child_chunks = [
            {
                "chunk_id": "table_001",
                "content_type": "table_markdown",
                "content": "| A | B |\n|---|---|\n| 1 | 2 |",
                "source_page_physical": 5,
                "parent_chunk_id": "chapter_1",
            },
            {
                "chunk_id": "table_002",
                "content_type": "table_markdown",
                "content": "| X | Y |\n|---|---|\n| 3 | 4 |",
                "source_page_physical": 7,
                "parent_chunk_id": "chapter_2",
            },
            {
                "chunk_id": "para_001",
                "content_type": "paragraph",
                "content": "Some text",
                "source_page_physical": 5,
                "parent_chunk_id": "chapter_1",
            },
        ]
        parent_chunks = [
            {"chunk_id": "chapter_1", "toc_entry": "Chapter 1"},
            {"chunk_id": "chapter_2", "toc_entry": "Chapter 2"},
        ]

        registry = assembly_service._build_visual_asset_registry(child_chunks, parent_chunks)

        assert registry["total_tables"] == 2
        assert len(registry["tables"]) == 2

    def test_counts_figures_correctly(self, assembly_service):
        """Total figures should match image_caption chunk count."""
        child_chunks = [
            {
                "chunk_id": "fig_001",
                "content_type": "image_caption",
                "content": "Figure 1.1: Revenue growth chart",
                "source_page_physical": 10,
                "parent_chunk_id": "chapter_1",
            },
            {
                "chunk_id": "fig_002",
                "content_type": "image_caption",
                "content": "Chart showing expenditure trends",
                "source_page_physical": 15,
                "parent_chunk_id": "chapter_2",
            },
        ]
        parent_chunks = [
            {"chunk_id": "chapter_1", "toc_entry": "Chapter 1"},
            {"chunk_id": "chapter_2", "toc_entry": "Chapter 2"},
        ]

        registry = assembly_service._build_visual_asset_registry(child_chunks, parent_chunks)

        assert registry["total_figures"] == 2
        assert len(registry["figures"]) == 2


class TestTablesBySection:
    """P1-14c: Test tables_by_section grouping."""

    def test_groups_tables_by_parent_chunk_id(self, assembly_service):
        """Tables should be grouped by their parent section."""
        child_chunks = [
            {
                "chunk_id": "table_001",
                "content_type": "table_markdown",
                "content": "| A | B |",
                "source_page_physical": 5,
                "parent_chunk_id": "chapter_1",
            },
            {
                "chunk_id": "table_002",
                "content_type": "table_markdown",
                "content": "| X | Y |",
                "source_page_physical": 6,
                "parent_chunk_id": "chapter_1",
            },
            {
                "chunk_id": "table_003",
                "content_type": "table_markdown",
                "content": "| M | N |",
                "source_page_physical": 10,
                "parent_chunk_id": "chapter_2",
            },
        ]
        parent_chunks = [
            {"chunk_id": "chapter_1", "toc_entry": "Chapter 1"},
            {"chunk_id": "chapter_2", "toc_entry": "Chapter 2"},
        ]

        registry = assembly_service._build_visual_asset_registry(child_chunks, parent_chunks)

        assert "tables_by_section" in registry
        assert len(registry["tables_by_section"]["chapter_1"]) == 2
        assert len(registry["tables_by_section"]["chapter_2"]) == 1
        assert "table_001" in registry["tables_by_section"]["chapter_1"]
        assert "table_003" in registry["tables_by_section"]["chapter_2"]


class TestFiguresBySection:
    """P1-14c: Test figures_by_section grouping."""

    def test_groups_figures_by_parent_chunk_id(self, assembly_service):
        """Figures should be grouped by their parent section."""
        child_chunks = [
            {
                "chunk_id": "fig_001",
                "content_type": "image_caption",
                "content": "Chart showing trend",
                "source_page_physical": 5,
                "parent_chunk_id": "section_1",
            },
            {
                "chunk_id": "fig_002",
                "content_type": "image_caption",
                "content": "Bar graph",
                "source_page_physical": 6,
                "parent_chunk_id": "section_1",
            },
            {
                "chunk_id": "fig_003",
                "content_type": "image_caption",
                "content": "Pie chart",
                "source_page_physical": 10,
                "parent_chunk_id": "section_2",
            },
        ]
        parent_chunks = [
            {"chunk_id": "section_1", "toc_entry": "Section 1"},
            {"chunk_id": "section_2", "toc_entry": "Section 2"},
        ]

        registry = assembly_service._build_visual_asset_registry(child_chunks, parent_chunks)

        assert "figures_by_section" in registry
        assert len(registry["figures_by_section"]["section_1"]) == 2
        assert len(registry["figures_by_section"]["section_2"]) == 1


class TestExtractionStats:
    """P1-14c: Test extraction_stats aggregation."""

    def test_aggregates_extraction_methods(self, assembly_service):
        """extraction_stats should count by extraction_method."""
        child_chunks = [
            {
                "chunk_id": "table_001",
                "content_type": "table_markdown",
                "content": "| A | B |",
                "source_page_physical": 5,
                "parent_chunk_id": "ch1",
                "extraction_method": "pdfplumber-lines_strict",
            },
            {
                "chunk_id": "table_002",
                "content_type": "table_markdown",
                "content": "| X | Y |",
                "source_page_physical": 6,
                "parent_chunk_id": "ch1",
                "extraction_method": "pdfplumber-lines_strict",
            },
            {
                "chunk_id": "table_003",
                "content_type": "table_markdown",
                "content": "| M | N |",
                "source_page_physical": 10,
                "parent_chunk_id": "ch2",
                "extraction_method": "docling-tableformer",
            },
        ]
        parent_chunks = [
            {"chunk_id": "ch1", "toc_entry": "Chapter 1"},
            {"chunk_id": "ch2", "toc_entry": "Chapter 2"},
        ]

        registry = assembly_service._build_visual_asset_registry(child_chunks, parent_chunks)

        assert "extraction_stats" in registry
        assert registry["extraction_stats"]["pdfplumber-lines_strict"] == 2
        assert registry["extraction_stats"]["docling-tableformer"] == 1

    def test_fallback_to_model_used_if_no_extraction_method(self, assembly_service):
        """Should use model_used if extraction_method is not set."""
        child_chunks = [
            {
                "chunk_id": "table_001",
                "content_type": "table_markdown",
                "content": "| A | B |",
                "source_page_physical": 5,
                "parent_chunk_id": "ch1",
                "model_used": "pdfplumber-text_fallback",  # No extraction_method
            },
        ]
        parent_chunks = [{"chunk_id": "ch1", "toc_entry": "Chapter 1"}]

        registry = assembly_service._build_visual_asset_registry(child_chunks, parent_chunks)

        assert "pdfplumber-text_fallback" in registry["extraction_stats"]
        assert registry["extraction_stats"]["pdfplumber-text_fallback"] == 1

    def test_unknown_when_neither_field_present(self, assembly_service):
        """Should use 'unknown' if neither extraction_method nor model_used is set."""
        child_chunks = [
            {
                "chunk_id": "table_001",
                "content_type": "table_markdown",
                "content": "| A | B |",
                "source_page_physical": 5,
                "parent_chunk_id": "ch1",
                # No extraction_method or model_used
            },
        ]
        parent_chunks = [{"chunk_id": "ch1", "toc_entry": "Chapter 1"}]

        registry = assembly_service._build_visual_asset_registry(child_chunks, parent_chunks)

        assert "unknown" in registry["extraction_stats"]


class TestEmptyRegistry:
    """P1-14c: Test empty registry case."""

    def test_empty_chunks_returns_empty_registry(self, assembly_service):
        """Empty child_chunks should return empty registry."""
        registry = assembly_service._build_visual_asset_registry([], [])

        assert registry["total_tables"] == 0
        assert registry["total_figures"] == 0
        assert registry["tables_by_section"] == {}
        assert registry["figures_by_section"] == {}
        assert registry["extraction_stats"] == {}

    def test_no_visuals_returns_empty_counts(self, assembly_service):
        """Chunks with no tables/figures should return zero counts."""
        child_chunks = [
            {
                "chunk_id": "para_001",
                "content_type": "paragraph",
                "content": "Some text",
                "source_page_physical": 5,
                "parent_chunk_id": "ch1",
            },
        ]
        parent_chunks = [{"chunk_id": "ch1", "toc_entry": "Chapter 1"}]

        registry = assembly_service._build_visual_asset_registry(child_chunks, parent_chunks)

        assert registry["total_tables"] == 0
        assert registry["total_figures"] == 0
