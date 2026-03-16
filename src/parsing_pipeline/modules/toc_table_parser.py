"""
TOC Table Parser: Extract Table of Contents from printed TOC pages.

This is Layer 2 of the Intelligent TOC Service. It parses the actual
printed Table of Contents (usually on pages 3-10) rather than relying
on PDF bookmarks which are often low-quality or missing.

CAG reports typically have TOC formats like:
- "Chapter I Introduction.......1"
- "1.1 Background 5"
- "Annexure I (Refer Para 2.1) 45"
"""

import re
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field
import logging

logger = logging.getLogger(__name__)


@dataclass
class TOCEntry:
    """Represents a parsed TOC entry."""

    level: int
    title: str
    page_num: int
    prefix: str = ""  # "Chapter I", "1.1", "Annexure I"
    raw_text: str = ""
    confidence: float = 1.0


class TOCTableParser:
    """
    Parses printed Table of Contents from document content.

    Handles CAG-specific TOC formats:
    - Chapters with Roman numerals: "Chapter I Introduction 1"
    - Numbered sections: "1.1 Background 5"
    - Dot leaders: "Executive Summary.......iii"
    - Mixed numbering: "Annexure I (Refer Para 2.1) 45"
    - Multi-column TOCs
    """

    # TOC page indicators
    TOC_HEADER_PATTERNS = [
        r"^contents$",
        r"^table\s+of\s+contents$",
        r"^index$",
        r"^list\s+of\s+contents$",
    ]

    # Patterns for TOC entry detection (order matters - more specific first)
    TOC_ENTRY_PATTERNS = [
        # Chapter with Roman numeral: "Chapter I Introduction 1" or "CHAPTER-I Introduction 1"
        (r"^(Chapter[\s\-]+[IVX]+)[:\s\-]+(.+?)\s+(\d+)$", 1),
        # Chapter with Arabic numeral: "Chapter 1: Introduction 1"
        (r"^(Chapter[\s\-]+\d+)[:\s\-]+(.+?)\s+(\d+)$", 1),
        # Numbered section 3 levels: "1.2.3 Detail 15"
        (r"^(\d+\.\d+\.\d+)\s+(.+?)\s+(\d+)$", 3),
        # Numbered section 2 levels: "1.1 Background 5"
        (r"^(\d+\.\d+)\s+(.+?)\s+(\d+)$", 2),
        # Single number section: "1 Introduction 1"
        (r"^(\d+)\s+([A-Z][a-z].+?)\s+(\d+)$", 1),
        # Annexure: "Annexure I 45" or "Annexure-I (Refer Para 2.1) 45"
        (r"^(Annexure[\s\-]+[IVX\d\-A-Z]+)\s*(\([^)]+\))?\s*(.*)?\s+(\d+)$", 1),
        # Appendix: "Appendix A 50"
        (r"^(Appendix[\s\-]+[A-Z\d]+)\s*(.*)?\s+(\d+)$", 1),
        # Lettered sections: "A. Karnataka 25"
        (r"^([A-Z])\.\s+(.+?)\s+(\d+)$", 2),
        # Standard sections: "Executive Summary iii" or "Preface i"
        (
            r"^(Executive\s+Summary|Preface|Foreword|Acknowledgements?|Glossary|Abbreviations?)\s+([ivx]+|\d+)$",
            1,
        ),
        # Entry with dot leader: "Introduction.......1"
        (r"^(.+?)\.{3,}\s*(\d+|[ivx]+)$", 1),
        # Simple entry with page: "Introduction 1"
        (r"^([A-Z][a-z][^0-9]{5,}?)\s+(\d+|[ivx]+)$", 1),
    ]

    # Patterns to REJECT (not TOC entries)
    REJECT_PATTERNS = [
        r"^Table\s+\d+",  # Table captions
        r"^Figure\s+\d+",  # Figure captions
        r"^Chart\s+\d+",  # Chart captions
        r"^\(₹",  # Currency
        r"^Report\s+No\.",  # Page headers
        r"^Page\s+\d+",  # Page numbers
        r"^\d+\s+\d+\s+\d+\s+\d+",  # Data rows
        r"^Source:",  # Source attributions
        r"^Note:",  # Notes
        r"^\d{4}-\d{2}",  # Year ranges
    ]

    def __init__(
        self,
        toc_page_range: Tuple[int, int] = (0, 15),
        min_entries: int = 3,
        confidence_threshold: float = 0.5,
    ):
        """
        Initialize TOC Table Parser.

        Args:
            toc_page_range: Pages to search for TOC (0-indexed)
            min_entries: Minimum entries to consider TOC valid
            confidence_threshold: Minimum confidence to accept parsed TOC
        """
        self.toc_page_range = toc_page_range
        self.min_entries = min_entries
        self.confidence_threshold = confidence_threshold

        # Compile patterns
        self._toc_header_patterns = [
            re.compile(p, re.IGNORECASE) for p in self.TOC_HEADER_PATTERNS
        ]
        self._entry_patterns = [
            (re.compile(p, re.IGNORECASE), level)
            for p, level in self.TOC_ENTRY_PATTERNS
        ]
        self._reject_patterns = [
            re.compile(p, re.IGNORECASE) for p in self.REJECT_PATTERNS
        ]

    def parse_from_chunks(
        self,
        child_chunks: List[Dict],
        report_id: str = "unknown",
    ) -> Tuple[List[TOCEntry], float]:
        """
        Extract TOC entries from document content chunks.

        Args:
            child_chunks: Extracted content chunks from content extraction phase
            report_id: Report identifier for logging

        Returns:
            Tuple of (list of TOCEntry, confidence score 0-1)
        """
        # Filter chunks from likely TOC pages
        toc_chunks = self._get_toc_page_chunks(child_chunks)

        if not toc_chunks:
            logger.debug(f"[{report_id}] No chunks found in TOC page range")
            return [], 0.0

        # Find TOC header
        toc_start_idx = self._find_toc_header(toc_chunks)

        if toc_start_idx is None:
            logger.debug(f"[{report_id}] No TOC header found")
            # Try parsing anyway - some reports don't have explicit header
            toc_start_idx = 0

        # Parse entries
        entries = []
        chunks_to_parse = toc_chunks[toc_start_idx:]

        for chunk in chunks_to_parse:
            content = chunk.get("content", "").strip()

            # Skip empty or very short
            if len(content) < 3:
                continue

            # Check for end of TOC (next major section)
            if self._is_toc_end(content):
                break

            # Try to parse as TOC entry
            entry = self._parse_toc_line(content)
            if entry:
                entries.append(entry)

        # Calculate confidence
        confidence = self._calculate_confidence(entries, toc_chunks)

        logger.info(
            f"[{report_id}] TOC Table Parser: Found {len(entries)} entries "
            f"with {confidence:.2f} confidence"
        )

        return entries, confidence

    def parse_from_table(
        self,
        table_content: str,
        report_id: str = "unknown",
    ) -> Tuple[List[TOCEntry], float]:
        """
        Parse TOC from a markdown table (already extracted).

        Args:
            table_content: Markdown table string
            report_id: Report identifier

        Returns:
            Tuple of (list of TOCEntry, confidence score)
        """
        entries = []

        # Split by rows
        lines = table_content.strip().split("\n")

        for line in lines:
            # Skip header separators
            if re.match(r"^\|?\s*[-:]+", line):
                continue

            # Extract cells
            cells = [c.strip() for c in line.split("|") if c.strip()]

            if len(cells) >= 2:
                # Try title | page format
                title = cells[0]
                page_str = cells[-1]

                # Clean and parse
                title = re.sub(r"\.{2,}", "", title).strip()
                page_num = self._parse_page_number(page_str)

                if title and page_num > 0:
                    level = self._infer_level_from_title(title)
                    entries.append(
                        TOCEntry(
                            level=level,
                            title=title,
                            page_num=page_num,
                            raw_text=line,
                        )
                    )

        confidence = self._calculate_confidence(entries, [])

        return entries, confidence

    def _get_toc_page_chunks(self, chunks: List[Dict]) -> List[Dict]:
        """Filter chunks from TOC page range."""
        toc_chunks = []

        for chunk in chunks:
            # Get page number from various locations
            page = None

            # Try metadata.location.page_physical
            meta = chunk.get("metadata", {})
            loc = meta.get("location", {})
            page = loc.get("page_physical")

            # Try direct page field
            if page is None:
                page = chunk.get("page_physical") or chunk.get("page_start")

            # Try extracting from chunk_id (e.g., "..._p005_...")
            if page is None:
                chunk_id = chunk.get("chunk_id", "")
                match = re.search(r"_p(\d{3})_", chunk_id)
                if match:
                    page = int(match.group(1))

            if (
                page is not None
                and self.toc_page_range[0] <= page <= self.toc_page_range[1]
            ):
                toc_chunks.append(chunk)

        # Sort by page and position
        toc_chunks.sort(
            key=lambda c: (
                c.get("metadata", {}).get("location", {}).get("page_physical", 0),
                c.get("metadata", {}).get("location", {}).get("bbox", [0])[1]
                if c.get("metadata", {}).get("location", {}).get("bbox")
                else 0,
            )
        )

        return toc_chunks

    def _find_toc_header(self, chunks: List[Dict]) -> Optional[int]:
        """Find index of TOC header in chunks."""
        for i, chunk in enumerate(chunks):
            content = chunk.get("content", "").strip()

            for pattern in self._toc_header_patterns:
                if pattern.match(content):
                    return i + 1  # Return index after header

        return None

    def _is_toc_end(self, content: str) -> bool:
        """Check if content indicates end of TOC."""
        end_patterns = [
            r"^(Preface|Introduction|Chapter\s+[IVX1]|CHAPTER)",
            r"^Report\s+of\s+the",
            r"^The\s+Comptroller",
        ]

        content_lower = content.lower().strip()

        # Don't end on these if they look like TOC entries (have page numbers)
        if re.search(r"\d+\s*$", content):
            return False

        for pattern in end_patterns:
            if re.match(pattern, content, re.IGNORECASE):
                return True

        return False

    def _parse_toc_line(self, line: str) -> Optional[TOCEntry]:
        """Parse a single line as TOC entry."""
        # Clean the line
        line = line.strip()

        # Skip if matches reject pattern
        for pattern in self._reject_patterns:
            if pattern.match(line):
                return None

        # Clean dot leaders
        cleaned = re.sub(r"\.{3,}", "  ", line).strip()
        cleaned = re.sub(r"\s{2,}", " ", cleaned)

        # Try each pattern
        for pattern, default_level in self._entry_patterns:
            match = pattern.match(cleaned)
            if match:
                groups = match.groups()

                # Handle different group configurations
                if len(groups) >= 3:
                    prefix = groups[0].strip()
                    title = groups[1].strip() if groups[1] else ""
                    page_str = groups[-1]
                elif len(groups) == 2:
                    prefix = ""
                    title = groups[0].strip()
                    page_str = groups[1]
                else:
                    continue

                page_num = self._parse_page_number(page_str)

                if page_num > 0:
                    # Determine level
                    level = self._infer_level_from_prefix(prefix) or default_level

                    # Build full title
                    full_title = f"{prefix} {title}".strip() if prefix else title

                    return TOCEntry(
                        level=level,
                        title=full_title,
                        page_num=page_num,
                        prefix=prefix,
                        raw_text=line,
                    )

        return None

    def _infer_level_from_prefix(self, prefix: str) -> Optional[int]:
        """Infer hierarchy level from prefix."""
        if not prefix:
            return None

        prefix_lower = prefix.lower().strip()

        # Chapter = Level 1
        if prefix_lower.startswith("chapter"):
            return 1

        # Annexure/Appendix = Level 1
        if prefix_lower.startswith(("annexure", "appendix")):
            return 1

        # Count dots for numbered sections
        if re.match(r"^\d+\.\d+\.\d+", prefix):
            return 3
        if re.match(r"^\d+\.\d+", prefix):
            return 2
        if re.match(r"^\d+$", prefix):
            return 1

        # Single letter = Level 2
        if re.match(r"^[A-Z]$", prefix):
            return 2

        return None

    def _infer_level_from_title(self, title: str) -> int:
        """Infer level from title content."""
        title_lower = title.lower().strip()

        # Level 1 indicators
        if any(
            ind in title_lower
            for ind in ["chapter", "annexure", "appendix", "executive summary"]
        ):
            return 1

        # Check for numbered prefix in title
        if re.match(r"^\d+\.\d+\.\d+", title):
            return 3
        if re.match(r"^\d+\.\d+", title):
            return 2

        return 1

    def _parse_page_number(self, page_str: str) -> int:
        """Convert page string (may be Roman numeral) to integer."""
        if not page_str:
            return 0

        page_str = page_str.strip().lower()

        # Roman numeral conversion
        roman_values = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100}

        if all(c in roman_values for c in page_str):
            result = 0
            prev = 0
            for c in reversed(page_str):
                val = roman_values[c]
                if val < prev:
                    result -= val
                else:
                    result += val
                prev = val
            return result

        # Arabic numeral
        try:
            return int(page_str)
        except ValueError:
            return 0

    def _calculate_confidence(
        self, entries: List[TOCEntry], chunks: List[Dict]
    ) -> float:
        """Calculate confidence score for parsed TOC."""
        if len(entries) < self.min_entries:
            return 0.0

        score = 0.5  # Base score for having entries

        # Bonus for having multiple levels
        levels = set(e.level for e in entries)
        if len(levels) > 1:
            score += 0.2

        # Bonus for sequential page numbers
        pages = [e.page_num for e in entries if e.page_num > 0]
        if len(pages) >= 2:
            sequential = sum(
                1 for i in range(len(pages) - 1) if pages[i] <= pages[i + 1]
            )
            score += (sequential / (len(pages) - 1)) * 0.2

        # Bonus for having Chapter entries
        has_chapters = any("chapter" in e.title.lower() for e in entries)
        if has_chapters:
            score += 0.1

        return min(1.0, score)

    def convert_to_toc_format(self, entries: List[TOCEntry]) -> List[List]:
        """
        Convert TOCEntry list to standard TOC format.

        Returns:
            List of [level, title, page_num] entries
        """
        return [[entry.level, entry.title, entry.page_num] for entry in entries]


# Convenience function for pipeline integration
def parse_toc_from_content(
    child_chunks: List[Dict],
    report_id: str = "unknown",
) -> Tuple[List[List], float]:
    """
    Parse TOC from document content chunks.

    Args:
        child_chunks: Content chunks from extraction phase
        report_id: Report identifier

    Returns:
        Tuple of (TOC list in [level, title, page] format, confidence)
    """
    parser = TOCTableParser()
    entries, confidence = parser.parse_from_chunks(child_chunks, report_id)
    toc = parser.convert_to_toc_format(entries)
    return toc, confidence
