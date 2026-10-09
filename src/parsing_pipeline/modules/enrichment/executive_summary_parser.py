"""
Executive Summary Parser: Extracts the structured finding/recommendation index
from executive summary sections and resolves paragraph citations to chunk IDs.

P4-4: Handles variants:
- "Executive Summary" (most common)
- "Highlights" (Direct Taxes reports)
- "Summary" / "Overview" / "Key Findings"
- Full-page boxed summaries (content extracted as text, or rows of a table)
- 1-page to 4-page summaries

The executive summary is the whole subtree under its heading, not only the
children directly under it. A chunk that is only a citation ("(Paras 2.1.1,
2.1.2, 2.2 and 2.3)", often its own line) belongs to the item before it.

Output: A list of summary items, each with text + resolved paragraph links.
"""

import re
from typing import Any, Dict, List, Optional

from src.parsing_pipeline.modules.enrichment.cross_reference_resolver import (
    ReferenceIndex,
    expand_number_list,
)


class ExecutiveSummaryParser:
    """Parser for executive summary sections with paragraph citation resolution."""

    # Section title patterns that indicate an executive summary ("5.Executive Summary" too)
    EXEC_SUMMARY_SECTION_PATTERNS = [
        r"^\W*\d*\W*executive\s+summary",
        r"^\W*\d*\W*highlights?\W*$",
        r"^\W*summary\W*$",
        r"^\W*\d*\W*overview\W*$",
        r"^\W*key\s+findings",
        r"^\W*summary\s+of\s+(?:audit\s+)?findings",
        r"^\W*what\s+(?:the|this)\s+(?:performance\s+)?audit\s+(?:report\s+)?says",
    ]

    _NUM_LIST = r"\d+(?:\.\d+)*\.?(?:\s*(?:,|&|\band\b|\bto\b)\s*\d+(?:\.\d+)*\.?)*"

    # Citation patterns in exec summary
    CITATION_PATTERNS = [
        # (Paragraph 3.2, Page no. 11), (Paras 3.4.1, 3.4.2 and 3.4.3), (Paragraphs 3.5.3 & 3.5.4.2),
        # (Para 3.1 to 3.7), (Paragraph No. 2.1)
        re.compile(
            r"\(\s*Para(?:graph)?s?\.?\s*(?:No\.?\s*)?(" + _NUM_LIST + r")"
            r"(?:\s*[,;]?\s*(?:of\s+)?(?:Chapter\s+[\dIVX]+)?)?"
            r"(?:\s*[,;]\s*Page\s*(?:no\.?\s*)?[\d\-–\s&,]+)?\s*\)",
            re.IGNORECASE,
        ),
        # "Refer Para 3.1.1", "Paragraph 3.1" closing a line without brackets
        re.compile(
            r"(?:\brefer\s+|^\s*)Para(?:graph)?s?\.?\s*(?:No\.?\s*)?("
            + _NUM_LIST
            + r")\s*\.?\s*$",
            re.IGNORECASE | re.MULTILINE,
        ),
    ]

    # A chunk that holds nothing but a citation
    _CITATION_ONLY = re.compile(
        r"^\W*(?:refer\s+)?para(?:graph)?s?\.?\s*(?:no\.?\s*)?[\d.\s,&]+(?:(?:and|to)\s*[\d.]+\s*)*"
        r"(?:[,;]?\s*(?:of\s+)?chapter\s+[\dIVX]+)?(?:[,;]\s*page\s*(?:no\.?\s*)?[\d\-–\s&,]+)?\W*$",
        re.IGNORECASE,
    )

    _FINDING_CUES = re.compile(
        r"\b(?:audit\s+(?:noticed|observed|found|revealed)|was\s+noticed|were\s+noticed|loss|shortfall|"
        r"short\s*fall|non-compliance|irregular(?:ly|ities)?|excess|avoidable|unfruitful|idle|"
        r"not\s+(?:been\s+)?(?:utilised|utilized|realised|realized|recovered|achieved|completed)|"
        r"failed|deprived|delay(?:s|ed)?|remained\s+(?:unutilised|unutilized|unspent|unrealised)|"
        r"diversion|lapse[ds]?|unspent|blocked|blocking)\b",
        re.IGNORECASE,
    )
    _RECOMMENDATION_CUES = re.compile(
        r"\b(?:recommend(?:s|ed|ation)?|may\s+consider|should\s+(?:ensure|consider|take|strengthen))\b",
        re.IGNORECASE,
    )
    _RECOMMENDATION_HEADING = re.compile(r"recommend", re.IGNORECASE)

    def __init__(self):
        """Initialize compiled patterns."""
        self._section_patterns = [
            re.compile(p, re.IGNORECASE) for p in self.EXEC_SUMMARY_SECTION_PATTERNS
        ]

    def _exec_parent_ids(
        self, parent_chunks: List[Dict], section_classifications: List[Dict]
    ) -> set:
        # Method 1: Use section classifications
        exec_ids = {
            sc.get("chunk_id")
            for sc in section_classifications
            if sc.get("section_type") == "executive_summary"
        }

        # Method 2: Direct TOC title matching (fallback), top-level headings only
        if not exec_ids:
            exec_ids = {
                p.get("chunk_id")
                for p in parent_chunks
                if (p.get("toc_level") or 1) <= 1
                and any(
                    pat.search(p.get("toc_entry", "")) for pat in self._section_patterns
                )
            }

        # The whole subtree: sub-headings promoted to parents sit under the same level_1
        roots = {
            (p.get("hierarchy") or {}).get("level_1") or p.get("toc_entry")
            for p in parent_chunks
            if p.get("chunk_id") in exec_ids and (p.get("toc_level") or 1) <= 1
        }
        for parent in parent_chunks:
            if ((parent.get("hierarchy") or {}).get("level_1") or "") in roots:
                exec_ids.add(parent.get("chunk_id"))
        return exec_ids

    def find_exec_summary_chunks(
        self,
        parent_chunks: List[Dict],
        child_chunks: List[Dict],
        section_classifications: List[Dict],
    ) -> List[Dict]:
        """Find all child chunks belonging to the executive summary section."""
        exec_parent_ids = self._exec_parent_ids(parent_chunks, section_classifications)
        if not exec_parent_ids:
            return []

        return [c for c in child_chunks if c.get("parent_chunk_id") in exec_parent_ids]

    def parse_executive_summary(
        self,
        parent_chunks: List[Dict],
        child_chunks: List[Dict],
        section_classifications: List[Dict],
        index: Optional[ReferenceIndex] = None,
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

        index = index or ReferenceIndex(parent_chunks, child_chunks)

        items: List[Dict[str, Any]] = []
        current_subheading = None

        for chunk in exec_chunks:
            content = chunk.get("content", "").strip()
            content_type = chunk.get("content_type", "")

            if not content:
                continue

            # A citation on its own line closes the item before it
            if self._CITATION_ONLY.match(content):
                citations = self._extract_citations(content)
                if items and citations:
                    self._add_citations(items[-1], citations, index)
                continue

            if len(content) < 10:
                continue

            # Detect sub-headings (bold chapter titles within exec summary)
            if content_type == "header" or (
                len(content) < 80
                and not content.endswith(".")
                and content_type != "list"
            ):
                current_subheading = content
                continue

            texts = (
                self._table_rows(content)
                if content_type == "table_markdown"
                else [content]
            )
            for text in texts:
                item = {
                    "text": text[:500],  # Limit to 500 chars
                    "paragraph_citations": [],
                    "resolved_chunk_ids": [],
                    "current_subheading": current_subheading,
                    "item_type": self._item_type(text, current_subheading),
                    "source_chunk_id": chunk.get("chunk_id"),
                    "page": chunk.get("source_page_physical"),
                }
                self._add_citations(item, self._extract_citations(text), index)
                items.append(item)

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

    def _item_type(self, text: str, subheading: Optional[str]) -> str:
        """Finding cues first: a finding that says 'ensure' is still a finding."""
        if self._FINDING_CUES.search(text) and not re.match(
            r"\W*(?:the\s+)?(?:\w+\s+){0,3}(?:may|should)\b", text, re.I
        ):
            return "finding"
        if self._RECOMMENDATION_CUES.search(text) or (
            subheading and self._RECOMMENDATION_HEADING.search(subheading)
        ):
            return "recommendation"
        return "general"

    @staticmethod
    def _table_rows(content: str) -> List[str]:
        """Rows of a boxed summary table, as text, without bullets and empty cells."""
        rows = []
        for line in content.splitlines():
            if not line.strip().startswith("|") or re.match(
                r"^\|[\s\-:|]+\|?$", line.strip()
            ):
                continue
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            text = " ".join(
                c for c in cells if c and not re.fullmatch(r"GLYPH<\d+>|[•\-–*]", c)
            )
            if len(text) >= 40:
                rows.append(text)
        return rows or [content]

    @staticmethod
    def _add_citations(
        item: Dict[str, Any], citations: List[str], index: ReferenceIndex
    ) -> None:
        for cite in citations:
            if cite in item["paragraph_citations"]:
                continue
            item["paragraph_citations"].append(cite)
            target, _ = index.resolve_section(cite)
            if target and target["chunk_id"] not in item["resolved_chunk_ids"]:
                item["resolved_chunk_ids"].append(target["chunk_id"])

    def _extract_citations(self, text: str) -> List[str]:
        """Extract paragraph numbers from citation patterns."""
        all_citations = []
        for pattern in self.CITATION_PATTERNS:
            for match in pattern.finditer(text):
                for part in expand_number_list(match.group(1)):
                    if "." in part:
                        all_citations.append(part)
        return list(dict.fromkeys(all_citations))  # Deduplicate, preserve order

    def _build_section_index(self, parent_chunks: List[Dict]) -> Dict[str, str]:
        """Build mapping: section number → parent chunk_id."""
        index = ReferenceIndex(parent_chunks, [])
        return {key: target["chunk_id"] for key, target in index.sections.items()}
