"""
Recommendation Extractor: Multi-strategy extraction that handles
consolidated, scattered, and dedicated-chapter recommendation patterns.

P4-3: Three-strategy priority system:
1. Structural: Dedicated rec sections/chapters → extract all content as recs
2. Numbered: "Recommendation No. X: ..." → explicit rec boundary
3. Verb-based: "Ministry should..." → existing pattern (fallback)
"""

import re
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field


@dataclass
class ExtractedRecommendation:
    """Raw extracted recommendation before conversion to data contract."""
    text: str
    source_chunk_id: str
    page: int
    chapter: Optional[str] = None
    section: Optional[str] = None
    rec_number: Optional[str] = None  # "Recommendation No. 18"
    extraction_strategy: str = "verb"  # "structural", "numbered", "verb"
    target_entity: Optional[str] = None
    action_required: Optional[str] = None
    paragraph_citations: List[str] = field(default_factory=list)  # ["3.1", "3.2"]
    confidence: float = 0.0


class RecommendationExtractor:
    """Multi-strategy recommendation extractor for audit reports."""

    # ══════════════════════════════════════════════════════════════
    # Strategy 1: Numbered recommendation patterns
    # ══════════════════════════════════════════════════════════════
    NUMBERED_REC_PATTERNS = [
        # "Recommendation No. 18: MoRTH may consider..."
        r"(Recommendation\s+No\.?\s*(\d+))\s*[:\-–]\s*(.+)",
        # "Recommendation 5: The Ministry should..."
        r"(Recommendation\s+(\d+))\s*[:\-–]\s*(.+)",
        # "Rec. No. 3: ..."
        r"(Rec\.?\s+No\.?\s*(\d+))\s*[:\-–]\s*(.+)",
    ]

    # ══════════════════════════════════════════════════════════════
    # Strategy 2: Structural section indicators
    # ══════════════════════════════════════════════════════════════
    REC_SECTION_PATTERNS = [
        r"^recommendations?$",
        r"^summary\s+of\s+recommendations?$",
        r"^audit\s+recommendations?$",
        r"^significant\s+audit\s+findings?\s+and\s+recommendations?$",
        r"^chapter\s+[ivxIVX\d]+[\s:]+recommendations?",
        r"^compliance\s+(?:of|with)\s+earlier\s+(?:reports?|recommendations?)",
    ]

    # ══════════════════════════════════════════════════════════════
    # Strategy 3: Verb-based patterns (existing, improved)
    # ══════════════════════════════════════════════════════════════
    VERB_REC_PATTERNS = [
        # "Audit recommends that..." (strongest signal)
        r"Audit\s+recommend(?:s|ed)\s+that\s+(.+?)(?:\.\s|$)",
        # "It is recommended that..."
        r"It\s+is\s+(?:recommended|suggested)\s+that\s+(.+?)(?:\.\s|$)",
        # "Ministry/Department/Government/GoI should/may/needs to..."
        r"(?:The\s+)?(?:Ministry|Department|Government|GoI|NHAI|Railways?|Board|Corporation|Authority)"
        r"\s+(?:should|may\s+consider|needs?\s+to|is\s+required\s+to|must)\s+(.+?)(?:\.\s|$)",
        # "CBDT may ensure that..." / "NHA may ensure..."
        r"(?:The\s+)?(?:[A-Z]{2,8})\s+(?:should|may\s+(?:consider|ensure)|needs?\s+to)\s+(.+?)(?:\.\s|$)",
    ]

    # ══════════════════════════════════════════════════════════════
    # Paragraph citation pattern (exec summary refs)
    # ══════════════════════════════════════════════════════════════
    PARA_CITATION_PATTERN = re.compile(
        r"\((?:Para(?:graph)?s?\.?\s*)([\d.]+(?:\s*(?:,|and)\s*[\d.]+)*)"
        r"(?:\s*,\s*Page\s+(?:no\.?\s*)?\d+)?\)",
        re.IGNORECASE,
    )

    # ══════════════════════════════════════════════════════════════
    # Target entity patterns
    # ══════════════════════════════════════════════════════════════
    TARGET_ENTITY_PATTERNS = [
        r"(Ministry\s+of\s+[A-Z][\w\s&]{2,40}?)(?:\s+(?:should|may|needs|is\s+required))",
        r"(Department\s+of\s+[A-Z][\w\s&]{2,40}?)(?:\s+(?:should|may|needs))",
        r"(Government\s+of\s+[A-Z][\w\s]+?)(?:\s+(?:should|may|needs))",
        r"(GoI|NHAI|FCI|CBDT|NHA|AAI|Railways?|Railway\s+Board)(?:\s+(?:should|may|needs))",
    ]

    # ══════════════════════════════════════════════════════════════
    # Action extraction patterns
    # ══════════════════════════════════════════════════════════════
    ACTION_PATTERNS = [
        r"(?:should|must|needs?\s+to)\s+(\w+(?:\s+\w+){0,4})",
        r"may\s+consider\s+(\w+(?:\s+\w+){0,4})",
        r"is\s+required\s+to\s+(\w+(?:\s+\w+){0,4})",
        r"may\s+ensure\s+(?:that\s+)?(\w+(?:\s+\w+){0,4})",
    ]

    def __init__(self):
        """Initialize compiled patterns."""
        self._numbered = [re.compile(p, re.IGNORECASE | re.DOTALL) for p in self.NUMBERED_REC_PATTERNS]
        self._section = [re.compile(p, re.IGNORECASE) for p in self.REC_SECTION_PATTERNS]
        self._verb = [re.compile(p, re.IGNORECASE | re.DOTALL) for p in self.VERB_REC_PATTERNS]
        self._target = [re.compile(p, re.IGNORECASE) for p in self.TARGET_ENTITY_PATTERNS]
        self._action = [re.compile(p, re.IGNORECASE) for p in self.ACTION_PATTERNS]

    def extract_all(
        self,
        report_id: str,
        parent_chunks: List[Dict],
        child_chunks: List[Dict],
        section_classifications: List[Dict],
    ) -> List[ExtractedRecommendation]:
        """
        Multi-strategy recommendation extraction.

        Priority order:
        1. Structural: chunks inside rec-classified sections
        2. Numbered: "Recommendation No. X" anywhere in document
        3. Verb-based: "should/may/must" patterns as fallback

        Deduplicates by content similarity.

        Args:
            report_id: Report identifier
            parent_chunks: Parent section chunks
            child_chunks: Content chunks
            section_classifications: Section type classifications

        Returns:
            List of ExtractedRecommendation objects
        """
        all_recs = []
        seen_texts = set()

        # ──────────────────────────────────────────────────────────
        # Strategy 1: Structural extraction
        # ──────────────────────────────────────────────────────────
        rec_section_ids = self._find_rec_section_ids(parent_chunks, section_classifications)
        if rec_section_ids:
            structural_recs = self._extract_from_sections(
                child_chunks, rec_section_ids, report_id
            )
            for rec in structural_recs:
                sig = rec.text[:80].lower()
                if sig not in seen_texts:
                    seen_texts.add(sig)
                    all_recs.append(rec)

        # ──────────────────────────────────────────────────────────
        # Strategy 2: Numbered recs
        # ──────────────────────────────────────────────────────────
        numbered_recs = self._extract_numbered(child_chunks, report_id)
        for rec in numbered_recs:
            sig = rec.text[:80].lower()
            if sig not in seen_texts:
                seen_texts.add(sig)
                all_recs.append(rec)

        # ──────────────────────────────────────────────────────────
        # Strategy 3: Verb-based (only for chunks not in rec sections)
        # ──────────────────────────────────────────────────────────
        non_rec_chunks = [
            c for c in child_chunks
            if c.get("parent_chunk_id") not in rec_section_ids
        ]
        verb_recs = self._extract_verb_based(non_rec_chunks, report_id)
        for rec in verb_recs:
            sig = rec.text[:80].lower()
            if sig not in seen_texts:
                seen_texts.add(sig)
                all_recs.append(rec)

        # ──────────────────────────────────────────────────────────
        # P1 FIX 3: Strategy 4 - Global dedup and sanity check
        # ──────────────────────────────────────────────────────────
        # If we found numbered recs, verb recs are likely duplicates restated elsewhere.
        # Apply stricter overlap detection: reject verb recs whose text substantially
        # overlaps with any numbered rec (shared 5+ word sequences).
        if numbered_recs:
            all_recs = self._deduplicate_against_numbered(all_recs, numbered_recs)

        # ──────────────────────────────────────────────────────────
        # Enrich all with target entity, action, citations
        # ──────────────────────────────────────────────────────────
        for rec in all_recs:
            if not rec.target_entity:
                rec.target_entity = self._extract_target(rec.text)
            if not rec.action_required:
                rec.action_required = self._extract_action(rec.text)
            rec.paragraph_citations = self._extract_para_citations(rec.text)

        return all_recs

    def _find_rec_section_ids(
        self, parent_chunks: List[Dict], classifications: List[Dict]
    ) -> set:
        """Find parent chunk IDs that are recommendation sections."""
        # From section classifications
        rec_ids = {
            sc.get("chunk_id") for sc in classifications
            if sc.get("section_type") in ("recommendations",)
        }

        # Also scan TOC entries directly for rec section patterns
        for parent in parent_chunks:
            toc = parent.get("toc_entry", "")
            for pattern in self._section:
                if pattern.search(toc):
                    rec_ids.add(parent.get("chunk_id"))
                    break

        return rec_ids

    def _extract_from_sections(
        self, child_chunks: List[Dict], section_ids: set, report_id: str
    ) -> List[ExtractedRecommendation]:
        """
        Extract recs from dedicated recommendation sections.

        In these sections, each bullet/paragraph IS a recommendation.
        Skip very short chunks (<30 chars) and table chunks.
        """
        recs = []
        for chunk in child_chunks:
            if chunk.get("parent_chunk_id") not in section_ids:
                continue
            if chunk.get("content_type") in ("table_markdown", "image_caption", "header"):
                continue

            content = chunk.get("content", "").strip()
            if len(content) < 30:
                continue

            # P1 FIX 2: Skip non-recommendation text (introductory paragraphs)
            # Always require at least one action verb, regardless of length
            has_action = bool(re.search(
                r'\b(?:should|may\s+consider|must|needs?\s+to|is\s+required|ensure|'
                r'recommend(?:s|ed)?|review|strengthen|take\s+(?:steps|action|measures)|'
                r'initiate|improve|complete|institute|expedite|fix)\b',
                content, re.IGNORECASE
            ))
            if not has_action:
                continue  # CHANGED: Always skip, regardless of length

            hierarchy = chunk.get("hierarchy", {})
            recs.append(ExtractedRecommendation(
                text=content,
                source_chunk_id=chunk.get("chunk_id", ""),
                page=chunk.get("source_page_physical", 0),
                chapter=hierarchy.get("level_1"),
                section=hierarchy.get("level_2"),
                extraction_strategy="structural",
                confidence=0.85,
            ))

        return recs

    def _extract_numbered(
        self, child_chunks: List[Dict], report_id: str
    ) -> List[ExtractedRecommendation]:
        """Extract "Recommendation No. X: ..." patterns from any chunk."""
        recs = []
        for chunk in child_chunks:
            content = chunk.get("content", "")
            for pattern in self._numbered:
                for match in pattern.finditer(content):
                    full_label = match.group(1)
                    rec_num = match.group(2)
                    rec_text = match.group(3).strip()

                    if len(rec_text) < 20:
                        continue

                    hierarchy = chunk.get("hierarchy", {})
                    recs.append(ExtractedRecommendation(
                        text=rec_text,
                        source_chunk_id=chunk.get("chunk_id", ""),
                        page=chunk.get("source_page_physical", 0),
                        chapter=hierarchy.get("level_1"),
                        section=hierarchy.get("level_2"),
                        rec_number=full_label,
                        extraction_strategy="numbered",
                        confidence=0.95,
                    ))
        return recs

    def _extract_verb_based(
        self, child_chunks: List[Dict], report_id: str
    ) -> List[ExtractedRecommendation]:
        """Verb-pattern extraction as fallback."""
        recs = []
        for chunk in child_chunks:
            if chunk.get("content_type") in ("table_markdown", "image_caption"):
                continue

            # P1 FIX: Reject verb matches from sections that quote rules, not make recommendations
            hierarchy = chunk.get("hierarchy", {})
            section_context = " ".join(str(v).lower() for v in hierarchy.values())
            if any(indicator in section_context for indicator in [
                "annexure", "appendix", "abbreviation", "glossary",
                "audit criteria", "audit scope", "audit methodology",
                "preface", "acknowledgement",
            ]):
                continue

            content = chunk.get("content", "")

            for pattern in self._verb:
                match = pattern.search(content)
                if match:
                    # Use the full chunk content as rec text, not just the capture group
                    # The capture group is often incomplete
                    rec_text = content.strip()
                    if len(rec_text) < 30:
                        continue

                    # P1 FIX: Reject chunks that are quoting official documents/acts/rules
                    # These use "should/may/must" prescriptively but aren't audit recommendations
                    if re.search(
                        r'\b(?:Act|Rules?|Manual|Agreement|Clause|Section\s+\d|'
                        r'provided\s+that|as\s+per|in\s+accordance|stipulated|prescribed)\b',
                        rec_text[:150], re.IGNORECASE
                    ) and not re.search(
                        r'\b(?:Audit|CAG)\s+recommend', rec_text, re.IGNORECASE
                    ):
                        continue

                    # P1 FIX 1: Reject past-tense observations (findings, not recommendations)
                    # "should have done", "may have been", "must have resulted"
                    if re.search(
                        r'\b(?:should|may|must|could)\s+have\s+(?:been|done|taken|ensured|completed|resulted|prevented)',
                        rec_text, re.IGNORECASE
                    ):
                        continue

                    # P1 FIX 1: Reject chunks that are clearly audit observations
                    # Key signal: "Audit observed/noticed/found that..." framing
                    if re.search(
                        r'\b(?:Audit|CAG|We)\s+(?:observed|noticed|found|noted)\b',
                        rec_text, re.IGNORECASE
                    ):
                        continue

                    # P1 FIX 1: Require the recommendation verb to appear in the
                    # FIRST 40% of the text. Real recs lead with the directive.
                    # Observations mention "should" deep in narrative context.
                    match_pos = match.start()
                    if len(rec_text) > 200 and match_pos > len(rec_text) * 0.4:
                        continue

                    hierarchy = chunk.get("hierarchy", {})
                    recs.append(ExtractedRecommendation(
                        text=rec_text,
                        source_chunk_id=chunk.get("chunk_id", ""),
                        page=chunk.get("source_page_physical", 0),
                        chapter=hierarchy.get("level_1"),
                        section=hierarchy.get("level_2"),
                        extraction_strategy="verb",
                        confidence=0.7,
                    ))
                    break  # One rec per chunk for verb strategy

        return recs

    def _deduplicate_against_numbered(
        self,
        all_recs: List[ExtractedRecommendation],
        numbered_recs: List[ExtractedRecommendation],
    ) -> List[ExtractedRecommendation]:
        """
        Remove verb/structural recs that substantially overlap with numbered recs.

        Numbered recs are highest confidence — if a verb rec covers the same
        content (shares a 6+ word phrase), it's a restated duplicate.

        Args:
            all_recs: All extracted recommendations
            numbered_recs: Numbered recommendations (high confidence)

        Returns:
            Filtered list with overlapping verb/structural recs removed
        """
        if not numbered_recs:
            return all_recs

        # Build set of 6-word shingles from all numbered recs
        numbered_shingles = set()
        for rec in numbered_recs:
            words = rec.text.lower().split()
            for i in range(len(words) - 5):
                shingle = " ".join(words[i:i+6])
                numbered_shingles.add(shingle)

        filtered = []
        for rec in all_recs:
            if rec.extraction_strategy == "numbered":
                filtered.append(rec)  # Always keep numbered
                continue

            # Check if this rec overlaps with any numbered rec
            words = rec.text.lower().split()
            overlap_count = 0
            for i in range(len(words) - 5):
                shingle = " ".join(words[i:i+6])
                if shingle in numbered_shingles:
                    overlap_count += 1

            # If >2 shingles overlap, it's a restatement
            if overlap_count > 2:
                continue

            filtered.append(rec)

        removed = len(all_recs) - len(filtered)
        if removed > 0:
            import logging
            logging.getLogger(__name__).info(
                f"Dedup: removed {removed} verb/structural recs overlapping with numbered recs"
            )

        return filtered

    def _extract_para_citations(self, text: str) -> List[str]:
        """Extract paragraph citations: (Paragraph 3.2, Page no. 11) → ["3.2"]"""
        citations = []
        for match in self.PARA_CITATION_PATTERN.finditer(text):
            raw = match.group(1)
            # Split "3.2.1, 3.3, and 3.4" into individual numbers
            parts = re.split(r'\s*(?:,|and)\s*', raw)
            for part in parts:
                part = part.strip()
                if re.match(r'^\d+(?:\.\d+)*$', part):
                    citations.append(part)
        return citations

    def _extract_target(self, text: str) -> Optional[str]:
        """Extract target entity (Ministry/Department/Organization)."""
        for p in self._target:
            m = p.search(text)
            if m:
                return m.group(1).strip()
        return None

    def _extract_action(self, text: str) -> Optional[str]:
        """Extract action phrase (should/may/must + action verb)."""
        for p in self._action:
            m = p.search(text)
            if m:
                return m.group(1).strip()
        return None
