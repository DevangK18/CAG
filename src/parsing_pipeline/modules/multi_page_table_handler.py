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
from typing import Callable, List, Optional, Set, Dict, Any, Tuple

from src.core.table_contracts import StructuredTable, TableRow, TableColumn
from src.parsing_pipeline.config import get_config, ChunkingConfig
from src.parsing_pipeline.instrumentation import get_noop_emitter

logger = logging.getLogger(__name__)


# A numeric token on a page line: 1,234 / 12.50 / (23.45) / 2019
_NUMERIC_TOKEN_RE = re.compile(r"^[(\-₹`]*\d[\d,]*(?:\.\d+)?\)?%?$")


def heading_section_keys(content: List[Any], order_key: Callable[[Any], Any]) -> Dict[str, Optional[str]]:
    """
    B-6-01: section key per table block ID: the last heading before it in reading order.

    Block IDs that are missing or shared ("temp" in Phase 6 output written before
    block IDs existed) are left out, so those tables' sections are unknown.
    """
    keys: Dict[str, Optional[str]] = {}
    seen: Set[str] = set()
    heading: Optional[str] = None
    for item in sorted(content, key=order_key):
        if item.content_type == "header":
            heading = f"{item.source_page_physical}:{(item.content or '').strip()[:60]}"
        elif item.content_type == "table_markdown" and item.structured_data:
            block_id = item.structured_data.get("source_chunk_id")
            if not block_id or block_id == "temp":
                continue
            if block_id in seen:
                keys.pop(block_id, None)
                continue
            seen.add(block_id)
            keys[block_id] = heading
    return keys


class GapPageProbe:
    """
    B-6-02: does a page with no table fragment still hold a table?

    True when pdfplumber finds a ruled table there, or when at least 3 text rows
    carry 3 or more numbers (a third of their words or more), not counting words
    inside extracted figures (chart labels). Pages are checked lazily, once each.
    """

    def __init__(
        self,
        pdf_path: Optional[str],
        extracted_table_pages: Optional[Set[int]] = None,
        figure_boxes: Optional[Dict[int, List[List[float]]]] = None,
    ):
        self.pdf_path = pdf_path
        self.extracted_table_pages = extracted_table_pages or set()
        self.figure_boxes = figure_boxes or {}
        self._cache: Dict[int, bool] = {}
        self._plumber = None
        self._fitz = None

    def __call__(self, page: int) -> bool:
        if page not in self._cache:
            self._cache[page] = self._check(page)
        return self._cache[page]

    def _check(self, page: int) -> bool:
        if page in self.extracted_table_pages:
            return False  # extracted (as a table or a table image), not lost
        if not self.pdf_path:
            return False
        try:
            return self._has_numeric_rows(page) or self._has_ruled_table(page)
        except Exception as e:
            logger.debug(f"M2-DLQ: could not inspect page {page}: {e}")
            return False

    def _has_numeric_rows(self, page: int) -> bool:
        import fitz

        if self._fitz is None:
            self._fitz = fitz.open(self.pdf_path)
        if page >= self._fitz.page_count:
            return False
        rows: Dict[int, List[str]] = {}
        for word in self._fitz[page].get_text("words"):
            if self._in_figure(page, word[:4]):
                continue
            rows.setdefault(round((word[1] + word[3]) / 6), []).append(word[4])
        numeric_rows = 0
        for words in rows.values():
            numbers = sum(1 for w in words if _NUMERIC_TOKEN_RE.match(w))
            if numbers >= 3 and numbers * 3 >= len(words):
                numeric_rows += 1
        return numeric_rows >= 3

    def _has_ruled_table(self, page: int) -> bool:
        import pdfplumber

        if self._plumber is None:
            self._plumber = pdfplumber.open(self.pdf_path)
        if page >= len(self._plumber.pages):
            return False
        pl_page = self._plumber.pages[page]
        try:
            tables = pl_page.find_tables(
                table_settings={"vertical_strategy": "lines", "horizontal_strategy": "lines"}
            )
            # Chart gridlines are ruled too: a "table" inside a figure is not one
            return any(
                len(t.rows) >= 2 and len(t.rows[0].cells) >= 2 and not self._in_figure(page, t.bbox)
                for t in tables
            )
        finally:
            pl_page.close()

    def _in_figure(self, page: int, bbox) -> bool:
        """True if the centre of bbox lies inside an extracted figure on the page."""
        cx, cy = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
        return any(
            b[0] <= cx <= b[2] and b[1] <= cy <= b[3] for b in self.figure_boxes.get(page, [])
        )

    def close(self):
        for doc in (self._plumber, self._fitz):
            if doc is not None:
                try:
                    doc.close()
                except Exception:
                    pass
        self._plumber = self._fitz = None


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
        contiguous_pairs: Optional[Set[Tuple[str, str]]] = None,
        section_keys: Optional[Dict[str, Optional[str]]] = None,
        gap_page_probe: Optional[Callable[[int], bool]] = None,
        lost_table_pages: Optional[Set[int]] = None,
    ) -> List[StructuredTable]:
        """
        Detect table continuations and merge fragments using graph-based transitive closure.

        REMEDIATION §5.1: Replaced greedy left-to-right chain building with UnionFind
        algorithm to handle transitive merging. If A merges with B and B merges with C,
        all three form one group even if A doesn't directly merge with C.

        Args:
            tables: List of StructuredTable objects, ordered by page number
            trace_emitter: Optional TraceEmitter for instrumentation
            contiguous_pairs: (prev_table_id, next_table_id) pairs with no heading or body
                              text between them in reading order. When given, only these
                              pairs can merge; a new annexure heading always starts a new table.
            section_keys: B-6-01: section of each table, keyed by its source_chunk_id
                          (the Phase 6 block ID). Tables in different sections never
                          merge; a missing or None key means unknown and blocks nothing.
            gap_page_probe: B-6-02: page -> True if the page looks like it holds a table.
                            A page between two tables is flagged as lost only if this
                            says so; without a probe nothing is flagged.
            lost_table_pages: pages where layout found a table that no extracted item
                              accounts for; flagged when they fall between two tables
                              whatever the tables look like.

        Returns:
            List of merged tables (fewer items than input if merges occurred)
        """
        emitter = trace_emitter or self._trace_emitter
        self._contiguous_pairs = contiguous_pairs
        self._section_keys = section_keys or {}
        # merged table_id -> fragment table_ids, for callers replacing fragments
        self.merge_groups: Dict[str, List[str]] = {}

        if len(tables) < 2:
            self.stats["tables_processed"] = len(tables)
            return tables

        # Sort tables by page number to ensure correct order
        sorted_tables = sorted(tables, key=lambda t: t.source_page_physical)
        n = len(sorted_tables)

        # REMEDIATION §5.1 Phase 1: Build merge graph using Union-Find
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

                # P0-03: pages inside the merged run with no fragment were lost upstream
                missing_pages = self._detect_missing_pages(merged_table)
                if missing_pages:
                    self.stats["missing_pages_detected"] += len(missing_pages)
                    self.stats["dlq_entries"] += 1

                    # Emit DLQ red flag for lost pages
                    emitter.emit_red_flag(
                        "7",
                        "multi_page_table_page_lost",
                        {
                            "table_id": merged_table.table_id,
                            "missing_pages": sorted(missing_pages),
                            "expected_range": f"{merged_table.source_pages[0]}-{merged_table.source_pages[-1]}",
                            "actual_pages": merged_table.source_pages,
                            "fragment_count": len(fragments),
                        },
                    )
                    logger.warning(
                        f"[{merged_table.table_id}] Missing pages detected: {sorted(missing_pages)} "
                        f"in range {merged_table.source_pages[0]}-{merged_table.source_pages[-1]}"
                    )

                merged.append(merged_table)
                self.merge_groups[merged_table.table_id] = [f.table_id for f in fragments]
                self.stats["tables_merged"] += 1
                self.stats["total_fragments_merged"] += len(fragments)

        self.stats["tables_processed"] = n

        # M2-FIX: After all merges, detect gaps between consecutive tables
        # This catches boundary pages that have no fragments at all
        sequence_gaps = self._detect_table_sequence_gaps(merged, gap_page_probe, lost_table_pages)
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

    def _section_of(self, table: StructuredTable) -> Optional[str]:
        """B-6-01: the table's section key, or None when unknown."""
        keys = getattr(self, "_section_keys", None) or {}
        return keys.get(table.source_chunk_id) if table.source_chunk_id else None

    def _same_section(self, prev: StructuredTable, curr: StructuredTable) -> bool:
        """False only when both sections are known and differ."""
        a, b = self._section_of(prev), self._section_of(curr)
        return a is None or b is None or a == b

    def _detect_missing_pages(self, merged_table: StructuredTable) -> Set[int]:
        """
        Pages inside a merged table's page range that contributed no fragment.

        Args:
            merged_table: StructuredTable after merging

        Returns:
            Set of missing page numbers (empty if none missing)
        """
        if not merged_table.source_pages or len(merged_table.source_pages) < 2:
            return set()

        pages = sorted(merged_table.source_pages)
        expected = set(range(pages[0], pages[-1] + 1))
        return expected - set(pages)

    def _detect_table_sequence_gaps(
        self,
        merged_tables: List[StructuredTable],
        gap_page_probe: Optional[Callable[[int], bool]] = None,
        lost_table_pages: Optional[Set[int]] = None,
    ) -> List[Dict[str, Any]]:
        """
        M2-FIX: Detect pages lost between two tables that look like one table run.

        B-6-02: a page between two tables is flagged only when the two tables would
        have merged by the column and marker rules (ignoring contiguity and the page
        gap), they are in the same section as far as known, and the page itself looks
        like it holds a table. Separate tables a few pages apart are the normal case.
        A page where layout found a table that was never extracted is always flagged.

        Args:
            merged_tables: List of merged/standalone tables, sorted by page
            gap_page_probe: page -> True if the page looks like it holds a table
            lost_table_pages: pages with a layout table that nothing was extracted for

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

            gap_size = curr_start - prev_end - 1
            if gap_size <= 0 or gap_size > self.MAX_PAGE_GAP:
                continue
            same_section = self._same_section(prev_table, curr_table)
            if not same_section:
                continue
            continues = self._would_continue(prev_table, curr_table)

            for missing_page in range(prev_end + 1, curr_start):
                lost = missing_page in (lost_table_pages or ())
                if not lost and not (
                    continues and gap_page_probe is not None and gap_page_probe(missing_page)
                ):
                    logger.debug(
                        f"M2-DLQ: page {missing_page} between p{prev_end} and p{curr_start} "
                        f"holds no table; not flagged"
                    )
                    continue
                section = self._section_of(prev_table)
                dlq_entries.append({
                    "page": missing_page,
                    "reason": "layout_table_not_extracted" if lost else "no_fragment_extracted",
                    "context": {
                        "prev_table_page": prev_end,
                        "next_table_page": curr_start,
                        "prev_table_id": prev_table.table_id,
                        "next_table_id": curr_table.table_id,
                        "same_section": same_section,
                        "section_id": section,
                    },
                })
                logger.warning(
                    f"M2-DLQ: Page {missing_page} has no table fragment "
                    f"(gap between p{prev_end} and p{curr_start})"
                )

        return dlq_entries

    def _would_continue(self, prev: StructuredTable, curr: StructuredTable) -> bool:
        """
        _should_merge's column and marker rules, as if the two tables were adjacent.

        The contiguity rule (any column count within 3 on facing pages) is left out:
        it is safe only for tables known to have nothing between them. A table of the
        same width is taken as a continuation: Docling gives every fragment a header
        row, so a continuation's first data row rarely matches the real header.
        """
        if curr.num_cols == prev.num_cols:
            return self._same_section(prev, curr)
        adjacent = curr.model_copy(update={"source_page_physical": prev.source_page_physical + 1})
        saved = getattr(self, "_contiguous_pairs", None)
        self._contiguous_pairs = None
        try:
            return self._should_merge(prev, adjacent)
        finally:
            self._contiguous_pairs = saved

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

        # B-6-01: tables in different sections are different tables
        if not self._same_section(prev, curr):
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

        # Calculate match percentage over the columns where either row has text: an
        # empty cell is a substring of everything and matched any header
        filled = [
            i for i in range(max(len(prev_header_texts), len(curr_header_texts)))
            if (i < len(prev_header_texts) and prev_header_texts[i])
            or (i < len(curr_header_texts) and curr_header_texts[i])
        ]
        matches = sum(
            1
            for i in filled
            if i < len(prev_header_texts) and i < len(curr_header_texts)
            and prev_header_texts[i] and curr_header_texts[i]
            and self._headers_match(prev_header_texts[i], curr_header_texts[i])
        )
        match_rate = matches / len(filled) if filled else 0.0

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

    @staticmethod
    def _row_key(row: TableRow) -> List[str]:
        return [" ".join(cell.cleaned_text.split()).lower() for cell in row.cells]

    @staticmethod
    def _is_column_number_row(texts: List[str]) -> bool:
        """A row numbering the columns: "1 | 2 | 3" or "(1) | (2) | (3)"."""
        numbers = [t.strip("()") for t in texts if t]
        return len(numbers) >= 3 and numbers == [str(i) for i in range(1, len(numbers) + 1)]

    def _repeatable_rows(self, base: StructuredTable) -> List[List[str]]:
        """Rows a continuation page reprints: the header rows and a column-number row."""
        k = base.num_header_rows
        rows = [self._row_key(r) for r in base.rows[:k]]
        if k < len(base.rows):
            following = self._row_key(base.rows[k])
            if self._is_column_number_row(following):
                rows.append(following)
        return [r for r in rows if any(r)]

    def _count_repeated_rows(self, repeatable: List[List[str]], fragment: StructuredTable) -> int:
        """Number of leading fragment rows that reprint the base's header rows."""
        count = 0
        limit = len(repeatable) + 1
        for row in fragment.rows[:limit]:
            key = self._row_key(row)
            if any(self._rows_match(key, header) for header in repeatable) or (
                row.row_type == "header" and self._is_column_number_row(key)
            ):
                count += 1
            else:
                break
        return count

    @staticmethod
    def _rows_match(a: List[str], b: List[str]) -> bool:
        """Same text in at least 80% of the columns where either row has text."""
        filled = [i for i in range(max(len(a), len(b)))
                  if (i < len(a) and a[i]) or (i < len(b) and b[i])]
        if not filled:
            return False
        same = sum(1 for i in filled if i < len(a) and i < len(b) and a[i] == b[i])
        if same / len(filled) >= 0.8:
            return True
        # Column positions can shift by a spanning cell: compare the texts in order
        return [t for t in a if t] == [t for t in b if t]

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
        # tagging each with its page so split pieces can cite the right page.
        # Only the base's leading header rows stay headers.
        all_rows = [
            row.model_copy(update={
                "source_page_physical": row.source_page_physical
                if row.source_page_physical is not None
                else base.source_page_physical,
                "row_type": "data" if row.row_type == "header" and idx >= base.num_header_rows
                else row.row_type,
            })
            for idx, row in enumerate(base.rows)
        ]
        all_pages = [base.source_page_physical]
        all_footnotes = list(base.footnotes)
        repeatable = self._repeatable_rows(base)

        # Merge subsequent fragments
        for fragment in fragments[1:]:
            # B-7-04: a continuation page repeats the header (and column-number) rows;
            # drop them whether or not they were classified as headers
            skip_rows = self._count_repeated_rows(repeatable, fragment)

            # Rows inside the merged table are body rows: an unmatched "header" row of a
            # continuation fragment is kept as data, not hidden or repeated as a header
            all_rows.extend(
                row.model_copy(update={
                    "source_page_physical": fragment.source_page_physical,
                    "row_type": "data" if row.row_type == "header" else row.row_type,
                })
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
            caption=base.caption,
            table_number=base.table_number,
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
        # Fragments merged under the base's columns may be a little wider
        num_cols = max([len(columns or [])] + [len(r.cells) for r in rows])

        def line(row: TableRow) -> str:
            # A pipe inside a cell would shift every later column when re-parsed
            cells_text = [cell.cleaned_text.replace("|", "\\|") for cell in row.cells]
            cells_text += [""] * (num_cols - len(cells_text))
            return f"| {' | '.join(cells_text)} |"

        separator = f"| {' | '.join(['---'] * num_cols)} |"

        # Rows in order; the separator follows row 0, as in pdfplumber's output. Rows
        # are never dropped: a "header" row inside the table is printed where it is.
        for i, row in enumerate(rows):
            markdown_lines.append(line(row))
            if i == 0:
                markdown_lines.append(separator)
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
