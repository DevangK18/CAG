"""
MultiPageTableHandler: Detects and merges tables that span multiple pages.

Handles CAG audit reports where tables frequently continue across pages:
- Detects continuation signals (markers, header repetition, column structure)
- Merges table fragments into unified StructuredTable objects
- Preserves all metadata and row classifications
- P0-03: Improved chain iteration, missing-page detection, DLQ red flags

Part of Phase 1 - P0-3: Multi-Page Table Stitching
"""

import logging
import re
from typing import List, Optional, Set, Dict, Any, Tuple
from collections import Counter

from src.core.table_contracts import StructuredTable, TableRow, TableColumn
from src.parsing_pipeline.config import get_config, ChunkingConfig
from src.parsing_pipeline.instrumentation import get_noop_emitter

logger = logging.getLogger(__name__)


# REMEDIATION §5.1: UnionFind for transitive table grouping
class UnionFind:
    """
    Union-Find (Disjoint Set Union) data structure for efficient connected components.

    Used to transitively group table fragments: if A merges with B, and B merges with C,
    then A, B, C form one connected component even if A doesn't directly merge with C.
    """

    def __init__(self, n: int):
        """Initialize n elements, each in its own set."""
        self.parent = list(range(n))
        self.rank = [0] * n

    def find(self, x: int) -> int:
        """Find root of x with path compression."""
        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])
        return self.parent[x]

    def union(self, x: int, y: int) -> bool:
        """Unite sets containing x and y. Returns True if they were separate."""
        px, py = self.find(x), self.find(y)
        if px == py:
            return False
        # Union by rank
        if self.rank[px] < self.rank[py]:
            px, py = py, px
        self.parent[py] = px
        if self.rank[px] == self.rank[py]:
            self.rank[px] += 1
        return True


class MultiPageTableHandler:
    """
    Detects and merges tables that span multiple pages into unified structures.

    Detection signals (in priority order):
    1. Continuation markers: "Contd.", "(continued)", "..." at end of table
    2. Header repetition: Same headers appear on next page
    3. Column structure match: Jaccard similarity > threshold (configured)
    4. Missing totals: First fragment has no "Total" row
    5. Position analysis: Table at bottom → content at top of next page

    P0-03 improvements:
    - Increased gap tolerance (2 → 3 pages) for chain iteration
    - Missing-page detection with DLQ red flags
    - Statistics tracking for quality metrics
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

    # P0-03: Increased gap tolerance from 2 to 3 pages to handle chain iteration
    # This allows merging across 1 missing page in a chain
    MAX_PAGE_GAP = 3  # Tolerates gaps of 1-3 pages

    def __init__(self, config: Optional[ChunkingConfig] = None, trace_emitter=None):
        """Initialize the multi-page table handler with configuration."""
        # Load from config if not provided
        if config is None:
            config = get_config().chunking

        self.column_similarity_threshold = config.multi_page_table_column_similarity_threshold
        self._trace_emitter = trace_emitter or get_noop_emitter()

        self.stats = {
            "tables_processed": 0,
            "tables_merged": 0,
            "total_fragments_merged": 0,
            "missing_pages_detected": 0,  # P0-03: Track missing pages
            "dlq_entries": 0,  # P0-03: Track DLQ red flags
        }
        # M2-FIX: Store actual DLQ entries for processing_metadata output
        self.dlq_entry_list: List[Dict[str, Any]] = []

    # ==================== MAIN DETECTION AND MERGING ====================

    def detect_and_merge(
        self,
        tables: List[StructuredTable],
        trace_emitter=None,
        section_page_ranges: Optional[Dict[str, Tuple[int, int]]] = None,
        contiguous_pairs: Optional[Set[Tuple[str, str]]] = None,
    ) -> List[StructuredTable]:
        """
        Detect table continuations and merge fragments using graph-based transitive closure.

        REMEDIATION §5.1: Replaced greedy left-to-right chain building with UnionFind
        algorithm to handle transitive merging. If A merges with B and B merges with C,
        all three form one group even if A doesn't directly merge with C.

        Args:
            tables: List of StructuredTable objects, ordered by page number
            trace_emitter: Optional TraceEmitter for instrumentation
            section_page_ranges: M1 fix - Optional mapping of source_chunk_id to (start_page, end_page)
                                 for accurate missing page detection at section boundaries
            contiguous_pairs: (prev_table_id, next_table_id) pairs with no heading or body
                              text between them in reading order. When given, only these
                              pairs can merge; a new annexure heading always starts a new table.

        Returns:
            List of merged tables (fewer items than input if merges occurred)
        """
        emitter = trace_emitter or self._trace_emitter
        self._section_page_ranges = section_page_ranges or {}
        self._contiguous_pairs = contiguous_pairs
        # merged table_id -> fragment table_ids, for callers replacing fragments
        self.merge_groups: Dict[str, List[str]] = {}

        if len(tables) < 2:
            self.stats["tables_processed"] = len(tables)
            return tables

        # Sort tables by page number to ensure correct order
        sorted_tables = sorted(tables, key=lambda t: t.source_page_physical)
        n = len(sorted_tables)

        # REMEDIATION §5.1 Phase 1: Build merge graph using Union-Find
        # Check ALL pairs within MAX_PAGE_GAP, not just sequential neighbors
        uf = UnionFind(n)
        merge_decisions = []  # For debugging

        # Only neighbours in page order can be continuations: comparing all pairs within
        # MAX_PAGE_GAP chained separate annexures into one 89K-char "table"
        for i in range(n - 1):
            j = i + 1
            if contiguous_pairs is not None and (
                (sorted_tables[i].table_id, sorted_tables[j].table_id) not in contiguous_pairs
            ):
                continue
            if self._should_merge(sorted_tables[i], sorted_tables[j]):
                uf.union(i, j)
                merge_decisions.append((
                    sorted_tables[i].source_page_physical,
                    sorted_tables[j].source_page_physical,
                    "forward",
                ))

        # REMEDIATION §5.1 Phase 2: Group tables by connected component
        components: Dict[int, List[int]] = {}
        for i in range(n):
            root = uf.find(i)
            components.setdefault(root, []).append(i)

        # Log component formation for debugging
        if len(components) < n:
            logger.debug(f"§5.1: Formed {len(components)} components from {n} tables via {len(merge_decisions)} merges")

        # REMEDIATION §5.1 Phase 3: Merge each component
        merged = []
        for root, indices in components.items():
            # Sort indices by page number within component
            indices.sort(key=lambda i: sorted_tables[i].source_page_physical)

            if len(indices) == 1:
                # No merge needed - single table
                merged.append(sorted_tables[indices[0]])
            else:
                # Merge all fragments in this component
                fragments = [sorted_tables[i] for i in indices]
                merged_table = self._merge_fragments(fragments)

                # P0-03 + M1 fix: Detect missing pages using section page range if available
                expected_span = None
                source_chunk_id = merged_table.source_chunk_id
                if source_chunk_id and source_chunk_id in self._section_page_ranges:
                    expected_span = self._section_page_ranges[source_chunk_id]

                missing_pages = self._detect_missing_pages(merged_table, expected_span)
                if missing_pages:
                    self.stats["missing_pages_detected"] += len(missing_pages)
                    self.stats["dlq_entries"] += 1

                    # Emit DLQ red flag for lost pages
                    emitter.emit_red_flag(
                        "7",
                        "multi_page_table_page_lost",
                        {
                            "table_id": merged_table.table_id,
                            "missing_pages": list(missing_pages),
                            "expected_range": f"{merged_table.source_pages[0]}-{merged_table.source_pages[-1]}",
                            "actual_pages": merged_table.source_pages,
                            "fragment_count": len(fragments),
                        },
                    )
                    logger.warning(
                        f"[{merged_table.table_id}] Missing pages detected: {missing_pages} "
                        f"in range {merged_table.source_pages[0]}-{merged_table.source_pages[-1]}"
                    )

                merged.append(merged_table)
                self.merge_groups[merged_table.table_id] = [f.table_id for f in fragments]
                self.stats["tables_merged"] += 1
                self.stats["total_fragments_merged"] += len(fragments)

        self.stats["tables_processed"] = n

        # M2-FIX: After all merges, detect gaps between consecutive tables
        # This catches boundary pages that have no fragments at all
        sequence_gaps = self._detect_table_sequence_gaps(merged)
        if sequence_gaps:
            self.dlq_entry_list.extend(sequence_gaps)
            self.stats["missing_pages_detected"] += len(sequence_gaps)
            self.stats["dlq_entries"] += len(sequence_gaps)

            # Emit red flags for sequence gap pages
            for entry in sequence_gaps:
                emitter.emit_red_flag(
                    "7",
                    "multi_page_table_page_lost",
                    {
                        "page": entry["page"],
                        "reason": entry["reason"],
                        "context": entry["context"],
                    },
                )

        return merged

    def _detect_missing_pages(
        self, merged_table: StructuredTable, expected_span: Optional[Tuple[int, int]] = None
    ) -> Set[int]:
        """
        D3: Detect missing pages using true expected span (not just extracted min/max).

        After merging, checks for gaps in source_pages. If pages are missing,
        they should either be recovered via tier-3 or logged to DLQ.

        Args:
            merged_table: StructuredTable after merging
            expected_span: (start_page, end_page) from TOC/layout, or None to use extracted range

        Returns:
            Set of missing page numbers (empty if none missing)
        """
        if not merged_table.source_pages or len(merged_table.source_pages) < 2:
            return set()

        pages = sorted(merged_table.source_pages)

        # D3: Use expected_span if provided, else fall back to extracted range
        if expected_span:
            start, end = expected_span
        else:
            # Fallback: use extracted range (can miss boundary pages)
            start, end = pages[0], pages[-1]

        expected = set(range(start, end + 1))
        actual = set(pages)
        missing = expected - actual

        return missing

    def _detect_table_sequence_gaps(
        self, merged_tables: List[StructuredTable]
    ) -> List[Dict[str, Any]]:
        """
        M2-FIX: Detect gaps between consecutive tables that indicate missing pages.

        After all merges, scans for page gaps between tables in the same section.
        Flags pages that likely had tables but failed extraction.

        Args:
            merged_tables: List of merged/standalone tables, sorted by page

        Returns:
            List of DLQ entries for pages in gaps
        """
        if len(merged_tables) < 2:
            return []

        dlq_entries = []
        sorted_tables = sorted(merged_tables, key=lambda t: t.source_page_physical)

        for i in range(len(sorted_tables) - 1):
            prev_table = sorted_tables[i]
            curr_table = sorted_tables[i + 1]

            # Get the end page of prev table (last page in source_pages or source_page_physical)
            prev_end = max(prev_table.source_pages) if prev_table.source_pages else prev_table.source_page_physical
            curr_start = curr_table.source_page_physical

            # Check for gap > 1 page between consecutive tables
            gap_size = curr_start - prev_end - 1
            if gap_size > 0 and gap_size <= 5:  # Only flag small gaps (likely same table run)
                # Check if tables are in the same section (same source_chunk_id)
                same_section = prev_table.source_chunk_id == curr_table.source_chunk_id

                for missing_page in range(prev_end + 1, curr_start):
                    dlq_entries.append({
                        "page": missing_page,
                        "reason": "no_fragment_extracted",
                        "context": {
                            "prev_table_page": prev_end,
                            "next_table_page": curr_start,
                            "same_section": same_section,
                            "section_id": prev_table.source_chunk_id if same_section else None,
                        },
                    })
                    logger.warning(
                        f"M2-DLQ: Page {missing_page} has no table fragment "
                        f"(gap between p{prev_end} and p{curr_start})"
                    )

        return dlq_entries

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
        # P0-03: RULE 1: Allow gap of 1, 2, or 3 pages (tolerates 1-2 missing pages in chain)
        # Increased from max gap of 2 to fix UK long-chain failure mode (11-page tables)
        page_gap = curr.source_page_physical - prev.source_page_physical
        if page_gap < 1 or page_gap > self.MAX_PAGE_GAP:
            return False

        # M1-FIX: RULE 1a: For CONSECUTIVE pages (gap=1), be very lenient
        # OCR artifacts cause column count variations - if pages are consecutive
        # and column counts are close (within ±3), merge. Only safe when the caller
        # confirmed nothing (heading/text) sits between the two tables; without that,
        # unrelated tables on facing pages merged.
        contiguity_known = getattr(self, "_contiguous_pairs", None) is not None
        if contiguity_known and page_gap == 1 and abs(prev.num_cols - curr.num_cols) <= 3:
            logger.debug(
                f"M1: Merging consecutive pages {prev.source_page_physical}->{curr.source_page_physical} "
                f"(cols {prev.num_cols}->{curr.num_cols})"
            )
            return True

        # RULE 2: Strong signal - continuation markers
        if self._has_continuation_marker(prev):
            # Still check basic compatibility (must have similar column counts)
            if abs(prev.num_cols - curr.num_cols) <= 1:
                return True

        # RULE 3: Column structure similarity (Jaccard index)
        col_similarity = self._column_similarity(prev, curr)
        if col_similarity < self.column_similarity_threshold:
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

        # Collect all rows (skipping repeated headers in subsequent fragments),
        # tagging each with its page so split pieces can cite the right page
        all_rows = [
            row.model_copy(update={"source_page_physical": row.source_page_physical
                                   if row.source_page_physical is not None
                                   else base.source_page_physical})
            for row in base.rows
        ]
        all_pages = [base.source_page_physical]
        all_footnotes = list(base.footnotes)

        # Merge subsequent fragments
        for fragment in fragments[1:]:
            # Determine if this fragment has repeated headers
            skip_rows = 0
            if self._has_repeated_header(base, fragment):
                skip_rows = fragment.num_header_rows

            # Append non-header rows from this fragment
            all_rows.extend(
                row.model_copy(update={"source_page_physical": fragment.source_page_physical})
                for row in fragment.rows[skip_rows:]
            )

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
            Dictionary with processing statistics including dlq_entry_list
        """
        result = self.stats.copy()
        # M2-FIX: Include actual DLQ entries (not just count)
        result["dlq_entry_list"] = list(self.dlq_entry_list)
        return result

    def reset_statistics(self):
        """Reset statistics counters."""
        self.stats = {
            "tables_processed": 0,
            "tables_merged": 0,
            "total_fragments_merged": 0,
            "missing_pages_detected": 0,  # P0-03
            "dlq_entries": 0,  # P0-03
        }
        # M2-FIX: Clear DLQ entry list
        self.dlq_entry_list = []
