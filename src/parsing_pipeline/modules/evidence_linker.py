"""
Evidence Cross-Reference Linking for CAG Audit Reports.

This module links audit findings to their supporting evidence (tables, paragraphs,
annexures, pages) by extracting and resolving references within finding text.

Part of Phase 1 Enhancement (P1-3: Evidence Cross-Reference Linking)
"""

import re
from dataclasses import asdict, dataclass
from typing import Dict, List, Optional

from src.parsing_pipeline.modules.enrichment.cross_reference_resolver import (
    ReferenceIndex,
    find_references,
    parents_from_children,
)


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

# Tables, paragraphs and annexures/appendices use the shared reference patterns
# (enrichment/cross_reference_resolver.py); pages are only extracted, never
# linked: "page 12" in a finding is nearly always a page of another document.
PAGE_REFERENCE_PATTERNS = [
    # "page 25", "pages 25-30"
    (r"\bpages?\s+(\d+(?:\s*-\s*\d+)?)", "page", 0.9),
    # "(p. 42)", "(pg. 42)"
    (r"\(p(?:g)?\.?\s*(\d+)\)", "page", 0.85),
]

_KIND_TO_TYPE = {
    "table": "table",
    "appendix": "annexure",
    "para": "paragraph",
    "section": "paragraph",
}
_CONFIDENCE = {"exact": 0.95, "prefix": 0.85, "ancestor": 0.75}


# ═══════════════════════════════════════════════════════════════════════
# EVIDENCE LINKER CLASS
# ═══════════════════════════════════════════════════════════════════════


class EvidenceLinker:
    """
    Links findings to supporting evidence by extracting and resolving references.

    Resolution goes through the report's ReferenceIndex: a table by its number
    (from its caption), an appendix by its exact ID, a paragraph by its section
    number or the nearest numbered section above it.
    """

    def __init__(self):
        self._page_patterns = [
            (re.compile(p, re.IGNORECASE), ref_type, conf)
            for p, ref_type, conf in PAGE_REFERENCE_PATTERNS
        ]

    def extract_references(self, text: str) -> List[ReferenceMatch]:
        """
        Extract all references from text: one per (type, identifier), lists expanded,
        another document's paragraphs ("Para 4.4.1 of SSIF") left out.
        """
        references = []
        seen = set()
        for ref in find_references(
            text or "", ("table", "appendix", "para", "section")
        ):
            ref_type = _KIND_TO_TYPE[ref.kind]
            if (ref_type, ref.target) in seen:
                continue
            seen.add((ref_type, ref.target))
            references.append(
                ReferenceMatch(
                    reference_type=ref_type,
                    identifier=ref.target,
                    matched_text=ref.text,
                    position=ref.start,
                    confidence=0.95,
                )
            )
        for pattern, ref_type, confidence in self._page_patterns:
            for match in pattern.finditer(text or ""):
                if (ref_type, match.group(1)) in seen:
                    continue
                seen.add((ref_type, match.group(1)))
                references.append(
                    ReferenceMatch(
                        ref_type,
                        match.group(1).strip(),
                        match.group(0),
                        match.start(),
                        confidence,
                    )
                )
        references.sort(key=lambda r: r.position)
        return references

    def link_finding_to_evidence(
        self,
        finding: Dict,
        tables: List[Dict],
        chunks: List[Dict],
        index: Optional[ReferenceIndex] = None,
        parent_chunks: Optional[List[Dict]] = None,
    ) -> List[EvidenceLink]:
        """
        Create evidence links for a finding.

        Args:
            finding: Finding dict with 'finding_id', 'text', etc.
            tables: Table chunks (table_markdown); also found in chunks when this is empty
            chunks: List of child chunk dicts
            index: The report's ReferenceIndex (built from parent_chunks and chunks if absent)
            parent_chunks: Parent chunks; rebuilt from the children's hierarchy if absent

        Returns:
            List of EvidenceLink objects, one per resolved (type, target)
        """
        finding_id = finding.get("finding_id", "")
        finding_text = finding.get("text", "")

        if not finding_text:
            return []

        if index is None:
            index = self._build_index(tables, chunks, parent_chunks)

        own = set(finding.get("source_chunk_ids") or [finding.get("source_chunk_id")])
        own_parents = {index.parent_of.get(c) for c in own if c}

        links = []
        seen_targets = set()
        for ref in find_references(
            finding_text, ("table", "appendix", "para", "section")
        ):
            target, how = index.resolve(ref)
            if not target:
                continue
            target_id = target["chunk_id"]
            # The finding's own chunk or own section is not evidence for it
            if target_id in own or (target_id in own_parents and how == "exact"):
                continue
            evidence_type = _KIND_TO_TYPE[ref.kind]
            if (evidence_type, target_id) in seen_targets:
                continue
            seen_targets.add((evidence_type, target_id))
            links.append(
                EvidenceLink(
                    link_id=f"link_{finding_id}_{target_id}",
                    finding_id=finding_id,
                    evidence_type=evidence_type,
                    evidence_id=target_id,
                    reference_text=ref.text,
                    confidence=_CONFIDENCE.get(how, 0.75),
                )
            )

        return links

    def link_all_findings(
        self,
        findings: List[Dict],
        tables: List[Dict],
        chunks: List[Dict],
        parent_chunks: Optional[List[Dict]] = None,
    ) -> Dict[str, List[EvidenceLink]]:
        """
        Create evidence links for all findings.

        Args:
            findings: List of finding dicts
            tables: Table chunks (table_markdown); also found in chunks when this is empty
            chunks: List of child chunk dicts
            parent_chunks: Parent chunks; rebuilt from the children's hierarchy if absent

        Returns:
            Dict mapping finding_id to list of EvidenceLink objects
        """
        index = self._build_index(tables, chunks, parent_chunks)
        all_links = {}

        for finding in findings:
            finding_id = finding.get("finding_id", "")
            links = self.link_finding_to_evidence(finding, tables, chunks, index=index)
            if links:
                all_links[finding_id] = links

        return all_links

    # ═══════════════════════════════════════════════════════════════════════
    # RESOLUTION HELPERS
    # ═══════════════════════════════════════════════════════════════════════

    @staticmethod
    def _build_index(
        tables: List[Dict], chunks: List[Dict], parent_chunks: Optional[List[Dict]]
    ) -> ReferenceIndex:
        known = {c.get("chunk_id") for c in chunks}
        children = list(chunks) + [
            t for t in tables or [] if t.get("chunk_id") not in known
        ]
        parents = (
            parent_chunks
            if parent_chunks is not None
            else parents_from_children(children)
        )
        return ReferenceIndex(parents, children)

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
        "avg_links_per_finding": total_links / total_findings
        if total_findings > 0
        else 0.0,
        "links_by_type": links_by_type,
    }
