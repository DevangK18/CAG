"""
MultiPageTableHandler: Detects and merges tables that span multiple pages.

Handles CAG audit reports where tables frequently continue across pages:
- Detects continuation signals (markers, header repetition, column structure)
- Merges table fragments into unified StructuredTable objects
- Preserves all metadata and row classifications

Part of Phase 1 - P0-3: Multi-Page Table Stitching
"""

import re
from typing import List, Optional, Set
from collections import Counter

from src.core.table_contracts import StructuredTable, TableRow, TableColumn


class MultiPageTableHandler:
    """
    Detects and merges tables that span multiple pages into unified structures.

    Detection signals (in priority order):
    1. Continuation markers: "Contd.", "(continued)", "..." at end of table
    2. Header repetition: Same headers appear on next page
    3. Column structure match: Jaccard similarity > 0.8
    4. Missing totals: First fragment has no "Total" row
    5. Position analysis: Table at bottom → content at top of next page
    """

    # Continuation marker patterns (case-insensitive)
    CONTINUATION_MARKERS = [
        r'\bcontd\.?\b',           # "Contd.", "Contd"
        r'\bcontinued\b',          # "continued"
        r'\(contd\.?\)',           # "(contd.)", "(contd)"
        r'\(continued\)',          # "(continued)"
        r'\.{3,}$',                # "..." at end of line
        r'\bcontinues?\b',         # "continue", "continues"
    ]

    # Similarity threshold for column structure matching
    COLUMN_SIMILARITY_THRESHOLD = 0.8

    def __init__(self):
        """Initialize the multi-page table handler."""
        self.stats = {
            "tables_processed": 0,
            "tables_merged": 0,
            "total_fragments_merged": 0,
        }

    # ==================== MAIN DETECTION AND MERGING ====================

    def detect_and_merge(
        self, tables: List[StructuredTable]
    ) -> List[StructuredTable]:
        """
        Detect table continuations and merge fragments.

        Args:
            tables: List of StructuredTable objects, ordered by page number

        Returns:
            List of merged tables (fewer items than input if merges occurred)
        """
        if len(tables) < 2:
            self.stats["tables_processed"] = len(tables)
            return tables

        # Sort tables by page number to ensure correct order
        sorted_tables = sorted(tables, key=lambda t: t.source_page_physical)

        merged = []
        i = 0

        while i < len(sorted_tables):
            current = sorted_tables[i]

            # Look for continuation on subsequent pages
            fragments = [current]
            j = i + 1

            while j < len(sorted_tables) and self._should_merge(
                fragments[-1], sorted_tables[j]
            ):
                fragments.append(sorted_tables[j])
                j += 1

            # Merge if multiple fragments detected
            if len(fragments) > 1:
                merged_table = self._merge_fragments(fragments)
                merged.append(merged_table)
                self.stats["tables_merged"] += 1
                self.stats["total_fragments_merged"] += len(fragments)
            else:
                merged.append(current)

            i = j  # Skip processed fragments

        self.stats["tables_processed"] = len(sorted_tables)
        return merged

    def _should_merge(
        self, prev: StructuredTable, curr: StructuredTable
    ) -> bool:
        """
        Determine if two tables should be merged.

        Args:
            prev: Previous table (potential first/intermediate fragment)
            curr: Current table (potential continuation)

        Returns:
            True if tables should be merged, False otherwise
        """
        # RULE 1: Must be consecutive or near-consecutive pages
        # Allow up to 1 page gap (for page break artifacts)
        page_gap = curr.source_page_physical - prev.source_page_physical
        if page_gap < 1 or page_gap > 2:
            return False

        # RULE 2: Strong signal - continuation markers
        if self._has_continuation_marker(prev):
            # Still check basic compatibility (must have similar column counts)
            if abs(prev.num_cols - curr.num_cols) <= 1:
                return True

        # RULE 3: Column structure similarity (Jaccard index)
        col_similarity = self._column_similarity(prev, curr)
        if col_similarity < self.COLUMN_SIMILARITY_THRESHOLD:
            return False  # Not similar enough to be same table

        # RULE 4: Additional validation for high-similarity tables
        # Check if header is repeated (strong continuation signal)
        if self._has_repeated_header(prev, curr):
            return True

        # Check if previous fragment is missing totals
        if not self._has_total_row(prev):
            # If no total row AND high column similarity, likely a continuation
            return True

        # RULE 5: Default to NOT merging if signals are weak
        # (prevents false positives)
        return False

    # ==================== DETECTION METHODS ====================

    def _has_continuation_marker(self, table: StructuredTable) -> bool:
        """
        Check if table has continuation markers.

        Looks for markers in:
        - Last row's first cell (common position)
        - Title/caption
        - Markdown representation (anywhere)

        Args:
            table: StructuredTable to check

        Returns:
            True if continuation marker found
        """
        # Check last row's first cell (most common location)
        if table.rows:
            last_row = table.rows[-1]
            if last_row.cells:
                first_cell_text = last_row.cells[0].cleaned_text.lower()
                for pattern in self.CONTINUATION_MARKERS:
                    if re.search(pattern, first_cell_text, re.IGNORECASE):
                        return True

        # Check title/caption
        if table.title:
            title_lower = table.title.lower()
            for pattern in self.CONTINUATION_MARKERS:
                if re.search(pattern, title_lower, re.IGNORECASE):
                    return True

        # Check markdown representation (last 100 chars)
        markdown_tail = table.markdown_representation[-100:].lower()
        for pattern in self.CONTINUATION_MARKERS:
            if re.search(pattern, markdown_tail, re.IGNORECASE):
                return True

        return False

    def _column_similarity(
        self, prev: StructuredTable, curr: StructuredTable
    ) -> float:
        """
        Calculate Jaccard similarity of column headers.

        Jaccard index = |A ∩ B| / |A ∪ B|

        Args:
            prev: Previous table
            curr: Current table

        Returns:
            Similarity score between 0.0 and 1.0
        """
        # Extract header texts from both tables
        prev_headers = self._extract_column_headers(prev)
        curr_headers = self._extract_column_headers(curr)

        if not prev_headers or not curr_headers:
            return 0.0

        # Convert to sets for Jaccard calculation
        prev_set = set(prev_headers)
        curr_set = set(curr_headers)

        # Calculate Jaccard index
        intersection = len(prev_set & curr_set)
        union = len(prev_set | curr_set)

        if union == 0:
            return 0.0

        return intersection / union

    def _extract_column_headers(self, table: StructuredTable) -> List[str]:
        """
        Extract normalized column header texts.

        Args:
            table: StructuredTable

        Returns:
            List of normalized header strings
        """
        headers = []

        for col in table.columns:
            # Use primary header text
            header = col.header_text.strip().lower()
            # Normalize whitespace
            header = " ".join(header.split())
            if header:
                headers.append(header)

        return headers

    def _has_repeated_header(
        self, prev: StructuredTable, curr: StructuredTable
    ) -> bool:
        """
        Check if current table repeats the header from previous table.

        Args:
            prev: Previous table
            curr: Current table

        Returns:
            True if headers are repeated (≥80% match)
        """
        # Get header rows from both tables
        if curr.num_header_rows == 0 or prev.num_header_rows == 0:
            return False

        # Compare first header row (most common case)
        prev_header_texts = self._get_header_row_texts(prev, 0)
        curr_header_texts = self._get_header_row_texts(curr, 0)

        if not prev_header_texts or not curr_header_texts:
            return False

        # Calculate match percentage
        matches = sum(
            1
            for p, c in zip(prev_header_texts, curr_header_texts)
            if self._headers_match(p, c)
        )

        max_len = max(len(prev_header_texts), len(curr_header_texts))
        match_rate = matches / max_len if max_len > 0 else 0.0

        return match_rate >= 0.8

    def _get_header_row_texts(
        self, table: StructuredTable, header_row_idx: int
    ) -> List[str]:
        """
        Extract text from a specific header row.

        Args:
            table: StructuredTable
            header_row_idx: Index of header row (0-based)

        Returns:
            List of cell texts from that header row
        """
        if header_row_idx >= len(table.rows):
            return []

        row = table.rows[header_row_idx]
        return [cell.cleaned_text.strip().lower() for cell in row.cells]

    def _headers_match(self, text1: str, text2: str) -> bool:
        """
        Check if two header texts match (fuzzy comparison).

        Args:
            text1: First header text
            text2: Second header text

        Returns:
            True if headers match (case-insensitive, whitespace-normalized)
        """
        # Normalize both texts
        norm1 = " ".join(text1.split()).lower()
        norm2 = " ".join(text2.split()).lower()

        # Exact match
        if norm1 == norm2:
            return True

        # Substring match (one contains the other)
        if norm1 in norm2 or norm2 in norm1:
            return True

        return False

    def _has_total_row(self, table: StructuredTable) -> bool:
        """
        Check if table has a total or subtotal row.

        Args:
            table: StructuredTable

        Returns:
            True if table has total/subtotal row
        """
        if not table.rows:
            return False

        # Check last few rows for totals (typically at end)
        check_rows = table.rows[-3:]  # Check last 3 rows

        for row in check_rows:
            if row.row_type in ["total", "subtotal"]:
                return True

        return False

    # ==================== MERGING LOGIC ====================

    def _merge_fragments(self, fragments: List[StructuredTable]) -> StructuredTable:
        """
        Merge multiple table fragments into one unified StructuredTable.

        Args:
            fragments: List of StructuredTable fragments (in page order)

        Returns:
            Merged StructuredTable
        """
        if not fragments:
            raise ValueError("Cannot merge empty fragment list")

        if len(fragments) == 1:
            return fragments[0]

        base = fragments[0]

        # Collect all rows (skipping repeated headers in subsequent fragments)
        all_rows = list(base.rows)
        all_pages = [base.source_page_physical]
        all_footnotes = list(base.footnotes)

        # Merge subsequent fragments
        for fragment in fragments[1:]:
            # Determine if this fragment has repeated headers
            skip_rows = 0
            if self._has_repeated_header(base, fragment):
                skip_rows = fragment.num_header_rows

            # Append non-header rows from this fragment
            all_rows.extend(fragment.rows[skip_rows:])

            # Collect page numbers
            all_pages.append(fragment.source_page_physical)

            # Collect footnotes (deduplicate)
            all_footnotes.extend(fragment.footnotes)

        # Deduplicate footnotes
        unique_footnotes = list(dict.fromkeys(all_footnotes))

        # Regenerate markdown representation
        merged_markdown = self._regenerate_markdown(all_rows, base.columns)

        # Merge time periods and entities
        all_time_periods = set(base.time_periods_covered)
        all_entities = set(base.entities_covered)

        for fragment in fragments[1:]:
            all_time_periods.update(fragment.time_periods_covered)
            all_entities.update(fragment.entities_covered)

        # Check if merged table has totals
        has_totals = any(row.row_type in ["total", "subtotal"] for row in all_rows)

        # Create merged table
        merged_table = StructuredTable(
            table_id=f"{base.table_id}_merged",
            source_chunk_id=base.source_chunk_id,
            source_page_physical=base.source_page_physical,  # Start page
            source_pages=all_pages,  # All pages
            source_bbox=base.source_bbox,  # Use first fragment's bbox
            is_multi_page=True,  # Mark as multi-page
            columns=base.columns,  # Column structure from base
            rows=all_rows,
            num_rows=len(all_rows),
            num_cols=base.num_cols,
            num_header_rows=base.num_header_rows,
            title=base.title,
            monetary_unit=base.monetary_unit,
            time_periods_covered=sorted(list(all_time_periods)),
            entities_covered=sorted(list(all_entities)),
            has_totals=has_totals,
            footnotes=unique_footnotes,
            markdown_representation=merged_markdown,
        )

        return merged_table

    def _regenerate_markdown(
        self, rows: List[TableRow], columns: List[TableColumn]
    ) -> str:
        """
        Regenerate markdown representation from merged rows.

        Args:
            rows: All rows (including headers)
            columns: Column metadata

        Returns:
            GitHub-flavored markdown string
        """
        if not rows:
            return ""

        markdown_lines = []
        num_cols = len(columns) if columns else (len(rows[0].cells) if rows else 0)

        # Add header row(s)
        for i, row in enumerate(rows):
            if row.row_type != "header":
                break  # Stop at first non-header row

            # Build row string
            cells_text = [cell.cleaned_text for cell in row.cells]
            # Pad to column count
            while len(cells_text) < num_cols:
                cells_text.append("")

            row_str = " | ".join(cells_text)
            markdown_lines.append(f"| {row_str} |")

            # Add separator after first header row
            if i == 0:
                separator = " | ".join(["---"] * num_cols)
                markdown_lines.append(f"| {separator} |")

        # Add data rows
        for row in rows:
            if row.row_type == "header":
                continue  # Already added

            cells_text = [cell.cleaned_text for cell in row.cells]
            # Pad to column count
            while len(cells_text) < num_cols:
                cells_text.append("")

            row_str = " | ".join(cells_text)
            markdown_lines.append(f"| {row_str} |")

        return "\n".join(markdown_lines)

    # ==================== UTILITY METHODS ====================

    def get_statistics(self) -> dict:
        """
        Get statistics about processed and merged tables.

        Returns:
            Dictionary with processing statistics
        """
        return self.stats.copy()

    def reset_statistics(self):
        """Reset statistics counters."""
        self.stats = {
            "tables_processed": 0,
            "tables_merged": 0,
            "total_fragments_merged": 0,
        }
