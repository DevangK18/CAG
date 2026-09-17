"""
Annexure Linker: Identifies references to annexures/appendices in body text
and creates bidirectional links between findings and their supporting annexure data.
"""

import re
from typing import List, Dict, Tuple, Optional


class AnnexureLinker:

    # Patterns to detect annexure references in body text
    # Note: Use non-capturing optional groups to avoid duplicates
    # Pattern explanation: [\w-]*(?:\.[\w]+)* allows "3.1" but not trailing "A."
    ANNEXURE_REF_PATTERNS = [
        # "Details are given in Annexure-A" / "Annexure-I" / "Annexure 3.1"
        r"(?:details?\s+(?:are\s+)?(?:given|provided|shown|placed)\s+(?:in|at)\s+)"
        r"(Annexure[\s-]*[A-Z0-9IVX]+[\w-]*(?:\.[\w]+)*)",
        # "as per Annexure-A" / "vide Annexure-II"
        r"(?:as\s+per|vide|refer|see)\s+(Annexure[\s-]*[A-Z0-9IVX]+[\w-]*(?:\.[\w]+)*)",
        # "(Annexure-A)" in parentheses
        r"\((Annexure[\s-]*[A-Z0-9IVX]+[\w-]*(?:\.[\w]+)*)\)",
        # General "in Annexure-X" pattern (more permissive)
        r"(?:^|\s)(?:in|at)\s+(Annexure[\s-]*[A-Z0-9IVX]+[\w-]*(?:\.[\w]+)*)",
        # Conjunctive references: "and Annexure-X" / "or Annexure-X" / "& Annexure-X"
        r"(?:and|or|&)\s+(Annexure[\s-]*[A-Z0-9IVX]+[\w-]*(?:\.[\w]+)*)",
        # Same patterns for Appendix
        r"(?:details?\s+(?:are\s+)?(?:given|provided|shown|placed)\s+(?:in|at)\s+)"
        r"(Appendix[\s-]*[A-Z0-9IVX]+[\w-]*(?:\.[\w]+)*)",
        r"(?:as\s+per|vide|refer|see)\s+(Appendix[\s-]*[A-Z0-9IVX]+[\w-]*(?:\.[\w]+)*)",
        r"\((Appendix[\s-]*[A-Z0-9IVX]+[\w-]*(?:\.[\w]+)*)\)",
        # General "in Appendix-X" pattern
        r"(?:^|\s)(?:in|at)\s+(Appendix[\s-]*[A-Z0-9IVX]+[\w-]*(?:\.[\w]+)*)",
        # Conjunctive references: "and Appendix-X"
        r"(?:and|or|&)\s+(Appendix[\s-]*[A-Z0-9IVX]+[\w-]*(?:\.[\w]+)*)",
    ]

    def __init__(self):
        self._ref_patterns = [
            re.compile(p, re.IGNORECASE) for p in self.ANNEXURE_REF_PATTERNS
        ]

    def _normalize_annexure_id(self, raw: str) -> str:
        """Normalize 'Annexure - A', 'Annexure-A', 'ANNEXURE A' → 'annexure_a'."""
        cleaned = raw.strip().lower()
        # Replace spaces, hyphens, and colons with underscores
        cleaned = re.sub(r'[\s\-:]+', '_', cleaned)
        return cleaned

    def _find_annexure_parents(self, parent_chunks: List[Dict]) -> Dict[str, Dict]:
        """
        Build index of annexure/appendix parent chunks.
        Returns: {"annexure_a": parent_chunk_dict, ...}
        """
        annexure_index = {}
        for parent in parent_chunks:
            toc_entry = parent.get("toc_entry", "")
            if re.match(r"(?:Annexure|Appendix)", toc_entry, re.IGNORECASE):
                norm_id = self._normalize_annexure_id(toc_entry)
                annexure_index[norm_id] = parent
        return annexure_index

    def link_annexures(
        self,
        child_chunks: List[Dict],
        parent_chunks: List[Dict],
        findings: List[Dict],
    ) -> List[Dict]:
        """
        Scan body text for annexure references and create links.

        Returns list of link dicts:
        [{
            "source_chunk_id": "...",
            "source_type": "finding" | "paragraph",
            "target_annexure_ref": "Annexure-A",
            "target_annexure_norm": "annexure_a",
            "target_parent_chunk_id": "...",
            "reference_text": "Details are given in Annexure-A",
            "resolved": True/False,
            "finding_id": "..." (if source is a finding),
        }]
        """
        annexure_index = self._find_annexure_parents(parent_chunks)
        if not annexure_index:
            return []

        links = []
        finding_chunk_ids = {f.get("source_chunk_id") for f in findings if f.get("source_chunk_id")}
        seen_refs = set()  # Track (chunk_id, norm_ref) to avoid duplicates

        for chunk in child_chunks:
            content = chunk.get("content", "")
            chunk_id = chunk.get("chunk_id", "")

            for pattern in self._ref_patterns:
                for match in pattern.finditer(content):
                    annexure_ref = match.group(1)
                    norm_ref = self._normalize_annexure_id(annexure_ref)

                    # Skip if we've already seen this reference in this chunk
                    ref_key = (chunk_id, norm_ref)
                    if ref_key in seen_refs:
                        continue
                    seen_refs.add(ref_key)

                    # Try to match against known annexure parents
                    target_parent = None
                    for norm_id, parent in annexure_index.items():
                        if norm_ref in norm_id or norm_id in norm_ref:
                            target_parent = parent
                            break

                    # Fuzzy match: try without trailing digits
                    if not target_parent:
                        base_ref = re.sub(r'_?\d+$', '', norm_ref)
                        for norm_id, parent in annexure_index.items():
                            if base_ref in norm_id:
                                target_parent = parent
                                break

                    link = {
                        "source_chunk_id": chunk_id,
                        "source_type": "finding" if chunk_id in finding_chunk_ids else "paragraph",
                        "target_annexure_ref": annexure_ref,
                        "target_annexure_norm": norm_ref,
                        "target_parent_chunk_id": target_parent.get("chunk_id") if target_parent else None,
                        "reference_text": match.group(0).strip()[:120],
                        "resolved": target_parent is not None,
                    }

                    # If source is a finding, attach finding_id
                    for f in findings:
                        if f.get("source_chunk_id") == chunk_id:
                            link["finding_id"] = f.get("finding_id")
                            break

                    links.append(link)

        return links
