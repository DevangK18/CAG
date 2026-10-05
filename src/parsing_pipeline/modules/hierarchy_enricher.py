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

2026-10 (B-7.5-01/02/03):
- Each parent scans only its own members (parent_chunk_id), not its page range
- Detected sections are de-duplicated report-wide; IDs include the enclosing
  parent; a section must be deeper than its parent (no invented L1 parents)
- Safety valve: duplicate IDs, children outside their parent's pages or a
  lopsided result -> WARNING and the input is returned unchanged
- Post-sync touches only re-parented children
- Trigger thresholds are named constants; ``aggressive_for_reason`` is the
  single place that maps a trigger reason to the ``aggressive`` flag
"""

import copy
import re
from difflib import SequenceMatcher
from typing import List, Dict, Tuple, Optional, Set, Any, Union
from dataclasses import dataclass, field, is_dataclass, asdict
from collections import defaultdict, Counter
import logging
import hashlib

from src.parsing_pipeline.instrumentation import get_noop_emitter

from src.parsing_pipeline.modules.printed_toc_parser import roman_to_int

logger = logging.getLogger(__name__)

# ── Phase 7.5 trigger thresholds (should_enrich_hierarchy) ──
FEW_PARENTS_THRESHOLD = 10  # fewer parents than this -> "few_parents"
FLAT_DEEP_RATE_THRESHOLD = 0.30  # share of children with level_2+ below this -> "flat_hierarchy"
HIGH_CONCENTRATION_THRESHOLD = 0.40  # one parent above this share -> "high_concentration"
OVERSIZED_PARENT_CHILDREN = 80  # one parent above this many children -> "oversized_parent"

# Trigger reasons that run detection in aggressive mode. Both runners must
# derive the flag through aggressive_for_reason() so they behave the same.
AGGRESSIVE_REASONS = frozenset({"flat_hierarchy", "high_concentration", "oversized_parent"})

# Reports with this many parents or fewer always use aggressive detection
SEVERELY_FLAT_MAX_PARENTS = 3

# ── Phase 7.5 safety valve ──
VALVE_PAGE_TOLERANCE = 1  # re-parented child may sit this many pages outside its parent
VALVE_MAX_CHILD_SHARE = HIGH_CONCENTRATION_THRESHOLD  # max share of children per parent / level_1
EXISTING_TITLE_SIMILARITY = 0.85  # detected section duplicates an existing parent at/above this


def aggressive_for_reason(reason: Optional[str]) -> bool:
    """The ``aggressive`` flag for a should_enrich_hierarchy() reason."""
    return reason in AGGRESSIVE_REASONS


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
    chunk_id: str = ""  # set when the sub-parent is created


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

    NUMBERED_TYPES = frozenset({"numbered", "numbered_3", "numbered_4", "numbered_5"})

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
        # Outcome of the last enrich_hierarchy() call:
        # {"status": "applied" | "no_change" | "rejected" | "skipped", ...}
        self.last_outcome: Dict[str, Any] = {"status": "skipped"}

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
        aggressive: bool = False,
        trace_emitter=None,
    ) -> Tuple[List[Any], List[Any]]:
        """
        Enrich flat hierarchy by detecting sub-sections.

        Each parent scans only its own members (children whose
        ``parent_chunk_id`` is that parent), so every child is examined once.
        Detected sections are de-duplicated report-wide, get IDs that include
        the enclosing parent, and must sit strictly below the enclosing
        parent's level. The result is validated (``_validate_enrichment``);
        if validation fails, the input is returned unchanged.

        Args:
            parent_chunks: Existing parent (TOC) chunks (dict or dataclass)
            child_chunks: Content chunks with parent references (dict or dataclass)
            report_id: Report identifier for logging
            aggressive: If True, use aggressive detection even with many parents
                       (see ``aggressive_for_reason``)
            trace_emitter: Optional TraceEmitter for instrumentation

        Returns:
            Tuple of (enriched_parent_chunks, updated_child_chunks) as dicts,
            or the inputs exactly as given when nothing changed or the safety
            valve rejected the result.
        """
        emitter = trace_emitter or self._trace_emitter
        self.last_outcome = {"status": "skipped", "reason": "no input"}

        if not parent_chunks or not child_chunks:
            return (
                [to_dict(p) for p in parent_chunks] if parent_chunks else [],
                [to_dict(c) for c in child_chunks] if child_chunks else [],
            )

        # Convert inputs to dicts. Dict inputs are shared, never mutated:
        # children are deep-copied before any change, so the caller's lists
        # stay a valid pre-7.5 hierarchy for the safety-valve fallback.
        parent_dicts = [to_dict(p) for p in parent_chunks]
        child_dicts = [to_dict(c) for c in child_chunks]
        total_children = len(child_dicts)

        is_severely_flat = len(parent_dicts) <= SEVERELY_FLAT_MAX_PARENTS or aggressive
        if is_severely_flat:
            reason = (
                "explicitly requested" if aggressive else f"{len(parent_dicts)} parents"
            )
            logger.info(f"[{report_id}] Aggressive hierarchy detection ({reason})")

        parent_lookup = {p.get("chunk_id"): p for p in parent_dicts}

        # Membership: parent_chunk_id -> its children
        members: Dict[str, List[Dict]] = defaultdict(list)
        for c in child_dicts:
            members[c.get("parent_chunk_id", "")].append(c)

        # Trace: Parent distribution sample (top 5 by child count)
        top_parents = sorted(
            ((pid, len(kids)) for pid, kids in members.items()),
            key=lambda x: -x[1],
        )[:5]
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

        existing_index = self._build_existing_parent_index(parent_dicts)

        # ── Pass 1: detect sections per parent, over its own members only ──
        # dedup key -> (section, enclosing parent, parent order)
        candidates: Dict[Tuple[int, str], Tuple[DetectedSection, Dict, int]] = {}
        members_in_range: Dict[str, List[Dict]] = {}
        skipped = Counter()

        for order, parent in enumerate(parent_dicts):
            parent_id = parent.get("chunk_id", "")
            page_start, page_end = self._get_page_range(parent)
            if page_start < 0 or page_end < 0:
                continue

            # Only members inside the parent's own pages are scanned and moved;
            # members placed by Phase 7's nearest-parent fallback stay put.
            kids = [
                c
                for c in members.get(parent_id, [])
                if (p := self._get_child_page(c)) is not None and page_start <= p <= page_end
            ]
            if not kids:
                continue
            kids.sort(
                key=lambda c: (
                    self._get_child_page(c) or 0,
                    self._get_child_y_position(c) or 0,
                )
            )
            members_in_range[parent_id] = kids

            parent_concentration = len(members.get(parent_id, [])) / total_children

            # Trace: Red flag for high concentration (>50%)
            if parent_concentration > 0.50:
                emitter.emit_red_flag(
                    "7.5",
                    "hierarchy_concentration",
                    {
                        "parent_id": parent_id[:50],
                        "parent_title": parent.get("toc_entry", "")[:50],
                        "child_count": len(members.get(parent_id, [])),
                        "percentage": round(parent_concentration * 100, 1),
                    },
                )

            # Force aggressive mode for parents with >30% of all children
            use_aggressive = is_severely_flat or parent_concentration > 0.30

            detected = self._detect_sections(
                kids, parent, report_id, aggressive=use_aggressive
            )

            parent_level = self._get_level(parent)
            parent_number = self._enclosing_number(parent)
            for section in detected:
                # A numbered section fits only under its own number: "5.5.2" under
                # "5.5 …" or chapter V, never under "4.1"; its level is relative to
                # the enclosing parent (B-7.5-01)
                fit = self._fit_level(section.section_id, parent_number, parent_level)
                if fit is None:
                    skipped["does_not_fit_enclosing_parent"] += 1
                    continue
                section.level = fit
                # No invented roots or siblings: a sub-section must be deeper
                # than the parent it is found in.
                if section.level <= parent_level:
                    skipped["not_deeper_than_parent"] += 1
                    continue
                if self._matches_existing_parent(section, existing_index):
                    skipped["duplicates_existing_parent"] += 1
                    continue
                key = self._dedup_key(section)
                prev = candidates.get(key)
                if prev is None:
                    candidates[key] = (section, parent, order)
                elif self._is_narrower(parent, order, prev[1], prev[2]):
                    candidates[key] = (section, parent, order)
                    skipped["duplicate_heading"] += 1
                else:
                    skipped["duplicate_heading"] += 1

        # ── Pass 2: create sub-parents and re-assign members ──
        sections_by_parent: Dict[str, List[DetectedSection]] = defaultdict(list)
        for section, parent, _ in candidates.values():
            sections_by_parent[parent.get("chunk_id", "")].append(section)

        new_parents: List[Dict] = []
        child_updates: Dict[str, str] = {}  # child chunk_id -> new parent chunk_id
        used_ids: Set[str] = set(parent_lookup)

        for parent in parent_dicts:
            parent_id = parent.get("chunk_id", "")
            sections = sections_by_parent.get(parent_id)
            if not sections:
                continue

            kept_sections = []
            for section in sections:
                section.chunk_id = self._sub_parent_id(section, parent_id, report_id)
                if section.chunk_id in used_ids:
                    skipped["id_collision"] += 1
                    continue
                used_ids.add(section.chunk_id)
                kept_sections.append(section)
            if not kept_sections:
                continue

            kids = members_in_range.get(parent_id, [])
            assignments = self._assign_children_to_sections(kids, kept_sections)
            child_updates.update(assignments)

            kids_by_section: Dict[str, List[Dict]] = defaultdict(list)
            for c in kids:
                sid = assignments.get(c.get("chunk_id", ""))
                if sid:
                    kids_by_section[sid].append(c)

            for section in kept_sections:
                new_parents.append(
                    self._create_sub_parent(
                        section, parent, report_id, kids_by_section.get(section.chunk_id, [])
                    )
                )

        if skipped:
            logger.info(f"[{report_id}] Hierarchy Enricher: skipped detections {dict(skipped)}")

        if not new_parents:
            logger.info(f"[{report_id}] Hierarchy Enricher: no sub-sections added")
            self.last_outcome = {"status": "no_change", "skipped": dict(skipped)}
            return parent_dicts, child_dicts

        # Apply child updates (deep copies; input children are never mutated)
        new_parent_lookup = {p["chunk_id"]: p for p in new_parents}
        updated_children = []
        for child in child_dicts:
            child_id = child.get("chunk_id", "")
            if child_id in child_updates:
                child = copy.deepcopy(child)
                child["parent_chunk_id"] = child_updates[child_id]
            updated_children.append(child)

        enriched_parents = parent_dicts + new_parents

        logger.info(
            f"[{report_id}] Hierarchy Enricher: Added {len(new_parents)} sub-sections, "
            f"updated {len(child_updates)} child assignments"
        )

        # ── POST-SYNC: copy the final hierarchy onto re-parented children only ──
        # Children that enrichment did not move keep their hierarchy (B-7.5-02).
        synced = 0
        for child in updated_children:
            if child.get("chunk_id", "") not in child_updates:
                continue
            parent = new_parent_lookup.get(child.get("parent_chunk_id", ""))
            if not parent:
                continue
            parent_h = parent.get("hierarchy", {})
            if child.get("hierarchy") != parent_h:
                child["hierarchy"] = dict(parent_h)
                synced += 1
            if isinstance(child.get("metadata"), dict):
                child["metadata"]["hierarchy"] = dict(parent_h)
        if synced > 0:
            logger.info(f"[{report_id}] Hierarchy post-sync: updated {synced} re-parented children")

        # ── SAFETY VALVE: never emit a corrupted hierarchy ──
        problems = self._validate_enrichment(
            parent_dicts, child_dicts, enriched_parents, updated_children, set(child_updates)
        )
        if problems:
            logger.warning(
                f"[{report_id}] Hierarchy enrichment rejected, keeping pre-7.5 hierarchy "
                f"({len(parent_dicts)} parents, {total_children} children): " + "; ".join(problems)
            )
            emitter.emit_red_flag(
                "7.5",
                "hierarchy_enrichment_rejected",
                {"problems": problems, "new_parents": len(new_parents), "reassignments": len(child_updates)},
            )
            self.last_outcome = {"status": "rejected", "problems": problems}
            return parent_chunks, child_chunks

        # Trace: Enrichment result
        emitter.emit_io(
            "7.5",
            {"parents_before": len(parent_dicts), "children_before": total_children},
            {
                "parents_after": len(enriched_parents),
                "new_parents": len(new_parents),
                "reassignments": len(child_updates),
            },
        )
        self.last_outcome = {
            "status": "applied",
            "new_parents": len(new_parents),
            "reassignments": len(child_updates),
            "skipped": dict(skipped),
        }
        return enriched_parents, updated_children

    # ─────────────────────────────────────────────────────────────────────
    # Dedup and validation helpers
    # ─────────────────────────────────────────────────────────────────────

    @staticmethod
    def _get_level(parent: Dict) -> int:
        try:
            return int(parent.get("toc_level") or 1)
        except (TypeError, ValueError):
            return 1

    @staticmethod
    def _normalize_title(text: str) -> str:
        return " ".join(re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).split())

    @classmethod
    def _title_words(cls, text: str) -> str:
        """Normalised title without section numbers (for similarity)."""
        t = cls._normalize_title(text)
        return " ".join(w for w in t.split() if not re.fullmatch(r"[0-9]+", w))

    def _dedup_key(self, section: DetectedSection) -> Tuple[int, str]:
        """Report-wide identity of a detected heading: page + normalised title."""
        return (section.page_physical, self._normalize_title(section.title))

    def _build_existing_parent_index(self, parents: List[Dict]) -> List[Tuple[int, int, str, str]]:
        """(start, end, raw title, title words) for every existing parent."""
        index = []
        for p in parents:
            start, end = self._get_page_range(p)
            title = str(p.get("toc_entry") or "")
            index.append((start, end, title, self._title_words(title)))
        return index

    def _matches_existing_parent(
        self, section: DetectedSection, existing_index: List[Tuple[int, int, str, str]]
    ) -> bool:
        """True if the section is already a parent on (or next to) its page.

        Dotted section numbers ("1.2", "5.6.1") match when an existing parent
        title carries the same number anywhere ("Organisational setup of PRIs
        1.2"). Other sections match on title similarity >= 0.85.
        """
        page = section.page_physical
        sid = (section.section_id or "").rstrip(".")
        number_re = (
            re.compile(rf"(?<![\d.]){re.escape(sid)}(?![\d]|\.\d)") if "." in sid else None
        )
        words = self._title_words(section.title)
        for start, end, title, title_words in existing_index:
            if start < 0 or not (start - 1 <= page <= end + 1):
                continue
            if number_re is not None:
                if number_re.search(title):
                    return True
            elif words and title_words and (
                SequenceMatcher(None, words, title_words).ratio() >= EXISTING_TITLE_SIMILARITY
            ):
                return True
        return False

    def _is_narrower(self, parent: Dict, order: int, other: Dict, other_order: int) -> bool:
        """True if ``parent`` is more specific than ``other`` (narrowest wins)."""

        def rank(p: Dict, o: int) -> Tuple[int, int, int]:
            start, end = self._get_page_range(p)
            return (end - start, -self._get_level(p), o)

        return rank(parent, order) < rank(other, other_order)

    def _validate_enrichment(
        self,
        parents_in: List[Dict],
        children_in: List[Dict],
        parents_out: List[Dict],
        children_out: List[Dict],
        reparented: Set[str],
    ) -> List[str]:
        """Return the list of failed checks (empty when the result is safe)."""
        problems = []

        # 1. Unique parent IDs
        ids = [p.get("chunk_id") for p in parents_out]
        dup_ids = sum(1 for n in Counter(ids).values() if n > 1)
        if dup_ids:
            problems.append(f"{dup_ids} duplicate parent ids ({len(ids)} parents, {len(set(ids))} unique)")

        # 2. Every re-parented child inside its new parent's pages (+/- tolerance).
        #    Children enrichment did not move are unchanged from the input.
        lookup = {p.get("chunk_id"): p for p in parents_out}
        tol = VALVE_PAGE_TOLERANCE
        outside = 0
        for c in children_out:
            if c.get("chunk_id", "") not in reparented:
                continue
            p = lookup.get(c.get("parent_chunk_id"))
            page = self._get_child_page(c)
            if p is None or page is None:
                outside += 1
                continue
            start, end = self._get_page_range(p)
            if not (start - tol <= page <= end + tol):
                outside += 1
        if outside:
            problems.append(
                f"{outside} of {len(reparented)} re-parented children outside their parent's pages (+/-{tol})"
            )

        # 3. No single parent, and no single top-level section, holding more
        #    than a sane share of all children (unless the input already did).
        total = len(children_out) or 1

        def max_share(children: List[Dict], key) -> Tuple[float, Any]:
            counts = Counter(key(c) for c in children)
            if not counts:
                return 0.0, None
            k, n = counts.most_common(1)[0]
            return n / total, k

        def top_level(c: Dict) -> Any:
            h = c.get("hierarchy")
            return h.get("level_1") if isinstance(h, dict) else None

        for label, key in (
            ("parent", lambda c: c.get("parent_chunk_id")),
            ("level_1 section", top_level),
        ):
            share_in, _ = max_share(children_in, key)
            share_out, k = max_share(children_out, key)
            allowed = max(VALVE_MAX_CHILD_SHARE, share_in)
            if share_out > allowed + 1e-9:
                problems.append(
                    f"one {label} ({str(k)[:60]!r}) holds {share_out:.0%} of children "
                    f"(limit {allowed:.0%})"
                )

        return problems

    def _get_page_range(self, parent: Dict) -> Tuple[int, int]:
        """Extract page range from parent chunk."""
        page_range = parent.get("page_range_physical", [-1, -1])
        if isinstance(page_range, (list, tuple)) and len(page_range) >= 2:
            return page_range[0], page_range[1]
        return -1, -1

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

        # Try direct fields (page 0 is valid, so test for None, not truthiness)
        for key in ("source_page_physical", "page_physical", "page_start"):
            page = child.get(key)
            if page is not None:
                return page
        return None

    def _get_child_page_logical(self, child: Dict) -> str:
        """Get the printed page label from a child chunk."""
        meta = child.get("metadata", {})
        if isinstance(meta, dict):
            loc = meta.get("location", {})
            if isinstance(loc, dict) and loc.get("page_logical"):
                return str(loc["page_logical"])
        value = child.get("source_page_logical")
        return str(value) if value else ""

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

                        # Only numbered sections create parents: roman, lettered and
                        # bullet points are list items in CAG reports (B-7.5-01)
                        if pattern_type not in self.NUMBERED_TYPES:
                            matched = True
                            break

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

    @staticmethod
    def _enclosing_number(parent: Dict) -> Optional[str]:
        """'5.5' for "5.5 Planning …" (or "Planning … 5.5"), '5' for "Chapter V …"."""
        title = str(parent.get("toc_entry") or "")
        m = re.match(r"^\s*(\d+(?:\.\d+)*)\.?\s", title) or re.search(r"\s(\d+(?:\.\d+)+)\s*$", title)
        if m:
            return m.group(1)
        m = re.match(r"^\s*(?:chapter|ch\.)\s*[-–:.]?\s*([ivxlc]+|\d+)\b", title, re.IGNORECASE)
        if not m:
            m = re.match(r"^\s*([IVX]{1,5})\s+(?=[A-Z]{2})", title)
        if m:
            token = m.group(1)
            return token if token.isdigit() else str(roman_to_int(token))
        return None

    @staticmethod
    def _fit_level(section_id: str, parent_number: Optional[str], parent_level: int) -> Optional[int]:
        """Level of a numbered section under its enclosing parent, or None if it does not fit."""
        parts = section_id.split(".") if section_id else []
        if not parts:
            return None
        if parent_number is None:
            return parent_level + 1
        prefix = parent_number.split(".")
        if len(parts) <= len(prefix) or parts[: len(prefix)] != prefix:
            return None
        return parent_level + (len(parts) - len(prefix))

    @staticmethod
    def _sub_parent_id(section: DetectedSection, enclosing_parent_id: str, report_id: str) -> str:
        """Chunk ID for a detected section. Includes the enclosing parent, so the
        same heading text under two different parents never shares an ID."""
        hash_input = (
            f"{report_id}:{enclosing_parent_id}:{section.section_id}:"
            f"{section.title}:{section.page_physical}"
        )
        chunk_hash = hashlib.md5(hash_input.encode()).hexdigest()[:8]
        section_id_safe = re.sub(r"[^a-zA-Z0-9]", "_", section.section_id)[:20]
        title_safe = re.sub(r"[^a-zA-Z0-9]", "_", section.title)[:20]
        return f"{report_id}_parent_L{section.level}_{section_id_safe or title_safe}_{chunk_hash}"

    def _create_sub_parent(
        self,
        section: DetectedSection,
        parent: Dict,
        report_id: str,
        assigned_children: Optional[List[Dict]] = None,
    ) -> Dict:
        """Create a new parent chunk for a detected section.

        The page range runs from the heading page to the last page of the
        children assigned to it (always within the enclosing parent's members).
        """
        chunk_id = section.chunk_id or self._sub_parent_id(
            section, parent.get("chunk_id", ""), report_id
        )

        # Build hierarchy from detected section structure, not from a single mega-parent
        parent_hierarchy = parent.get("hierarchy", {})
        if not isinstance(parent_hierarchy, dict):
            parent_hierarchy = {}

        # Only inherit levels ABOVE the detected section's level
        hierarchy = {}
        for key, value in parent_hierarchy.items():
            if key.startswith("level_"):
                try:
                    level_num = int(key.split("_")[1])
                    if level_num < section.level:
                        hierarchy[key] = value
                except (IndexError, ValueError):
                    pass

        # Add the detected section at its level
        hierarchy[f"level_{section.level}"] = section.title

        end_page, end_logical = section.page_physical, section.page_logical
        for c in assigned_children or []:
            page = self._get_child_page(c)
            if page is not None and page > end_page:
                end_page = page
                end_logical = self._get_child_page_logical(c) or end_logical

        return {
            "chunk_id": chunk_id,
            "report_id": report_id,
            "toc_entry": section.title,
            "toc_level": section.level,
            "page_range_physical": [section.page_physical, end_page],
            "page_range_logical": [section.page_logical, end_logical],
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
    ) -> Dict[str, str]:
        """
        Assign each child to the nearest preceding detected section.

        ``children`` must be the members of the parent the sections were
        detected in. Children before the first section are not re-assigned.

        Returns:
            Dict mapping child_id -> section chunk_id
        """
        if not sections:
            return {}

        sorted_sections = sorted(
            sections, key=lambda s: (s.page_physical, s.bbox[1] if s.bbox else 0)
        )

        assignments = {}
        for child in children:
            child_page = self._get_child_page(child) or 0
            child_y = self._get_child_y_position(child) or 0

            assigned_section = None
            for section in sorted_sections:
                if section.page_physical < child_page:
                    assigned_section = section
                elif section.page_physical == child_page:
                    section_y = section.bbox[1] if section.bbox else 0
                    if section_y <= child_y:
                        assigned_section = section

            if assigned_section:
                assignments[child.get("chunk_id", "")] = assigned_section.chunk_id

        return assignments


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
        Tuple of (enriched_parents, updated_children); the inputs unchanged
        if the safety valve rejects the result
    """
    enricher = HierarchyEnricher(trace_emitter=trace_emitter)
    return enricher.enrich_hierarchy(parent_chunks, child_chunks, report_id, aggressive, trace_emitter=trace_emitter)



def should_enrich_hierarchy(
    parent_chunks: List[Any],
    child_chunks: List[Any],
) -> Tuple[bool, Optional[str]]:
    """
    Determine if hierarchy enrichment is needed.

    This function checks four conditions (thresholds are module constants):
    1. Few parents (< FEW_PARENTS_THRESHOLD)
    2. Flat hierarchy (< FLAT_DEEP_RATE_THRESHOLD of children have level_2+ hierarchy)
    3. High concentration (> HIGH_CONCENTRATION_THRESHOLD of children under one parent)
    4. Oversized parent (> OVERSIZED_PARENT_CHILDREN children under one parent)

    Args:
        parent_chunks: List of parent chunks (Pydantic objects or dicts)
        child_chunks: List of child chunks (Pydantic objects or dicts)

    Returns:
        Tuple of (needs_enrichment: bool, reason: str or None)
        reason is one of: "few_parents", "flat_hierarchy", "high_concentration",
        "oversized_parent", or None

    Usage (both runners):
        needs_enrichment, enrich_reason = should_enrich_hierarchy(
            task.parent_chunks, task.child_chunks
        )
        if needs_enrichment:
            parents, children = enricher.enrich_hierarchy(
                ..., aggressive=aggressive_for_reason(enrich_reason)
            )
    """
    # Condition 1: Few parents (original logic)
    if len(parent_chunks) < FEW_PARENTS_THRESHOLD:
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
        if deep_rate < FLAT_DEEP_RATE_THRESHOLD:
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
            if concentration > HIGH_CONCENTRATION_THRESHOLD:
                return True, "high_concentration"

            # Condition 4: Oversized parent. With correct chapter-level TOCs (printed
            # contents often lists chapters only), one chapter can hold 100+ children
            # while no single parent reaches 40% of the report.
            if max_children > OVERSIZED_PARENT_CHILDREN:
                return True, "oversized_parent"

    return False, None
