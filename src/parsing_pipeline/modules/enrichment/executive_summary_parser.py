"""
Executive Summary Parser: Extracts the structured finding/recommendation index
from executive summary sections and resolves paragraph citations to chunk IDs.

P4-4: Handles variants:
- "Executive Summary" (most common)
- "Highlights" (Direct Taxes reports)
- "Summary" / "Overview" / "Key Findings"
- Full-page boxed summaries (content extracted as text)
- 1-page to 4-page summaries

Output: A list of summary items, each with text + resolved paragraph links.
"""

import re
from typing import List, Dict, Optional, Tuple, Any


class ExecutiveSummaryParser:
    """Parser for executive summary sections with paragraph citation resolution."""

    # Section title patterns that indicate an executive summary
    EXEC_SUMMARY_SECTION_PATTERNS = [
        r"^executive\s+summary",
        r"^highlights?$",
        r"^summary$",
        r"^overview$",
        r"^key\s+findings",
        r"^summary\s+of\s+(?:audit\s+)?findings",
        r"^what\s+(?:the|this)\s+(?:performance\s+)?audit\s+(?:report\s+)?says",
    ]

    # Citation patterns in exec summary
    CITATION_PATTERNS = [
        # (Paragraph 3.2, Page no. 11) or (Paragraph 3.2)
        re.compile(
            r"\(Para(?:graph)?s?\.?\s*([\d.]+(?:\s*(?:,|and)\s*[\d.]+)*)"
            r"(?:\s*,\s*Page\s+(?:no\.?\s*)?\d+)?\)",
            re.IGNORECASE,
        ),
        # (Para 3.1.1) — abbreviated
        re.compile(
            r"\(Para\.?\s*([\d.]+(?:\s*(?:,|and)\s*[\d.]+)*)\)",
            re.IGNORECASE,
        ),
        # (Paras 3.4.1, 3.4.2 and 3.4.3) — plural with "and"
        re.compile(
            r"\(Paras?\.?\s*([\d.]+(?:\s*,\s*[\d.]+)*(?:\s+and\s+[\d.]+)?)\)",
            re.IGNORECASE,
        ),
    ]

    # Sub-heading patterns within exec summary (chapter-level groupings)
    SUBHEADING_PATTERN = re.compile(
        r"^(?:Chapter[-\s]*[IVXivx\d]+\s*[:\-–]\s*)?(.+?)$", re.IGNORECASE
    )

    def __init__(self):
        """Initialize compiled patterns."""
        self._section_patterns = [
            re.compile(p, re.IGNORECASE) for p in self.EXEC_SUMMARY_SECTION_PATTERNS
        ]

    def find_exec_summary_chunks(
        self,
        parent_chunks: List[Dict],
        child_chunks: List[Dict],
        section_classifications: List[Dict],
    ) -> List[Dict]:
        """Find all child chunks belonging to the executive summary section."""

        # Method 1: Use section classifications
        exec_parent_ids = {
            sc.get("chunk_id") for sc in section_classifications
            if sc.get("section_type") == "executive_summary"
        }

        # Method 2: Direct TOC title matching (fallback)
        if not exec_parent_ids:
            for parent in parent_chunks:
                toc = parent.get("toc_entry", "")
                for pattern in self._section_patterns:
                    if pattern.search(toc):
                        exec_parent_ids.add(parent.get("chunk_id"))
                        break

        if not exec_parent_ids:
            return []

        return [
            c for c in child_chunks
            if c.get("parent_chunk_id") in exec_parent_ids
        ]

    def parse_executive_summary(
        self,
        parent_chunks: List[Dict],
        child_chunks: List[Dict],
        section_classifications: List[Dict],
    ) -> Optional[Dict[str, Any]]:
        """
        Parse the executive summary into a structured index.

        Returns:
        {
            "section_title": "Executive Summary",
            "page_range": [3, 6],
            "items": [
                {
                    "text": "Audit noticed that...",
                    "paragraph_citations": ["3.2", "3.3"],
                    "resolved_chunk_ids": ["..._parent_p012_...", ...],
                    "current_subheading": "Beneficiary Identification",
                    "item_type": "finding" | "recommendation" | "general",
                    "source_chunk_id": "...",
                }
            ],
            "total_items": 15,
            "resolved_count": 12,
            "resolution_rate": 0.8,
        }
        """
        exec_chunks = self.find_exec_summary_chunks(
            parent_chunks, child_chunks, section_classifications
        )
        if not exec_chunks:
            return None

        # Build section number → parent chunk ID index for resolution
        section_index = self._build_section_index(parent_chunks)

        items = []
        current_subheading = None

        for chunk in exec_chunks:
            content = chunk.get("content", "").strip()
            content_type = chunk.get("content_type", "")

            if not content or len(content) < 10:
                continue

            # Detect sub-headings (bold chapter titles within exec summary)
            if content_type == "header" or (len(content) < 80 and not content.endswith(".")):
                current_subheading = content
                continue

            # Extract paragraph citations
            citations = self._extract_citations(content)

            # Resolve citations to chunk IDs
            resolved = []
            for cite in citations:
                chunk_id = section_index.get(cite)
                if chunk_id:
                    resolved.append(chunk_id)

            # Classify item type
            item_type = "general"
            if re.search(r'\b(?:recommend|should|may\s+consider|ensure)\b', content, re.I):
                item_type = "recommendation"
            elif re.search(r'\b(?:audit\s+(?:noticed|observed|found)|loss|shortfall|'
                          r'non-compliance|irregular|excess|avoidable)\b', content, re.I):
                item_type = "finding"

            items.append({
                "text": content[:500],  # Limit to 500 chars
                "paragraph_citations": citations,
                "resolved_chunk_ids": resolved,
                "current_subheading": current_subheading,
                "item_type": item_type,
                "source_chunk_id": chunk.get("chunk_id"),
                "page": chunk.get("source_page_physical"),
            })

        if not items:
            return None

        pages = [i["page"] for i in items if i.get("page") is not None]
        total_citations = sum(len(i["paragraph_citations"]) for i in items)
        total_resolved = sum(len(i["resolved_chunk_ids"]) for i in items)

        return {
            "section_title": "Executive Summary",
            "page_range": [min(pages), max(pages)] if pages else None,
            "items": items,
            "total_items": len(items),
            "total_citations": total_citations,
            "resolved_count": total_resolved,
            "resolution_rate": round(total_resolved / max(total_citations, 1), 2),
        }

    def _extract_citations(self, text: str) -> List[str]:
        """Extract paragraph numbers from citation patterns."""
        all_citations = []
        for pattern in self.CITATION_PATTERNS:
            for match in pattern.finditer(text):
                raw = match.group(1)
                parts = re.split(r'\s*(?:,|and)\s*', raw)
                for part in parts:
                    part = part.strip()
                    if re.match(r'^\d+(?:\.\d+)*$', part):
                        all_citations.append(part)
        return list(dict.fromkeys(all_citations))  # Deduplicate, preserve order

    def _build_section_index(self, parent_chunks: List[Dict]) -> Dict[str, str]:
        """Build mapping: section number → parent chunk_id."""
        index = {}
        for parent in parent_chunks:
            toc = parent.get("toc_entry", "")
            # "3.2.1 Implementation Status" → key "3.2.1"
            num_match = re.match(r'^([\d]+(?:\.[\d]+)*)', toc)
            if num_match:
                index[num_match.group(1)] = parent.get("chunk_id")
        return index
