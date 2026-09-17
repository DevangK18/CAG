"""
Evidence Cross-Reference Linking for CAG Audit Reports.

This module links audit findings to their supporting evidence (tables, paragraphs,
annexures, pages) by extracting and resolving references within finding text.

Part of Phase 1 Enhancement (P1-3: Evidence Cross-Reference Linking)
"""

import re
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, asdict, field


# ═══════════════════════════════════════════════════════════════════════
# DATA MODELS
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class EvidenceLink:
    """
    Links a finding to its supporting evidence.

    Evidence can be:
    - Tables (referenced by "Table 3.2", "Annexure A")
    - Paragraphs (referenced by "Para 4.1.2", "paragraph 3.5")
    - Pages (referenced by "page 25", "(p. 42)")
    - Annexures (referenced by "Annexure B", "Annex-III")
    """

    link_id: str
    finding_id: str
    evidence_type: str  # "table", "paragraph", "annexure", "page"
    evidence_id: str  # Table ID, chunk ID, or identifier
    reference_text: str  # Original reference text found in finding
    confidence: float  # 0.0-1.0 confidence that link is correct

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class ReferenceMatch:
    """A matched reference in text."""

    reference_type: str  # "table", "paragraph", "page", "annexure"
    identifier: str  # The extracted identifier (e.g., "3.2", "A", "25")
    matched_text: str  # The full matched text
    position: int  # Character position in text
    confidence: float  # Confidence of the match


# ═══════════════════════════════════════════════════════════════════════
# REFERENCE EXTRACTION PATTERNS
# ═══════════════════════════════════════════════════════════════════════

# Table references
TABLE_REFERENCE_PATTERNS = [
    # "Table 3.2", "Table 3.2.1"
    (r"Table\s+(\d+(?:\.\d+)*)", "table", 0.95),
    # "as shown in Table 3.2"
    (r"(?:as\s+(?:shown|given|detailed|indicated)\s+in\s+)?Table\s+(\d+(?:\.\d+)*)", "table", 0.9),
    # "vide Table 3.2", "refer Table 3.2"
    (r"(?:vide|see|refer|refer\s+to)\s+Table\s+(\d+(?:\.\d+)*)", "table", 0.9),
    # "(Table 3.2)"
    (r"\(Table\s+(\d+(?:\.\d+)*)\)", "table", 0.85),
]

# Annexure references
ANNEXURE_REFERENCE_PATTERNS = [
    # "Annexure A", "Annexure-B", "Annexure III" (Roman numerals first to match longer sequences)
    (r"Annexure[\s-]?([IVX]+\b)", "annexure", 0.95),  # Roman numerals (with word boundary)
    (r"Annexure[\s-]?([A-Z](?![a-z]))", "annexure", 0.95),  # Single letter (not followed by lowercase)
    (r"Annexure[\s-]?(\d+)", "annexure", 0.95),  # Numbers
    # "Appendix A", "Annex B"
    (r"(?:Appendix|Annex)[\s-]?([IVX]+\b)", "annexure", 0.9),
    (r"(?:Appendix|Annex)[\s-]?([A-Z](?![a-z]))", "annexure", 0.9),
    (r"(?:Appendix|Annex)[\s-]?(\d+)", "annexure", 0.9),
    # "as per Annexure A"
    (r"(?:as\s+per|vide|see|refer\s+to)\s+Annexure[\s-]?([IVX]+\b|[A-Z](?![a-z])|\d+)", "annexure", 0.9),
    # "(Annexure A)"
    (r"\(Annexure[\s-]?([IVX]+\b|[A-Z](?![a-z])|\d+)\)", "annexure", 0.85),
]

# Paragraph references
PARAGRAPH_REFERENCE_PATTERNS = [
    # "Para 3.2.1", "Paragraph 4.5"
    (r"Para(?:graph)?\.?\s+(\d+(?:\.\d+)*)", "paragraph", 0.95),
    # "as mentioned in Para 3.2"
    (r"(?:as\s+(?:mentioned|discussed|stated)\s+(?:in|at)\s+)?Para(?:graph)?\.?\s+(\d+(?:\.\d+)*)", "paragraph", 0.9),
    # "vide Para 3.2"
    (r"(?:vide|see|refer\s+to)\s+Para(?:graph)?\.?\s+(\d+(?:\.\d+)*)", "paragraph", 0.9),
    # "(Para 3.2)"
    (r"\(Para(?:graph)?\.?\s+(\d+(?:\.\d+)*)\)", "paragraph", 0.85),
]

# Page references
PAGE_REFERENCE_PATTERNS = [
    # "page 25", "pages 25-30"
    (r"pages?\s+(\d+(?:\s*-\s*\d+)?)", "page", 0.9),
    # "(p. 42)", "(pg. 42)"
    (r"\(p(?:g)?\.?\s*(\d+)\)", "page", 0.85),
    # "at page 25"
    (r"at\s+page\s+(\d+)", "page", 0.9),
]


# ═══════════════════════════════════════════════════════════════════════
# EVIDENCE LINKER CLASS
# ═══════════════════════════════════════════════════════════════════════


class EvidenceLinker:
    """
    Links findings to supporting evidence by extracting and resolving references.
    """

    def __init__(self):
        """Initialize with compiled reference patterns."""
        self._table_patterns = [
            (re.compile(p, re.IGNORECASE), ref_type, conf)
            for p, ref_type, conf in TABLE_REFERENCE_PATTERNS
        ]
        self._annexure_patterns = [
            (re.compile(p, re.IGNORECASE), ref_type, conf)
            for p, ref_type, conf in ANNEXURE_REFERENCE_PATTERNS
        ]
        self._paragraph_patterns = [
            (re.compile(p, re.IGNORECASE), ref_type, conf)
            for p, ref_type, conf in PARAGRAPH_REFERENCE_PATTERNS
        ]
        self._page_patterns = [
            (re.compile(p, re.IGNORECASE), ref_type, conf)
            for p, ref_type, conf in PAGE_REFERENCE_PATTERNS
        ]

    def extract_references(self, text: str) -> List[ReferenceMatch]:
        """
        Extract all references from text.

        Args:
            text: Text to extract references from

        Returns:
            List of ReferenceMatch objects
        """
        references = []

        # Extract table references
        references.extend(self._extract_references_by_patterns(text, self._table_patterns))

        # Extract annexure references
        references.extend(
            self._extract_references_by_patterns(text, self._annexure_patterns)
        )

        # Extract paragraph references
        references.extend(
            self._extract_references_by_patterns(text, self._paragraph_patterns)
        )

        # Extract page references
        references.extend(self._extract_references_by_patterns(text, self._page_patterns))

        # Sort by position in text
        references.sort(key=lambda r: r.position)

        return references

    def _extract_references_by_patterns(
        self, text: str, patterns: List[Tuple[re.Pattern, str, float]]
    ) -> List[ReferenceMatch]:
        """Extract references using a set of patterns."""
        references = []
        seen_positions = set()  # Avoid duplicate matches at same position

        for pattern, ref_type, confidence in patterns:
            for match in pattern.finditer(text):
                position = match.start()

                # Skip if we already have a reference at this position
                if position in seen_positions:
                    continue

                seen_positions.add(position)

                identifier = match.group(1).strip()
                matched_text = match.group(0)

                references.append(
                    ReferenceMatch(
                        reference_type=ref_type,
                        identifier=identifier,
                        matched_text=matched_text,
                        position=position,
                        confidence=confidence,
                    )
                )

        return references

    def link_finding_to_evidence(
        self,
        finding: Dict,
        tables: List[Dict],
        chunks: List[Dict],
    ) -> List[EvidenceLink]:
        """
        Create evidence links for a finding.

        Args:
            finding: Finding dict with 'finding_id', 'text', etc.
            tables: List of table dicts (from structured_data or extracted_content)
            chunks: List of child chunk dicts

        Returns:
            List of EvidenceLink objects
        """
        finding_id = finding.get("finding_id", "")
        finding_text = finding.get("text", "")

        if not finding_text:
            return []

        # Extract all references from finding text
        references = self.extract_references(finding_text)

        # Create links
        links = []

        for ref in references:
            if ref.reference_type == "table":
                linked_table = self._find_table_by_number(ref.identifier, tables)
                if linked_table:
                    table_id = linked_table.get("table_id") or linked_table.get(
                        "chunk_id", ""
                    )
                    links.append(
                        EvidenceLink(
                            link_id=f"link_{finding_id}_{table_id}",
                            finding_id=finding_id,
                            evidence_type="table",
                            evidence_id=table_id,
                            reference_text=ref.matched_text,
                            confidence=ref.confidence,
                        )
                    )

            elif ref.reference_type == "annexure":
                linked_annexure = self._find_annexure(ref.identifier, chunks)
                if linked_annexure:
                    annexure_id = linked_annexure.get("chunk_id", "")
                    links.append(
                        EvidenceLink(
                            link_id=f"link_{finding_id}_{annexure_id}",
                            finding_id=finding_id,
                            evidence_type="annexure",
                            evidence_id=annexure_id,
                            reference_text=ref.matched_text,
                            confidence=ref.confidence,
                        )
                    )

            elif ref.reference_type == "paragraph":
                linked_para = self._find_chunk_by_para(ref.identifier, chunks)
                if linked_para:
                    para_id = linked_para.get("chunk_id", "")
                    links.append(
                        EvidenceLink(
                            link_id=f"link_{finding_id}_{para_id}",
                            finding_id=finding_id,
                            evidence_type="paragraph",
                            evidence_id=para_id,
                            reference_text=ref.matched_text,
                            confidence=ref.confidence,
                        )
                    )

            elif ref.reference_type == "page":
                # Page references are stored directly as page numbers
                page_num = self._parse_page_number(ref.identifier)
                if page_num:
                    links.append(
                        EvidenceLink(
                            link_id=f"link_{finding_id}_page_{page_num}",
                            finding_id=finding_id,
                            evidence_type="page",
                            evidence_id=str(page_num),
                            reference_text=ref.matched_text,
                            confidence=ref.confidence,
                        )
                    )

        return links

    def link_all_findings(
        self,
        findings: List[Dict],
        tables: List[Dict],
        chunks: List[Dict],
    ) -> Dict[str, List[EvidenceLink]]:
        """
        Create evidence links for all findings.

        Args:
            findings: List of finding dicts
            tables: List of table dicts
            chunks: List of child chunk dicts

        Returns:
            Dict mapping finding_id to list of EvidenceLink objects
        """
        all_links = {}

        for finding in findings:
            finding_id = finding.get("finding_id", "")
            links = self.link_finding_to_evidence(finding, tables, chunks)
            if links:
                all_links[finding_id] = links

        return all_links

    # ═══════════════════════════════════════════════════════════════════════
    # RESOLUTION HELPERS
    # ═══════════════════════════════════════════════════════════════════════

    def _find_table_by_number(
        self, table_number: str, tables: List[Dict]
    ) -> Optional[Dict]:
        """
        Find a table by its number (e.g., "3.2").

        Args:
            table_number: Table number string (e.g., "3.2", "4")
            tables: List of table dicts or ExtractedContent dicts

        Returns:
            Matching table dict or None
        """
        table_number_normalized = table_number.strip()

        for table in tables:
            # Check if this is an ExtractedContent with structured_data
            if table.get("content_type") == "table":
                # Check title for table number
                title = table.get("title", "")
                if title:
                    # Match "Table 3.2" or similar in title
                    match = re.search(
                        r"Table\s+(\d+(?:\.\d+)*)", title, re.IGNORECASE
                    )
                    if match and match.group(1) == table_number_normalized:
                        return table

                # Check structured_data if present
                structured = table.get("structured_data")
                if structured and isinstance(structured, dict):
                    struct_title = structured.get("title", "")
                    if struct_title:
                        match = re.search(
                            r"Table\s+(\d+(?:\.\d+)*)", struct_title, re.IGNORECASE
                        )
                        if match and match.group(1) == table_number_normalized:
                            return table

        return None

    def _find_annexure(self, annexure_id: str, chunks: List[Dict]) -> Optional[Dict]:
        """
        Find an annexure chunk by its identifier.

        Args:
            annexure_id: Annexure identifier (e.g., "A", "III", "1")
            chunks: List of child chunk dicts

        Returns:
            Matching chunk dict or None
        """
        annexure_id_normalized = annexure_id.strip().upper()

        for chunk in chunks:
            # Check metadata for section type
            metadata = chunk.get("metadata", {})
            hierarchy = metadata.get("hierarchy", {})

            # Look for "annexure" in hierarchy
            for level, value in hierarchy.items():
                if isinstance(value, str) and "annexure" in value.lower():
                    # Try to extract annexure ID from value
                    match = re.search(
                        r"Annexure[\s-]?([A-Z]|\d+|[IVX]+)", value, re.IGNORECASE
                    )
                    if match and match.group(1).upper() == annexure_id_normalized:
                        return chunk

            # Also check content for annexure heading
            content = chunk.get("content", "")
            if "annexure" in content.lower()[:100]:  # Check first 100 chars
                match = re.search(
                    r"Annexure[\s-]?([A-Z]|\d+|[IVX]+)", content, re.IGNORECASE
                )
                if match and match.group(1).upper() == annexure_id_normalized:
                    return chunk

        return None

    def _find_chunk_by_para(
        self, para_number: str, chunks: List[Dict]
    ) -> Optional[Dict]:
        """
        Find a chunk by paragraph number.

        Args:
            para_number: Paragraph number (e.g., "3.2.1", "4.5")
            chunks: List of child chunk dicts

        Returns:
            Matching chunk dict or None
        """
        para_number_normalized = para_number.strip()

        for chunk in chunks:
            # Check chunk metadata
            metadata = chunk.get("metadata", {})
            chunk_para = metadata.get("paragraph_number")

            if chunk_para == para_number_normalized:
                return chunk

            # Check hierarchy for matching structure
            hierarchy = metadata.get("hierarchy", {})
            # Build a para-like number from hierarchy levels
            levels = [
                hierarchy.get(f"level_{i}")
                for i in range(1, 10)
                if hierarchy.get(f"level_{i}")
            ]

            # Try to match hierarchical structure to para number
            # E.g., "3.2.1" might match hierarchy level_1=3, level_2=2, level_3=1
            if self._hierarchy_matches_para(levels, para_number_normalized):
                return chunk

        return None

    def _hierarchy_matches_para(self, levels: List[str], para_number: str) -> bool:
        """Check if hierarchy levels match a paragraph number."""
        # Extract numeric parts from levels
        numeric_levels = []
        for level in levels:
            # Try to extract leading number from level
            match = re.match(r"^(\d+)", str(level))
            if match:
                numeric_levels.append(match.group(1))

        # Build dotted number
        if numeric_levels:
            hierarchy_num = ".".join(numeric_levels)
            return hierarchy_num == para_number

        return False

    def _parse_page_number(self, page_ref: str) -> Optional[int]:
        """Parse page number from reference string."""
        # Handle ranges: "25-30" -> 25 (first page)
        if "-" in page_ref:
            page_ref = page_ref.split("-")[0].strip()

        try:
            return int(page_ref)
        except ValueError:
            return None


# ═══════════════════════════════════════════════════════════════════════
# STATISTICS AND ANALYSIS
# ═══════════════════════════════════════════════════════════════════════


def calculate_link_coverage(
    findings: List[Dict], evidence_links: Dict[str, List[EvidenceLink]]
) -> Dict[str, float]:
    """
    Calculate coverage statistics for evidence linking.

    Args:
        findings: List of finding dicts
        evidence_links: Dict mapping finding_id to evidence links

    Returns:
        Dict with coverage statistics
    """
    total_findings = len(findings)
    if total_findings == 0:
        return {
            "total_findings": 0,
            "findings_with_links": 0,
            "coverage_percentage": 0.0,
            "avg_links_per_finding": 0.0,
            "links_by_type": {},
        }

    findings_with_links = len(evidence_links)
    total_links = sum(len(links) for links in evidence_links.values())

    # Count links by type
    links_by_type = {}
    for links in evidence_links.values():
        for link in links:
            link_type = link.evidence_type
            links_by_type[link_type] = links_by_type.get(link_type, 0) + 1

    return {
        "total_findings": total_findings,
        "findings_with_links": findings_with_links,
        "coverage_percentage": (findings_with_links / total_findings) * 100,
        "total_links": total_links,
        "avg_links_per_finding": total_links / total_findings if total_findings > 0 else 0.0,
        "links_by_type": links_by_type,
    }
