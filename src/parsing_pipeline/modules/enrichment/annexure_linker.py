"""
Annexure Linker: Identifies references to annexures/appendices in body text
and creates bidirectional links between findings and their supporting annexure data.

Annexure and Appendix are the same thing. A reference resolves only to the
appendix with the same number ("Appendix 2.1" never lands on "Appendix 2.10"):
- an appendix parent ("Appendix 5.1 Statement showing ...");
- or, when every appendix sits under one "Annexures" parent, the heading chunk
  that starts that appendix ("Annexure III (Refer Para 5.1.3.1) ...").
"Appendix-15(i)" falls back to "Appendix 15"; "Appendix 15" resolves to "15(i)"
only when that is its one sub-appendix. Anything else is recorded unresolved.
"""

from typing import Dict, List, Optional

from src.parsing_pipeline.modules.enrichment.cross_reference_resolver import (
    ReferenceIndex,
    find_references,
    is_contents_listing,
    is_title_match,
    normalize_appendix_id,
)


class AnnexureLinker:
    def _normalize_annexure_id(self, raw: str) -> str:
        """'Annexure - A', 'Appendix-A', 'ANNEXURE A' -> 'appendix:a'; 'Appendix 2.1' -> 'appendix:2.1'."""
        return f"appendix:{normalize_appendix_id(raw)}"

    def _find_annexure_parents(self, parent_chunks: List[Dict]) -> Dict[str, Dict]:
        """
        Index of appendix parents by normalized ID.
        Returns: {"appendix:a": parent_chunk_dict, ...}
        """
        index = ReferenceIndex(parent_chunks, [])
        by_id = {p.get("chunk_id"): p for p in parent_chunks}
        return {
            f"appendix:{key}": by_id[t["chunk_id"]]
            for key, t in index.appendices.items()
        }

    def link_annexures(
        self,
        child_chunks: List[Dict],
        parent_chunks: List[Dict],
        findings: List[Dict],
        index: Optional[ReferenceIndex] = None,
    ) -> List[Dict]:
        """
        Scan body text for annexure references and create links.

        Returns list of link dicts:
        [{
            "source_chunk_id": "...",
            "source_type": "finding" | "paragraph",
            "target_annexure_ref": "Annexure-A",
            "target_annexure_norm": "appendix:a",
            "target_parent_chunk_id": "...",   # the appendix parent, or the parent holding its heading
            "target_chunk_id": "...",          # the appendix parent or heading chunk itself
            "target_chunk_type": "parent" | "child",
            "reference_text": "(Annexure-A)",
            "resolved": True/False,
            "resolved_by": "exact" | "ancestor" | "prefix" | None,
            "finding_id": "..." (if source is a finding),
            "finding_ids": [...],
        }]
        """
        index = index or ReferenceIndex(parent_chunks, child_chunks)
        parent_of = {c.get("chunk_id"): c.get("parent_chunk_id") for c in child_chunks}

        findings_by_chunk: Dict[str, List[str]] = {}
        for f in findings:
            for cid in f.get("source_chunk_ids") or [f.get("source_chunk_id")]:
                if cid:
                    findings_by_chunk.setdefault(cid, []).append(f.get("finding_id"))

        links = []
        for chunk in child_chunks:
            content = chunk.get("content", "")
            chunk_id = chunk.get("chunk_id", "")
            if not content or is_contents_listing(chunk):
                continue
            seen = set()  # one link per appendix per chunk
            for ref in find_references(content, ("appendix",)):
                if is_title_match(chunk, ref) or index.names_itself(chunk, ref):
                    continue
                norm_ref = f"appendix:{ref.target}"
                if norm_ref in seen:
                    continue
                seen.add(norm_ref)
                target, how = index.resolve(ref)
                target_id = target["chunk_id"] if target else None
                if target and target["chunk_type"] == "child":
                    target_parent = parent_of.get(target_id)
                else:
                    target_parent = target_id

                link = {
                    "source_chunk_id": chunk_id,
                    "source_type": "finding"
                    if chunk_id in findings_by_chunk
                    else "paragraph",
                    "target_annexure_ref": ref.text,
                    "target_annexure_norm": norm_ref,
                    "target_parent_chunk_id": target_parent,
                    "target_chunk_id": target_id,
                    "target_chunk_type": target["chunk_type"] if target else None,
                    "reference_text": content[max(0, ref.start - 40) : ref.end].strip()[
                        :120
                    ],
                    "resolved": target is not None,
                    "resolved_by": how,
                }
                if chunk_id in findings_by_chunk:
                    link["finding_id"] = findings_by_chunk[chunk_id][0]
                    link["finding_ids"] = findings_by_chunk[chunk_id]
                links.append(link)

        return links
