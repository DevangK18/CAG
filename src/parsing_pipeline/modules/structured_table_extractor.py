"""
StructuredTableExtractor: Converts markdown tables to queryable JSON structures.

Transforms markdown table strings into structured representations with:
- Type-aware cell parsing (currency, fiscal years, percentages, dates)
- Column classification (entity, time_period, metric, variance, status)
- Row classification (header, data, total, subtotal)
- Indian currency normalization (crore/lakh → paise)
- Multi-level header support

Part of Phase 1 - P0-1: Structured Table Extraction
"""

import re
from typing import List, Tuple, Optional, Dict, Any, Union
from collections import Counter

from src.core.table_contracts import (
    StructuredTable,
    TableCell,
    TableColumn,
    TableRow,
    CellDataType,
    CellSemanticType,
    ColumnType,
    TableExtractionMetadata,
)


class StructuredTableExtractor:
    """
    Extracts structured, queryable data from markdown table strings.

    Handles CAG-specific patterns:
    - Indian currency formats (₹, crore, lakh)
    - Fiscal years (2021-22, FY 2021-22)
    - Negative values in parentheses: (23.45) → -23.45
    - Total row detection (Total, Grand Total, All India, etc.)
    """

    # ==================== PATTERN CONSTANTS ====================

    # Indian currency patterns
    CURRENCY_PATTERNS = [
        # ₹847.71 crore, ₹ 23.45 lakh
        (r"^[₹`]?\s*([\d,]+(?:\.\d+)?)\s*(crore|cr\.?|lakh|lac)s?$", "with_unit"),
        # ₹847.71, `123.45` (raw rupee values)
        (r"^[₹`]\s*([\d,]+(?:\.\d+)?)\s*$", "rupee_symbol"),
        # Plain numbers that might be currency (context-dependent)
        (r"^([\d,]+(?:\.\d+)?)\s*$", "plain_number"),
        # Negative values in parentheses: (23.45)
        (r"^\(([\d,]+(?:\.\d+)?)\)$", "negative_paren"),
    ]

    # Fiscal year patterns
    FISCAL_YEAR_PATTERNS = [
        r"^(\d{4})-(\d{2,4})$",  # 2021-22, 2021-2022
        r"^FY\s*(\d{4})-(\d{2,4})$",  # FY 2021-22
        r"^(\d{4})\s*-\s*(\d{2,4})$",  # 2021 - 22
    ]

    # Percentage patterns
    PERCENTAGE_PATTERN = r"^([\d,]+(?:\.\d+)?)\s*%$"

    # Date patterns (dd-mm-yyyy, dd/mm/yyyy, etc.)
    DATE_PATTERNS = [
        r"^\d{1,2}[-/]\d{1,2}[-/]\d{2,4}$",
        r"^\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{2,4}$",
    ]

    # Total row indicators (case-insensitive matching)
    TOTAL_INDICATORS = [
        r"\btotal\b",
        r"\bgrand\s+total\b",
        r"\bsub[\-\s]?total\b",
        r"\ball\s+india\b",
        r"\boverall\b",
        r"\baggregate\b",
    ]

    # Column classification keywords
    ENTITY_KEYWORDS = [
        "state",
        "ministry",
        "department",
        "scheme",
        "name",
        "particulars",
        "entity",
        "organization",
    ]
    TIME_KEYWORDS = ["year", "period", "fy", "quarter", "month", "date"]
    METRIC_KEYWORDS = [
        "amount",
        "expenditure",
        "receipt",
        "budget",
        "actual",
        "revenue",
        "allocation",
        "utilization",
        "count",
        "number",
    ]
    VARIANCE_KEYWORDS = [
        "difference",
        "variance",
        "change",
        "shortfall",
        "excess",
        "deviation",
    ]
    STATUS_KEYWORDS = ["status", "compliance", "progress", "achievement", "completion"]

    # Currency unit to paise multipliers
    CURRENCY_MULTIPLIERS = {
        "crore": 100_00_00_000,  # 1 crore = 10^9 paise
        "cr": 100_00_00_000,
        "lakh": 100_00_000,  # 1 lakh = 10^7 paise
        "lac": 100_00_000,
        "thousand": 100_000,  # 1 thousand = 10^5 paise
        "rupee": 100,  # 1 rupee = 100 paise
    }

    def __init__(self):
        """Initialize the structured table extractor."""
        self.warnings: List[str] = []

    # ==================== MAIN EXTRACTION METHOD ====================

    def extract(
        self,
        markdown_table: str,
        table_id: str,
        source_chunk_id: str,
        source_page_physical: int,
        source_bbox: List[float],
    ) -> Optional[StructuredTable]:
        """
        Convert markdown table to structured representation.

        Args:
            markdown_table: GitHub-flavored markdown table string
            table_id: Unique identifier for this table
            source_chunk_id: Parent chunk ID
            source_page_physical: 0-indexed page number
            source_bbox: [x0, y0, x1, y1] bounding box

        Returns:
            StructuredTable object or None if parsing fails
        """
        self.warnings = []  # Reset warnings

        # Step 1: Parse markdown to raw 2D array
        raw_data = self._parse_markdown_table(markdown_table)
        if not raw_data:
            self.warnings.append("Failed to parse markdown table structure")
            return None

        num_rows = len(raw_data)
        num_cols = len(raw_data[0]) if raw_data else 0

        # Step 2: Detect header rows (typically 1, but can be more)
        num_header_rows = self._detect_header_rows(raw_data)

        # Step 3: Classify columns
        columns = self._classify_columns(raw_data, num_header_rows)

        # Step 4: Parse cells with type detection
        rows = self._parse_rows(raw_data, columns, num_header_rows)

        # Step 5: Extract metadata
        title = self._extract_title(markdown_table)
        monetary_unit = self._detect_monetary_unit(markdown_table, rows)
        time_periods = self._extract_time_periods(columns, rows)
        entities = self._extract_entities(columns, rows)
        has_totals = any(row.row_type in ["total", "subtotal"] for row in rows)

        # Step 6: Build structured table
        structured_table = StructuredTable(
            table_id=table_id,
            source_chunk_id=source_chunk_id,
            source_page_physical=source_page_physical,
            source_bbox=source_bbox,
            columns=columns,
            rows=rows,
            num_rows=num_rows,
            num_cols=num_cols,
            num_header_rows=num_header_rows,
            title=title,
            monetary_unit=monetary_unit,
            time_periods_covered=time_periods,
            entities_covered=entities,
            has_totals=has_totals,
            markdown_representation=markdown_table,
        )

        return structured_table

    # ==================== MARKDOWN PARSING ====================

    def _parse_markdown_table(self, markdown: str) -> List[List[str]]:
        """
        Parse GitHub-flavored markdown table into 2D list.

        Args:
            markdown: Markdown table string

        Returns:
            2D list of cell strings (empty list on failure)
        """
        lines = [line.strip() for line in markdown.strip().split("\n") if line.strip()]

        if len(lines) < 2:
            return []

        rows = []
        for i, line in enumerate(lines):
            # Skip separator row (second line with ---)
            if i == 1 and re.match(r"^\|[\s\-:|]+\|$", line):
                continue

            # Parse cell values
            # Remove leading/trailing pipes and split
            cells = [cell.strip() for cell in line.split("|")]
            # Remove empty first/last elements (from leading/trailing pipes)
            if cells and cells[0] == "":
                cells = cells[1:]
            if cells and cells[-1] == "":
                cells = cells[:-1]

            if cells:
                rows.append(cells)

        return rows

    def _detect_header_rows(self, raw_data: List[List[str]]) -> int:
        """
        Detect number of header rows (typically 1, sometimes multi-level).

        Heuristics:
        - First row is always a header
        - Additional rows are headers if they contain mostly short text
        - Stop at first row with predominantly numeric data

        Args:
            raw_data: 2D list of cell strings

        Returns:
            Number of header rows (minimum 1)
        """
        if not raw_data:
            return 1

        # Always count first row as header
        num_headers = 1

        # Check subsequent rows
        for i in range(1, min(3, len(raw_data))):  # Check up to 3 rows
            row = raw_data[i]
            numeric_count = sum(1 for cell in row if self._is_numeric(cell))

            # If more than 50% of cells are numeric, this is a data row
            if numeric_count > len(row) * 0.5:
                break

            # If most cells are short text, it's likely a header
            short_text_count = sum(1 for cell in row if len(cell) < 30)
            if short_text_count > len(row) * 0.7:
                num_headers += 1
            else:
                break

        return num_headers

    # ==================== COLUMN CLASSIFICATION ====================

    def _classify_columns(
        self, raw_data: List[List[str]], num_header_rows: int
    ) -> List[TableColumn]:
        """
        Classify each column by semantic type and data type.

        Args:
            raw_data: 2D list of cell strings
            num_header_rows: Number of header rows

        Returns:
            List of TableColumn objects
        """
        if not raw_data:
            return []

        num_cols = len(raw_data[0])
        columns = []

        for col_idx in range(num_cols):
            # Extract header text(s)
            header_hierarchy = [
                raw_data[row_idx][col_idx]
                for row_idx in range(num_header_rows)
                if col_idx < len(raw_data[row_idx])
            ]
            header_text = header_hierarchy[0] if header_hierarchy else ""

            # Classify column type
            column_type = self._classify_column_type(header_text, raw_data, col_idx, num_header_rows)

            # Determine dominant data type from data rows
            data_values = [
                raw_data[row_idx][col_idx]
                for row_idx in range(num_header_rows, len(raw_data))
                if col_idx < len(raw_data[row_idx])
            ]
            dominant_data_type = self._determine_dominant_data_type(data_values)

            columns.append(
                TableColumn(
                    col_idx=col_idx,
                    header_text=header_text,
                    header_hierarchy=header_hierarchy,
                    column_type=column_type,
                    dominant_data_type=dominant_data_type,
                )
            )

        return columns

    def _classify_column_type(
        self, header: str, raw_data: List[List[str]], col_idx: int, num_header_rows: int
    ) -> ColumnType:
        """
        Classify column semantic type based on header and content.

        Args:
            header: Column header text
            raw_data: Full table data
            col_idx: Column index
            num_header_rows: Number of header rows

        Returns:
            ColumnType enum value
        """
        header_lower = header.lower()

        # Check header keywords
        if any(kw in header_lower for kw in self.ENTITY_KEYWORDS):
            return ColumnType.ENTITY
        if any(kw in header_lower for kw in self.TIME_KEYWORDS):
            return ColumnType.TIME_PERIOD
        if any(kw in header_lower for kw in self.METRIC_KEYWORDS):
            return ColumnType.METRIC
        if any(kw in header_lower for kw in self.VARIANCE_KEYWORDS):
            return ColumnType.VARIANCE
        if any(kw in header_lower for kw in self.STATUS_KEYWORDS):
            return ColumnType.STATUS

        # Analyze content if header doesn't match
        data_values = [
            raw_data[row_idx][col_idx]
            for row_idx in range(num_header_rows, len(raw_data))
            if col_idx < len(raw_data[row_idx])
        ]

        # Check if contains fiscal years
        fy_matches = sum(1 for val in data_values if self._parse_fiscal_year(val))
        if fy_matches > len(data_values) * 0.5:
            return ColumnType.TIME_PERIOD

        # Check if contains currency
        currency_matches = sum(1 for val in data_values if self._parse_currency(val)[0] is not None)
        if currency_matches > len(data_values) * 0.5:
            return ColumnType.METRIC

        # First column is usually entity if text-heavy
        if col_idx == 0:
            text_count = sum(1 for val in data_values if not self._is_numeric(val))
            if text_count > len(data_values) * 0.5:
                return ColumnType.ENTITY

        return ColumnType.OTHER

    def _determine_dominant_data_type(self, values: List[str]) -> CellDataType:
        """
        Determine most common data type in a list of cell values.

        Args:
            values: List of cell strings

        Returns:
            Most common CellDataType
        """
        if not values:
            return CellDataType.TEXT

        type_counts = Counter()

        for value in values:
            cell_type = self._detect_cell_data_type(value)
            type_counts[cell_type] += 1

        # Return most common type (excluding EMPTY if other types exist)
        if len(type_counts) > 1 and CellDataType.EMPTY in type_counts:
            del type_counts[CellDataType.EMPTY]

        return type_counts.most_common(1)[0][0] if type_counts else CellDataType.TEXT

    # ==================== ROW PARSING ====================

    def _parse_rows(
        self, raw_data: List[List[str]], columns: List[TableColumn], num_header_rows: int
    ) -> List[TableRow]:
        """
        Parse all rows with cell type detection and classification.

        Args:
            raw_data: 2D list of cell strings
            columns: Column metadata
            num_header_rows: Number of header rows

        Returns:
            List of TableRow objects
        """
        rows = []

        for row_idx, raw_row in enumerate(raw_data):
            # Classify row type
            if row_idx < num_header_rows:
                row_type = "header"
            else:
                row_type = self._classify_row_type(raw_row)

            # Parse cells
            cells = []
            for col_idx, raw_text in enumerate(raw_row):
                cell = self._parse_cell(
                    row_idx=row_idx,
                    col_idx=col_idx,
                    raw_text=raw_text,
                    column=columns[col_idx] if col_idx < len(columns) else None,
                    row_type=row_type,
                )
                cells.append(cell)

            rows.append(TableRow(row_idx=row_idx, cells=cells, row_type=row_type))

        return rows

    def _classify_row_type(self, row: List[str]) -> str:
        """
        Classify row as data, total, or subtotal.

        Args:
            row: List of cell strings

        Returns:
            'data', 'total', or 'subtotal'
        """
        if not row:
            return "data"

        # Check first cell for total indicators
        first_cell = row[0].lower().strip()

        for pattern in self.TOTAL_INDICATORS:
            if re.search(pattern, first_cell, re.IGNORECASE):
                if "sub" in first_cell:
                    return "subtotal"
                return "total"

        return "data"

    def _parse_cell(
        self,
        row_idx: int,
        col_idx: int,
        raw_text: str,
        column: Optional[TableColumn],
        row_type: str,
    ) -> TableCell:
        """
        Parse a single cell with type detection and value extraction.

        Args:
            row_idx: Row index
            col_idx: Column index
            raw_text: Raw cell text
            column: Column metadata (for type hints)
            row_type: Row classification

        Returns:
            TableCell object
        """
        # Clean text
        cleaned_text = " ".join(raw_text.split())

        # Detect semantic type
        if row_type == "header":
            semantic_type = CellSemanticType.COLUMN_HEADER
        elif col_idx == 0 and row_type == "data":
            semantic_type = CellSemanticType.ROW_HEADER
        elif row_type == "total":
            semantic_type = CellSemanticType.TOTAL
        elif row_type == "subtotal":
            semantic_type = CellSemanticType.SUBTOTAL
        else:
            semantic_type = CellSemanticType.DATA

        # Detect data type and parse value
        data_type = self._detect_cell_data_type(cleaned_text)
        parsed_value, unit, normalized_value = self._parse_cell_value(
            cleaned_text, data_type, column
        )

        return TableCell(
            row_idx=row_idx,
            col_idx=col_idx,
            raw_text=raw_text,
            cleaned_text=cleaned_text,
            data_type=data_type,
            semantic_type=semantic_type,
            parsed_value=parsed_value,
            unit=unit,
            normalized_value=normalized_value,
        )

    # ==================== CELL TYPE DETECTION ====================

    def _detect_cell_data_type(self, text: str) -> CellDataType:
        """
        Detect data type of cell content.

        Args:
            text: Cleaned cell text

        Returns:
            CellDataType enum value
        """
        if not text or text == "-":
            return CellDataType.EMPTY

        # Check fiscal year
        if self._parse_fiscal_year(text):
            return CellDataType.FISCAL_YEAR

        # Check percentage
        if re.match(self.PERCENTAGE_PATTERN, text):
            return CellDataType.PERCENTAGE

        # Check currency
        if self._parse_currency(text)[0] is not None:
            return CellDataType.CURRENCY

        # Check date
        for pattern in self.DATE_PATTERNS:
            if re.match(pattern, text, re.IGNORECASE):
                return CellDataType.DATE

        # Check integer vs decimal
        if self._is_integer(text):
            return CellDataType.INTEGER
        if self._is_decimal(text):
            return CellDataType.DECIMAL

        # Default to text
        return CellDataType.TEXT

    def _parse_cell_value(
        self, text: str, data_type: CellDataType, column: Optional[TableColumn]
    ) -> Tuple[Optional[Union[str, int, float]], Optional[str], Optional[float]]:
        """
        Parse cell value based on detected type.

        Args:
            text: Cleaned cell text
            data_type: Detected data type
            column: Column metadata for context

        Returns:
            Tuple of (parsed_value, unit, normalized_value)
        """
        if data_type == CellDataType.EMPTY:
            return (None, None, None)

        if data_type == CellDataType.CURRENCY:
            amount, unit = self._parse_currency(text)
            if amount is not None:
                normalized = self._normalize_currency(amount, unit)
                return (amount, unit, normalized)

        if data_type == CellDataType.PERCENTAGE:
            match = re.match(self.PERCENTAGE_PATTERN, text)
            if match:
                value = float(match.group(1).replace(",", ""))
                return (value, "%", value / 100.0)  # Normalize to decimal

        if data_type == CellDataType.FISCAL_YEAR:
            fy_data = self._parse_fiscal_year(text)
            if fy_data:
                return (text, "fiscal_year", None)

        if data_type in [CellDataType.INTEGER, CellDataType.DECIMAL]:
            try:
                cleaned_num = text.replace(",", "")
                if "." in cleaned_num:
                    value = float(cleaned_num)
                else:
                    value = int(cleaned_num)
                return (value, None, float(value))
            except ValueError:
                pass

        # Default: return as text
        return (text, None, None)

    # ==================== CURRENCY PARSING ====================

    def _parse_currency(self, text: str) -> Tuple[Optional[float], Optional[str]]:
        """
        Parse Indian currency formats.

        Handles:
        - ₹847.71 crore
        - ₹23.45 lakh
        - (23.45) → negative
        - Plain numbers

        Args:
            text: Cell text

        Returns:
            Tuple of (amount, unit) or (None, None)
        """
        for pattern, pattern_type in self.CURRENCY_PATTERNS:
            match = re.match(pattern, text, re.IGNORECASE)
            if match:
                try:
                    amount_str = match.group(1).replace(",", "")
                    amount = float(amount_str)

                    # Handle negative values in parentheses
                    if pattern_type == "negative_paren":
                        amount = -amount

                    # Extract unit if present
                    unit = None
                    if pattern_type == "with_unit" and len(match.groups()) > 1:
                        unit = match.group(2).lower()
                        # Normalize unit names
                        if unit.startswith("cr"):
                            unit = "crore"
                        elif unit.startswith("la") or unit.startswith("lac"):
                            unit = "lakh"

                    return (amount, unit)

                except (ValueError, IndexError):
                    continue

        return (None, None)

    def _normalize_currency(self, amount: float, unit: Optional[str]) -> float:
        """
        Normalize currency to paise (smallest unit).

        Args:
            amount: Numeric amount
            unit: Unit string ('crore', 'lakh', etc.)

        Returns:
            Amount in paise
        """
        if unit and unit in self.CURRENCY_MULTIPLIERS:
            multiplier = self.CURRENCY_MULTIPLIERS[unit]
            return amount * multiplier
        else:
            # Assume rupees if no unit specified
            return amount * 100  # Convert rupees to paise

    # ==================== FISCAL YEAR PARSING ====================

    def _parse_fiscal_year(self, text: str) -> Optional[Dict[str, int]]:
        """
        Parse fiscal year formats.

        Args:
            text: Cell text

        Returns:
            Dict with 'start' and 'end' years, or None
        """
        for pattern in self.FISCAL_YEAR_PATTERNS:
            match = re.match(pattern, text.strip(), re.IGNORECASE)
            if match:
                start_year = int(match.group(1))
                end_year_str = match.group(2)

                # Handle 2-digit end year (2021-22 → 2022)
                if len(end_year_str) == 2:
                    end_year = int(str(start_year)[:2] + end_year_str)
                else:
                    end_year = int(end_year_str)

                return {"start": start_year, "end": end_year}

        return None

    # ==================== HELPER METHODS ====================

    def _is_numeric(self, text: str) -> bool:
        """Check if text represents a number."""
        try:
            float(text.replace(",", "").replace("₹", "").replace("`", "").strip())
            return True
        except ValueError:
            return False

    def _is_integer(self, text: str) -> bool:
        """Check if text represents an integer."""
        try:
            cleaned = text.replace(",", "")
            return "." not in cleaned and int(cleaned) is not None
        except ValueError:
            return False

    def _is_decimal(self, text: str) -> bool:
        """Check if text represents a decimal number."""
        try:
            cleaned = text.replace(",", "")
            return "." in cleaned and float(cleaned) is not None
        except ValueError:
            return False

    # ==================== METADATA EXTRACTION ====================

    def _extract_title(self, markdown: str) -> Optional[str]:
        """
        Extract table title from markdown (if present above table).

        Args:
            markdown: Full markdown string

        Returns:
            Title string or None
        """
        # Look for text before first pipe character
        lines = markdown.split("\n")
        for line in lines[:3]:  # Check first 3 lines
            if "|" not in line and line.strip():
                return line.strip()
        return None

    def _detect_monetary_unit(
        self, markdown: str, rows: List[TableRow]
    ) -> Optional[str]:
        """
        Detect monetary unit context (e.g., '₹ in crore').

        Args:
            markdown: Full markdown string
            rows: Parsed table rows

        Returns:
            Unit string or None
        """
        # Check for unit in header or caption
        unit_patterns = [
            r"₹\s*in\s+(crore|lakh|thousand)s?",
            r"Rs\.?\s*in\s+(crore|lakh|thousand)s?",
            r"\(in\s+(crore|lakh|thousand)s?\)",
        ]

        for pattern in unit_patterns:
            match = re.search(pattern, markdown, re.IGNORECASE)
            if match:
                return f"₹ in {match.group(1)}"

        # Infer from cell data
        if rows:
            unit_counts = Counter()
            for row in rows:
                for cell in row.cells:
                    if cell.unit:
                        unit_counts[cell.unit] += 1

            if unit_counts:
                most_common_unit = unit_counts.most_common(1)[0][0]
                return f"₹ in {most_common_unit}"

        return None

    def _extract_time_periods(
        self, columns: List[TableColumn], rows: List[TableRow]
    ) -> List[str]:
        """
        Extract time periods covered in table.

        Args:
            columns: Column metadata
            rows: Parsed rows

        Returns:
            List of time period strings
        """
        time_periods = set()

        # Check column headers
        for col in columns:
            if col.column_type == ColumnType.TIME_PERIOD:
                time_periods.add(col.header_text)
                time_periods.update(col.header_hierarchy)

        # Check cell values
        for row in rows:
            for cell in row.cells:
                if cell.data_type == CellDataType.FISCAL_YEAR:
                    time_periods.add(cell.cleaned_text)

        return sorted(list(time_periods))

    def _extract_entities(
        self, columns: List[TableColumn], rows: List[TableRow]
    ) -> List[str]:
        """
        Extract entities mentioned in table (states, ministries, schemes).

        Args:
            columns: Column metadata
            rows: Parsed rows

        Returns:
            List of entity names
        """
        entities = set()

        # Find entity column
        entity_col_idx = None
        for col in columns:
            if col.column_type == ColumnType.ENTITY:
                entity_col_idx = col.col_idx
                break

        if entity_col_idx is None:
            return []

        # Extract entity names from data rows
        for row in rows:
            if row.row_type == "data" and entity_col_idx < len(row.cells):
                cell = row.cells[entity_col_idx]
                if cell.cleaned_text:
                    entities.add(cell.cleaned_text)

        return sorted(list(entities))[:50]  # Limit to 50 entities
