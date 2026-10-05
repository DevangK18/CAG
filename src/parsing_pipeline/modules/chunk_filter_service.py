"""
ChunkFilterService: Filter garbage and noise chunks before assembly.
Implements filtering rules from diagnostic report.
"""

import logging
import re
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from src.core.data_contracts import ExtractedContent

logger = logging.getLogger(__name__)

# Short lines that carry meaning however short they are: table units, source and note
# lines, captions, chapter banners and front/back matter titles. Dropping them lost
# the "(₹ in crore)" unit of most tables and the heading anchors of many sections.
UNIT_LINE_RE = re.compile(
    r"^[\[(]?\s*(?:"
    r"(?:₹|`|Rs\.?|INR)\s*(?:in\s+)?(?:crore|lakh|thousand|million|billion|cr)\b"
    r"|(?:amount|figures?|values?|expenditure|area|quantity|length|cost)s?\s+(?:are\s+)?in\b"
    r"|in\s+(?:₹|`|Rs\.?|INR|crore|lakh|per\s*cent|%)"
    r")"
    # OCR-garbled rupee sign: "(Zin crore)", "'Amount in @)"
    r"|^['(\[]\s*\S{0,2}\s*in\s+(?:crore|lakh|thousand)\b|^'?\(?amount\s+in\b"
    # any short bracketed unit note: "(Qty in million tonne)", "(Figures denote percentage)"
    r"|^\(\s*(?:[^()]{0,40}\bin\s+[^()]{1,30}"
    r"|(?:figures?|amount|qty|quantity|status|values?|area|numbers?)\b[^()]{0,40})\)$",
    re.IGNORECASE,
)
SOURCE_NOTE_RE = re.compile(
    r"^[\[(*]?\s*(?:Sources?(?:\s+of\b[^:]{0,40})?|Notes?|N\.\s?B\.?)\s*(?:[:.\-–)]|$)",
    re.IGNORECASE,
)
CAPTION_RE = re.compile(
    r"^(?i:Table|Chart|Figure|Fig\.|Graph|Annexure|Appendix|Exhibit|Box|Map|Picture|Statement|Photograph)"
    r"\s*[-–:.]?\s*[\dIVXA-Z]"
)
CHAPTER_RE = re.compile(r"^(?:Chapter\b|CHAPTER|PART[-\s–]|Part\s*[-–]\s*[IVXA-Z\d]\b)")
MATTER_TITLE_RE = re.compile(
    r"^(?:Executive\s+Summary|Preface|Foreword|Prefatory\s+Remarks?|Glossary\b.*|Abbreviations"
    r"|List\s+of\s+(?:Abbreviations|Acronyms|Tables|Charts|Figures|Appendices|Annexures)"
    r"|Appendices|Annexures|Introduction|Overview|Conclusions?|Recommendations?"
    r"|(?:Table\s+of\s+)?Contents|Acknowledge?ments?)\W*$",
    re.IGNORECASE,
)
ROMAN_BANNER_RE = re.compile(r"^[IVXL]{1,6}$")
# Lead-ins to a list of observations or recommendations ("It is recommended that:")
LEAD_IN_RE = re.compile(
    r"^\w+(?:\s+\S+){1,8}?\s+(?:following|that|below|under)\s*[:;.]?$", re.IGNORECASE
)

# Content types that are never running headers or duplicates
_NEVER_RUNNING = {"table_markdown", "image_caption", "chart_data_path", "caption"}
_BODY_TYPES = {"paragraph", "list", "table_markdown", "footnote"}
_PER_TABLE_KINDS = ("unit", "source_note", "caption")
_IMAGE_TYPES = {"image_caption", "chart_data_path"}
# Visuals Phase 10b extracts data from: kept even without a caption
_DATA_VISUALS = {"chart", "map", "diagram", "table_as_image"}


def protected_kind(text: str, content_type: str = "paragraph") -> Optional[str]:
    """Name of the meaningful short-line pattern the text matches, or None."""
    text = text.strip()
    if UNIT_LINE_RE.match(text):
        return "unit"
    if SOURCE_NOTE_RE.match(text):
        return "source_note"
    if CAPTION_RE.match(text):
        return "caption"
    if CHAPTER_RE.match(text):
        return "chapter"
    if len(text) <= 80 and MATTER_TITLE_RE.match(text):
        return "matter_title"
    if content_type == "header" and ROMAN_BANNER_RE.match(text):
        return "chapter"
    if LEAD_IN_RE.match(text):
        return "lead_in"
    return None


def collapse_table_padding(markdown: str) -> str:
    """Collapse the space padding Docling puts in every cell of a column."""
    return "\n".join(
        re.sub(r" {2,}", " ", line) if line.lstrip().startswith("|") else line
        for line in markdown.split("\n")
    )


class ChunkFilterService:
    """
    Filters extracted content to remove garbage, noise, and invalid chunks.

    Filtering rules:
    - Minimum content length (units, sources, captions and titles exempt)
    - Pattern-based rejection (page numbers, section numbers, etc.)
    - Running header/footer removal (same text, same y, top or bottom band, many pages)
    - Content type validation
    """

    # Garbage patterns to reject
    GARBAGE_PATTERNS = [
        r"^[ivxlc]+$",  # Roman numerals only
        r"^\d{1,3}$",  # Page numbers only (1-3 digits)
        r"^\d+\.\d+(\.\d+)?$",  # Section numbers only
        r"^\(\d+\)$",  # Numbered markers
        r"^\(Paragraph\s+\d+\.\d+\)$",  # Cross-references
        r"^\(Para\s+\d+\.\d+\)$",  # Short cross-references
        r"^[A-Z]\.$",  # Single letter markers
        r"^\*+$",  # Asterisks only
        r"^[-–—]+$",  # Dashes only
        r"^\d+\s+\d+\s+\d+\s+\d+",  # Number sequences (table data)
    ]

    # Minimum length thresholds by content type
    MIN_LENGTH = {
        "paragraph": 30,
        "header": 3,
        "list": 5,
        "footnote": 3,  # "1 Source: UDISE+" is a whole footnote
        "caption": 0,  # never dropped for length
        "table_markdown": 20,
        "image_caption": 10,
        "chart_data_path": 5,
    }

    # Running header/footer: same text on at least this many pages, within this
    # many points of the same y, inside this fraction of the page at top or bottom
    RUNNING_MIN_PAGES = 3
    RUNNING_Y_TOLERANCE = 5.0
    RUNNING_BAND = 0.10
    # A heading followed by body text is a running header only on this many pages:
    # real section headings ("Recommendations") can start a few pages at the same y
    RUNNING_MIN_PAGES_HEADING = 5

    def __init__(
        self,
        min_paragraph_length: int = 30,
        max_duplicate_ratio: float = 0.8,
    ):
        self.min_paragraph_length = min_paragraph_length
        self.max_duplicate_ratio = max_duplicate_ratio

        # Compile patterns for efficiency
        self._garbage_patterns = [
            re.compile(p, re.IGNORECASE) for p in self.GARBAGE_PATTERNS
        ]
        self._running: Dict[int, str] = {}
        self._seen_images: Dict[str, int] = {}

    def filter_extracted_content(
        self,
        content_list: List[ExtractedContent],
        page_heights: Optional[Dict[int, float]] = None,
    ) -> Tuple[List[ExtractedContent], List[ExtractedContent]]:
        """
        Filter extracted content, separating valid from garbage.

        Args:
            content_list: List of ExtractedContent objects
            page_heights: Optional page height per physical page, for the running
                header band; estimated from the items' boxes when not given

        Returns:
            Tuple of (valid_content, filtered_content)
        """
        valid = []
        filtered = []

        items = self._merge_short_runs(content_list)
        for content in items:
            if content.content_type == "table_markdown" and content.content:
                content.content = collapse_table_padding(content.content)
        self._running = self._find_running_headers(items, page_heights)
        self._seen_images = {}

        for content in items:
            is_valid, reason = self._validate_content(content)

            if is_valid:
                valid.append(content)
            else:
                if content.content_type == "table_markdown":
                    logger.warning(
                        f"Garbage filter dropped a table on page {content.source_page_physical}: {reason}"
                    )
                filtered.append(content)

        return (valid, filtered)

    @staticmethod
    def _join_boxes(parts: List[ExtractedContent], text: str) -> ExtractedContent:
        """One item from several, with the union of their boxes."""
        if len(parts) == 1:
            return parts[0]
        boxes = [
            c.source_bbox for c in parts if c.source_bbox and len(c.source_bbox) == 4
        ]
        bbox = (
            [
                min(b[0] for b in boxes),
                min(b[1] for b in boxes),
                max(b[2] for b in boxes),
                max(b[3] for b in boxes),
            ]
            if boxes
            else parts[0].source_bbox
        )
        return parts[0].model_copy(update={"content": text, "source_bbox": bbox})

    def _join_line_fragments(
        self, content_list: List[ExtractedContent]
    ) -> List[ExtractedContent]:
        """
        Docling splits "(₹ in crore)" into "(", "₹" and "in crore)", in any order.
        Put the one- or two-character fragments on the same row back into their
        unit, source or caption line.
        """

        def is_fragment(c: ExtractedContent) -> bool:
            return (
                c.content_type == "paragraph"
                and 0 < len(c.content.strip()) <= 2
                and bool(c.source_bbox)
            )

        def same_row(a: List[float], b: List[float]) -> bool:
            overlap = min(a[3], b[3]) - max(a[1], b[1])
            gap = max(a[0], b[0]) - min(a[2], b[2])
            return overlap > 0.5 * min(a[3] - a[1], b[3] - b[1]) and gap < 15

        used = set()
        joined: Dict[int, ExtractedContent] = {}
        for i, line in enumerate(content_list):
            text = line.content.strip()
            if (
                line.content_type != "paragraph"
                or len(text) < 3
                or not line.source_bbox
                or not protected_kind(text)
            ):
                continue
            parts = [line]
            for j in range(max(0, i - 3), min(len(content_list), i + 4)):
                c = content_list[j]
                if (
                    j != i
                    and j not in used
                    and is_fragment(c)
                    and c.source_page_physical == line.source_page_physical
                    and any(same_row(c.source_bbox, p.source_bbox) for p in parts)
                ):
                    parts.append(c)
                    used.add(j)
            if len(parts) > 1:
                parts.sort(key=lambda c: c.source_bbox[0])
                text = " ".join(c.content.strip() for c in parts)
                text = re.sub(r"([(\[])\s+", r"\1", text)
                joined[i] = self._join_boxes(parts, text)
        return [joined.get(i, c) for i, c in enumerate(content_list) if i not in used]

    def _merge_short_runs(
        self, content_list: List[ExtractedContent]
    ) -> List[ExtractedContent]:
        """
        Join consecutive short paragraph blocks on the same page into one block.

        Label/value boxes (direct-tax case headers: "Case I CIT Charge:", "Pr. CIT-6,
        Mumbai", "Assessee Name:", "M/s G5 Ltd.", "Assessment Year:", "2017-18") come
        out of layout analysis as separate short blocks, each below the minimum length.
        Filtered one by one they were all dropped; joined they keep the case's identity.
        Unit, source and caption lines stay separate so they can bind to their table.
        """
        min_length = self.MIN_LENGTH["paragraph"]

        def is_short(c):
            text = c.content.strip()
            return (
                c.content_type == "paragraph"
                and len(text) < min_length
                and not protected_kind(text)
            )

        merged: List[ExtractedContent] = []
        run: List[ExtractedContent] = []

        def flush():
            if run:
                merged.append(
                    self._join_boxes(
                        list(run), " ".join(c.content.strip() for c in run)
                    )
                )
            run.clear()

        for content in self._join_line_fragments(content_list):
            if is_short(content) and (
                not run or run[-1].source_page_physical == content.source_page_physical
            ):
                run.append(content)
                continue
            flush()
            if is_short(content):
                run.append(content)
            else:
                merged.append(content)
        flush()
        return merged

    @staticmethod
    def _running_key(text: str) -> str:
        """Normalised text of a header/footer line, without a page number at either end."""
        text = " ".join(text.lower().split())
        return re.sub(
            r"^(?:page\s+)?\d{1,4}(?:\s*\|)?\s+|\s+(?:\|\s*)?(?:page\s+)?\d{1,4}$",
            "",
            text,
        )

    def _find_running_headers(
        self,
        items: List[ExtractedContent],
        page_heights: Optional[Dict[int, float]],
    ) -> Dict[int, str]:
        """
        Items that are running headers or footers: the same text on many pages at
        about the same y, inside the top or bottom band of the page. Returns
        {id(item): reason}.
        """
        boxes = [
            c.source_bbox for c in items if c.source_bbox and len(c.source_bbox) == 4
        ]
        if not boxes:
            return {}
        fallback_height = max(b[3] for b in boxes)

        def in_band(c: ExtractedContent) -> bool:
            height = (page_heights or {}).get(c.source_page_physical) or fallback_height
            return (
                c.source_bbox[1] < self.RUNNING_BAND * height
                or c.source_bbox[3] > (1 - self.RUNNING_BAND) * height
            )

        def body_follows(i: int) -> bool:
            c = items[i]
            if c.content_type != "header":
                return False
            for nxt in items[i + 1 :]:
                if nxt.source_page_physical != c.source_page_physical:
                    return False
                if nxt.content_type in _BODY_TYPES:
                    return True
                if nxt.content_type == "header":
                    return False
            return False

        groups: Dict[str, List[int]] = defaultdict(list)
        for i, c in enumerate(items):
            text = c.content.strip()
            if (
                c.content_type in _NEVER_RUNNING
                or not text
                or not c.source_bbox
                or len(c.source_bbox) != 4
                # sentences ("Reply of the Ministry is awaited.")
                or text.endswith((".", ";"))
                # year or number banners of year-wise tables ("2018-19")
                or not re.search(r"[A-Za-z]{2}", text)
                # a unit, source or caption line repeated at the top of each page
                # of a long table belongs to that page's table
                or protected_kind(text, c.content_type) in _PER_TABLE_KINDS
                or not in_band(c)
            ):
                continue
            groups[self._running_key(text)].append(i)

        running: Dict[int, str] = {}
        for key, idxs in groups.items():
            if not key:
                continue
            for i in idxs:
                y = items[i].source_bbox[1]
                pages = {
                    items[j].source_page_physical
                    for j in idxs
                    if abs(items[j].source_bbox[1] - y) <= self.RUNNING_Y_TOLERANCE
                }
                min_pages = (
                    self.RUNNING_MIN_PAGES_HEADING
                    if body_follows(i)
                    else self.RUNNING_MIN_PAGES
                )
                if len(pages) >= min_pages:
                    running[id(items[i])] = "running_header"
            # A repeated chapter or annexure banner keeps its first occurrence as the anchor
            marked = [i for i in idxs if id(items[i]) in running]
            if marked and protected_kind(
                items[marked[0]].content, items[marked[0]].content_type
            ):
                del running[id(items[marked[0]])]
        return running

    def _validate_content(self, content: ExtractedContent) -> Tuple[bool, str]:
        """
        Validate a single content item.

        Returns:
            Tuple of (is_valid, rejection_reason)
        """
        text = content.content.strip()
        content_type = content.content_type

        if content_type in _IMAGE_TYPES:
            return self._validate_image(content)

        # Check 1: Empty content
        if not text:
            return (False, "empty_content")

        # Check 2: Running headers and footers (page furniture, not content)
        if id(content) in self._running:
            return (False, self._running[id(content)])

        # Units, sources, captions and titles are kept however short
        if protected_kind(text, content_type):
            return (True, "")

        # Check 3: Minimum length by type
        min_length = self.MIN_LENGTH.get(content_type, 20)
        if len(text) < min_length:
            return (False, f"too_short_{len(text)}_chars")

        # Check 4: Pattern-based rejection (for paragraph/text types)
        if content_type in ("paragraph", "header", "list"):
            for pattern in self._garbage_patterns:
                if pattern.match(text):
                    return (False, "matches_garbage_pattern")

        # Check 5: Whitespace ratio (mostly whitespace = garbage). Tables are exempt:
        # Docling pads every cell to its column's widest cell.
        if content_type != "table_markdown" and len(text) > 10:
            non_whitespace = len(text.replace(" ", "").replace("\n", ""))
            whitespace_ratio = 1 - (non_whitespace / len(text))
            if whitespace_ratio > 0.7:
                return (False, "excessive_whitespace")

        return (True, "")

    def _validate_image(self, content: ExtractedContent) -> Tuple[bool, str]:
        """
        Images are kept on their file, not their text: content is the caption (often
        empty) and the file path is in structured_data["image_path"]. Older items have
        the path as content. No whitespace or garbage-pattern rules apply.
        """
        data = (
            content.structured_data if isinstance(content.structured_data, dict) else {}
        )
        text = content.content.strip()
        image_path = data.get("image_path")

        # The same file twice is one image; two charts may share a caption
        key = f"{content.content_type}:{(image_path or text).strip().lower()}"
        seen = self._seen_images.get(key, 0)
        self._seen_images[key] = seen + 1
        if seen >= 2:
            return (False, "duplicate_content")

        if image_path:
            if text or data.get("visual_subtype") in _DATA_VISUALS:
                return (True, "")
            return (False, "empty_image")

        # Older shape: the path is the content
        if not text:
            return (False, "empty_content")
        min_length = self.MIN_LENGTH.get(content.content_type, 20)
        if len(text) < min_length and data.get("visual_subtype") not in _DATA_VISUALS:
            return (False, f"too_short_{len(text)}_chars")
        return (True, "")
