"""
Hierarchy Enricher: Create deeper hierarchy from flat TOC.

This is Layer 4 of the Intelligent TOC Service. It scans content
within each parent chunk to detect numbered sub-sections and creates
additional hierarchy levels.

FIXED VERSION 3 (2025-12-26):
- Handles both dict and dataclass/Pydantic objects
- Added patterns for standalone section names (Preface, Executive Summary, etc.)
- Added patterns for roman numerals without parentheses (i., ii., iii.)
- Added patterns for Chapter headings
- More aggressive detection for flat hierarchies
- NEW: Added lowercase lettered patterns at Level 2 (for Direct Taxes reports)
- NEW: Added aggressive parameter to enrich_hierarchy method
- NEW: Fixed concentration issue by detecting sub-sections within large chapters
"""

import re
from typing import List, Dict, Tuple, Optional, Set, Any, Union
from dataclasses import dataclass, field, is_dataclass, asdict
from collections import defaultdict, Counter
import logging
import hashlib

from src.parsing_pipeline.instrumentation import get_noop_emitter

logger = logging.getLogger(__name__)


def safe_get(obj: Any, key: str, default: Any = None) -> Any:
    """Safely get a value from either a dict or dataclass object."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    else:
        return getattr(obj, key, default)


def to_dict(obj: Any) -> Dict:
    """Convert a dataclass/Pydantic object to dict, or return dict as-is."""
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "dict"):  # Pydantic model
        return obj.dict()
    if is_dataclass(obj):
        return asdict(obj)
    if hasattr(obj, "__dict__"):
        return vars(obj).copy()
    return {}


@dataclass
class DetectedSection:
    """Represents a detected sub-section within a parent."""

    section_id: str
    title: str
    level: int
    page_physical: int
    page_logical: str
    bbox: Optional[List[float]] = None
    parent_chunk_id: str = ""
    confidence: float = 1.0


class HierarchyEnricher:
    """
    Enriches flat TOC with deeper hierarchy by detecting
    numbered sections within each chapter.

    Detection patterns (IMPROVED for CAG reports):
    - Standalone sections: Preface, Executive Summary, Introduction, etc.
    - Chapter headings: Chapter I, Chapter 1, CHAPTER ONE
    - Numbered sections: 1.1, 1.2.1, 1.2.1.1
    - Roman numerals: i., ii., iii. (with or without parentheses)
    - Lettered sections: A. Karnataka, B. Rajasthan
    - Lettered sub-points: (a) Detail, (b) Detail
    - Lowercase lettered: a. Irregularities, b. Short levy (Direct Taxes style)
    - Paragraph numbers: Para 2.3.1
    """

    # =========================================================================
    # SECTION PATTERNS - Each pattern returns (section_id, title) groups
    # =========================================================================
    SECTION_PATTERNS = {
        # Level 1: Major document sections (standalone names)
        1: [
            # Standalone section names (common in CAG reports)
            (r"^(Preface)$", "standalone"),
            (r"^(Executive\s+Summary)$", "standalone"),
            (r"^(Introduction)$", "standalone"),
            (r"^(Conclusion)$", "standalone"),
            (r"^(Recommendations?)$", "standalone"),
            (r"^(Acknowledgements?)$", "standalone"),
            (r"^(Glossary)$", "standalone"),
            (r"^(Abbreviations?)$", "standalone"),
            (r"^(Annexures?)$", "standalone"),
            (r"^(Appendix)$", "standalone"),
            # Chapter patterns
            (r"^(Chapter)\s+([IVXivx]+)\b", "chapter_roman"),
            (r"^(Chapter)\s+(\d+)\b", "chapter_num"),
            (r"^(CHAPTER)\s+([IVXivx]+)\b", "chapter_roman_upper"),
            (r"^(CHAPTER)\s+(\d+)\b", "chapter_num_upper"),
        ],
        # Level 2: Main sections within a chapter
        2: [
            # Numbered: "1.1 Introduction" or "1.1. Introduction"
            (r"^(\d+\.\d+)\.?\s+([A-Z].{5,})$", "numbered"),
            # Numbered with just period: "1. Introduction"
            (r"^(\d+)\.\s+([A-Z][a-z].{5,})$", "numbered_single"),
            # Lettered state names: "A. Karnataka" or "A. Himachal Pradesh"
            (r"^([A-Z])\.\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)$", "lettered_state"),
            # Lettered general: "A. Overview"
            (r"^([A-Z])\.\s+([A-Z][a-z].{3,})$", "lettered"),
            # Roman numeral sections (uppercase): "I. Introduction"
            (r"^([IVX]+)\.\s+([A-Z].{3,})$", "roman_upper"),
            # =================================================================
            # NEW PATTERNS FOR DIRECT TAXES REPORTS (lowercase lettered at L2)
            # =================================================================
            # Lowercase lettered: "a. Irregularities in assessment"
            (r"^([a-z])\.\s+([A-Z][A-Za-z].{3,})$", "lettered_lower"),
            # Lowercase lettered with longer title requirement
            (r"^([a-z])\.\s+([A-Z][a-z]{2,}.{5,})$", "lettered_lower_long"),
        ],
        # Level 3: Sub-sections
        3: [
            # Three-level numbered: "1.1.1 Background"
            (r"^(\d+\.\d+\.\d+)\.?\s+([A-Z].{3,})$", "numbered_3"),
            # Roman numeral with parentheses: "(i) Non-compliance with..."
            (r"^\(([ivx]+)\)\s+([A-Z].{5,})$", "roman_paren"),
            # Roman numeral WITHOUT parentheses: "i. whether all..." (COMMON IN CAG!)
            (r"^([ivx]+)\.\s+([a-z].{5,})$", "roman_dot_lower"),
            (r"^([ivx]+)\.\s+([A-Z].{5,})$", "roman_dot_upper"),
            # Capitalized roman with parentheses: "(I) Major Finding"
            (r"^\(([IVX]+)\)\s+([A-Z].{5,})$", "roman_cap_paren"),
            # =================================================================
            # NEW: Lettered with parentheses at Level 3 (sub-sub-sections)
            # =================================================================
            (r"^\(([a-z])\)\s+([A-Z].{5,})$", "lettered_paren"),
        ],
        # Level 4: Detail points
        4: [
            # Four-level numbered: "1.1.1.1 Specific detail"
            (r"^(\d+\.\d+\.\d+\.\d+)\.?\s+(.{5,})$", "numbered_4"),
            # Bullet style: "• Finding detail"
            (r"^[•●○]\s+(.{10,})$", "bullet"),
        ],
        # Level 5: Deep detail (rare)
        5: [
            # Five-level numbered
            (r"^(\d+\.\d+\.\d+\.\d+\.\d+)\.?\s+(.{3,})$", "numbered_5"),
            # Sub-lettered: "(i)(a) Very specific"
            (r"^\([ivx]+\)\s*\([a-z]\)\s+(.{5,})$", "roman_lettered"),
        ],
    }

    # =========================================================================
    # HEADER INDICATORS - Patterns that suggest a line is a header
    # =========================================================================
    HEADER_INDICATORS = [
        # Chapter patterns
        r"^Chapter\s+[IVXivx\d]+",
        r"^CHAPTER\s+[IVXivx\d]+",
        # Numbered sections
        r"^\d+\.\d+(\.\d+)*\.?\s+[A-Z]",
        r"^\d+\.\s+[A-Z]",
        # Lettered sections (uppercase)
        r"^[A-Z]\.\s+[A-Z]",
        # Lettered sections (lowercase) - NEW FOR DIRECT TAXES
        r"^[a-z]\.\s+[A-Z]",
        # Roman numerals (with and without parentheses)
        r"^\([ivxIVX]+\)\s+[A-Za-z]",
        r"^[ivxIVX]+\.\s+[A-Za-z]",
        # Lettered points
        r"^\([a-z]\)\s+[A-Z]",
        # Paragraph references
        r"^Para(graph)?\s+\d+",
        # Standalone section names (CRITICAL for CAG reports!)
        r"^Preface$",
        r"^Executive\s+Summary$",
        r"^Introduction$",
        r"^Conclusion$",
        r"^Recommendations?$",
        r"^Acknowledgements?$",
        r"^Annexures?\s*",
        r"^Appendix",
        r"^Glossary$",
        r"^Table\s+of\s+Contents$",
        # Audit-specific headers
        r"^(Audit\s+)?(Objective|Finding|Recommendation|Scope|Methodology)",
        r"^Summary\s+of\s+(Audit\s+)?Findings",
        r"^Background$",
        r"^Overview$",
        # Direct Taxes specific patterns
        r"^[a-z]\.\s+[A-Z][a-z]+",  # "a. Irregularities..."
        r"^[a-z]\.\s+Short\s+",  # "a. Short levy..."
        r"^[a-z]\.\s+Incorrect\s+",  # "b. Incorrect allowance..."
        r"^[a-z]\.\s+Non[-\s]",  # "c. Non-compliance..."
        r"^[a-z]\.\s+Errors?\s+",  # "e. Errors in assessment..."
    ]

    # Content types that are likely to contain section headers
    HEADER_CONTENT_TYPES = {
        "header",
        "section-header",
        "title",
        "heading",
        "Section-header",
        "Title",
        "Heading",
    }

    def __init__(
        self,
        min_section_length: int = 5,  # Reduced from 10 for short titles like "Preface"
        max_section_title_length: int = 200,
        detect_in_paragraphs: bool = True,
        trace_emitter=None,
    ):
        """
        Initialize Hierarchy Enricher.

        Args:
            min_section_length: Minimum characters for section title
            max_section_title_length: Maximum characters for section title
            detect_in_paragraphs: Whether to detect sections in paragraph starts
            trace_emitter: Optional TraceEmitter for instrumentation
        """
        self.min_section_length = min_section_length
        self.max_section_title_length = max_section_title_length
        self.detect_in_paragraphs = detect_in_paragraphs
        self._trace_emitter = trace_emitter or get_noop_emitter()

        # Compile patterns
        self._section_patterns = {}
        for level, patterns in self.SECTION_PATTERNS.items():
            self._section_patterns[level] = [
                (
                    re.compile(
                        p,
                        re.MULTILINE | re.IGNORECASE
                        if "standalone" in ptype
                        else re.MULTILINE,
                    ),
                    ptype,
                )
                for p, ptype in patterns
            ]

        self._header_indicators = [
            re.compile(p, re.IGNORECASE) for p in self.HEADER_INDICATORS
        ]

    def enrich_hierarchy(
        self,
        parent_chunks: List[Any],
        child_chunks: List[Any],
        report_id: str = "unknown",
        aggressive: bool = False,  # NEW PARAMETER
        trace_emitter=None,
    ) -> Tuple[List[Dict], List[Dict]]:
        """
        Enrich flat hierarchy by detecting sub-sections.

        Args:
            parent_chunks: Existing parent (TOC) chunks (dict or dataclass)
            child_chunks: Content chunks with parent references (dict or dataclass)
            report_id: Report identifier for logging
            aggressive: If True, use aggressive detection even with many parents
                       (used for flat hierarchies and high concentration)
            trace_emitter: Optional TraceEmitter for instrumentation

        Returns:
            Tuple of (enriched_parent_chunks, updated_child_chunks) as dicts
        """
        emitter = trace_emitter or self._trace_emitter

        if not parent_chunks or not child_chunks:
            return (
                [to_dict(p) for p in parent_chunks] if parent_chunks else [],
                [to_dict(c) for c in child_chunks] if child_chunks else [],
            )

        # Convert all inputs to dicts for processing
        parent_dicts = [to_dict(p) for p in parent_chunks]
        child_dicts = [to_dict(c) for c in child_chunks]

        # Check if this is a severely flat hierarchy (needs aggressive detection)
        # OR if aggressive mode was explicitly requested
        is_severely_flat = (
            len(parent_dicts) <= 3 or aggressive
        )

        if is_severely_flat:
            reason = (
                "explicitly requested" if aggressive else f"{len(parent_dicts)} parents"
            )
            logger.info(f"[{report_id}] Aggressive hierarchy detection ({reason})")

        # Build parent lookup
        parent_lookup = {p.get("chunk_id"): p for p in parent_dicts}

        # Trace: Parent distribution sample (top 5 by child count)
        parent_child_counts = Counter()
        for c in child_dicts:
            pid = c.get("parent_chunk_id", "")
            parent_child_counts[pid] += 1

        top_parents = parent_child_counts.most_common(5)
        if top_parents:
            parent_distribution = [
                {
                    "parent_id": pid[:50] if pid else "none",
                    "parent_title": parent_lookup.get(pid, {}).get("toc_entry", "")[:50] if pid else "orphan",
                    "child_count": count,
                }
                for pid, count in top_parents
            ]
            emitter.emit_sample("7.5", "parent_distribution", parent_distribution)

        # Track new parents and updates
        new_parents = []
        child_updates = {}  # chunk_id -> new parent_chunk_id

        # Process each parent
        for parent in parent_dicts:
            parent_id = parent.get("chunk_id", "")
            page_start, page_end = self._get_page_range(parent)

            if page_start < 0 or page_end < 0:
                continue

            # Get children in this parent's range
            children_in_range = self._get_children_in_range(
                child_dicts, page_start, page_end
            )

            if not children_in_range:
                continue

            # NEW: Check if this parent has high concentration
            # If it has many children, we should definitely try to enrich
            parent_child_count = len(children_in_range)
            total_children = len(child_dicts)
            parent_concentration = (
                parent_child_count / total_children if total_children > 0 else 0
            )

            # Trace: Red flag for high concentration (>50%)
            if parent_concentration > 0.50:
                emitter.emit_red_flag(
                    "7.5",
                    "hierarchy_concentration",
                    {
                        "parent_id": parent_id[:50],
                        "parent_title": parent.get("toc_entry", "")[:50],
                        "child_count": parent_child_count,
                        "percentage": round(parent_concentration * 100, 1),
                    },
                )

            # Force aggressive mode for parents with >30% of all children
            use_aggressive = is_severely_flat or parent_concentration > 0.30

            # Detect sub-sections (use aggressive mode for flat hierarchies and concentrated parents)
            detected_sections = self._detect_sections(
                children_in_range, parent, report_id, aggressive=use_aggressive
            )

            if detected_sections:
                # Create new parent chunks for detected sections
                for section in detected_sections:
                    new_parent = self._create_sub_parent(section, parent, report_id)
                    new_parents.append(new_parent)

                # Update child assignments
                section_assignments = self._assign_children_to_sections(
                    children_in_range, detected_sections, parent_id
                )
                child_updates.update(section_assignments)

        # Apply child updates
        updated_children = []
        for child in child_dicts:
            child_id = child.get("chunk_id", "")
            if child_id in child_updates:
                child = child.copy()
                new_parent_id = child_updates[child_id]
                child["parent_chunk_id"] = new_parent_id

                # Update hierarchy metadata
                self._update_child_hierarchy(
                    child, new_parent_id, new_parents
                )

            updated_children.append(child)

        # Combine parents
        enriched_parents = parent_dicts + new_parents

        # Trace: Enrichment result
        emitter.emit_io(
            "7.5",
            {"parents_before": len(parent_dicts), "children_before": len(child_dicts)},
            {
                "parents_after": len(enriched_parents),
                "new_parents": len(new_parents),
                "reassignments": len(child_updates),
            },
        )

        logger.info(
            f"[{report_id}] Hierarchy Enricher: Added {len(new_parents)} sub-sections, "
            f"updated {len(child_updates)} child assignments"
        )

        # ── POST-PROCESS: Force-sync child hierarchies to final parent state ──
        # This fixes timing issues where _update_child_hierarchy() ran before
        # parent hierarchy was fully built (e.g., missing inherited levels).
        parent_lookup_final = {p.get("chunk_id"): p for p in enriched_parents}
        synced = 0
        for child in updated_children:
            pid = child.get("parent_chunk_id", "")
            parent = parent_lookup_final.get(pid)
            if not parent:
                continue
            parent_h = parent.get("hierarchy", {})
            if child.get("hierarchy") != parent_h:
                child["hierarchy"] = parent_h.copy()
                if isinstance(child.get("metadata"), dict):
                    child["metadata"]["hierarchy"] = parent_h.copy()
                synced += 1
        if synced > 0:
            logger.info(f"[{report_id}] Hierarchy post-sync: fixed {synced} child↔parent mismatches")

        return enriched_parents, updated_children

    def _get_page_range(self, parent: Dict) -> Tuple[int, int]:
        """Extract page range from parent chunk."""
        page_range = parent.get("page_range_physical", [-1, -1])
        if isinstance(page_range, (list, tuple)) and len(page_range) >= 2:
            return page_range[0], page_range[1]
        return -1, -1

    def _get_children_in_range(
        self, children: List[Dict], page_start: int, page_end: int
    ) -> List[Dict]:
        """Get children within a page range."""
        result = []

        for child in children:
            page = self._get_child_page(child)
            if page is not None and page_start <= page <= page_end:
                result.append(child)

        # Sort by page and vertical position
        result.sort(
            key=lambda c: (
                self._get_child_page(c) or 0,
                self._get_child_y_position(c) or 0,
            )
        )

        return result

    def _get_child_page(self, child: Dict) -> Optional[int]:
        """Get page number from child chunk."""
        # Try metadata.location.page_physical
        meta = child.get("metadata", {})
        if isinstance(meta, dict):
            loc = meta.get("location", {})
            if isinstance(loc, dict):
                page = loc.get("page_physical")
                if page is not None:
                    return page

        # Try direct fields
        page = (
            child.get("source_page_physical")
            or child.get("page_physical")
            or child.get("page_start")
        )
        return page

    def _get_child_y_position(self, child: Dict) -> Optional[float]:
        """Get Y position from child chunk."""
        meta = child.get("metadata", {})
        if isinstance(meta, dict):
            loc = meta.get("location", {})
            if isinstance(loc, dict):
                bbox = loc.get("bbox")
                if bbox and len(bbox) >= 2:
                    return bbox[1]  # Y coordinate

        # Try direct bbox
        bbox = child.get("source_bbox") or child.get("bbox")
        if bbox and len(bbox) >= 2:
            return bbox[1]

        return None

    def _detect_sections(
        self,
        chunks: List[Dict],
        parent: Dict,
        report_id: str,
        aggressive: bool = False,
    ) -> List[DetectedSection]:
        """
        Detect numbered sections in chunks.

        Args:
            chunks: List of child chunks to scan
            parent: Parent chunk these children belong to
            report_id: Report ID for logging
            aggressive: If True, be more aggressive in detection (for flat hierarchies)
        """
        detected = []
        seen_sections: Set[str] = set()

        for chunk in chunks:
            content = chunk.get("content", "")
            if isinstance(content, str):
                content = content.strip()
            else:
                continue

            content_type = chunk.get("content_type", "")

            # Skip if too short
            if len(content) < self.min_section_length:
                continue

            # For long content, only check first line
            if len(content) > self.max_section_title_length:
                if (
                    self.detect_in_paragraphs or aggressive
                ):
                    content = content.split("\n")[0][: self.max_section_title_length]
                else:
                    continue

            # Check if this looks like a section header
            is_header_type = content_type in self.HEADER_CONTENT_TYPES
            is_header_pattern = any(p.match(content) for p in self._header_indicators)

            # In aggressive mode, also check first line of paragraphs
            if not (is_header_type or is_header_pattern):
                if (
                    aggressive or self.detect_in_paragraphs
                ) and content_type == "paragraph":
                    first_line = content.split("\n")[0].strip()
                    is_header_pattern = any(
                        p.match(first_line) for p in self._header_indicators
                    )
                    if is_header_pattern:
                        content = first_line

                if not is_header_pattern:
                    continue

            # Try to match section patterns
            matched = False
            for level, patterns in self._section_patterns.items():
                if matched:
                    break

                for pattern, pattern_type in patterns:
                    match = pattern.match(content)
                    if match:
                        groups = match.groups()

                        # Extract section ID and title based on pattern type
                        if pattern_type == "standalone":
                            # Standalone sections like "Preface", "Executive Summary"
                            section_id = ""
                            title = groups[0] if groups else content
                        elif pattern_type in (
                            "chapter_roman",
                            "chapter_num",
                            "chapter_roman_upper",
                            "chapter_num_upper",
                        ):
                            # Chapter patterns: "Chapter I" or "Chapter 1"
                            section_id = groups[1] if len(groups) > 1 else ""
                            title = (
                                f"{groups[0]} {groups[1]}"
                                if len(groups) > 1
                                else content
                            )
                        elif len(groups) >= 2:
                            section_id = groups[0]
                            title = groups[1]
                        elif len(groups) == 1:
                            section_id = ""
                            title = groups[0]
                        else:
                            continue

                        # Create unique key
                        section_key = f"{level}:{section_id}:{title[:30]}"

                        if section_key in seen_sections:
                            continue
                        seen_sections.add(section_key)

                        # Build full title
                        if section_id and section_id not in title:
                            full_title = f"{section_id} {title}".strip()
                        else:
                            full_title = title.strip()

                        # Get page info
                        page_physical = self._get_child_page(chunk) or 0

                        # Get page_logical
                        meta = chunk.get("metadata", {})
                        page_logical = ""
                        if isinstance(meta, dict):
                            loc = meta.get("location", {})
                            if isinstance(loc, dict):
                                page_logical = loc.get("page_logical", "")
                        if not page_logical:
                            page_logical = chunk.get("source_page_logical", "")

                        # Get bbox
                        bbox = None
                        if isinstance(meta, dict):
                            loc = meta.get("location", {})
                            if isinstance(loc, dict):
                                bbox = loc.get("bbox")
                        if not bbox:
                            bbox = chunk.get("source_bbox") or chunk.get("bbox")

                        section = DetectedSection(
                            section_id=section_id,
                            title=full_title,
                            level=level,
                            page_physical=page_physical,
                            page_logical=str(page_logical) if page_logical else "",
                            bbox=bbox,
                            parent_chunk_id=parent.get("chunk_id", ""),
                        )
                        detected.append(section)
                        matched = True
                        break

        # Log what we found
        if detected:
            logger.info(
                f"[{report_id}] Detected {len(detected)} sections: {[s.title[:30] for s in detected[:5]]}"
            )

        return detected

    def _create_sub_parent(
        self,
        section: DetectedSection,
        parent: Dict,
        report_id: str,
    ) -> Dict:
        """Create a new parent chunk for a detected section."""
        # Generate unique chunk ID
        hash_input = (
            f"{report_id}:{section.section_id}:{section.title}:{section.page_physical}"
        )
        chunk_hash = hashlib.md5(hash_input.encode()).hexdigest()[:8]

        section_id_safe = re.sub(r"[^a-zA-Z0-9]", "_", section.section_id)[:20]
        title_safe = re.sub(r"[^a-zA-Z0-9]", "_", section.title)[:20]
        chunk_id = f"{report_id}_parent_L{section.level}_{section_id_safe or title_safe}_{chunk_hash}"

        # Build hierarchy from detected section structure, not from a single mega-parent
        parent_hierarchy = parent.get("hierarchy", {})
        if not isinstance(parent_hierarchy, dict):
            parent_hierarchy = {}

        # Only inherit levels ABOVE the detected section's level
        # AND only if they make structural sense
        hierarchy = {}
        for key, value in parent_hierarchy.items():
            if key.startswith("level_"):
                try:
                    level_num = int(key.split("_")[1])
                    # Only inherit levels strictly above this section's level
                    if level_num < section.level:
                        hierarchy[key] = value
                except (IndexError, ValueError):
                    # Skip malformed level keys
                    pass

        # Add the detected section at its level
        hierarchy[f"level_{section.level}"] = section.title

        return {
            "chunk_id": chunk_id,
            "report_id": report_id,
            "toc_entry": section.title,
            "toc_level": section.level,
            "page_range_physical": [section.page_physical, section.page_physical],
            "page_range_logical": [section.page_logical, section.page_logical],
            "hierarchy": hierarchy,
            "parent_chunk_id": parent.get("chunk_id"),
            "detected_by": "hierarchy_enricher",
            "section_id": section.section_id,
            # Tier metadata comes from the enclosing parent, not model defaults
            **{
                key: parent[key]
                for key in ("government_body_type", "state_name", "department", "audit_category")
                if parent.get(key) is not None
            },
        }

    def _assign_children_to_sections(
        self,
        children: List[Dict],
        sections: List[DetectedSection],
        fallback_parent_id: str,
    ) -> Dict[str, str]:
        """
        Assign children to their nearest detected section.

        Returns:
            Dict mapping child_id -> new_parent_id
        """
        if not sections:
            return {}

        # Sort sections by page
        sorted_sections = sorted(
            sections, key=lambda s: (s.page_physical, s.bbox[1] if s.bbox else 0)
        )

        assignments = {}

        for child in children:
            child_id = child.get("chunk_id", "")
            child_page = self._get_child_page(child) or 0
            child_y = self._get_child_y_position(child) or 0

            # Find the section this child belongs to
            assigned_section = None

            for section in sorted_sections:
                if section.page_physical < child_page:
                    assigned_section = section
                elif section.page_physical == child_page:
                    section_y = section.bbox[1] if section.bbox else 0
                    if section_y <= child_y:
                        assigned_section = section

            if assigned_section:
                # Build new parent ID (must match what _create_sub_parent generates)
                report_id = child.get(
                    "report_id",
                    fallback_parent_id.split("_parent_")[0]
                    if "_parent_" in fallback_parent_id
                    else "unknown",
                )
                hash_input = f"{report_id}:{assigned_section.section_id}:{assigned_section.title}:{assigned_section.page_physical}"
                chunk_hash = hashlib.md5(hash_input.encode()).hexdigest()[:8]
                section_id_safe = re.sub(
                    r"[^a-zA-Z0-9]", "_", assigned_section.section_id
                )[:20]
                title_safe = re.sub(r"[^a-zA-Z0-9]", "_", assigned_section.title)[:20]
                new_parent_id = f"{report_id}_parent_L{assigned_section.level}_{section_id_safe or title_safe}_{chunk_hash}"

                assignments[child_id] = new_parent_id

        return assignments

    def _update_child_hierarchy(
        self,
        child: Dict,
        new_parent_id: str,
        new_parents: List[Dict],
    ) -> None:
        """Update child's hierarchy metadata."""
        # Find the new parent
        new_parent = None
        for p in new_parents:
            if p.get("chunk_id") == new_parent_id:
                new_parent = p
                break

        if not new_parent:
            return

        # Write to top-level "hierarchy" field (read by assembly service)
        new_hierarchy = new_parent.get("hierarchy", {})
        if isinstance(new_hierarchy, dict):
            child["hierarchy"] = new_hierarchy.copy()  # ← CORRECT LOCATION

        # Also update metadata for consistency
        if "metadata" not in child or not isinstance(child.get("metadata"), dict):
            child["metadata"] = {}
        child["metadata"]["hierarchy"] = new_hierarchy.copy()


def enrich_report_hierarchy(
    parent_chunks: List[Any],
    child_chunks: List[Any],
    report_id: str = "unknown",
    aggressive: bool = False,
    trace_emitter=None,
) -> Tuple[List[Dict], List[Dict]]:
    """
    Convenience function for pipeline integration.

    Args:
        parent_chunks: Existing parent chunks (dict or dataclass)
        child_chunks: Child content chunks (dict or dataclass)
        report_id: Report identifier
        aggressive: If True, use aggressive section detection
        trace_emitter: Optional TraceEmitter for instrumentation

    Returns:
        Tuple of (enriched_parents, updated_children) as dicts
    """
    enricher = HierarchyEnricher(trace_emitter=trace_emitter)
    return enricher.enrich_hierarchy(parent_chunks, child_chunks, report_id, aggressive, trace_emitter=trace_emitter)


OVERSIZED_PARENT_CHILDREN = 80


def should_enrich_hierarchy(
    parent_chunks: List[Any],
    child_chunks: List[Any],
) -> Tuple[bool, Optional[str]]:
    """
    Determine if hierarchy enrichment is needed.

    This function checks four conditions:
    1. Few parents (< 10) - original behavior
    2. Flat hierarchy (< 30% of children have level_2+ hierarchy)
    3. High concentration (> 40% of children assigned to one parent)
    4. Oversized parent (> OVERSIZED_PARENT_CHILDREN children under one parent)

    Args:
        parent_chunks: List of parent chunks (Pydantic objects or dicts)
        child_chunks: List of child chunks (Pydantic objects or dicts)

    Returns:
        Tuple of (needs_enrichment: bool, reason: str or None)
        reason is one of: "few_parents", "flat_hierarchy", "high_concentration",
        "oversized_parent", or None

    Usage in main.py:
        from modules.hierarchy_enricher import should_enrich_hierarchy

        needs_enrichment, enrich_reason = should_enrich_hierarchy(
            task.parent_chunks, task.child_chunks
        )
        if needs_enrichment:
            # Run enrichment with aggressive mode for flat/concentrated hierarchies
            aggressive_mode = enrich_reason in ["flat_hierarchy", "high_concentration"]
            ...
    """
    # Condition 1: Few parents (original logic)
    if len(parent_chunks) < 10:
        return True, "few_parents"

    # Condition 2: Flat hierarchy (children don't have deep links)
    if child_chunks:
        deep_count = 0
        for c in child_chunks:
            # Handle both Pydantic objects and dicts
            if hasattr(c, "hierarchy"):
                h = c.hierarchy
            elif isinstance(c, dict):
                h = c.get("hierarchy", {})
            else:
                h = {}

            if isinstance(h, dict) and len(h) > 1:  # Has level_2 or deeper
                deep_count += 1

        deep_rate = deep_count / len(child_chunks) if child_chunks else 0
        if deep_rate < 0.30:  # Less than 30% have nested hierarchy
            return True, "flat_hierarchy"

    # Condition 3: High concentration (most children assigned to one parent)
    if child_chunks and parent_chunks:
        parent_counts: Counter = Counter()
        for c in child_chunks:
            if hasattr(c, "parent_chunk_id"):
                pid = c.parent_chunk_id
            elif isinstance(c, dict):
                pid = c.get("parent_chunk_id", "")
            else:
                pid = ""
            parent_counts[pid] += 1

        if parent_counts:
            max_children = parent_counts.most_common(1)[0][1]
            concentration = max_children / len(child_chunks)
            if concentration > 0.40:  # More than 40% to one parent
                return True, "high_concentration"

            # Condition 4: Oversized parent. With correct chapter-level TOCs (printed
            # contents often lists chapters only), one chapter can hold 100+ children
            # while no single parent reaches 40% of the report.
            if max_children > OVERSIZED_PARENT_CHILDREN:
                return True, "oversized_parent"

    return False, None
