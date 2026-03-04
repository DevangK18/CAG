"""
Data contracts for structured table representation in CAG parsing pipeline.

These models enable queryable JSON structures for tables, supporting:
- Type-aware cell parsing (currency, fiscal years, percentages)
- Column classification (entity, time_period, metric, etc.)
- Multi-level header support
- Indian currency normalization (crore, lakh → paise)
- Total/subtotal detection

Part of Phase 1 - P0-1: Structured Table Extraction
"""

from typing import List, Optional, Union, Dict, Any
from pydantic import BaseModel, Field
from enum import Enum


# ==================== ENUMERATIONS ====================


class CellDataType(str, Enum):
    """Data type classification for table cells."""

    TEXT = "text"
    INTEGER = "integer"
    DECIMAL = "decimal"
    CURRENCY = "currency"
    PERCENTAGE = "percentage"
    DATE = "date"
    YEAR = "year"
    FISCAL_YEAR = "fiscal_year"
    EMPTY = "empty"


class CellSemanticType(str, Enum):
    """Semantic role of a cell in table structure."""

    COLUMN_HEADER = "column_header"
    ROW_HEADER = "row_header"
    DATA = "data"
    TOTAL = "total"
    SUBTOTAL = "subtotal"


class ColumnType(str, Enum):
    """Semantic classification of table columns."""

    ENTITY = "entity"  # State, Ministry, Scheme names
    TIME_PERIOD = "time_period"  # Years, fiscal years, quarters
    METRIC = "metric"  # Amounts, counts, measurements
    VARIANCE = "variance"  # Differences, changes
    STATUS = "status"  # Compliance status, progress indicators
    DESCRIPTION = "description"  # Textual descriptions
    OTHER = "other"


# ==================== CORE DATA MODELS ====================


class TableCell(BaseModel):
    """A single cell in a structured table with parsed metadata."""

    row_idx: int = Field(..., description="0-indexed row position")
    col_idx: int = Field(..., description="0-indexed column position")
    raw_text: str = Field(..., description="Original OCR text")
    cleaned_text: str = Field(..., description="Normalized text (whitespace cleaned)")
    data_type: CellDataType = Field(..., description="Detected data type")
    semantic_type: CellSemanticType = Field(..., description="Semantic role in table")
    parsed_value: Optional[Union[str, int, float]] = Field(
        None, description="Typed value (e.g., 847.71 for currency)"
    )
    unit: Optional[str] = Field(
        None, description="Unit if applicable: 'crore', 'lakh', '%', etc."
    )
    normalized_value: Optional[float] = Field(
        None, description="Normalized numeric value (currency → paise, % → decimal)"
    )


class TableColumn(BaseModel):
    """Column metadata and classification."""

    col_idx: int = Field(..., description="0-indexed column position")
    header_text: str = Field(..., description="Primary header text")
    header_hierarchy: List[str] = Field(
        default_factory=list,
        description="Multi-level headers top to bottom (e.g., ['Expenditure', '2021-22'])"
    )
    column_type: ColumnType = Field(..., description="Semantic column classification")
    dominant_data_type: CellDataType = Field(
        ..., description="Most common data type in this column"
    )


class TableRow(BaseModel):
    """Row metadata with classified cells."""

    row_idx: int = Field(..., description="0-indexed row position")
    cells: List[TableCell] = Field(..., description="All cells in this row")
    row_type: str = Field(
        ..., description="Row classification: 'header', 'data', 'total', 'subtotal'"
    )


class StructuredTable(BaseModel):
    """
    Complete structured representation of a table.

    Enables direct querying without LLM re-parsing:
    - table.get_cell(2, 3) → specific cell value
    - table.sum_column(2) → sum of numeric column
    - table.find_column_by_header("2021-22") → column index
    """

    # Identifiers
    table_id: str = Field(..., description="Unique table identifier")
    source_chunk_id: str = Field(..., description="Link to parent child chunk")

    # Source location
    source_page_physical: int = Field(..., description="0-indexed page number")
    source_pages: List[int] = Field(
        default_factory=list,
        description="All pages if multi-page (empty for single page)"
    )
    source_bbox: List[float] = Field(..., description="[x0, y0, x1, y1] on first page")
    is_multi_page: bool = Field(default=False, description="True if stitched from fragments")

    # Structure
    columns: List[TableColumn] = Field(..., description="Column metadata")
    rows: List[TableRow] = Field(..., description="All rows with cells")
    num_rows: int = Field(..., description="Total row count")
    num_cols: int = Field(..., description="Total column count")
    num_header_rows: int = Field(..., description="Number of header rows")

    # Semantic metadata
    title: Optional[str] = Field(None, description="Table title/caption if detected")
    monetary_unit: Optional[str] = Field(
        None, description="Currency unit context: '₹ in crore', 'Rs. lakh', etc."
    )
    time_periods_covered: List[str] = Field(
        default_factory=list, description="Fiscal years or time periods in table"
    )
    entities_covered: List[str] = Field(
        default_factory=list, description="States, ministries, schemes mentioned"
    )
    has_totals: bool = Field(default=False, description="True if total row detected")
    footnotes: List[str] = Field(
        default_factory=list, description="Table footnotes or notes"
    )

    # Backward compatibility
    markdown_representation: str = Field(
        ..., description="Original markdown format for display"
    )

    # ==================== HELPER METHODS ====================

    def get_cell(self, row_idx: int, col_idx: int) -> Optional[TableCell]:
        """
        Retrieve a specific cell by coordinates.

        Args:
            row_idx: 0-indexed row position
            col_idx: 0-indexed column position

        Returns:
            TableCell if found, None otherwise
        """
        if 0 <= row_idx < len(self.rows):
            row = self.rows[row_idx]
            if 0 <= col_idx < len(row.cells):
                return row.cells[col_idx]
        return None

    def get_column_values(
        self, col_idx: int, skip_headers: bool = True
    ) -> List[Any]:
        """
        Extract all values from a specific column.

        Args:
            col_idx: Column index
            skip_headers: If True, exclude header rows

        Returns:
            List of parsed values (preserves None for empty/unparseable cells)
        """
        values = []
        start_row = self.num_header_rows if skip_headers else 0

        for row in self.rows[start_row:]:
            if col_idx < len(row.cells):
                cell = row.cells[col_idx]
                values.append(cell.parsed_value)

        return values

    def find_column_by_header(self, pattern: str) -> Optional[int]:
        """
        Find column index by matching header text (case-insensitive substring).

        Args:
            pattern: Search string (e.g., "2021-22", "expenditure")

        Returns:
            Column index if found, None otherwise
        """
        pattern_lower = pattern.lower()
        for col in self.columns:
            # Check primary header
            if pattern_lower in col.header_text.lower():
                return col.col_idx
            # Check header hierarchy
            for header in col.header_hierarchy:
                if pattern_lower in header.lower():
                    return col.col_idx
        return None

    def sum_column(self, col_idx: int, exclude_totals: bool = True) -> float:
        """
        Sum numeric values in a column.

        Args:
            col_idx: Column index
            exclude_totals: If True, skip rows marked as 'total' or 'subtotal'

        Returns:
            Sum of all numeric values (0.0 if no numeric values)
        """
        total = 0.0
        start_row = self.num_header_rows

        for row in self.rows[start_row:]:
            # Skip total/subtotal rows if requested
            if exclude_totals and row.row_type in ["total", "subtotal"]:
                continue

            if col_idx < len(row.cells):
                cell = row.cells[col_idx]
                # Use normalized value if available, otherwise try parsed value
                value = cell.normalized_value or cell.parsed_value
                if isinstance(value, (int, float)):
                    total += value

        return total

    def get_row_by_entity(self, entity_name: str) -> Optional[TableRow]:
        """
        Find a data row by entity name (state, ministry, scheme).

        Args:
            entity_name: Entity to search for (case-insensitive)

        Returns:
            First matching TableRow or None
        """
        entity_lower = entity_name.lower()

        # Find entity column (typically first column)
        entity_col_idx = None
        for col in self.columns:
            if col.column_type == ColumnType.ENTITY:
                entity_col_idx = col.col_idx
                break

        if entity_col_idx is None:
            return None

        # Search rows
        for row in self.rows[self.num_header_rows:]:
            if entity_col_idx < len(row.cells):
                cell = row.cells[entity_col_idx]
                if entity_lower in cell.cleaned_text.lower():
                    return row

        return None


# ==================== EXTRACTION METADATA ====================


class TableExtractionMetadata(BaseModel):
    """
    Metadata about the structured extraction process.

    Used for debugging and quality monitoring.
    """

    extraction_method: str = Field(
        ...,
        description="V2: 'pdfplumber-lines_strict', 'pdfplumber-text_fallback', "
                    "'docling-tableformer', 'gemini-2.5-flash'"
    )
    num_cells_parsed: int = Field(..., description="Total cells processed")
    num_cells_with_values: int = Field(..., description="Non-empty cells")
    num_currency_cells: int = Field(default=0, description="Currency values detected")
    num_date_cells: int = Field(default=0, description="Date values detected")
    dominant_currency_unit: Optional[str] = Field(
        None, description="Most common currency unit: 'crore', 'lakh', etc."
    )
    parsing_warnings: List[str] = Field(
        default_factory=list, description="Issues encountered during parsing"
    )

    # V2 ADDITIONS
    needs_review: bool = Field(
        default=False,
        description="V2: True if extraction confidence < 0.5 or quality issues detected"
    )
    original_image_path: Optional[str] = Field(
        default=None,
        description="V2: Path to source image if extracted via vision (Gemini)"
    )
