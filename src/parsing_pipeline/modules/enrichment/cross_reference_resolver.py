"""
Cross-Reference Resolver: Detects and resolves intra-document references.

Handles:
1. Paragraph references: "Para 3.2.1", "paragraph 2.1.3"
2. Section references: "Chapter III", "Section 2.1"
3. Table references: "Table 1.3", "Table-1"
4. Page references: "page 47"

Does NOT handle semantic similarity linking (that's a Phase 4 embedding task).
"""

import re
from typing import List, Dict, Optional, Tuple


class CrossReferenceResolver:

    # Reference detection patterns
    REFERENCE_PATTERNS = [
        # Para references: "Para 3.2.1", "para 2.1", "paragraph 3.1.2"
        (r"(?:Para(?:graph)?\.?\s*)([\d]+\.[\d]+(?:\.[\d]+)?)", "para"),
        # Section references: "Section 2.1", "section 3.2.1"
        (r"(?:Section\s*)([\d]+\.[\d]+(?:\.[\d]+)?)", "section"),
        # Chapter references: "Chapter III", "Chapter 3"
        (r"(?:Chapter\s+)([IVXivx]+|\d+)", "chapter"),
        # Table references: "Table 1.3", "Table-1", "Table No. 2"
        (r"(?:Table(?:\s+No\.?)?\s*[-\s]?)([\d]+(?:\.[\d]+)?)", "table"),
        # "as discussed above/earlier in Para..."
        (r"(?:as\s+(?:discussed|mentioned|stated|noted|indicated)\s+"
         r"(?:above|earlier|in)\s+(?:Para\.?\s*)?)([\d]+\.[\d]+(?:\.[\d]+)?)", "para"),
    ]

    def __init__(self):
        self._patterns = [
            (re.compile(pat, re.IGNORECASE), ref_type)
            for pat, ref_type in self.REFERENCE_PATTERNS
        ]

    def _build_section_index(
        self, parent_chunks: List[Dict], child_chunks: List[Dict]
    ) -> Dict[str, Dict]:
        """
        Build lookup index from section/para numbers to chunk IDs.

        Keys: normalized identifiers like "3.2.1", "chapter_iii", "table_1.3"
        Values: {"chunk_id": ..., "chunk_type": "parent"|"child", "content_preview": ...}
        """
        index = {}

        # Index parent chunks by their TOC entry number
        for parent in parent_chunks:
            toc_entry = parent.get("toc_entry", "")

            # Extract number from "3.2.1 Implementation Status"
            num_match = re.match(r"^([\d]+(?:\.[\d]+)*)", toc_entry)
            if num_match:
                key = num_match.group(1)
                page_range = parent.get("page_range_physical")
                page = page_range[0] if page_range and len(page_range) > 0 else 0
                index[key] = {
                    "chunk_id": parent.get("chunk_id"),
                    "chunk_type": "parent",
                    "toc_entry": toc_entry[:80],
                    "page": page,
                }

            # Index chapter headings
            chapter_match = re.match(
                r"Chapter\s+([IVXivx]+|\d+)", toc_entry, re.IGNORECASE
            )
            if chapter_match:
                chapter_id = chapter_match.group(1).lower()
                page_range = parent.get("page_range_physical")
                page = page_range[0] if page_range and len(page_range) > 0 else 0
                index[f"chapter_{chapter_id}"] = {
                    "chunk_id": parent.get("chunk_id"),
                    "chunk_type": "parent",
                    "toc_entry": toc_entry[:80],
                    "page": page,
                }

        # Index table chunks
        for child in child_chunks:
            if child.get("content_type") == "table_markdown":
                content = child.get("content", "")
                # Try to extract table number from content or hierarchy
                hierarchy = child.get("hierarchy") or {}
                for level_val in hierarchy.values():
                    table_match = re.match(
                        r"(?:Table\s*[-\s]?)([\d]+(?:\.[\d]+)?)", level_val, re.IGNORECASE
                    )
                    if table_match:
                        key = f"table_{table_match.group(1)}"
                        index[key] = {
                            "chunk_id": child.get("chunk_id"),
                            "chunk_type": "child",
                            "content_preview": content[:60],
                            "page": child.get("source_page_physical", 0),
                        }

        return index

    def resolve_references(
        self,
        child_chunks: List[Dict],
        parent_chunks: List[Dict],
    ) -> List[Dict]:
        """
        Scan all chunks for cross-references and resolve them.

        Returns list of resolved references:
        [{
            "source_chunk_id": "...",
            "source_page": 47,
            "reference_type": "para" | "section" | "chapter" | "table",
            "reference_target": "3.2.1",
            "reference_text": "Para 3.2.1",
            "resolved_chunk_id": "..." or None,
            "resolved_chunk_type": "parent" | "child" or None,
            "resolved": True | False,
        }]
        """
        section_index = self._build_section_index(parent_chunks, child_chunks)
        references = []

        for chunk in child_chunks:
            content = chunk.get("content", "")
            chunk_id = chunk.get("chunk_id", "")
            chunk_page = chunk.get("source_page_physical", 0)

            for pattern, ref_type in self._patterns:
                for match in pattern.finditer(content):
                    target_id = match.group(1)

                    # Build lookup key
                    if ref_type == "chapter":
                        lookup_key = f"chapter_{target_id.lower()}"
                    elif ref_type == "table":
                        lookup_key = f"table_{target_id}"
                    else:
                        lookup_key = target_id

                    # Resolve
                    resolved = section_index.get(lookup_key)

                    # Don't create self-references
                    if resolved and resolved["chunk_id"] == chunk_id:
                        continue

                    ref = {
                        "source_chunk_id": chunk_id,
                        "source_page": chunk_page,
                        "reference_type": ref_type,
                        "reference_target": target_id,
                        "reference_text": match.group(0).strip()[:60],
                        "resolved_chunk_id": resolved["chunk_id"] if resolved else None,
                        "resolved_chunk_type": resolved["chunk_type"] if resolved else None,
                        "resolved_page": resolved.get("page") if resolved else None,
                        "resolved": resolved is not None,
                    }
                    references.append(ref)

        return references
