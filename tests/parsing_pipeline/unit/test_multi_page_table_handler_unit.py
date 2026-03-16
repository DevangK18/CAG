"""
Unit tests for MultiPageTableHandler: Multi-page table stitching (P0-3).

Tests P0-3 functionality:
- Continuation marker detection ("Contd.", "(continued)", etc.)
- Column structure similarity (Jaccard index)
- Header repetition matching
- Total row detection
- Fragment merging correctness
- Edge cases (single table, non-consecutive pages, etc.)
"""

import pytest
from typing import List

from src.parsing_pipeline.modules.multi_page_table_handler import MultiPageTableHandler
from src.core.table_contracts import (
    StructuredTable,
    TableCell,
    TableColumn,
    TableRow,
    CellDataType,
    CellSemanticType,
    ColumnType,
)


class TestMultiPageTableHandler:
    """Test suite for MultiPageTableHandler."""

    @pytest.fixture
    def handler(self):
        """Create MultiPageTableHandler instance."""
        return MultiPageTableHandler()

    @pytest.fixture
    def sample_table_fragment_1(self):
        """Create a sample table fragment (page 1)."""
        # Header row
        header_cells = [
            TableCell(
                row_idx=0,
                col_idx=0,
                raw_text="State",
                cleaned_text="State",
                data_type=CellDataType.TEXT,
                semantic_type=CellSemanticType.COLUMN_HEADER,
                parsed_value="State",
                unit=None,
                normalized_value=None,
            ),
            TableCell(
                row_idx=0,
                col_idx=1,
                raw_text="2021-22",
                cleaned_text="2021-22",
                data_type=CellDataType.FISCAL_YEAR,
                semantic_type=CellSemanticType.COLUMN_HEADER,
                parsed_value="2021-22",
                unit="fiscal_year",
                normalized_value=None,
            ),
            TableCell(
                row_idx=0,
                col_idx=2,
                raw_text="2022-23",
                cleaned_text="2022-23",
                data_type=CellDataType.FISCAL_YEAR,
                semantic_type=CellSemanticType.COLUMN_HEADER,
                parsed_value="2022-23",
                unit="fiscal_year",
                normalized_value=None,
            ),
        ]

        # Data row 1
        data_row1_cells = [
            TableCell(
                row_idx=1,
                col_idx=0,
                raw_text="Maharashtra",
                cleaned_text="Maharashtra",
                data_type=CellDataType.TEXT,
                semantic_type=CellSemanticType.ROW_HEADER,
                parsed_value="Maharashtra",
                unit=None,
                normalized_value=None,
            ),
            TableCell(
                row_idx=1,
                col_idx=1,
                raw_text="847.71",
                cleaned_text="847.71",
                data_type=CellDataType.CURRENCY,
                semantic_type=CellSemanticType.DATA,
                parsed_value=847.71,
                unit="crore",
                normalized_value=847_71_00_000_00,
            ),
            TableCell(
                row_idx=1,
                col_idx=2,
                raw_text="923.45",
                cleaned_text="923.45",
                data_type=CellDataType.CURRENCY,
                semantic_type=CellSemanticType.DATA,
                parsed_value=923.45,
                unit="crore",
                normalized_value=923_45_00_000_00,
            ),
        ]

        # Continuation marker row
        contd_row_cells = [
            TableCell(
                row_idx=2,
                col_idx=0,
                raw_text="Contd.",
                cleaned_text="Contd.",
                data_type=CellDataType.TEXT,
                semantic_type=CellSemanticType.DATA,
                parsed_value="Contd.",
                unit=None,
                normalized_value=None,
            ),
            TableCell(
                row_idx=2,
                col_idx=1,
                raw_text="",
                cleaned_text="",
                data_type=CellDataType.EMPTY,
                semantic_type=CellSemanticType.DATA,
                parsed_value=None,
                unit=None,
                normalized_value=None,
            ),
            TableCell(
                row_idx=2,
                col_idx=2,
                raw_text="",
                cleaned_text="",
                data_type=CellDataType.EMPTY,
                semantic_type=CellSemanticType.DATA,
                parsed_value=None,
                unit=None,
                normalized_value=None,
            ),
        ]

        columns = [
            TableColumn(
                col_idx=0,
                header_text="State",
                header_hierarchy=["State"],
                column_type=ColumnType.ENTITY,
                dominant_data_type=CellDataType.TEXT,
            ),
            TableColumn(
                col_idx=1,
                header_text="2021-22",
                header_hierarchy=["2021-22"],
                column_type=ColumnType.TIME_PERIOD,
                dominant_data_type=CellDataType.CURRENCY,
            ),
            TableColumn(
                col_idx=2,
                header_text="2022-23",
                header_hierarchy=["2022-23"],
                column_type=ColumnType.TIME_PERIOD,
                dominant_data_type=CellDataType.CURRENCY,
            ),
        ]

        rows = [
            TableRow(row_idx=0, cells=header_cells, row_type="header"),
            TableRow(row_idx=1, cells=data_row1_cells, row_type="data"),
            TableRow(row_idx=2, cells=contd_row_cells, row_type="data"),
        ]

        return StructuredTable(
            table_id="table_1_100_200",
            source_chunk_id="temp",
            source_page_physical=1,
            source_bbox=[100, 200, 500, 600],
            columns=columns,
            rows=rows,
            num_rows=3,
            num_cols=3,
            num_header_rows=1,
            title="State-wise Allocation",
            monetary_unit="₹ in crore",
            time_periods_covered=["2021-22", "2022-23"],
            entities_covered=["Maharashtra"],
            has_totals=False,
            markdown_representation="| State | 2021-22 | 2022-23 |\n| --- | --- | --- |\n| Maharashtra | 847.71 | 923.45 |\n| Contd. | | |",
        )

    @pytest.fixture
    def sample_table_fragment_2(self):
        """Create a sample table fragment (page 2) - continuation."""
        # Header row (repeated)
        header_cells = [
            TableCell(
                row_idx=0,
                col_idx=0,
                raw_text="State",
                cleaned_text="State",
                data_type=CellDataType.TEXT,
                semantic_type=CellSemanticType.COLUMN_HEADER,
                parsed_value="State",
                unit=None,
                normalized_value=None,
            ),
            TableCell(
                row_idx=0,
                col_idx=1,
                raw_text="2021-22",
                cleaned_text="2021-22",
                data_type=CellDataType.FISCAL_YEAR,
                semantic_type=CellSemanticType.COLUMN_HEADER,
                parsed_value="2021-22",
                unit="fiscal_year",
                normalized_value=None,
            ),
            TableCell(
                row_idx=0,
                col_idx=2,
                raw_text="2022-23",
                cleaned_text="2022-23",
                data_type=CellDataType.FISCAL_YEAR,
                semantic_type=CellSemanticType.COLUMN_HEADER,
                parsed_value="2022-23",
                unit="fiscal_year",
                normalized_value=None,
            ),
        ]

        # Data row 2
        data_row2_cells = [
            TableCell(
                row_idx=1,
                col_idx=0,
                raw_text="Karnataka",
                cleaned_text="Karnataka",
                data_type=CellDataType.TEXT,
                semantic_type=CellSemanticType.ROW_HEADER,
                parsed_value="Karnataka",
                unit=None,
                normalized_value=None,
            ),
            TableCell(
                row_idx=1,
                col_idx=1,
                raw_text="512.34",
                cleaned_text="512.34",
                data_type=CellDataType.CURRENCY,
                semantic_type=CellSemanticType.DATA,
                parsed_value=512.34,
                unit="crore",
                normalized_value=512_34_00_000_00,
            ),
            TableCell(
                row_idx=1,
                col_idx=2,
                raw_text="580.90",
                cleaned_text="580.90",
                data_type=CellDataType.CURRENCY,
                semantic_type=CellSemanticType.DATA,
                parsed_value=580.90,
                unit="crore",
                normalized_value=580_90_00_000_00,
            ),
        ]

        # Total row
        total_row_cells = [
            TableCell(
                row_idx=2,
                col_idx=0,
                raw_text="Total",
                cleaned_text="Total",
                data_type=CellDataType.TEXT,
                semantic_type=CellSemanticType.TOTAL,
                parsed_value="Total",
                unit=None,
                normalized_value=None,
            ),
            TableCell(
                row_idx=2,
                col_idx=1,
                raw_text="1360.05",
                cleaned_text="1360.05",
                data_type=CellDataType.CURRENCY,
                semantic_type=CellSemanticType.TOTAL,
                parsed_value=1360.05,
                unit="crore",
                normalized_value=1360_05_00_000_00,
            ),
            TableCell(
                row_idx=2,
                col_idx=2,
                raw_text="1504.35",
                cleaned_text="1504.35",
                data_type=CellDataType.CURRENCY,
                semantic_type=CellSemanticType.TOTAL,
                parsed_value=1504.35,
                unit="crore",
                normalized_value=1504_35_00_000_00,
            ),
        ]

        columns = [
            TableColumn(
                col_idx=0,
                header_text="State",
                header_hierarchy=["State"],
                column_type=ColumnType.ENTITY,
                dominant_data_type=CellDataType.TEXT,
            ),
            TableColumn(
                col_idx=1,
                header_text="2021-22",
                header_hierarchy=["2021-22"],
                column_type=ColumnType.TIME_PERIOD,
                dominant_data_type=CellDataType.CURRENCY,
            ),
            TableColumn(
                col_idx=2,
                header_text="2022-23",
                header_hierarchy=["2022-23"],
                column_type=ColumnType.TIME_PERIOD,
                dominant_data_type=CellDataType.CURRENCY,
            ),
        ]

        rows = [
            TableRow(row_idx=0, cells=header_cells, row_type="header"),
            TableRow(row_idx=1, cells=data_row2_cells, row_type="data"),
            TableRow(row_idx=2, cells=total_row_cells, row_type="total"),
        ]

        return StructuredTable(
            table_id="table_2_100_50",
            source_chunk_id="temp",
            source_page_physical=2,
            source_bbox=[100, 50, 500, 400],
            columns=columns,
            rows=rows,
            num_rows=3,
            num_cols=3,
            num_header_rows=1,
            title=None,
            monetary_unit="₹ in crore",
            time_periods_covered=["2021-22", "2022-23"],
            entities_covered=["Karnataka"],
            has_totals=True,
            markdown_representation="| State | 2021-22 | 2022-23 |\n| --- | --- | --- |\n| Karnataka | 512.34 | 580.90 |\n| Total | 1360.05 | 1504.35 |",
        )

    # ==================== CONTINUATION MARKER DETECTION TESTS ====================

    def test_has_continuation_marker_contd(self, handler, sample_table_fragment_1):
        """Test detection of 'Contd.' marker."""
        assert handler._has_continuation_marker(sample_table_fragment_1) is True

    def test_has_continuation_marker_none(self, handler, sample_table_fragment_2):
        """Test no continuation marker on complete table."""
        assert handler._has_continuation_marker(sample_table_fragment_2) is False

    def test_has_continuation_marker_in_title(self, handler):
        """Test continuation marker in table title."""
        table = StructuredTable(
            table_id="test",
            source_chunk_id="test",
            source_page_physical=1,
            source_bbox=[0, 0, 100, 100],
            columns=[],
            rows=[],
            num_rows=0,
            num_cols=0,
            num_header_rows=0,
            title="Budget Allocation (continued)",
            markdown_representation="",
        )
        assert handler._has_continuation_marker(table) is True

    # ==================== COLUMN SIMILARITY TESTS ====================

    def test_column_similarity_identical(self, handler, sample_table_fragment_1, sample_table_fragment_2):
        """Test column similarity for identical headers."""
        similarity = handler._column_similarity(
            sample_table_fragment_1, sample_table_fragment_2
        )
        assert similarity == 1.0  # 100% match

    def test_column_similarity_different(self, handler, sample_table_fragment_1):
        """Test column similarity for completely different headers."""
        # Create a table with different headers
        different_columns = [
            TableColumn(
                col_idx=0,
                header_text="Ministry",
                header_hierarchy=["Ministry"],
                column_type=ColumnType.ENTITY,
                dominant_data_type=CellDataType.TEXT,
            ),
            TableColumn(
                col_idx=1,
                header_text="Budget",
                header_hierarchy=["Budget"],
                column_type=ColumnType.METRIC,
                dominant_data_type=CellDataType.CURRENCY,
            ),
        ]

        different_table = StructuredTable(
            table_id="different",
            source_chunk_id="temp",
            source_page_physical=2,
            source_bbox=[0, 0, 100, 100],
            columns=different_columns,
            rows=[],
            num_rows=0,
            num_cols=2,
            num_header_rows=1,
            markdown_representation="",
        )

        similarity = handler._column_similarity(sample_table_fragment_1, different_table)
        assert similarity == 0.0  # 0% match

    # ==================== HEADER REPETITION TESTS ====================

    def test_has_repeated_header_true(self, handler, sample_table_fragment_1, sample_table_fragment_2):
        """Test detection of repeated headers."""
        assert handler._has_repeated_header(
            sample_table_fragment_1, sample_table_fragment_2
        ) is True

    def test_has_repeated_header_false(self, handler, sample_table_fragment_1):
        """Test no header repetition for different headers."""
        # Create table with different header
        different_header_cells = [
            TableCell(
                row_idx=0,
                col_idx=0,
                raw_text="Ministry",
                cleaned_text="Ministry",
                data_type=CellDataType.TEXT,
                semantic_type=CellSemanticType.COLUMN_HEADER,
                parsed_value="Ministry",
                unit=None,
                normalized_value=None,
            ),
        ]

        different_table = StructuredTable(
            table_id="different",
            source_chunk_id="temp",
            source_page_physical=2,
            source_bbox=[0, 0, 100, 100],
            columns=[
                TableColumn(
                    col_idx=0,
                    header_text="Ministry",
                    header_hierarchy=["Ministry"],
                    column_type=ColumnType.ENTITY,
                    dominant_data_type=CellDataType.TEXT,
                )
            ],
            rows=[
                TableRow(
                    row_idx=0, cells=different_header_cells, row_type="header"
                )
            ],
            num_rows=1,
            num_cols=1,
            num_header_rows=1,
            markdown_representation="",
        )

        assert handler._has_repeated_header(sample_table_fragment_1, different_table) is False

    # ==================== TOTAL ROW DETECTION TESTS ====================

    def test_has_total_row_true(self, handler, sample_table_fragment_2):
        """Test detection of total row."""
        assert handler._has_total_row(sample_table_fragment_2) is True

    def test_has_total_row_false(self, handler, sample_table_fragment_1):
        """Test no total row in fragment."""
        assert handler._has_total_row(sample_table_fragment_1) is False

    # ==================== MERGING LOGIC TESTS ====================

    def test_should_merge_consecutive_pages_with_marker(
        self, handler, sample_table_fragment_1, sample_table_fragment_2
    ):
        """Test merging decision for consecutive pages with continuation marker."""
        assert handler._should_merge(sample_table_fragment_1, sample_table_fragment_2) is True

    def test_should_not_merge_non_consecutive_pages(self, handler, sample_table_fragment_1):
        """Test no merging for non-consecutive pages."""
        # Create table on page 5 (gap of 3 pages)
        distant_table = StructuredTable(
            table_id="distant",
            source_chunk_id="temp",
            source_page_physical=5,
            source_bbox=[0, 0, 100, 100],
            columns=sample_table_fragment_1.columns,
            rows=[],
            num_rows=0,
            num_cols=3,
            num_header_rows=1,
            markdown_representation="",
        )

        assert handler._should_merge(sample_table_fragment_1, distant_table) is False

    def test_merge_fragments_basic(
        self, handler, sample_table_fragment_1, sample_table_fragment_2
    ):
        """Test basic fragment merging."""
        fragments = [sample_table_fragment_1, sample_table_fragment_2]
        merged = handler._merge_fragments(fragments)

        # Verify merged table properties
        assert merged.is_multi_page is True
        assert merged.table_id == "table_1_100_200_merged"
        assert merged.source_pages == [1, 2]
        assert merged.has_totals is True

        # Verify row count (header + data rows from both, minus repeated header)
        # Fragment 1: header + 2 data rows = 3 rows
        # Fragment 2: header (skipped) + 1 data + 1 total = 2 rows
        # Total: 3 + 2 = 5 rows
        assert merged.num_rows == 5

        # Verify entities merged
        assert "Maharashtra" in merged.entities_covered
        assert "Karnataka" in merged.entities_covered

    def test_detect_and_merge_single_table(self, handler, sample_table_fragment_1):
        """Test no merging for single table."""
        tables = [sample_table_fragment_1]
        result = handler.detect_and_merge(tables)

        assert len(result) == 1
        assert result[0].is_multi_page is False

    def test_detect_and_merge_two_fragments(
        self, handler, sample_table_fragment_1, sample_table_fragment_2
    ):
        """Test merging two consecutive fragments."""
        tables = [sample_table_fragment_1, sample_table_fragment_2]
        result = handler.detect_and_merge(tables)

        assert len(result) == 1  # Two fragments merged into one
        assert result[0].is_multi_page is True
        assert result[0].has_totals is True

    def test_detect_and_merge_three_fragments(
        self, handler, sample_table_fragment_1, sample_table_fragment_2
    ):
        """Test merging three consecutive fragments."""
        # Create third fragment (page 3)
        fragment_3 = StructuredTable(
            table_id="table_3_100_50",
            source_chunk_id="temp",
            source_page_physical=3,
            source_bbox=[100, 50, 500, 400],
            columns=sample_table_fragment_1.columns,
            rows=sample_table_fragment_2.rows,  # Reuse rows for simplicity
            num_rows=3,
            num_cols=3,
            num_header_rows=1,
            title=None,
            monetary_unit="₹ in crore",
            time_periods_covered=["2021-22", "2022-23"],
            entities_covered=["Tamil Nadu"],
            has_totals=True,
            markdown_representation="...",
        )

        tables = [sample_table_fragment_1, sample_table_fragment_2, fragment_3]
        result = handler.detect_and_merge(tables)

        # Should merge all three
        assert len(result) == 1
        assert result[0].source_pages == [1, 2, 3]

    def test_detect_and_merge_independent_tables(self, handler):
        """Test no merging for independent tables."""
        # Create two unrelated tables
        table1 = StructuredTable(
            table_id="table1",
            source_chunk_id="temp",
            source_page_physical=1,
            source_bbox=[0, 0, 100, 100],
            columns=[
                TableColumn(
                    col_idx=0,
                    header_text="State",
                    header_hierarchy=["State"],
                    column_type=ColumnType.ENTITY,
                    dominant_data_type=CellDataType.TEXT,
                )
            ],
            rows=[],
            num_rows=1,
            num_cols=1,
            num_header_rows=1,
            has_totals=True,  # Complete table
            markdown_representation="",
        )

        table2 = StructuredTable(
            table_id="table2",
            source_chunk_id="temp",
            source_page_physical=3,  # Gap of 1 page
            source_bbox=[0, 0, 100, 100],
            columns=[
                TableColumn(
                    col_idx=0,
                    header_text="Ministry",
                    header_hierarchy=["Ministry"],
                    column_type=ColumnType.ENTITY,
                    dominant_data_type=CellDataType.TEXT,
                )
            ],
            rows=[],
            num_rows=1,
            num_cols=1,
            num_header_rows=1,
            has_totals=True,
            markdown_representation="",
        )

        tables = [table1, table2]
        result = handler.detect_and_merge(tables)

        # Should not merge (different headers, both have totals, gap)
        assert len(result) == 2
        assert result[0].is_multi_page is False
        assert result[1].is_multi_page is False

    # ==================== STATISTICS TESTS ====================

    def test_statistics_tracking(
        self, handler, sample_table_fragment_1, sample_table_fragment_2
    ):
        """Test statistics tracking during merging."""
        tables = [sample_table_fragment_1, sample_table_fragment_2]
        handler.detect_and_merge(tables)

        stats = handler.get_statistics()
        assert stats["tables_processed"] == 2
        assert stats["tables_merged"] == 1
        assert stats["total_fragments_merged"] == 2

    def test_statistics_reset(self, handler):
        """Test statistics reset."""
        handler.stats["tables_processed"] = 10
        handler.reset_statistics()

        stats = handler.get_statistics()
        assert stats["tables_processed"] == 0
        assert stats["tables_merged"] == 0
        assert stats["total_fragments_merged"] == 0

    # ==================== EDGE CASES ====================

    def test_merge_fragments_empty_list(self, handler):
        """Test merging with empty fragment list."""
        with pytest.raises(ValueError, match="Cannot merge empty fragment list"):
            handler._merge_fragments([])

    def test_merge_fragments_single_fragment(self, handler, sample_table_fragment_1):
        """Test merging with single fragment."""
        result = handler._merge_fragments([sample_table_fragment_1])
        assert result == sample_table_fragment_1  # Returns unchanged

    def test_regenerate_markdown(self, handler, sample_table_fragment_1):
        """Test markdown regeneration after merging."""
        markdown = handler._regenerate_markdown(
            sample_table_fragment_1.rows, sample_table_fragment_1.columns
        )

        # Verify markdown contains headers and data
        assert "State" in markdown
        assert "2021-22" in markdown
        assert "Maharashtra" in markdown
        assert "---" in markdown  # Separator

    def test_column_similarity_with_empty_tables(self, handler):
        """Test column similarity with tables that have no columns."""
        empty_table1 = StructuredTable(
            table_id="empty1",
            source_chunk_id="temp",
            source_page_physical=1,
            source_bbox=[0, 0, 100, 100],
            columns=[],
            rows=[],
            num_rows=0,
            num_cols=0,
            num_header_rows=0,
            markdown_representation="",
        )

        empty_table2 = StructuredTable(
            table_id="empty2",
            source_chunk_id="temp",
            source_page_physical=2,
            source_bbox=[0, 0, 100, 100],
            columns=[],
            rows=[],
            num_rows=0,
            num_cols=0,
            num_header_rows=0,
            markdown_representation="",
        )

        similarity = handler._column_similarity(empty_table1, empty_table2)
        assert similarity == 0.0
