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

# B-6-10: a printed table caption ("Table 3.2: ...", "Statement No. 5", "Chart IV").
# Running headers such as "Report No. 8 of 2025" are not captions.
TABLE_CAPTION_RE = re.compile(
    r"^[\s*_#]*(?:Table|Statement|Chart)\s*(?:No\.?\s*)?[-–:]?\s*"
    r"((?:\d+|[IVX]+\b)(?:\s*\.\s*\d+)*)",
    re.IGNORECASE,
)
# An appendix or annexure heading printed over its table: a title, but its number
# is not a table number
APPENDIX_TITLE_RE = re.compile(r"^[\s*_#]*(?:Appendix|Annexure|Annex)\s*[-–:]?\s*[\dIVX]", re.IGNORECASE)
# A markdown delimiter row: | --- | :---: | (each cell three or more dashes)
_SEPARATOR_CELL_RE = re.compile(r"^:?-{3,}:?$")
# A serial number cell: "1", "1.", "(1)", "23)", "iv.", "(ii)"
_SERIAL_RE = re.compile(r"^(?:\(?\d{1,3}[.)]?|\(?[ivx]{1,5}[.)])$", re.IGNORECASE)


def split_markdown_cells(line: str) -> List[str]:
    """Cells of one markdown table line; "\\|" inside a cell is a literal pipe."""
    cells = [cell.strip().replace("\\|", "|") for cell in re.split(r"(?<!\\)\|", line.strip())]
    # Leading/trailing pipes leave empty first/last elements
    if cells and cells[0] == "":
        cells = cells[1:]
    if cells and cells[-1] == "":
        cells = cells[:-1]
    return cells


def is_markdown_separator(line: str) -> bool:
    """True for a markdown delimiter row, wherever it sits in the table."""
    if "|" not in line or "-" not in line:
        return False
    cells = split_markdown_cells(line)
    return bool(cells) and all(_SEPARATOR_CELL_RE.match(c.replace(" ", "")) for c in cells)


def split_table_markdown(markdown: str) -> Tuple[List[str], List[str], List[str]]:
    """
    Split table markdown into (leading non-pipe lines, table lines, trailing lines).

    Docling's export puts whatever it bound as caption (often a running header) on a
    line before the table; those lines are caption candidates, not row 0.
    """
    lines = [line.strip() for line in (markdown or "").strip().split("\n") if line.strip()]
    first = next((i for i, line in enumerate(lines) if "|" in line), None)
    if first is None:
        return lines, [], []
    last = max(i for i, line in enumerate(lines) if "|" in line)
    table = [line for line in lines[first:last + 1] if "|" in line]
    return lines[:first], table, lines[last + 1:]


def parse_table_caption(text: Optional[str]) -> Optional[Tuple[str, str]]:
    """(caption, table_number) if text is a printed table caption, else None."""
    if not text:
        return None
    caption = " ".join(text.strip().strip("*_#").split())
    match = TABLE_CAPTION_RE.match(caption)
    if not match:
        return None
    return caption, re.sub(r"\s+", "", match.group(1))


def is_serial_number(text: str) -> bool:
    """A cell holding only a serial number ("1.", "(2)", "iv)")."""
    return bool(_SERIAL_RE.match((text or "").strip()))


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

    # B-6-11: table/column unit context, e.g. "(₹ in crore)", "Amount (Rs. in lakh)"
    TABLE_UNIT_PATTERN = re.compile(
        r"(?:₹|`|Rs\.?|INR|amount|figures?)\s*(?:in\s+)?(?:₹\s*)?"
        r"(lakh\s+crore|crore|lakh|lac|thousand)s?\b"
        r"|\(\s*in\s+(?:₹\s*)?(lakh\s+crore|crore|lakh|lac|thousand)s?\s*\)",
        re.IGNORECASE,
    )
    # A column header that names money without a unit: values are rupees
    MONEY_HEADER_PATTERN = re.compile(r"₹|`|\bRs\b\.?|\bINR\b|\bamount\b", re.IGNORECASE)
    # Columns that hold counts, shares or years even inside a "(₹ in crore)" table
    NON_MONEY_HEADER_PATTERN = re.compile(
        r"\b(?:no|nos|number|count|sl|s\.\s*no|per\s*cent|percentage|year|years|ratio|units?)\b|%|\bno\.",
        re.IGNORECASE,
    )

    # Currency unit to paise multipliers
    CURRENCY_MULTIPLIERS = {
        "lakh crore": 10**14,  # 1 lakh crore = 10^12 rupees
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
        caption: Optional[str] = None,
    ) -> Optional[StructuredTable]:
        """
        Convert markdown table to structured representation.

        Args:
            markdown_table: GitHub-flavored markdown table string
            table_id: Unique identifier for this table
            source_chunk_id: Phase 6 block ID of the table
            source_page_physical: 0-indexed page number
            source_bbox: [x0, y0, x1, y1] bounding box
            caption: Caption bound to the table by the caller, if any; otherwise a
                leading "Table x.y" line of the markdown is used

        Returns:
            StructuredTable object or None if parsing fails
        """
        self.warnings = []  # Reset warnings

        # Step 1: Parse markdown to raw 2D array; rows above the separator are headers
        raw_data, separator_rows = self._parse_markdown_rows(markdown_table)
        if not raw_data:
            self.warnings.append("Failed to parse markdown table structure")
            return None

        # B-6-10: width is the widest row, not row 0 (which may be a caption line)
        num_rows = len(raw_data)
        num_cols = max(len(row) for row in raw_data)
        raw_data = [row + [""] * (num_cols - len(row)) for row in raw_data]

        # Step 2: Detect header rows (typically 1, but can be more)
        num_header_rows = self._detect_header_rows(raw_data, separator_rows)

        # Step 3: Classify columns
        columns = self._classify_columns(raw_data, num_header_rows)

        # Step 4: Parse cells with type detection. B-6-11: plain numbers are money
        # only in a column with a monetary unit, and then take that unit
        table_unit = self._detect_table_unit(markdown_table, raw_data[:num_header_rows])
        column_units = [self._column_money_unit(col, table_unit) for col in columns]
        for col, unit in zip(columns, column_units):
            if unit and col.dominant_data_type in (CellDataType.INTEGER, CellDataType.DECIMAL):
                col.dominant_data_type = CellDataType.CURRENCY
        rows = self._parse_rows(raw_data, columns, num_header_rows, column_units)

        # Step 5: Extract metadata
        parsed_caption = parse_table_caption(caption) if caption else None
        if parsed_caption is None:
            parsed_caption = self._extract_caption(markdown_table)
        if parsed_caption:
            title, table_number = parsed_caption
        else:
            # A bound caption without a number is still the title
            title = " ".join(caption.split()) if caption else None
            table_number = None
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
            caption=title,
            table_number=table_number,
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
        return self._parse_markdown_rows(markdown)[0]

    def _parse_markdown_rows(self, markdown: str) -> Tuple[List[List[str]], Optional[int]]:
        """
        Parse markdown into rows, and the number of rows above the first separator.

        B-6-10: lines without a pipe (captions such as "Table 3.2 (₹ in crore)", or a
        running header Docling bound as caption) are not rows; separator rows are
        found by pattern on any line and are never data rows.

        Returns:
            (2D list of cell strings, rows above the separator or None if there is none)
        """
        _, lines, _ = split_table_markdown(markdown)
        rows: List[List[str]] = []
        separator_rows: Optional[int] = None
        for line in lines:
            if is_markdown_separator(line):
                if separator_rows is None:
                    separator_rows = len(rows)
                continue
            cells = split_markdown_cells(line)
            if cells:
                rows.append(cells)

        # A lone row is a caption or a fragment, not a table
        if len(rows) < 2 and not (rows and separator_rows is not None):
            return [], None
        return rows, separator_rows

    def _detect_header_rows(
        self, raw_data: List[List[str]], separator_rows: Optional[int] = None
    ) -> int:
        """
        Detect number of header rows.

        B-6-09: the header is the rows above the markdown separator (row 0 when there
        is none). A further row is a header only in the multi-level pattern: no
        numeric cell, and an empty or spanned cell, under a row that spans columns
        this row splits. A row led by a serial number ("1. | Nor | Kullu | 0.39") is
        data, never a header, so a continuation fragment can have no header at all.

        Args:
            raw_data: 2D list of cell strings
            separator_rows: Rows above the markdown separator, if one was found

        Returns:
            Number of header rows
        """
        if not raw_data:
            return 1

        base = separator_rows if separator_rows else 1
        base = min(base, len(raw_data))
        num_headers = 0
        while num_headers < base and not self._is_serial_led(raw_data[num_headers]):
            num_headers += 1
        if num_headers < base:
            return num_headers

        # Up to two sub-header rows under the separator header
        while num_headers < min(base + 2, len(raw_data) - 1):
            if self._is_sub_header_row(raw_data[num_headers], raw_data[num_headers - 1]):
                num_headers += 1
            else:
                break
        return num_headers

    @staticmethod
    def _is_serial_led(row: List[str]) -> bool:
        """True if the row's first non-empty cell (within the first two) is a serial number."""
        for cell in row[:2]:
            if cell.strip():
                return is_serial_number(cell)
        return False

    def _is_sub_header_row(self, row: List[str], above: List[str]) -> bool:
        """Multi-level header pattern: sub-headings under a header that spans columns."""
        if self._is_serial_led(row):
            return False
        if any(self._is_numeric(cell) for cell in row if cell.strip()):
            return False
        if any(len(cell) >= 40 for cell in row):
            return False

        def spanned(cells: List[str], i: int) -> bool:
            # Empty, or Docling's copy of a spanning cell's text
            return not cells[i].strip() or (i > 0 and cells[i] == cells[i - 1])

        has_span = any(
            spanned(row, i) or (i < len(above) and row[i] == above[i] and row[i].strip())
            for i in range(len(row))
        )
        # The row above spans a column this row gives its own heading
        splits_above = any(
            i < len(above) and spanned(above, i) and row[i].strip() and row[i] != above[i]
            for i in range(len(row))
        )
        return has_span and splits_above

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

        num_cols = max(len(row) for row in raw_data)
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

        # A fiscal-year heading ("2021-22") makes a per-year column
        if self._parse_fiscal_year(header):
            return ColumnType.TIME_PERIOD

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
        self,
        raw_data: List[List[str]],
        columns: List[TableColumn],
        num_header_rows: int,
        column_units: Optional[List[Optional[str]]] = None,
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
                    money_unit=(
                        column_units[col_idx]
                        if column_units and col_idx < len(column_units) and row_type != "header"
                        else None
                    ),
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

        # The row label is the first cell, or the next one when column 1 is a serial
        # number or empty ("| 23 | Total | ... |", "| | Total | 42.67 |")
        label = ""
        for idx, cell in enumerate(row[:3]):
            text = cell.lower().strip()
            if text and not is_serial_number(text):
                # Past column 1 only a short label counts ("Total", not
                # "Total Sanitation Campaign works in 12 districts")
                label = text if idx == 0 or len(text) <= 30 else ""
                break

        for pattern in self.TOTAL_INDICATORS:
            if re.search(pattern, label, re.IGNORECASE):
                if "sub" in label:
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
        money_unit: Optional[str] = None,
    ) -> TableCell:
        """
        Parse a single cell with type detection and value extraction.

        Args:
            row_idx: Row index
            col_idx: Column index
            raw_text: Raw cell text
            column: Column metadata (for type hints)
            row_type: Row classification
            money_unit: Monetary unit of the column ("crore", "lakh", "rupee") or None

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
        data_type = self._detect_cell_data_type(cleaned_text, money_unit)
        parsed_value, unit, normalized_value = self._parse_cell_value(
            cleaned_text, data_type, column, money_unit
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

    def _detect_cell_data_type(self, text: str, money_unit: Optional[str] = None) -> CellDataType:
        """
        Detect data type of cell content.

        Args:
            text: Cleaned cell text
            money_unit: Column monetary unit; without one, a plain number is a
                number, not currency (B-6-11)

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
        if self._parse_currency(text, allow_plain=money_unit is not None)[0] is not None:
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
        self,
        text: str,
        data_type: CellDataType,
        column: Optional[TableColumn],
        money_unit: Optional[str] = None,
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
                # B-6-11: "847.71" in a "(₹ in crore)" column is 847.71 crore
                if unit is None and money_unit and money_unit != "rupee":
                    unit = money_unit
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

    def _parse_currency(
        self, text: str, allow_plain: bool = True
    ) -> Tuple[Optional[float], Optional[str]]:
        """
        Parse Indian currency formats.

        Handles:
        - ₹847.71 crore
        - ₹23.45 lakh
        - (23.45) → negative
        - Plain numbers

        Args:
            text: Cell text
            allow_plain: Also read plain and "(23.45)" numbers as currency

        Returns:
            Tuple of (amount, unit) or (None, None)
        """
        for pattern, pattern_type in self.CURRENCY_PATTERNS:
            if not allow_plain and pattern_type in ("plain_number", "negative_paren"):
                continue
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

    def _extract_caption(self, markdown: str) -> Optional[Tuple[str, Optional[str]]]:
        """
        B-6-10: (caption, table_number) from a leading "Table x.y" line, or (title,
        None) from a leading "Appendix 5.2 ..." line.

        Other leading lines (a running header such as "Report No. 8 of 2025", a unit
        or source line) are not titles.
        """
        leading, _, _ = split_table_markdown(markdown)
        for line in leading:
            parsed = parse_table_caption(line)
            if parsed:
                return parsed
        for line in leading:
            if APPENDIX_TITLE_RE.match(line):
                return " ".join(line.strip().strip("*_#").split()), None
        return None

    def _detect_table_unit(
        self, markdown: str, header_rows: List[List[str]]
    ) -> Optional[str]:
        """B-6-11: Unit stated for the whole table, in its caption or header rows."""
        caption = " ".join(line for line in markdown.split("\n") if "|" not in line)
        match = self.TABLE_UNIT_PATTERN.search(caption)
        if match:
            return self._canonical_unit(match.group(1) or match.group(2))
        # A header cell holding only the unit, e.g. "| (₹ in crore) | | |"; a unit
        # inside a column header ("Amount (₹ in lakh)") belongs to that column only
        for row in header_rows:
            for cell in row:
                match = self.TABLE_UNIT_PATTERN.search(cell)
                if match and len(cell.strip(" ()*")) <= len(match.group(0)) + 2:
                    return self._canonical_unit(match.group(1) or match.group(2))
        return None

    def _column_money_unit(
        self, column: TableColumn, table_unit: Optional[str]
    ) -> Optional[str]:
        """B-6-11: Monetary unit of a column, or None if its plain numbers are not money."""
        header = " ".join(column.header_hierarchy or [column.header_text or ""])
        match = self.TABLE_UNIT_PATTERN.search(header)
        if match:
            return self._canonical_unit(match.group(1) or match.group(2))
        if self.NON_MONEY_HEADER_PATTERN.search(header):
            return None
        if table_unit:
            return table_unit
        if self.MONEY_HEADER_PATTERN.search(header):
            return "rupee"
        return None

    @staticmethod
    def _canonical_unit(unit: str) -> str:
        unit = re.sub(r"\s+", " ", unit.lower())
        return "lakh" if unit == "lac" else unit

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
