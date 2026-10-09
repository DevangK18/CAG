"""
ChunkingService: Hierarchical chunking for Parent-Document Retrieval pattern.
Creates section-level parent chunks and atomic child chunks with proper linking.

PHASE 1 FIXES IMPLEMENTED:
- Fix 1.3: Hierarchy propagation - children inherit full ancestor chain from parent
- Fix 1.4: Page range inversions - forward-looking calculation, guaranteed end >= start
- Fix 1.5: Parent assignment - children assigned to MOST SPECIFIC (deepest) parent
- P0-2: Y-coordinate aware parent assignment for multi-section pages
- P0-3: Multi-page table stitching before chunking
"""

import logging
import re

from difflib import SequenceMatcher
from typing import Any, List, Tuple, Optional, Dict, Set
from pathlib import Path
import hashlib

from src.core.data_contracts import (
    DocumentTask,
    ExtractedContent,
    ParentChunk,
    ChildChunk,
)

from src.core.table_contracts import StructuredTable
from src.parsing_pipeline.config import get_config
from src.parsing_pipeline.modules.multi_page_table_handler import (
    GapPageProbe,
    MultiPageTableHandler,
    heading_section_keys,
)
from src.parsing_pipeline.modules.printed_toc_parser import roman_to_int

logger = logging.getLogger(__name__)

# A line like this between two tables means the second is a new table, not a continuation
TABLE_TITLE_RE = re.compile(
    r"^\s*(annexure|appendix|table|statement|exhibit|schedule|chart|figure)\b", re.IGNORECASE
)
# A lettered part of an appendix: "B. Service level …", "(A) Status of …"
TABLE_PART_RE = re.compile(r"^(?:\([A-H]\)|[A-H]\.)\s+\S")
SENTENCE_END_RE = re.compile(r"(?<=[.;])\s+(?=[A-Z(])")


class ChunkingService:
    """
    Implements hierarchical chunking strategy for RAG with Parent-Document Retrieval.

    Strategy:
    - Parent chunks: Section-level context from ToC structure
    - Child chunks: Atomic content units (paragraphs, tables, images)
    - Linking: Every child references its parent via parent_chunk_id

    PHASE 1 FIXES:
    - Children are assigned to the MOST SPECIFIC (deepest level) parent for their page
    - Children inherit the FULL hierarchy from their assigned parent
    - Page ranges are calculated forward-looking with guaranteed end >= start
    """

    def __init__(self, trace_emitter=None):
        """Initialize the chunking service.

        Args:
            trace_emitter: Optional TraceEmitter for Phase 7 instrumentation
        """
        self.multi_page_handler = MultiPageTableHandler()
        self._trace_emitter = trace_emitter
        self.max_child_chars = get_config().chunking.max_child_chunk_chars
        logger.info(
            "ChunkingService initialized for hierarchical chunk creation (Phase 1 + P0-3 applied)."
        )

    def chunk_document(
        self, task: DocumentTask, trace_emitter=None
    ) -> Tuple[List[ParentChunk], List[ChildChunk]]:
        """
        Main entry point: create hierarchical parent and child chunks.

        Args:
            task: DocumentTask with scaffold and extracted_content populated
            trace_emitter: Optional TraceEmitter for Phase 7 instrumentation

        Returns:
            Tuple of (parent_chunks, child_chunks)
        """
        emitter = trace_emitter or self._trace_emitter

        # Validate inputs
        if not task.extracted_content:
            logger.warning(f"Warning: No extracted content for {task.report_id}")
            if emitter:
                emitter.emit_decision(
                    "7",
                    "chunking_input",
                    "no_content",
                    ["has_content", "no_content"],
                    "No extracted content available for chunking",
                )
            return ([], [])

        # Merge multi-page tables before chunking
        # B4 fix: Pass emitter for DLQ red flags
        merged_count = self._merge_multi_page_tables(task, emitter)
        if emitter and merged_count > 0:
            emitter.emit_decision(
                "7",
                "multi_page_table_merge",
                f"merged_{merged_count}",
                [],
                f"Merged {merged_count} multi-page table groups",
            )

        # Split tables/paragraphs too long to embed (each piece keeps its own page)
        task.extracted_content = self._split_oversized_content(task.extracted_content)

        # Create parent chunks from ToC
        parent_chunks = self._create_parent_chunks(task)

        if not parent_chunks:
            logger.warning(f"Warning: No parent chunks created for {task.report_id}")
            if emitter:
                emitter.emit_decision(
                    "7",
                    "parent_creation",
                    "no_parents",
                    ["has_parents", "no_parents"],
                    "No TOC entries to create parent chunks from",
                )
            return ([], [])

        # Cover and front-matter pages before the first contents entry get their own
        # parent instead of falling back to the first section
        parent_chunks = self._add_front_matter_parent(task, parent_chunks)

        # Create child chunks from extracted content
        child_chunks = self._create_child_chunks(task, parent_chunks)

        # Drop empty and heading-only parents, then take ranges from the children
        page_map = (task.scaffold or {}).get("page_map", {})
        parent_chunks = self._cleanup_parents(parent_chunks, child_chunks)
        self._derive_page_ranges(parent_chunks, child_chunks, page_map)

        # Log distribution statistics
        self._log_distribution_stats(parent_chunks, child_chunks)

        # Emit instrumentation for parent assignment distribution
        if emitter and child_chunks:
            unassigned = sum(1 for c in child_chunks if not c.parent_chunk_id)
            if unassigned > 0:
                unassigned_pct = unassigned / len(child_chunks) * 100
                emitter.emit_sample(
                    "7",
                    "parent_assignment",
                    [{"unassigned_count": unassigned, "total_children": len(child_chunks), "pct": round(unassigned_pct, 1)}],
                )
                if unassigned_pct > 20:
                    emitter.emit_red_flag(
                        "7",
                        f"High unassigned child rate: {unassigned_pct:.1f}%",
                        {"unassigned": unassigned, "total": len(child_chunks)},
                    )

        logger.info(
            f"Chunking complete for {task.report_id}: "
            f"{len(parent_chunks)} parents, {len(child_chunks)} children"
        )

        return (parent_chunks, child_chunks)

    def _merge_multi_page_tables(
        self,
        task: DocumentTask,
        trace_emitter=None,
        section_keys: Optional[Dict[str, Optional[str]]] = None,
    ) -> int:
        """
        Merge multi-page tables in extracted content (P0-3).

        Detects tables that span multiple pages and merges them into
        unified StructuredTable objects. Updates task.extracted_content
        in place.

        Args:
            task: DocumentTask with extracted_content
            trace_emitter: Optional TraceEmitter for DLQ red flags (B4 fix)
            section_keys: B-6-01: section key per table, keyed by the table's
                source_chunk_id (Phase 6 block ID); None for a table means unknown.
                Defaults to the last heading before each table in reading order.

        Returns:
            Number of multi-page tables merged
        """
        if not task.extracted_content:
            return 0

        # The handler is reused across reports; its stats and DLQ list must not leak
        self.multi_page_handler.reset_statistics()

        # Extract tables with structured data
        table_items = []
        non_table_items = []

        for item in task.extracted_content:
            if (
                item.content_type == "table_markdown"
                and item.structured_data is not None
            ):
                # Parse structured_data dict back to StructuredTable
                try:
                    structured_table = StructuredTable(**item.structured_data)
                    table_items.append((item, structured_table))
                except Exception as e:
                    logger.error(f"Warning: Failed to parse structured table: {e}")
                    non_table_items.append(item)
            else:
                non_table_items.append(item)

        if len(table_items) < 2:
            # No multi-page tables possible
            return 0

        # Extract just the StructuredTable objects for merging
        structured_tables = [st for _, st in table_items]

        if section_keys is None:
            section_keys = heading_section_keys(task.extracted_content, self._reading_order_key)

        # B-6-02: a page between two tables is flagged as lost only if it holds a table
        # that no extracted item accounts for
        pdf_path = (
            task.ocred_pdf_path
            if task.classification == "scanned" and task.ocred_pdf_path
            else task.local_pdf_path
        )
        layout_table_pages = {
            int(page)
            for page, blocks in (task.layout or {}).items()
            if any(block.get("label") == "Table" for block in blocks)
        }
        extracted_table_pages = {
            item.source_page_physical
            for item in task.extracted_content
            if item.layout_label == "Table" or item.content_type == "table_markdown"
        }
        figure_boxes: Dict[int, List[List[float]]] = {}
        for item in task.extracted_content:
            if item.content_type == "image_caption" and item.source_bbox:
                figure_boxes.setdefault(item.source_page_physical, []).append(item.source_bbox)
        probe = GapPageProbe(pdf_path, extracted_table_pages, figure_boxes)

        # Run multi-page detection and merging
        # B4 fix: Pass trace_emitter for DLQ red flags on missing pages
        try:
            merged_tables = self.multi_page_handler.detect_and_merge(
                structured_tables,
                trace_emitter,
                contiguous_pairs=self._find_contiguous_table_pairs(task.extracted_content),
                section_keys=section_keys,
                gap_page_probe=probe,
                lost_table_pages=layout_table_pages - extracted_table_pages,
            )
        finally:
            probe.close()

        # Get statistics
        stats = self.multi_page_handler.get_statistics()
        if stats["tables_merged"] > 0:
            logger.info(
                f"  P0-3: Merged {stats['tables_merged']} multi-page tables "
                f"({stats['total_fragments_merged']} fragments)"
            )

        # M2-FIX: Store DLQ entries on task for output JSON
        if stats.get("dlq_entry_list"):
            task.dlq_entries = stats["dlq_entry_list"]
            logger.info(
                f"  M2-DLQ: {len(stats['dlq_entry_list'])} pages flagged as missing fragments"
            )

        # Rebuild extracted_content: the first fragment of each merged group becomes the
        # merged table; the other fragments (and only those) are dropped
        base_to_merged = {}
        fragment_ids: Set[str] = set()
        for merged_table in merged_tables:
            group = self.multi_page_handler.merge_groups.get(merged_table.table_id)
            if group:
                base_to_merged[group[0]] = merged_table
                fragment_ids.update(group[1:])

        new_extracted_content = []
        for item, structured_table in table_items:
            table_id = structured_table.table_id
            if table_id in fragment_ids:
                continue
            merged_table = base_to_merged.get(table_id)
            if merged_table is None:
                new_extracted_content.append(item)
                continue
            # A copy of the base item keeps its other fields (block ID, logical page,
            # provenance); only the table content changes. The caption, unit line and
            # notes Phase 6 attached stay in the searchable text, as for a one-page table
            structured = merged_table.model_dump()
            unit_line = (item.structured_data or {}).get("unit_line")
            if unit_line:
                structured["unit_line"] = unit_line
            text = [x for x in (merged_table.caption, unit_line) if x]
            text += [merged_table.markdown_representation] + list(merged_table.footnotes)
            new_extracted_content.append(
                item.model_copy(update={
                    "content": "\n".join(text),
                    "source_page_physical": merged_table.source_page_physical,
                    "source_bbox": merged_table.source_bbox,
                    "structured_data": structured,
                })
            )

        # Add back non-table items
        new_extracted_content.extend(non_table_items)

        # Restore reading order (page, then vertical position)
        new_extracted_content.sort(key=self._reading_order_key)

        # Update task
        task.extracted_content = new_extracted_content

        return stats["tables_merged"]

    @staticmethod
    def _reading_order_key(item: ExtractedContent) -> Tuple[int, float]:
        return (item.source_page_physical, item.source_bbox[1] if item.source_bbox else 0)

    @staticmethod
    def _breaks_table_run(item: ExtractedContent) -> bool:
        """True if this block between two tables means the second one is a new table."""
        if item.content_type != "paragraph" and item.content_type != "list":
            return True  # headers, other tables, figures
        text = (item.content or "").strip()
        if TABLE_TITLE_RE.match(text) or text.endswith(":"):
            return True
        # Short lines (units, "Contd.", source notes, footnotes) can sit between fragments
        return len(text) > 200

    def _find_contiguous_table_pairs(
        self, content: List[ExtractedContent]
    ) -> Set[Tuple[str, str]]:
        """
        Pairs of consecutive tables (reading order) with no heading, caption or body
        text between them: the only tables that can be one table split across pages.
        """
        pairs: Set[Tuple[str, str]] = set()
        prev_id: Optional[str] = None
        prev_page: Optional[int] = None
        broken = False
        titled: Set[str] = set()
        for item in sorted(content, key=self._reading_order_key):
            if item.content_type == "table_markdown" and item.structured_data:
                table_id = item.structured_data.get("table_id")
                if prev_id and table_id and not broken:
                    pairs.add((prev_id, table_id))
                prev_id, prev_page, broken = table_id, item.source_page_physical, False
            else:
                if prev_id and item.source_page_physical == prev_page and self._is_sideways_part_title(item):
                    titled.add(prev_id)
                if self._breaks_table_run(item):
                    broken = True
        return {pair for pair in pairs if pair[1] not in titled}

    @staticmethod
    def _is_sideways_part_title(item: ExtractedContent) -> bool:
        """
        A part title ("B. Service level benchmarks …") set sideways beside a table.

        On a page printed sideways the title of a table sorts after it in reading
        order, so it cannot separate the table from the one before (BR p.176).
        """
        box = item.source_bbox
        if item.content_type not in ("caption", "header") or not box or len(box) < 4:
            return False
        if (box[3] - box[1]) < 3 * (box[2] - box[0]):
            return False
        return bool(TABLE_PART_RE.match((item.content or "").strip()))

    def _split_oversized_content(
        self, content: List[ExtractedContent]
    ) -> List[ExtractedContent]:
        """Split tables and paragraphs longer than max_child_chars into embeddable pieces."""
        result = []
        for item in content:
            if len(item.content or "") <= self.max_child_chars:
                result.append(item)
            elif item.content_type == "table_markdown":
                result.extend(self._split_table(item))
            else:
                result.extend(self._split_text(item))
        return result

    def _split_table(self, item: ExtractedContent) -> List[ExtractedContent]:
        """Split a table into row groups, repeating the header rows in every piece."""
        table = None
        if item.structured_data:
            try:
                table = StructuredTable(**item.structured_data)
            except Exception:
                table = None

        if table is None or not table.rows:
            return self._split_markdown_table(item)

        # B-7-04: only the leading header rows repeat in each piece; a "header" row
        # further down is body text and must not be repeated
        k = min(table.num_header_rows, len(table.rows))
        headers = table.rows[:k]
        data_rows = table.rows[k:]
        render = self.multi_page_handler._regenerate_markdown
        header_len = len(render(headers, table.columns))
        budget = self.max_child_chars - header_len
        # Slack for keeping a total with its rows and for absorbing a short tail
        hard_budget = int(self.max_child_chars * 1.1) - header_len

        def row_len(row) -> int:
            return sum(len(c.cleaned_text) + 3 for c in row.cells) + 2

        groups, current, size = [], [], 0
        for row in data_rows:
            length = row_len(row)
            if current and size + length > budget:
                is_total = row.row_type in ("total", "subtotal")
                if is_total and size + length <= hard_budget:
                    pass  # a total stays with the rows it totals
                else:
                    carry = []
                    if is_total and len(current) > 1:
                        # Too big to fit: take the last row along so the total is not alone
                        carry = [current.pop()]
                    groups.append(current)
                    current = carry
                    size = sum(row_len(r) for r in carry)
            current.append(row)
            size += length
        if current:
            groups.append(current)

        # A short last piece (one row, or a row and its total) joins the previous one
        limit = int(self.max_child_chars * 1.1)
        lead = [x for x in (getattr(table, "caption", None), (item.structured_data or {}).get("unit_line")) if x]
        lead_len = sum(len(x) + 1 for x in lead)
        if len(groups) > 1 and len(groups[-1]) < 3:
            if lead_len + len(render(headers + groups[-2] + groups[-1], table.columns)) <= limit:
                groups[-2].extend(groups.pop())

        # The row estimate can undercount the rendered table: halve any piece that is
        # still over the limit
        checked = []
        while groups:
            rows = groups.pop(0)
            if len(rows) > 1 and lead_len + len(render(headers + rows, table.columns)) > limit:
                half = len(rows) // 2
                groups[:0] = [rows[:half], rows[half:]]
                continue
            checked.append(rows)
        groups = checked

        pieces = []
        for n, rows in enumerate(groups, 1):
            pages = sorted({r.source_page_physical for r in rows if r.source_page_physical is not None})
            page = pages[0] if pages else item.source_page_physical
            piece = table.model_copy(update={
                "table_id": f"{table.table_id}_part{n}",
                "rows": headers + rows,
                "num_rows": len(headers) + len(rows),
                "source_page_physical": page,
                "source_pages": pages,
                "markdown_representation": render(headers + rows, table.columns),
            })
            pieces.append(item.model_copy(update={
                # Every piece keeps the caption and unit line in its searchable text
                "content": "\n".join(lead + [piece.markdown_representation]),
                "source_page_physical": page,
                "structured_data": piece.model_dump(),
            }))
        return pieces

    def _split_markdown_table(self, item: ExtractedContent) -> List[ExtractedContent]:
        """Split a markdown table without structured rows, repeating its header lines."""
        lines = item.content.split("\n")
        header, body = lines[:2], lines[2:]
        budget = self.max_child_chars - sum(len(l) + 1 for l in header)
        pieces, current, size = [], [], 0
        for line in body:
            if current and size + len(line) + 1 > budget:
                pieces.append(current)
                current, size = [], 0
            current.append(line)
            size += len(line) + 1
        if current:
            pieces.append(current)
        return [
            item.model_copy(update={"content": "\n".join(header + rows)})
            for rows in pieces
        ]

    def _split_text(self, item: ExtractedContent) -> List[ExtractedContent]:
        """Split long text at sentence boundaries."""
        pieces, current = [], ""
        for sentence in SENTENCE_END_RE.split(item.content):
            if current and len(current) + len(sentence) + 1 > self.max_child_chars:
                pieces.append(current)
                current = ""
            current = f"{current} {sentence}".strip()
        if current:
            pieces.append(current)
        return [item.model_copy(update={"content": text}) for text in pieces]

    def _log_distribution_stats(
        self, parent_chunks: List[ParentChunk], child_chunks: List[ChildChunk]
    ) -> None:
        """Log statistics about child distribution across parents."""
        from collections import Counter

        parent_counts = Counter(c.parent_chunk_id for c in child_chunks)
        parents_with_children = len(parent_counts)
        total_parents = len(parent_chunks)

        if parent_counts:
            max_children = parent_counts.most_common(1)[0][1]
            concentration = (
                (max_children / len(child_chunks)) * 100 if child_chunks else 0
            )
        else:
            concentration = 0

        # Count children with deep hierarchy (level_2+)
        deep_children = sum(1 for c in child_chunks if len(c.hierarchy) > 1)
        deep_rate = (deep_children / len(child_chunks)) * 100 if child_chunks else 0

        logger.info(
            f"  Distribution: {parents_with_children}/{total_parents} parents have children"
        )
        logger.info(f"  Concentration: {concentration:.1f}% to top parent")
        logger.info(f"  Deep hierarchy: {deep_rate:.1f}% of children have level_2+")

    def _create_parent_chunks(self, task: DocumentTask) -> List[ParentChunk]:
        """
        Create parent chunks from ToC structure or fallback.

        Args:
            task: DocumentTask with scaffold data

        Returns:
            List of ParentChunk objects
        """
        scaffold = task.scaffold or {}
        toc = scaffold.get("toc", [])
        page_map = scaffold.get("page_map", {})

        if toc and len(toc) > 0:
            # Create parent chunks from ToC entries
            return self._create_parent_chunks_from_toc(task, toc, page_map)
        else:
            # Fallback: create single document-level parent
            return self._create_parent_chunks_fallback(task)

    def _create_parent_chunks_from_toc(
        self, task: DocumentTask, toc: List[List], page_map: Dict[int, str]
    ) -> List[ParentChunk]:
        """
        Create one parent per ToC entry.

        The ToC is first put in reading order, (page, y), because Phase 5.5 appends
        entries out of page order (B-7-02). Page ranges computed here are only the
        starting point: once children are assigned they are re-derived from the
        children's pages (_derive_page_ranges).
        """
        parent_chunks = []
        scaffold = task.scaffold or {}
        heading_positions = scaffold.get("heading_positions", {})

        max_page = (
            max(content.source_page_physical for content in task.extracted_content)
            if task.extracted_content
            else 0
        )

        def y_of(entry) -> float:
            return heading_positions.get(f"{entry[2]}_{str(entry[1])[:30]}", 0.0) or 0.0

        toc = [
            entry
            for _, entry in sorted(
                enumerate(toc), key=lambda pair: (pair[1][2], y_of(pair[1]), pair[0])
            )
        ]
        metadata = self._tier_metadata(task)

        for i, toc_entry in enumerate(toc):
            level, title, page_physical = toc_entry[:3]
            start_page = page_physical

            # End before the next entry of the same or a higher level, in page order
            end_page = max_page
            for j in range(i + 1, len(toc)):
                next_level, _, next_page = toc[j][:3]
                if next_level <= level:
                    end_page = max(start_page, next_page - 1 if next_page > start_page else start_page)
                    break

            chunk_id = self._generate_parent_chunk_id(task.report_id, level, title, i)
            hierarchy = self._build_hierarchy_for_parent(toc, i)

            parent_chunks.append(
                ParentChunk(
                    chunk_id=chunk_id,
                    report_id=task.report_id,
                    hierarchy=hierarchy,
                    page_range_physical=(start_page, end_page),
                    page_range_logical=(page_map.get(start_page), page_map.get(end_page)),
                    toc_entry=title,
                    toc_level=level,
                    content_summary=None,
                    start_y_position=heading_positions.get(f"{start_page}_{title[:30]}"),
                    **metadata,
                )
            )

        return parent_chunks

    def _add_front_matter_parent(
        self, task: DocumentTask, parents: List[ParentChunk]
    ) -> List[ParentChunk]:
        if not parents or not task.extracted_content:
            return parents
        first_start = min(p.page_range_physical[0] for p in parents)
        first_page = min(c.source_page_physical for c in task.extracted_content)
        if first_page >= first_start:
            return parents
        page_map = (task.scaffold or {}).get("page_map", {})
        end = first_start - 1
        front = ParentChunk(
            chunk_id=f"{task.report_id}_parent_front_matter",
            report_id=task.report_id,
            hierarchy={"level_1": "Front matter"},
            page_range_physical=(first_page, end),
            page_range_logical=(page_map.get(first_page), page_map.get(end)),
            toc_entry="Front matter",
            toc_level=1,
            content_summary=None,
            start_y_position=0.0,
            **self._tier_metadata(task),
        )
        return [front] + parents

    @staticmethod
    def _tier_metadata(task: DocumentTask) -> Dict[str, Any]:
        """Tier fields every parent and child carries (B-7-03, C-8-01)."""
        meta = task.initial_metadata or {}
        category = meta.get("audit_category") or "compliance"
        subtype = meta.get("report_subtype")
        return {
            "government_body_type": meta.get("government_body_type", "union"),
            "state_name": meta.get("state_name"),
            "department": meta.get("department"),
            "audit_category": category,
            "report_subtype": subtype if subtype in ("PSE", "Revenue", "PRI_ULB") else None,
        }

    def _create_parent_chunks_fallback(self, task: DocumentTask) -> List[ParentChunk]:
        """
        Fallback: create single document-level parent when ToC unavailable.

        Args:
            task: DocumentTask

        Returns:
            List with single ParentChunk covering entire document
        """
        if not task.extracted_content:
            return []

        # Calculate document page range
        pages = [content.source_page_physical for content in task.extracted_content]
        start_page = min(pages)
        end_page = max(pages)

        # Get logical pages if available
        page_map = task.scaffold.get("page_map", {}) if task.scaffold else {}
        start_logical = page_map.get(start_page)
        end_logical = page_map.get(end_page)

        # Use report title as single parent
        report_title = task.initial_metadata.get("Title", "Document")

        chunk_id = f"{task.report_id}_parent_document"

        parent_chunk = ParentChunk(
            chunk_id=chunk_id,
            report_id=task.report_id,
            hierarchy={"level_1": report_title},
            page_range_physical=(start_page, end_page),
            page_range_logical=(start_logical, end_logical),
            toc_entry=report_title,
            toc_level=1,
            content_summary=None,
            **self._tier_metadata(task),
        )

        return [parent_chunk]

    def _create_child_chunks(
        self, task: DocumentTask, parent_chunks: List[ParentChunk]
    ) -> List[ChildChunk]:
        """
        Create child chunks from extracted content and link to parents.

        PHASE 1 FIX: Children are now assigned to the MOST SPECIFIC (deepest level)
        parent that contains their page, not just the first matching parent.

        Args:
            task: DocumentTask with extracted_content
            parent_chunks: List of parent chunks

        Returns:
            List of ChildChunk objects
        """
        child_chunks = []

        # Get metadata for all child chunks
        report_title = task.initial_metadata.get("Title", "Unknown")
        # Handle None values explicitly (ATIR reports may have no Report No)
        report_no = task.initial_metadata.get("Report No") or "Unknown"
        source_filename = (
            Path(task.local_pdf_path).name if task.local_pdf_path else "unknown.pdf"
        )
        page_map = task.scaffold.get("page_map", {}) if task.scaffold else {}

        # Assign each item to a parent by walking the content in reading order and
        # switching parent at each heading that matches a ToC entry (B-7-01 a)
        assignment = self._assign_by_reading_order(task.extracted_content, parent_chunks)
        metadata = self._tier_metadata(task)

        fallback_count = 0
        for i, extracted_content in enumerate(task.extracted_content):
            chunk_id = self._generate_child_chunk_id(task.report_id, extracted_content, i)

            parent_chunk = assignment.get(i)
            if parent_chunk is None:
                parent_chunk = parent_chunks[0]
                fallback_count += 1

            child_chunk = ChildChunk(
                chunk_id=chunk_id,
                parent_chunk_id=parent_chunk.chunk_id,
                content_type=extracted_content.content_type,
                content=extracted_content.content,
                source_page_physical=extracted_content.source_page_physical,
                # The printed page number, or None where none is printed (A-4-06)
                source_page_logical=page_map.get(extracted_content.source_page_physical),
                source_bbox=extracted_content.source_bbox,
                model_used=extracted_content.model_used,
                layout_label=extracted_content.layout_label,
                layout_confidence=extracted_content.layout_confidence,
                report_id=task.report_id,
                report_title=report_title,
                report_no=report_no,
                source_filename=source_filename,
                hierarchy=parent_chunk.hierarchy.copy(),
                structured_data=extracted_content.structured_data,
                # P1-14b: Propagate extraction provenance from ExtractedContent
                extraction_method=extracted_content.extraction_method,
                extraction_confidence=extracted_content.extraction_confidence,
                **metadata,
            )

            child_chunks.append(child_chunk)

        if fallback_count > 0:
            logger.info(
                f"  ⚠️  {fallback_count}/{len(task.extracted_content)} children "
                f"({fallback_count/len(task.extracted_content)*100:.1f}%) assigned via fallback"
            )

        return child_chunks

    SECTION_NO_RE = re.compile(r"^\s*(\d+(?:\.\d+)+)\b")
    CHAPTER_NO_RE = re.compile(
        r"^\s*(?:chapter|ch\.)\s*[-–:.]?\s*([ivxlc]+|\d+)\b", re.IGNORECASE
    )

    @classmethod
    def _heading_key(cls, title: str) -> Tuple[Optional[str], str]:
        """(section or chapter number, normalised words) for matching a heading to an entry."""
        title = title or ""
        number = None
        m = cls.SECTION_NO_RE.match(title)
        if m:
            number = m.group(1)
        else:
            m = cls.CHAPTER_NO_RE.match(title)
            if m:
                token = m.group(1)
                number = "ch" + (token if token.isdigit() else str(roman_to_int(token)))
        words = re.sub(r"[^a-z]+", " ", title.lower()).strip()
        return number, words

    def _anchor_matches(self, heading: str, entry_title: str) -> bool:
        h_number, h_words = self._heading_key(heading)
        e_number, e_words = self._heading_key(entry_title)
        if h_number and e_number:
            return h_number == e_number
        if not h_words or not e_words:
            return False
        if h_words == e_words or (len(h_words) >= 12 and (h_words.startswith(e_words) or e_words.startswith(h_words))):
            return True
        return SequenceMatcher(None, h_words, e_words).ratio() >= 0.8

    def _assign_by_reading_order(
        self, items: List[ExtractedContent], parents: List[ParentChunk]
    ) -> Dict[int, ParentChunk]:
        """
        item index -> parent. Each parent starts where its heading is found in the text:
        a header within one page of the entry's page that matches it (same section or
        chapter number, or the same title). An entry whose heading is not found starts
        at its ToC page and y (or the top of that page). Items before the first start
        fall back to the page-range rule. Same-page sections are ordered by position,
        so a y copied from another page or a missing y no longer decides (B-7-01).
        """
        if not parents:
            return {}
        order = sorted(range(len(items)), key=lambda k: self._reading_order_key(items[k]))

        # Anchor each parent to the first matching header in reading order
        anchors: Dict[int, Tuple[int, float]] = {}
        used_items = set()
        for p_index, parent in enumerate(parents):
            start = parent.page_range_physical[0]
            for k in order:
                item = items[k]
                if k in used_items or not (
                    item.content_type == "header" or item.layout_label in ("Section-header", "Title")
                ):
                    continue
                page = item.source_page_physical
                if page < start - 1:
                    continue
                if page > start + 1:
                    break
                if self._anchor_matches(item.content, parent.toc_entry):
                    anchors[p_index] = self._reading_order_key(item)
                    used_items.add(k)
                    break

        starts = []
        for p_index, parent in enumerate(parents):
            if p_index in anchors:
                starts.append((anchors[p_index], p_index))
            else:
                y = parent.start_y_position or 0.0
                starts.append(((parent.page_range_physical[0], y), p_index))
        starts.sort()
        self._anchor_stats = {"anchored": len(anchors), "parents": len(parents)}

        page_index = self._build_page_parent_index(parents)
        assignment: Dict[int, ParentChunk] = {}
        current = None
        s = 0
        for k in order:
            position = self._reading_order_key(items[k])
            while s < len(starts) and starts[s][0] <= position:
                current = parents[starts[s][1]]
                s += 1
            if current is None:
                current = self._find_best_parent_for_page(
                    items[k].source_page_physical, parents, page_index, items[k].source_bbox
                )
                assignment[k] = current
                current = None
                continue
            assignment[k] = current
        return assignment

    def _derive_page_ranges(
        self, parents: List[ParentChunk], children: List[ChildChunk], page_map: Dict[int, str]
    ) -> None:
        """
        Page range of each parent = its start page to the last page of its own
        children and of its sub-sections' children (B-7-02).
        """
        last_page: Dict[str, int] = {}
        for child in children:
            last_page[child.parent_chunk_id] = max(
                last_page.get(child.parent_chunk_id, -1), child.source_page_physical
            )
        # Walk from the deepest entries up so a parent covers its sub-sections
        for i in sorted(range(len(parents)), key=lambda i: -parents[i].toc_level):
            parent = parents[i]
            start = parent.page_range_physical[0]
            end = max(start, last_page.get(parent.chunk_id, start))
            for later in parents[i + 1:]:
                if later.toc_level <= parent.toc_level:
                    break
                end = max(end, later.page_range_physical[1])
            parent.page_range_physical = (start, end)
            parent.page_range_logical = (page_map.get(start), page_map.get(end))

    def _cleanup_parents(
        self, parents: List[ParentChunk], children: List[ChildChunk]
    ) -> List[ParentChunk]:
        """
        Remove parents that hold nothing (C-8-05, P7-03): a leaf entry with no children
        is dropped, and a leaf whose only children are its heading(s) hands them to the
        next section in reading order (the heading belongs with the text that follows).
        """
        by_parent: Dict[str, List[ChildChunk]] = {}
        for child in children:
            by_parent.setdefault(child.parent_chunk_id, []).append(child)

        def is_leaf(i: int) -> bool:
            return i + 1 >= len(parents) or parents[i + 1].toc_level <= parents[i].toc_level

        keep = []
        moved = 0
        for i, parent in enumerate(parents):
            own = by_parent.get(parent.chunk_id, [])
            if not is_leaf(i):
                keep.append(parent)
                continue
            if not own:
                continue
            if all(c.content_type == "header" for c in own) and i + 1 < len(parents):
                target = parents[i + 1]
                for child in own:
                    child.parent_chunk_id = target.chunk_id
                    child.hierarchy = target.hierarchy.copy()
                by_parent.setdefault(target.chunk_id, []).extend(own)
                moved += len(own)
                continue
            keep.append(parent)
        dropped = len(parents) - len(keep)
        if dropped:
            logger.info(f"  Parent cleanup: dropped {dropped} empty or heading-only parents ({moved} headings moved)")
        return keep

    def _build_page_parent_index(
        self, parent_chunks: List[ParentChunk]
    ) -> Dict[int, List[ParentChunk]]:
        """
        Build an index mapping each page number to all parents that contain it.

        This enables efficient lookup of candidate parents for each child.

        Args:
            parent_chunks: List of parent chunks

        Returns:
            Dict mapping page_num -> list of ParentChunks containing that page
        """
        page_index: Dict[int, List[ParentChunk]] = {}

        for parent in parent_chunks:
            start, end = parent.page_range_physical
            for page in range(start, end + 1):
                if page not in page_index:
                    page_index[page] = []
                page_index[page].append(parent)

        return page_index

    def _find_best_parent_for_page(
        self,
        page_num: int,
        parent_chunks: List[ParentChunk],
        page_parent_index: Dict[int, List[ParentChunk]],
        content_bbox: Optional[List[float]] = None,
    ) -> Optional[ParentChunk]:
        """
        Find the MOST SPECIFIC (deepest level) parent chunk for a given page.

        PHASE 1 FIX: This replaces the old _find_parent_for_page which returned
        the first matching parent. Now we return the parent with:
        1. The highest ToC level (most specific/deepest)
        2. Among ties, the one with the smallest page range (most precise)
        3. Among ties, the one that starts closest to the page

        P0-2: Now uses Y-coordinate awareness when multiple parents start on the same page.
        Content must be at or below the section heading's Y-position to belong to that section.

        Args:
            page_num: Physical page number (0-indexed)
            parent_chunks: List of all parent chunks
            page_parent_index: Pre-built index of pages to parents
            content_bbox: [x0, y0, x1, y1] bounding box of content (for Y-position filtering)

        Returns:
            Best matching ParentChunk or None
        """
        if not parent_chunks:
            return None

        # Get all parents that contain this page
        candidates = page_parent_index.get(page_num, [])

        if not candidates:
            # Page not in any parent's range - find nearest parent
            return self._find_nearest_parent(page_num, parent_chunks)

        if len(candidates) == 1:
            return candidates[0]

        # Y-coordinate aware filtering for multi-section pages
        # Algorithm: Find the LAST section that starts AT OR BEFORE the content's Y-position
        if content_bbox and len(candidates) > 1:
            content_y = content_bbox[1]  # y0 coordinate (top of content)

            # Get all sections that start on this page with Y-positions
            sections_starting_here = [
                (p, p.start_y_position)
                for p in candidates
                if p.page_range_physical[0] == page_num
                and p.start_y_position is not None
            ]

            # Only apply Y-filtering if we have sections with Y-positions on this page
            if sections_starting_here:
                # Sort sections by Y-position (top to bottom)
                sections_starting_here.sort(key=lambda x: x[1])

                # Find the last section that starts AT OR BEFORE the content (with 10px tolerance)
                best_parent = None

                # First check: sections from previous pages (they come before any section on this page)
                parents_from_before = [
                    p for p in candidates
                    if p.page_range_physical[0] < page_num
                ]

                # Check sections starting on this page
                for section, section_y in sections_starting_here:
                    if section_y <= content_y + 10:  # Section starts at or before content (with tolerance)
                        best_parent = section  # Update to latest section before/at content
                    else:
                        # Section starts BELOW content, stop searching
                        break

                # If no section on this page starts before content, use most specific
                # parent from a previous page
                if best_parent is None and parents_from_before:
                    # Pick the deepest-level (most specific) parent among previous-page candidates
                    # On ties, prefer the one whose page range starts closest to this page
                    parents_from_before.sort(
                        key=lambda p: (-p.toc_level, -(p.page_range_physical[0]))
                    )
                    best_parent = parents_from_before[0]

                # Apply the Y-filtered result
                if best_parent:
                    candidates = [best_parent]

        # Sort candidates to find the MOST SPECIFIC parent (deepest level, then Y-position)
        # Priority: highest toc_level > smallest page range > closest start page
        def sort_key(parent: ParentChunk) -> Tuple[int, int, int]:
            start, end = parent.page_range_physical
            page_range_size = end - start
            distance_from_start = abs(page_num - start)

            # Negative toc_level because we want HIGHEST level first
            # (level 3 is more specific than level 1)
            return (-parent.toc_level, page_range_size, distance_from_start)

        sorted_candidates = sorted(candidates, key=sort_key)
        return sorted_candidates[0]

    def _find_nearest_parent(
        self, page_num: int, parent_chunks: List[ParentChunk]
    ) -> Optional[ParentChunk]:
        """
        Fallback: find the nearest parent when page is outside all ranges.

        Args:
            page_num: Physical page number
            parent_chunks: List of parent chunks

        Returns:
            Nearest ParentChunk by page distance
        """
        if not parent_chunks:
            return None

        def distance(parent: ParentChunk) -> Tuple[int, int]:
            start, end = parent.page_range_physical
            if page_num < start:
                dist = start - page_num
            elif page_num > end:
                dist = page_num - end
            else:
                dist = 0
            # Prefer deeper levels among equidistant parents
            return (dist, -parent.toc_level)

        return min(parent_chunks, key=distance)

    def _find_parent_for_page(
        self, page_num: int, parent_chunks: List[ParentChunk]
    ) -> Optional[str]:
        """
        DEPRECATED: Use _find_best_parent_for_page instead.
        Kept for backward compatibility.

        Find which parent chunk contains the given page.

        Args:
            page_num: Physical page number (0-indexed)
            parent_chunks: List of parent chunks

        Returns:
            parent_chunk_id or None
        """
        if not parent_chunks:
            return None

        # Build index on the fly (less efficient than pre-building)
        page_index = self._build_page_parent_index(parent_chunks)
        best_parent = self._find_best_parent_for_page(
            page_num, parent_chunks, page_index
        )

        return best_parent.chunk_id if best_parent else None

    def _generate_parent_chunk_id(
        self, report_id: str, level: int, title: str, index: int
    ) -> str:
        """
        Generate unique parent chunk identifier.

        Args:
            report_id: Report identifier
            level: ToC level
            title: ToC entry title
            index: Index in ToC list

        Returns:
            Unique chunk_id string
        """
        # Create hash from title for uniqueness
        title_hash = hashlib.md5(title.encode()).hexdigest()[:8]
        return f"{report_id}_parent_L{level}_{index:03d}_{title_hash}"

    def _generate_child_chunk_id(
        self, report_id: str, content: ExtractedContent, index: int
    ) -> str:
        """
        Generate unique child chunk identifier.

        Args:
            report_id: Report identifier
            content: Extracted content
            index: Index in extracted_content list

        Returns:
            Unique chunk_id string
        """
        page = content.source_page_physical
        ctype = content.content_type
        return f"{report_id}_child_p{page:03d}_{ctype}_{index:04d}"

    def _build_hierarchy_for_parent(
        self, toc: List[List], current_index: int
    ) -> Dict[str, str]:
        """
        Build hierarchy dict for a parent chunk from ToC context.

        Walks backward through TOC to collect ALL ancestor entries,
        building a complete hierarchy chain.

        Args:
            toc: Full ToC list
            current_index: Index of current ToC entry

        Returns:
            Hierarchy dict like {"level_1": "Chapter III", "level_2": "3.1 Implementation"}
        """
        current_entry = toc[current_index]
        current_level = current_entry[0]
        hierarchy: Dict[str, str] = {}

        # Always include current entry
        hierarchy[f"level_{current_level}"] = current_entry[1]

        # Walk backwards to collect all ancestors
        # Track which levels we've found to avoid duplicates
        levels_found = {current_level}

        lowest = current_level
        for i in range(current_index - 1, -1, -1):
            level, title, _ = toc[i][:3]

            # Only entries above every level found so far are ancestors
            if level < lowest and level not in levels_found:
                hierarchy[f"level_{level}"] = title
                levels_found.add(level)
                lowest = level

                # Stop once we reach level 1
                if level == 1:
                    break

        # Return sorted by level key for consistency
        return {
            k: v
            for k, v in sorted(
                hierarchy.items(), key=lambda item: int(item[0].split("_")[1])
            )
        }
