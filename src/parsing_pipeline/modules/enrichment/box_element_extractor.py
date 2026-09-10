"""
BoxElementExtractor: Detects "Box X.X" illustrative elements in CAG audit reports.

P4-2: Only matches explicit "Box X.X: Title" captions, NOT chunks that happen
to be on colored backgrounds.
"""

import re
from typing import List, Dict, Any


class BoxElementExtractor:
    """
    Detects Box X.X illustrative elements across child chunks.

    Strategy:
    1. Scan for "Box X.X: Title" pattern in chunk content
    2. The chunk containing the caption represents the box
    3. Do NOT tag chunks just because they're on a colored background

    Only boxes with explicit "Box X.X" captions are detected.
    """

    # Only match explicit "Box X.X" labels
    BOX_CAPTION_PATTERNS = [
        # "Box 3.1: Illustration of excess expenditure"
        r"(Box\s+\d+(?:\.\d+)?)\s*[:\-–]\s*(.+?)(?:\.|$)",
        # "Box 3.1 Illustration of ..." (no colon)
        r"(Box\s+\d+(?:\.\d+)?)\s+([A-Z].+?)(?:\.|$)",
        # "Box-1: ..." (some reports use hyphen)
        r"(Box[-\s]+\d+(?:\.\d+)?)\s*[:\-–]\s*(.+?)(?:\.|$)",
    ]

    # Subtype classification for box content
    BOX_SUBTYPE_KEYWORDS = {
        "illustration": ["illustration", "illustrat", "example", "case study", "instance"],
        "calculation": ["calculation", "computation", "working", "formula"],
        "case_study": ["case study", "case of", "specific case"],
        "summary": ["summary", "gist", "brief", "snapshot"],
        "comparison": ["comparison", "comparative", "vis-a-vis", "versus"],
    }

    def __init__(self):
        """Initialize with compiled regex patterns."""
        self._patterns = [
            re.compile(p, re.IGNORECASE) for p in self.BOX_CAPTION_PATTERNS
        ]

    def detect_box_elements(self, child_chunks: List[Dict]) -> List[Dict[str, Any]]:
        """
        P4-2: Detect "Box X.X" illustrative elements across child chunks.

        Args:
            child_chunks: List of child chunk dictionaries

        Returns:
            List of box descriptors with metadata
        """
        boxes = []

        for chunk in child_chunks:
            content = chunk.get("content", "")

            for pattern in self._patterns:
                # Only check start of chunk (first 200 chars)
                match = pattern.search(content[:200])
                if match:
                    box_id = match.group(1).strip()
                    box_title = match.group(2).strip() if match.lastindex >= 2 else ""

                    # Classify box subtype
                    box_subtype = self._classify_box_subtype(box_title, content)

                    boxes.append({
                        "box_id": re.sub(r'\s+', '_', box_id.lower()),
                        "box_number": box_id,
                        "box_title": box_title,
                        "box_subtype": box_subtype,
                        "caption_chunk_id": chunk.get("chunk_id"),
                        "page_physical": chunk.get("source_page_physical"),
                        "parent_section": chunk.get("hierarchy", {}),
                    })
                    break  # One box per chunk

        return boxes

    def _classify_box_subtype(self, box_title: str, content: str) -> str:
        """
        Classify box subtype based on title and content keywords.

        Args:
            box_title: The box title text
            content: Full chunk content

        Returns:
            Subtype string (e.g., "illustration", "calculation", "general")
        """
        content_lower = (box_title + " " + content).lower()

        for subtype, keywords in self.BOX_SUBTYPE_KEYWORDS.items():
            if any(kw in content_lower for kw in keywords):
                return subtype

        return "general"
