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

from typing import List, Tuple, Optional, Dict
from pathlib import Path
import hashlib

from src.core.data_contracts import (
    DocumentTask,
    ExtractedContent,
    ParentChunk,
    ChildChunk,
)

logger = logging.getLogger(__name__)
from src.core.table_contracts import StructuredTable
from src.parsing_pipeline.modules.multi_page_table_handler import MultiPageTableHandler


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
        merged_count = self._merge_multi_page_tables(task)
        if emitter and merged_count > 0:
            emitter.emit_decision(
                "7",
                "multi_page_table_merge",
                f"merged_{merged_count}",
                [],
                f"Merged {merged_count} multi-page table groups",
            )

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

        # Create child chunks from extracted content
        child_chunks = self._create_child_chunks(task, parent_chunks)

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

    def _merge_multi_page_tables(self, task: DocumentTask) -> int:
        """
        Merge multi-page tables in extracted content (P0-3).

        Detects tables that span multiple pages and merges them into
        unified StructuredTable objects. Updates task.extracted_content
        in place.

        Args:
            task: DocumentTask with extracted_content

        Returns:
            Number of multi-page tables merged
        """
        if not task.extracted_content:
            return 0

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

        # Run multi-page detection and merging
        merged_tables = self.multi_page_handler.detect_and_merge(structured_tables)

        # Get statistics
        stats = self.multi_page_handler.get_statistics()
        if stats["tables_merged"] > 0:
            logger.info(
                f"  P0-3: Merged {stats['tables_merged']} multi-page tables "
                f"({stats['total_fragments_merged']} fragments)"
            )

        # Rebuild extracted_content list
        # Create mapping from original table_id to merged table
        original_to_merged = {}
        for merged_table in merged_tables:
            if merged_table.is_multi_page:
                # Extract original table IDs from merged table ID
                # Format: "table_X_Y_Z_merged"
                base_id = merged_table.table_id.replace("_merged", "")
                original_to_merged[base_id] = merged_table
            else:
                # Not merged, use as-is
                original_to_merged[merged_table.table_id] = merged_table

        # Reconstruct extracted_content
        new_extracted_content = []
        skip_ids = set()  # Track table IDs that were merged (fragments to skip)

        for item, structured_table in table_items:
            table_id = structured_table.table_id

            # Check if this table was merged into another
            if table_id in skip_ids:
                continue  # Skip fragments that were merged

            # Check if this is a merged table or original
            if table_id in original_to_merged:
                merged_table = original_to_merged[table_id]

                # If this is a multi-page merged table, mark fragments for skipping
                if merged_table.is_multi_page and table_id == merged_table.table_id.replace(
                    "_merged", ""
                ):
                    # This is the base table - use the merged version
                    # Add fragment IDs to skip set (they're on different pages)
                    # We'll identify them by checking if their page is in source_pages
                    # but not the first page
                    pass  # Fragments will be skipped when encountered

                # Update ExtractedContent with merged table
                updated_item = ExtractedContent(
                    content_type=item.content_type,
                    content=merged_table.markdown_representation,
                    source_page_physical=merged_table.source_page_physical,
                    source_bbox=merged_table.source_bbox,
                    model_used=item.model_used,
                    layout_label=item.layout_label,
                    layout_confidence=item.layout_confidence,
                    structured_data=merged_table.model_dump(),
                )
                new_extracted_content.append(updated_item)

                # Mark subsequent pages' fragments for skipping
                if merged_table.is_multi_page:
                    for page in merged_table.source_pages[1:]:
                        # Mark any table on this page as skipped (crude but effective)
                        for other_item, other_table in table_items:
                            if (
                                other_table.source_page_physical == page
                                and other_table.table_id != table_id
                            ):
                                skip_ids.add(other_table.table_id)
            else:
                # Table not in merge results, keep original
                new_extracted_content.append(item)

        # Add back non-table items
        new_extracted_content.extend(non_table_items)

        # Sort by page number to maintain order
        new_extracted_content.sort(key=lambda x: x.source_page_physical)

        # Update task
        task.extracted_content = new_extracted_content

        return stats["tables_merged"]

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
        Create parent chunks from ToC entries.

        PHASE 1 FIX: Page range calculation now looks FORWARD properly
        and guarantees end_page >= start_page.

        P0-2: Now captures start_y_position from scaffold for accurate child assignment.

        Args:
            task: DocumentTask
            toc: ToC in format [[level, title, page], ...]
            page_map: Physical → logical page mapping

        Returns:
            List of ParentChunk objects
        """
        parent_chunks = []

        # Get heading positions from scaffold for Y-coordinate aware chunking
        scaffold = task.scaffold or {}
        heading_positions = scaffold.get("heading_positions", {})

        # Determine max page from extracted content
        if task.extracted_content:
            max_page = max(
                content.source_page_physical for content in task.extracted_content
            )
        else:
            max_page = 0

        for i, toc_entry in enumerate(toc):
            level, title, page_physical = toc_entry[:3]
            start_page = page_physical

            # Generate position key for this section
            position_key = f"{start_page}_{title[:30]}"

            # Look FORWARD for next entry at same or higher level (with Y-position awareness)
            # to determine end page
            end_page = max_page  # Default: section goes to end of document

            for j in range(i + 1, len(toc)):
                next_level, next_title, next_page = toc[j][:3]
                if next_level <= level:  # Same or higher level = end of this section
                    # Check if next section has Y-position on the same page
                    next_position_key = f"{next_page}_{next_title[:30]}"
                    next_has_y_position = next_position_key in heading_positions

                    # If Y-positions available and next section on same page, extend to that page
                    # Y-filtering will disambiguate. Otherwise, end before next section's page.
                    if next_has_y_position and next_page == start_page:
                        # Both sections on same page, extend to that page
                        end_page = start_page
                    elif next_has_y_position and position_key in heading_positions:
                        # Y-positions available for both sections, allow overlap
                        end_page = next_page  # Include the page where next section starts
                    else:
                        # No Y-positions, use original logic: end before next section
                        end_page = max(start_page, next_page - 1)
                    break

            # CRITICAL: Ensure end_page >= start_page to avoid invalid page ranges
            if end_page < start_page:
                end_page = start_page

            # Generate unique parent_chunk_id
            chunk_id = self._generate_parent_chunk_id(task.report_id, level, title, i)

            # Build hierarchy dict (already correct in original)
            hierarchy = self._build_hierarchy_for_parent(toc, i)

            # Get logical page labels
            start_logical = page_map.get(start_page, str(start_page + 1))
            end_logical = page_map.get(end_page, str(end_page + 1))

            # Get Y-position from heading_positions dict (position_key already defined above)
            start_y_position = heading_positions.get(position_key, None)

            parent_chunk = ParentChunk(
                chunk_id=chunk_id,
                report_id=task.report_id,
                hierarchy=hierarchy,
                page_range_physical=(start_page, end_page),
                page_range_logical=(start_logical, end_logical),
                toc_entry=title,
                toc_level=level,
                content_summary=None,
                start_y_position=start_y_position,
                # Multi-tier metadata (Phase A expansion)
                government_body_type=task.initial_metadata.get("government_body_type", "union"),
                state_name=task.initial_metadata.get("state_name"),
            )

            parent_chunks.append(parent_chunk)

        return parent_chunks

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
        start_logical = page_map.get(start_page, str(start_page + 1))
        end_logical = page_map.get(end_page, str(end_page + 1))

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
            # Multi-tier metadata (Phase A expansion)
            government_body_type=task.initial_metadata.get("government_body_type", "union"),
            state_name=task.initial_metadata.get("state_name"),
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
        report_no = task.initial_metadata.get("Report No", "Unknown")
        source_filename = (
            Path(task.local_pdf_path).name if task.local_pdf_path else "unknown.pdf"
        )
        page_map = task.scaffold.get("page_map", {}) if task.scaffold else {}

        # Pre-build page-to-parents index for efficient lookup
        page_parent_index = self._build_page_parent_index(parent_chunks)

        # Track fallback assignments for diagnostics
        fallback_count = 0

        for i, extracted_content in enumerate(task.extracted_content):
            # Generate unique child_chunk_id
            chunk_id = self._generate_child_chunk_id(
                task.report_id, extracted_content, i
            )

            # Find the MOST SPECIFIC parent for this page (deepest level match with Y-awareness)
            # Pass content bbox for Y-aware assignment
            parent_chunk = self._find_best_parent_for_page(
                extracted_content.source_page_physical,
                parent_chunks,
                page_parent_index,
                extracted_content.source_bbox,  # Pass bbox for Y-position filtering
            )

            if parent_chunk:
                parent_chunk_id = parent_chunk.chunk_id
                # Inherit the FULL hierarchy from parent (not just immediate parent level)
                hierarchy = parent_chunk.hierarchy.copy()
            else:
                # Fallback: assign to first parent
                parent_chunk_id = (
                    parent_chunks[0].chunk_id if parent_chunks else "unknown"
                )
                hierarchy = (
                    parent_chunks[0].hierarchy.copy()
                    if parent_chunks
                    else {"level_1": "Document"}
                )
                fallback_count += 1
                logger.info(
                    f"  ⚠️  Fallback assignment: page {extracted_content.source_page_physical}, "
                    f"type={extracted_content.content_type} → {parent_chunks[0].toc_entry if parent_chunks else 'unknown'}"
                )

            # Get logical page number
            logical_page = page_map.get(
                extracted_content.source_page_physical,
                str(extracted_content.source_page_physical + 1),
            )

            child_chunk = ChildChunk(
                chunk_id=chunk_id,
                parent_chunk_id=parent_chunk_id,
                content_type=extracted_content.content_type,
                content=extracted_content.content,
                source_page_physical=extracted_content.source_page_physical,
                source_page_logical=logical_page,
                source_bbox=extracted_content.source_bbox,
                model_used=extracted_content.model_used,
                layout_label=extracted_content.layout_label,
                layout_confidence=extracted_content.layout_confidence,
                report_id=task.report_id,
                report_title=report_title,
                report_no=report_no,
                source_filename=source_filename,
                hierarchy=hierarchy,
                structured_data=extracted_content.structured_data,
                # Multi-tier metadata (Phase A expansion) - propagates to Qdrant payloads
                government_body_type=task.initial_metadata.get("government_body_type", "union"),
                state_name=task.initial_metadata.get("state_name"),
                audit_category=task.initial_metadata.get("audit_category", "compliance"),
            )

            child_chunks.append(child_chunk)

        if fallback_count > 0:
            logger.info(
                f"  ⚠️  {fallback_count}/{len(task.extracted_content)} children "
                f"({fallback_count/len(task.extracted_content)*100:.1f}%) assigned via fallback"
            )

        return child_chunks

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

        for i in range(current_index - 1, -1, -1):
            level, title, _ = toc[i][:3]

            # Only add if this is a higher level (smaller number) we haven't seen
            if level < current_level and level not in levels_found:
                hierarchy[f"level_{level}"] = title
                levels_found.add(level)

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
