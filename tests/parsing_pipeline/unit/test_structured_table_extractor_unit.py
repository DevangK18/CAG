"""
Unit tests for StructuredTableExtractor: Markdown to queryable JSON conversion.

Tests P0-1 functionality:
- Currency parsing (Indian formats: crore, lakh, negative parentheses)
- Fiscal year detection (2021-22, FY 2021-22)
- Column classification (entity, time_period, metric, etc.)
- Row classification (header, data, total, subtotal)
- Cell type detection and value parsing
- Helper methods (get_cell, sum_column, find_column_by_header)
"""

import pytest
from typing import List

from src.parsing_pipeline.modules.structured_table_extractor import StructuredTableExtractor
from src.core.table_contracts import (
    StructuredTable,
    CellDataType,
    CellSemanticType,
    ColumnType,
)


class TestStructuredTableExtractor:
    """Test suite for StructuredTableExtractor."""

    @pytest.fixture
    def extractor(self):
        """Create StructuredTableExtractor instance."""
        return StructuredTableExtractor()

    # ==================== CURRENCY PARSING TESTS ====================

    def test_parse_currency_crore(self, extractor):
        """Test parsing currency in crores."""
        amount, unit = extractor._parse_currency("₹847.71 crore")
        assert amount == 847.71
        assert unit == "crore"

        amount, unit = extractor._parse_currency("847.71 cr")
        assert amount == 847.71
        assert unit == "crore"

    def test_parse_currency_lakh(self, extractor):
        """Test parsing currency in lakhs."""
        amount, unit = extractor._parse_currency("₹23.45 lakh")
        assert amount == 23.45
        assert unit == "lakh"

        amount, unit = extractor._parse_currency("50 lac")
        assert amount == 50.0
        assert unit == "lakh"

    def test_parse_currency_negative_parentheses(self, extractor):
        """Test parsing negative values in parentheses."""
        amount, unit = extractor._parse_currency("(23.45)")
        assert amount == -23.45
        assert unit is None

    def test_parse_currency_with_commas(self, extractor):
        """Test parsing currency with thousands separators."""
        amount, unit = extractor._parse_currency("₹1,234.56 crore")
        assert amount == 1234.56
        assert unit == "crore"

    def test_normalize_currency_crore(self, extractor):
        """Test normalization of crore to paise."""
        normalized = extractor._normalize_currency(100, "crore")
        assert normalized == 100_00_00_000 * 100  # 100 crore in paise

    def test_normalize_currency_lakh(self, extractor):
        """Test normalization of lakh to paise."""
        normalized = extractor._normalize_currency(50, "lakh")
        assert normalized == 50_00_000 * 100  # 50 lakh in paise

    # ==================== FISCAL YEAR PARSING TESTS ====================

    def test_parse_fiscal_year_standard(self, extractor):
        """Test parsing standard fiscal year format."""
        fy_data = extractor._parse_fiscal_year("2021-22")
        assert fy_data == {"start": 2021, "end": 2022}

    def test_parse_fiscal_year_fy_prefix(self, extractor):
        """Test parsing fiscal year with FY prefix."""
        fy_data = extractor._parse_fiscal_year("FY 2021-22")
        assert fy_data == {"start": 2021, "end": 2022}

    def test_parse_fiscal_year_four_digit(self, extractor):
        """Test parsing fiscal year with 4-digit end year."""
        fy_data = extractor._parse_fiscal_year("2021-2022")
        assert fy_data == {"start": 2021, "end": 2022}

    # ==================== MARKDOWN PARSING TESTS ====================

    def test_parse_simple_markdown_table(self, extractor):
        """Test parsing basic markdown table."""
        markdown = """| State | 2021-22 | 2022-23 |
| --- | --- | --- |
| Maharashtra | 847.71 | 923.45 |
| Gujarat | 456.12 | 501.33 |"""

        raw_data = extractor._parse_markdown_table(markdown)
        assert len(raw_data) == 3  # 1 header + 2 data rows
        assert raw_data[0] == ["State", "2021-22", "2022-23"]
        assert raw_data[1] == ["Maharashtra", "847.71", "923.45"]
        assert raw_data[2] == ["Gujarat", "456.12", "501.33"]

    def test_parse_markdown_with_total_row(self, extractor):
        """Test parsing markdown table with total row."""
        markdown = """| State | Amount |
| --- | --- |
| State A | 100 |
| State B | 200 |
| Total | 300 |"""

        raw_data = extractor._parse_markdown_table(markdown)
        assert len(raw_data) == 4  # 1 header + 2 data + 1 total
        assert raw_data[3][0] == "Total"

    # ==================== CELL TYPE DETECTION TESTS ====================

    def test_detect_cell_type_currency(self, extractor):
        """Test currency detection."""
        assert extractor._detect_cell_data_type("₹847.71 crore") == CellDataType.CURRENCY
        assert extractor._detect_cell_data_type("23.45 lakh") == CellDataType.CURRENCY

    def test_detect_cell_type_fiscal_year(self, extractor):
        """Test fiscal year detection."""
        assert extractor._detect_cell_data_type("2021-22") == CellDataType.FISCAL_YEAR
        assert extractor._detect_cell_data_type("FY 2021-22") == CellDataType.FISCAL_YEAR

    def test_detect_cell_type_percentage(self, extractor):
        """Test percentage detection."""
        assert extractor._detect_cell_data_type("85.5%") == CellDataType.PERCENTAGE
        assert extractor._detect_cell_data_type("100 %") == CellDataType.PERCENTAGE

    def test_detect_cell_type_integer(self, extractor):
        """Test integer detection."""
        assert extractor._detect_cell_data_type("123") == CellDataType.INTEGER
        assert extractor._detect_cell_data_type("1,234") == CellDataType.INTEGER

    def test_detect_cell_type_decimal(self, extractor):
        """Test decimal detection."""
        assert extractor._detect_cell_data_type("123.45") == CellDataType.DECIMAL
        assert extractor._detect_cell_data_type("1,234.56") == CellDataType.DECIMAL

    def test_detect_cell_type_empty(self, extractor):
        """Test empty cell detection."""
        assert extractor._detect_cell_data_type("") == CellDataType.EMPTY
        assert extractor._detect_cell_data_type("-") == CellDataType.EMPTY

    def test_detect_cell_type_text(self, extractor):
        """Test text detection."""
        assert extractor._detect_cell_data_type("Maharashtra") == CellDataType.TEXT
        assert extractor._detect_cell_data_type("Non-compliance") == CellDataType.TEXT

    # ==================== ROW CLASSIFICATION TESTS ====================

    def test_classify_row_type_total(self, extractor):
        """Test total row classification."""
        assert extractor._classify_row_type(["Total", "1000", "2000"]) == "total"
        assert extractor._classify_row_type(["Grand Total", "5000"]) == "total"
        assert extractor._classify_row_type(["All India", "100%"]) == "total"

    def test_classify_row_type_subtotal(self, extractor):
        """Test subtotal row classification."""
        assert extractor._classify_row_type(["Sub-Total", "500"]) == "subtotal"
        assert extractor._classify_row_type(["Subtotal", "750"]) == "subtotal"

    def test_classify_row_type_data(self, extractor):
        """Test data row classification."""
        assert extractor._classify_row_type(["Maharashtra", "847.71"]) == "data"
        assert extractor._classify_row_type(["Department of Health", "123"]) == "data"

    # ==================== COLUMN CLASSIFICATION TESTS ====================

    def test_classify_column_entity(self, extractor):
        """Test entity column classification."""
        raw_data = [["State", "Amount"], ["Maharashtra", "100"], ["Gujarat", "200"]]
        columns = extractor._classify_columns(raw_data, 1)
        assert columns[0].column_type == ColumnType.ENTITY

    def test_classify_column_time_period(self, extractor):
        """Test time period column classification."""
        raw_data = [["State", "2021-22"], ["Maharashtra", "100"], ["Gujarat", "200"]]
        columns = extractor._classify_columns(raw_data, 1)
        assert columns[1].column_type == ColumnType.TIME_PERIOD

    def test_classify_column_metric(self, extractor):
        """Test metric column classification."""
        raw_data = [["State", "Expenditure"], ["Maharashtra", "100"], ["Gujarat", "200"]]
        columns = extractor._classify_columns(raw_data, 1)
        assert columns[1].column_type == ColumnType.METRIC

    # ==================== FULL EXTRACTION TESTS ====================

    def test_extract_simple_table(self, extractor):
        """Test complete extraction of simple table."""
        markdown = """| State | 2021-22 | 2022-23 |
| --- | --- | --- |
| Maharashtra | ₹847.71 crore | ₹923.45 crore |
| Gujarat | ₹456.12 crore | ₹501.33 crore |
| Total | ₹1303.83 crore | ₹1424.78 crore |"""

        structured = extractor.extract(
            markdown_table=markdown,
            table_id="test_table_1",
            source_chunk_id="chunk_1",
            source_page_physical=10,
            source_bbox=[100, 200, 500, 400],
        )

        assert structured is not None
        assert structured.table_id == "test_table_1"
        assert structured.num_rows == 4  # 1 header + 3 data/total rows
        assert structured.num_cols == 3
        assert structured.num_header_rows == 1
        assert structured.has_totals is True

        # Check columns
        assert len(structured.columns) == 3
        assert structured.columns[0].column_type == ColumnType.ENTITY
        assert structured.columns[1].column_type == ColumnType.TIME_PERIOD
        assert structured.columns[2].column_type == ColumnType.TIME_PERIOD

        # Check rows
        assert len(structured.rows) == 4
        assert structured.rows[0].row_type == "header"
        assert structured.rows[1].row_type == "data"
        assert structured.rows[3].row_type == "total"

    def test_extract_table_with_percentages(self, extractor):
        """Test extraction of table with percentages."""
        markdown = """| Scheme | Achievement |
| --- | --- |
| PMGSY | 85.5% |
| NHAI | 92.0% |
| Total | 88.75% |"""

        structured = extractor.extract(
            markdown_table=markdown,
            table_id="test_table_2",
            source_chunk_id="chunk_2",
            source_page_physical=15,
            source_bbox=[100, 200, 400, 350],
        )

        assert structured is not None

        # Check percentage parsing
        cell = structured.get_cell(1, 1)  # PMGSY achievement
        assert cell.data_type == CellDataType.PERCENTAGE
        assert cell.parsed_value == 85.5
        assert cell.unit == "%"
        assert cell.normalized_value == 0.855  # Normalized to decimal

    # ==================== HELPER METHOD TESTS ====================

    def test_get_cell(self, extractor):
        """Test get_cell helper method."""
        markdown = """| State | Amount |
| --- | --- |
| Maharashtra | 100 |"""

        structured = extractor.extract(
            markdown_table=markdown,
            table_id="test",
            source_chunk_id="chunk",
            source_page_physical=1,
            source_bbox=[0, 0, 100, 100],
        )

        cell = structured.get_cell(1, 0)  # Data row, first column
        assert cell is not None
        assert cell.cleaned_text == "Maharashtra"

    def test_get_column_values(self, extractor):
        """Test get_column_values helper method."""
        markdown = """| State | Amount |
| --- | --- |
| Maharashtra | 100 |
| Gujarat | 200 |
| Total | 300 |"""

        structured = extractor.extract(
            markdown_table=markdown,
            table_id="test",
            source_chunk_id="chunk",
            source_page_physical=1,
            source_bbox=[0, 0, 100, 100],
        )

        # Get amount column values (skip headers)
        values = structured.get_column_values(1, skip_headers=True)
        assert len(values) == 3  # 2 data rows + 1 total
        assert 100 in values or 100.0 in values
        assert 200 in values or 200.0 in values

    def test_find_column_by_header(self, extractor):
        """Test find_column_by_header helper method."""
        markdown = """| State | 2021-22 | 2022-23 |
| --- | --- | --- |
| Maharashtra | 100 | 200 |"""

        structured = extractor.extract(
            markdown_table=markdown,
            table_id="test",
            source_chunk_id="chunk",
            source_page_physical=1,
            source_bbox=[0, 0, 100, 100],
        )

        col_idx = structured.find_column_by_header("2021-22")
        assert col_idx == 1

        col_idx = structured.find_column_by_header("2022")
        assert col_idx == 2  # Substring match

    def test_sum_column(self, extractor):
        """Test sum_column helper method."""
        markdown = """| State | Amount |
| --- | --- |
| Maharashtra | 100 |
| Gujarat | 200 |
| Total | 300 |"""

        structured = extractor.extract(
            markdown_table=markdown,
            table_id="test",
            source_chunk_id="chunk",
            source_page_physical=1,
            source_bbox=[0, 0, 100, 100],
        )

        # Sum excluding totals
        total = structured.sum_column(1, exclude_totals=True)
        assert total == 300.0  # 100 + 200

        # Sum including totals
        total = structured.sum_column(1, exclude_totals=False)
        assert total == 600.0  # 100 + 200 + 300

    def test_get_row_by_entity(self, extractor):
        """Test get_row_by_entity helper method."""
        markdown = """| State | Amount |
| --- | --- |
| Maharashtra | 100 |
| Gujarat | 200 |"""

        structured = extractor.extract(
            markdown_table=markdown,
            table_id="test",
            source_chunk_id="chunk",
            source_page_physical=1,
            source_bbox=[0, 0, 100, 100],
        )

        row = structured.get_row_by_entity("Maharashtra")
        assert row is not None
        assert row.cells[0].cleaned_text == "Maharashtra"

        row = structured.get_row_by_entity("gujarat")  # Case-insensitive
        assert row is not None
        assert "Gujarat" in row.cells[0].cleaned_text

    # ==================== METADATA EXTRACTION TESTS ====================

    def test_detect_monetary_unit(self, extractor):
        """Test monetary unit detection."""
        markdown = """**Table 1: Expenditure (₹ in crore)**

| State | Amount |
| --- | --- |
| Maharashtra | 847.71 |"""

        structured = extractor.extract(
            markdown_table=markdown,
            table_id="test",
            source_chunk_id="chunk",
            source_page_physical=1,
            source_bbox=[0, 0, 100, 100],
        )

        # Should detect from markdown or infer from data
        assert structured.monetary_unit is not None

    def test_extract_time_periods(self, extractor):
        """Test time period extraction."""
        markdown = """| State | 2021-22 | 2022-23 |
| --- | --- | --- |
| Maharashtra | 100 | 200 |"""

        structured = extractor.extract(
            markdown_table=markdown,
            table_id="test",
            source_chunk_id="chunk",
            source_page_physical=1,
            source_bbox=[0, 0, 100, 100],
        )

        assert len(structured.time_periods_covered) >= 2
        assert any("2021-22" in period for period in structured.time_periods_covered)
        assert any("2022-23" in period for period in structured.time_periods_covered)

    def test_extract_entities(self, extractor):
        """Test entity extraction."""
        markdown = """| State | Amount |
| --- | --- |
| Maharashtra | 100 |
| Gujarat | 200 |
| Karnataka | 150 |"""

        structured = extractor.extract(
            markdown_table=markdown,
            table_id="test",
            source_chunk_id="chunk",
            source_page_physical=1,
            source_bbox=[0, 0, 100, 100],
        )

        assert len(structured.entities_covered) == 3
        assert "Maharashtra" in structured.entities_covered
        assert "Gujarat" in structured.entities_covered
        assert "Karnataka" in structured.entities_covered


class TestEdgeCases:
    """Test edge cases and error handling."""

    @pytest.fixture
    def extractor(self):
        """Create StructuredTableExtractor instance."""
        return StructuredTableExtractor()

    def test_empty_table(self, extractor):
        """Test handling of empty table."""
        markdown = ""
        structured = extractor.extract(
            markdown_table=markdown,
            table_id="test",
            source_chunk_id="chunk",
            source_page_physical=1,
            source_bbox=[0, 0, 100, 100],
        )
        assert structured is None

    def test_malformed_markdown(self, extractor):
        """Test handling of malformed markdown."""
        markdown = "This is not a table"
        structured = extractor.extract(
            markdown_table=markdown,
            table_id="test",
            source_chunk_id="chunk",
            source_page_physical=1,
            source_bbox=[0, 0, 100, 100],
        )
        assert structured is None

    def test_table_with_merged_cells(self, extractor):
        """Test handling of irregular column counts (merged cells)."""
        # Markdown doesn't truly support merged cells, but rows might have different lengths
        markdown = """| State | Amount |
| --- | --- |
| Maharashtra | 100 |
| Gujarat |"""  # Missing value

        structured = extractor.extract(
            markdown_table=markdown,
            table_id="test",
            source_chunk_id="chunk",
            source_page_physical=1,
            source_bbox=[0, 0, 100, 100],
        )

        # Should still parse, treating missing cell as empty
        assert structured is not None
