# Phase 4: Document Structure Intelligence

## Design Principle: Generalisation Guard

Every pattern in this phase is implemented as **configurable profiles**, not hardcoded logic. CAG reports are the primary target, but the patterns (boxes, footnotes, executive summaries, cross-references) exist in government audit reports worldwide, corporate annual reports, legal filings, and regulatory documents. Where a pattern is CAG-specific, it lives in a `profiles/cag_audit.py` config file that can be swapped.

**Rule**: If a feature only works on CAG reports and breaks on a random PDF, it doesn't ship.

---

## Execution Order

```
P4-1  Footnote Capture                    (standalone, touches extraction layer)
P4-2  Box Element Detection               (standalone, semantic enrichment)
P4-3  Recommendation Extraction Overhaul  (standalone, replaces current rec logic)
P4-4  Executive Summary Parser            (needs: P4-3 rec patterns)
P4-5  Visual Asset Registry               (standalone, assembly layer)
P4-6  Rotated Page & Visual Subtype       (standalone, layout/extraction layer)
P4-7  Validation Updates                  (needs: all above)
```

Parallel tracks:
- **Track A**: P4-1 → P4-2 → P4-3 → P4-4
- **Track B**: P4-5 + P4-6 (independent)
- **Track C**: P4-7 (after merge)

---

## P4-1: Footnote Capture

**Problem**: Docling classifies `Footnote` blocks correctly, but `ContentExtractionService` routes them to `TextExtractor` (line 86) — identical to body text. They lose their identity and pollute paragraph content.

**Files to modify**:
- `src/parsing_pipeline/content_extraction_service.py`
- `src/core/data_contracts.py`

### 1.1 Add `footnote` to content_type literals

In `data_contracts.py`, update the `content_type` Literal in both `ExtractedContent` (line 28) and `ChildChunk` (line 95):

```python
content_type: Literal[
    "paragraph",
    "table_markdown",
    "image_caption",
    "chart_data_path",
    "list",
    "header",
    "footnote",      # P4-1
]
```

### 1.2 Add footnote extraction to ContentExtractionService

Replace the router entry (line 86):
```python
# Before:
"Footnote": self.text_extractor.extract,

# After:
"Footnote": self._extract_footnote,
```

Add method:
```python
def _extract_footnote(
    self, block: Dict, pdf_path: str, page_num: int, task: DocumentTask
) -> Optional[ExtractedContent]:
    """
    Extract footnote with number detection.
    Delegates text extraction to TextExtractor, then overrides content_type
    and prepends footnote number if detectable.
    """
    result = self.text_extractor.extract(block, pdf_path, page_num, task)
    if not result:
        return None

    content = result.content.strip()

    # Detect footnote number: "7 FSSAI standards..." or "¹ FSSAI..."
    footnote_num = None
    num_match = re.match(r'^(\d{1,3})\s+', content)
    if num_match:
        footnote_num = num_match.group(1)
    else:
        # Unicode superscript: ¹²³⁴⁵⁶⁷⁸⁹⁰
        sup_match = re.match(r'^([¹²³⁴⁵⁶⁷⁸⁹⁰]+)\s*', content)
        if sup_match:
            # Convert superscript to normal digits
            sup_map = str.maketrans('¹²³⁴⁵⁶⁷⁸⁹⁰', '1234567890')
            footnote_num = sup_match.group(1).translate(sup_map)

    # Tag as footnote
    result.content_type = "footnote"

    # Prefix with [Footnote X] for RAG context
    if footnote_num:
        result.content = f"[Footnote {footnote_num}] {content}"

    return result
```

### 1.3 Assembly: exclude footnotes from main content, store separately

In `assembly_service.py`, after serializing child chunks, add a footnote index:

```python
# P4-1: Build footnote index
footnotes = [
    {
        "footnote_number": self._extract_footnote_number(c["content"]),
        "content": c["content"],
        "page_physical": c["source_page_physical"],
        "chunk_id": c["chunk_id"],
        "parent_section": c.get("hierarchy", {}),
    }
    for c in assembled_data["child_chunks"]
    if c["content_type"] == "footnote"
]
assembled_data["footnote_index"] = footnotes
```

This gives you a flat list to query later without polluting paragraph retrieval.

---

## P4-2: Box Element Detection

**Problem**: "Box 3.1: Illustration of excess expenditure" is a semantic element — an illustrative callout, example, or calculation. Currently treated as plain text.

**Key constraint from your observation**: Many reports wrap large sections in colored boxes that are just regular body text. Only boxes with explicit "Box X.X" captions should be tagged.

**Files to modify**:
- `src/enrichment/semantic_enrichment_service.py`
- `src/core/data_contracts.py`

### 2.1 Add box detection patterns

Add to `semantic_enrichment_service.py` after `ENTITY_PATTERNS` (line 377):

```python
# ==================== BOX ELEMENT PATTERNS ====================

# Only match explicit "Box X.X" labels — NOT colored-background sections
BOX_CAPTION_PATTERNS = [
    # "Box 3.1: Illustration of excess expenditure"
    r"(Box\s+\d+(?:\.\d+)?)\s*[:\-–]\s*(.+?)(?:\.|$)",
    # "Box 3.1 Illustration of ..."
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
```

### 2.2 Add box detection method

```python
def _detect_box_elements(
    self, child_chunks: List[Dict]
) -> List[Dict[str, Any]]:
    """
    Detect "Box X.X" elements across child chunks.
    
    Strategy:
    1. Scan for "Box X.X: Title" pattern in chunk content
    2. The chunk containing the caption + subsequent chunks on same/next page
       until next section heading = box content
    3. Do NOT tag chunks just because they're on a colored background
    
    Returns list of box descriptors (not modifying chunks — just metadata).
    """
    boxes = []
    compiled = [re.compile(p, re.IGNORECASE) for p in self.BOX_CAPTION_PATTERNS]
    
    for i, chunk in enumerate(child_chunks):
        content = chunk.get("content", "")
        
        for pattern in compiled:
            match = pattern.search(content[:200])  # Only check start of chunk
            if match:
                box_id = match.group(1).strip()
                box_title = match.group(2).strip() if match.lastindex >= 2 else ""
                
                # Classify box subtype
                box_subtype = "general"
                content_lower = (box_title + " " + content).lower()
                for subtype, keywords in self.BOX_SUBTYPE_KEYWORDS.items():
                    if any(kw in content_lower for kw in keywords):
                        box_subtype = subtype
                        break
                
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
```

### 2.3 Integration

In `enrich_document`, after entity extraction:

```python
# P4-2: Detect box elements
box_elements = self._detect_box_elements(child_chunks)
print(f"  Detected {len(box_elements)} box elements")
```

Add `box_elements` field to `SemanticEnrichment` data contract:
```python
box_elements: List[Dict[str, Any]] = Field(
    default_factory=list,
    description="P4-2: Detected Box X.X illustrative elements"
)
```

### Why this doesn't overfit

The pattern `Box\s+\d+(?:\.\d+)?` is standard across government and corporate reports globally. World Bank reports, EU audit reports, OECD publications all use numbered boxes. The subtype classification uses generic keywords. No CAG-specific logic.

---

## P4-3: Recommendation Extraction Overhaul

**Problem**: Current extraction only catches "should/may/needs to" verb patterns (lines 270-285). Misses:
- **Pattern A**: Numbered "Recommendation No. 18: MoRTH may consider..." (image3)
- **Pattern B**: Dedicated "Summary of Recommendations" section with bulleted recs (image9)
- **Pattern C**: Entire chapter titled "Recommendations" (image16, Chapter IX)
- **Pattern D**: Bold/italic inline recs within executive summary (image15)
- **Pattern E**: Numbered recs in colored tables within exec summary (image4)

**Files to modify**:
- `src/enrichment/semantic_enrichment_service.py` (replace `_extract_recommendations`)

**Files to create**:
- `src/enrichment/recommendation_extractor.py`

### 3.1 Create `recommendation_extractor.py`

```python
"""
Recommendation Extractor: Multi-strategy extraction that handles
consolidated, scattered, and dedicated-chapter recommendation patterns.

Strategy priority:
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

    # ── Strategy 1: Numbered recommendation patterns ──
    NUMBERED_REC_PATTERNS = [
        # "Recommendation No. 18: MoRTH may consider..."
        r"(Recommendation\s+No\.?\s*(\d+))\s*[:\-–]\s*(.+)",
        # "Recommendation 5: The Ministry should..."
        r"(Recommendation\s+(\d+))\s*[:\-–]\s*(.+)",
        # "Rec. No. 3: ..."
        r"(Rec\.?\s+No\.?\s*(\d+))\s*[:\-–]\s*(.+)",
    ]

    # ── Strategy 2: Structural section indicators ──
    REC_SECTION_PATTERNS = [
        r"^recommendations?$",
        r"^summary\s+of\s+recommendations?$",
        r"^audit\s+recommendations?$",
        r"^significant\s+audit\s+findings?\s+and\s+recommendations?$",
        r"^chapter\s+[ivxIVX\d]+[\s:]+recommendations?",
        r"^compliance\s+(?:of|with)\s+earlier\s+(?:reports?|recommendations?)",
    ]

    # ── Strategy 3: Verb-based patterns (existing, improved) ──
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

    # ── Paragraph citation pattern (exec summary refs) ──
    PARA_CITATION_PATTERN = re.compile(
        r"\((?:Para(?:graph)?s?\.?\s*)([\d.]+(?:\s*(?:,|and)\s*[\d.]+)*)"
        r"(?:\s*,\s*Page\s+(?:no\.?\s*)?\d+)?\)",
        re.IGNORECASE,
    )

    # ── Target entity patterns ──
    TARGET_ENTITY_PATTERNS = [
        r"(Ministry\s+of\s+[A-Z][\w\s&]{2,40}?)(?:\s+(?:should|may|needs|is\s+required))",
        r"(Department\s+of\s+[A-Z][\w\s&]{2,40}?)(?:\s+(?:should|may|needs))",
        r"(Government\s+of\s+[A-Z][\w\s]+?)(?:\s+(?:should|may|needs))",
        r"(GoI|NHAI|FCI|CBDT|NHA|AAI|Railways?|Railway\s+Board)(?:\s+(?:should|may|needs))",
    ]

    # ── Action extraction patterns ──
    ACTION_PATTERNS = [
        r"(?:should|must|needs?\s+to)\s+(\w+(?:\s+\w+){0,4})",
        r"may\s+consider\s+(\w+(?:\s+\w+){0,4})",
        r"is\s+required\s+to\s+(\w+(?:\s+\w+){0,4})",
        r"may\s+ensure\s+(?:that\s+)?(\w+(?:\s+\w+){0,4})",
    ]

    def __init__(self):
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
        """
        all_recs = []
        seen_texts = set()

        # ── Strategy 1: Structural extraction ──
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

        # ── Strategy 2: Numbered recs ──
        numbered_recs = self._extract_numbered(child_chunks, report_id)
        for rec in numbered_recs:
            sig = rec.text[:80].lower()
            if sig not in seen_texts:
                seen_texts.add(sig)
                all_recs.append(rec)

        # ── Strategy 3: Verb-based (only for chunks not in rec sections) ──
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

        # Enrich all with target entity, action, citations
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
        """Extract recs from dedicated recommendation sections.
        
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
            
            # Skip non-recommendation text (introductory paragraphs)
            # Heuristic: if it doesn't contain an action verb, it's probably intro text
            has_action = bool(re.search(
                r'\b(?:should|may|must|needs?\s+to|is\s+required|ensure|consider|review|'
                r'establish|strengthen|take\s+action|initiate|fix|improve|complete)\b',
                content, re.IGNORECASE
            ))
            if not has_action and len(content) < 150:
                continue
            
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
            content = chunk.get("content", "")
            
            for pattern in self._verb:
                match = pattern.search(content)
                if match:
                    # Use the full chunk content as rec text, not just the capture group
                    # The capture group is often incomplete
                    rec_text = content.strip()
                    if len(rec_text) < 30:
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
        for p in self._target:
            m = p.search(text)
            if m:
                return m.group(1).strip()
        return None

    def _extract_action(self, text: str) -> Optional[str]:
        for p in self._action:
            m = p.search(text)
            if m:
                return m.group(1).strip()
        return None
```

### 3.2 Integration: replace current _extract_recommendations

In `semantic_enrichment_service.py`, `enrich_document` method (line 498), replace:

```python
# OLD:
recommendations = self._extract_recommendations(report_id, child_chunks)

# NEW:
from src.enrichment.recommendation_extractor import RecommendationExtractor
rec_extractor = RecommendationExtractor()
raw_recs = rec_extractor.extract_all(
    report_id, parent_chunks, child_chunks,
    [s.to_dict() for s in section_classifications]
)

# Convert to Recommendation data contracts
recommendations = []
for i, raw in enumerate(raw_recs):
    recommendations.append(Recommendation(
        recommendation_id=f"{report_id}_rec_{i+1:03d}",
        report_id=report_id,
        text=raw.text,
        summary=raw.text[:200],
        target_entity=raw.target_entity,
        action_required=raw.action_required,
        chapter=raw.chapter,
        section=raw.section,
        page=raw.page,
        source_chunk_id=raw.source_chunk_id,
        status="pending",
        # P4-3: new fields
        # Store extraction metadata for debugging
    ))
print(f"  Extracted {len(recommendations)} recommendations "
      f"(structural={sum(1 for r in raw_recs if r.extraction_strategy=='structural')}, "
      f"numbered={sum(1 for r in raw_recs if r.extraction_strategy=='numbered')}, "
      f"verb={sum(1 for r in raw_recs if r.extraction_strategy=='verb')})")
```

### Why this doesn't overfit

The three-strategy approach (structural → numbered → verb) is how recommendation extraction works in any audit/regulatory document. The structural strategy uses `section_classifications` which themselves are regex-based and configurable. The numbered pattern `Recommendation\s+No\.?\s*\d+` is universal in formal reports. The verb patterns work on any English-language document.

---

## P4-4: Executive Summary Parser

**Problem**: Executive summaries contain a structured index of findings+recs with `(Paragraph X.X.X)` citations that map directly to body paragraphs. This is the single highest-value navigation structure in the document.

**Files to create**:
- `src/enrichment/executive_summary_parser.py`

**Files to modify**:
- `src/enrichment/semantic_enrichment_service.py` (integrate)
- `src/core/data_contracts.py` (add to SemanticEnrichment)

### 4.1 Add to `SemanticEnrichment`:

```python
# P4-4: Executive summary structured index
executive_summary_index: Optional[Dict[str, Any]] = Field(
    default=None,
    description="Structured index from exec summary: findings/recs mapped to paragraph citations"
)
```

### 4.2 Create `executive_summary_parser.py`

```python
"""
Executive Summary Parser: Extracts the structured finding/recommendation index
from executive summary sections and resolves paragraph citations to chunk IDs.

Handles variants:
- "Executive Summary" (most common)
- "Highlights" (Direct Taxes reports)
- "Summary" / "Overview" / "Key Findings"
- Full-page boxed summaries (content still extracted as text)
- 1-page to 4-page summaries

Output: A list of summary items, each with text + resolved paragraph links.
"""

import re
from typing import List, Dict, Optional, Tuple


class ExecutiveSummaryParser:

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
                "text": content[:500],
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
```

### 4.3 Integration in `enrich_document`:

```python
# P4-4: Parse executive summary
from src.enrichment.executive_summary_parser import ExecutiveSummaryParser
exec_parser = ExecutiveSummaryParser()
exec_summary_index = exec_parser.parse_executive_summary(
    parent_chunks, child_chunks,
    [s.to_dict() for s in section_classifications]
)
if exec_summary_index:
    print(f"  Exec summary: {exec_summary_index['total_items']} items, "
          f"{exec_summary_index['resolution_rate']*100:.0f}% citations resolved")
```

Add `executive_summary_index=exec_summary_index` to SemanticEnrichment return.

---

## P4-5: Visual Asset Registry

**Problem**: Your frontend has `useTables` and `useCharts` hooks that call `fetchReportTables(reportId)` and `fetchReportCharts(reportId)`. These expect `{tables: TableItem[], total}` and `{charts: ChartItem[], total}`. The API needs structured data from the pipeline JSON. Currently tables/charts are just child chunks with `content_type: "table_markdown"` or `"image_caption"` — no dedicated registry.

**Files to modify**:
- `src/parsing_pipeline/assembly_service.py`

### 5.1 Add `_build_visual_asset_registry` to AssemblyService

```python
def _build_visual_asset_registry(
    self,
    child_chunks: List[Dict],
    parent_chunks: List[Dict],
) -> Dict[str, Any]:
    """
    Build a flat registry of all tables, figures, and charts
    for frontend navigation.
    
    Returns:
    {
        "tables": [{table_id, caption, page, section, chunk_id, row_count, col_count, ...}],
        "figures": [{figure_id, caption, page, section, chunk_id, visual_subtype, ...}],
        "total_tables": N,
        "total_figures": M,
    }
    """
    tables = []
    figures = []
    
    # Build parent lookup
    parent_lookup = {p.get("chunk_id"): p for p in parent_chunks}
    
    for chunk in child_chunks:
        content_type = chunk.get("content_type", "")
        content = chunk.get("content", "")
        chunk_id = chunk.get("chunk_id", "")
        page = chunk.get("source_page_physical", 0)
        page_logical = chunk.get("source_page_logical")
        bbox = chunk.get("metadata", {}).get("location", {}).get("bbox", [])
        hierarchy = chunk.get("hierarchy", {})
        parent_id = chunk.get("parent_chunk_id")
        
        # Parent section context
        parent = parent_lookup.get(parent_id, {})
        parent_section = parent.get("toc_entry", "")
        
        if content_type == "table_markdown":
            # Extract table number and caption from content or context
            table_num, table_caption = self._extract_table_identity(content, hierarchy)
            
            # Count rows/cols from markdown
            lines = [l for l in content.split('\n') if l.strip().startswith('|')]
            row_count = max(0, len(lines) - 1)  # Exclude header separator
            col_count = len(lines[0].split('|')) - 2 if lines else 0  # Exclude edge pipes
            
            # Check for structured data
            structured = chunk.get("structured_data")
            
            tables.append({
                "table_id": table_num or f"table_p{page}_{len(tables)+1}",
                "caption": table_caption or f"Table on page {page + 1}",
                "page_physical": page,
                "page_logical": page_logical,
                "bbox": bbox,
                "parent_section": parent_section,
                "hierarchy": hierarchy,
                "chunk_id": chunk_id,
                "row_count": row_count,
                "col_count": col_count,
                "has_structured_data": structured is not None,
            })
        
        elif content_type == "image_caption":
            # Extract figure number
            fig_match = re.match(
                r'(?:Figure|Fig\.?|Chart|Graph|Diagram|Map)\s*([\d.]+)',
                content, re.IGNORECASE
            )
            fig_num = f"fig_{fig_match.group(1)}" if fig_match else None
            
            figures.append({
                "figure_id": fig_num or f"fig_p{page}_{len(figures)+1}",
                "caption": content[:200],
                "page_physical": page,
                "page_logical": page_logical,
                "bbox": bbox,
                "parent_section": parent_section,
                "hierarchy": hierarchy,
                "chunk_id": chunk_id,
            })
    
    return {
        "tables": tables,
        "figures": figures,
        "total_tables": len(tables),
        "total_figures": len(figures),
    }


def _extract_table_identity(
    self, content: str, hierarchy: Dict
) -> Tuple[Optional[str], Optional[str]]:
    """Extract table number and caption from table content or context."""
    # Check first line for "Table X.X: Caption"
    first_line = content.split('\n')[0] if content else ""
    
    table_match = re.match(
        r'(?:\*\*)?(?:Table)\s*([\d.]+)\s*[:\-–]?\s*(.+?)(?:\*\*)?$',
        first_line, re.IGNORECASE
    )
    if table_match:
        return f"table_{table_match.group(1)}", table_match.group(2).strip()
    
    # Check hierarchy for table references
    for val in hierarchy.values():
        table_match = re.match(
            r'(?:Table)\s*([\d.]+)\s*[:\-–]?\s*(.+)',
            str(val), re.IGNORECASE
        )
        if table_match:
            return f"table_{table_match.group(1)}", table_match.group(2).strip()
    
    return None, None
```

### 5.2 Integration in `assemble_document`

After building `assembled_data` (line 171), before writing JSON:

```python
# P4-5: Build visual asset registry
assembled_data["visual_asset_registry"] = self._build_visual_asset_registry(
    assembled_data["child_chunks"],
    assembled_data["parent_chunks"],
)
print(f"  Visual assets: {assembled_data['visual_asset_registry']['total_tables']} tables, "
      f"{assembled_data['visual_asset_registry']['total_figures']} figures")
```

### 5.3 API layer mapping

Your backend API serving `fetchReportTables(reportId)` should read from `report_json["visual_asset_registry"]["tables"]` and map to the `TableItem` interface your frontend expects. Same for charts. This is an API-layer change, not pipeline.

---

## P4-6: Rotated Page Detection & Visual Subtype Classification

**Problem**: 90°-rotated landscape tables extract as garbage. Charts/photos/maps/flowcharts are all "image_caption" with no subtype.

**Files to modify**:
- `src/parsing_pipeline/layout_analysis_service.py` (or wherever Docling is invoked)
- `src/parsing_pipeline/content_extraction_service.py`

### 6.1 Rotated page detection

Add before layout analysis (where PDF pages are processed):

```python
import fitz  # PyMuPDF

def _detect_and_fix_rotation(self, pdf_path: str) -> Dict[int, int]:
    """
    Detect pages with non-zero rotation and return rotation map.
    Returns: {page_num: rotation_degrees}
    """
    rotations = {}
    doc = fitz.open(pdf_path)
    for page_num in range(len(doc)):
        page = doc[page_num]
        rotation = page.rotation
        if rotation != 0:
            rotations[page_num] = rotation
    doc.close()
    return rotations
```

In the layout analysis loop, before passing a page to Docling:

```python
# P4-6: Handle rotated pages
if page_num in rotation_map:
    # Rotate page to 0° before layout analysis
    page = doc[page_num]
    page.set_rotation(0)
    # Re-render for Docling
```

This is the simplest fix — rotate before analysis, not after.

### 6.2 Visual subtype classification (heuristic, no ML)

Add to `content_extraction_service.py`:

```python
VISUAL_SUBTYPE_KEYWORDS = {
    # From caption/context text
    "chart": ["chart", "graph", "trend", "bar chart", "pie chart", "line graph", "histogram"],
    "map": ["map", "geographical", "district-wise", "state-wise map", "location"],
    "flowchart": ["flow chart", "flowchart", "process flow", "workflow", "decision tree"],
    "diagram": ["diagram", "schematic", "structure", "organization", "org chart"],
    "photo": ["photograph", "photo", "image of", "construction site", "physical verification"],
    "table_as_image": ["table", "statement", "annexure"],
}

def _classify_visual_subtype(
    self, caption: str, hierarchy: Dict, layout_label: str
) -> str:
    """
    Classify a visual element's subtype based on caption and context.
    Returns: "chart" | "map" | "flowchart" | "diagram" | "photo" | "data_visualization" | "unknown"
    """
    context = (caption + " " + " ".join(str(v) for v in hierarchy.values())).lower()
    
    for subtype, keywords in self.VISUAL_SUBTYPE_KEYWORDS.items():
        if any(kw in context for kw in keywords):
            return subtype
    
    # Fallback: if layout_label is "Figure" it's more likely a chart/diagram
    # If "Picture" it's more likely a photo
    if layout_label == "Figure":
        return "data_visualization"
    elif layout_label == "Picture":
        return "photo"
    
    return "unknown"
```

Store `visual_subtype` in the chunk metadata during extraction. This flows through to the visual asset registry automatically.

---

## P4-7: Validation Updates

**Files to modify**: `src/core/validation_service.py`

### Add validation methods for new Phase 4 features:

```python
def _validate_recommendations(self, enrichment: Dict) -> Dict[str, Any]:
    """Check recommendation extraction quality."""
    recs = enrichment.get("recommendations", [])
    if not recs:
        return {"status": "EMPTY", "total": 0}
    
    by_strategy = {}
    for r in recs:
        # If we stored extraction_strategy, count it
        strategy = r.get("extraction_strategy", "unknown")
        by_strategy[strategy] = by_strategy.get(strategy, 0) + 1
    
    orphan = sum(1 for r in recs if not r.get("related_finding_ids"))
    no_target = sum(1 for r in recs if not r.get("target_entity"))
    
    return {
        "total": len(recs),
        "by_strategy": by_strategy,
        "orphan_count": orphan,
        "no_target_entity": no_target,
        "status": "OK" if len(recs) > 0 else "EMPTY",
    }


def _validate_exec_summary(self, enrichment: Dict) -> Dict[str, Any]:
    """Check executive summary parsing quality."""
    index = enrichment.get("executive_summary_index")
    if not index:
        return {"status": "NOT_FOUND"}
    
    return {
        "total_items": index.get("total_items", 0),
        "total_citations": index.get("total_citations", 0),
        "resolved_count": index.get("resolved_count", 0),
        "resolution_rate": index.get("resolution_rate", 0),
        "status": "OK" if index.get("resolution_rate", 0) > 0.5 else "LOW_RESOLUTION",
    }


def _validate_visual_registry(self, report_data: Dict) -> Dict[str, Any]:
    """Check visual asset registry completeness."""
    registry = report_data.get("visual_asset_registry", {})
    tables = registry.get("tables", [])
    figures = registry.get("figures", [])
    
    # Check for tables without captions
    no_caption_tables = sum(1 for t in tables if "page" in (t.get("caption") or ""))
    
    return {
        "total_tables": len(tables),
        "total_figures": len(figures),
        "tables_without_caption": no_caption_tables,
        "status": "OK" if tables or figures else "EMPTY",
    }


def _validate_footnotes(self, report_data: Dict) -> Dict[str, Any]:
    """Check footnote capture."""
    footnotes = report_data.get("footnote_index", [])
    return {
        "total_footnotes": len(footnotes),
        "status": "OK" if footnotes else "NONE_FOUND",
    }
```

---

## Summary: Files Changed/Created

### New files (2):
| File | Purpose |
|------|---------|
| `src/enrichment/recommendation_extractor.py` | P4-3: Multi-strategy recommendation extraction |
| `src/enrichment/executive_summary_parser.py` | P4-4: Exec summary → paragraph citation index |

### Modified files (5):
| File | Changes |
|------|---------|
| `src/core/data_contracts.py` | `footnote` content_type, `executive_summary_index` + `box_elements` on SemanticEnrichment |
| `src/parsing_pipeline/content_extraction_service.py` | P4-1: footnote extractor, P4-6: visual subtype classifier |
| `src/enrichment/semantic_enrichment_service.py` | P4-2: box detection, P4-3: new rec extractor integration, P4-4: exec summary call |
| `src/parsing_pipeline/assembly_service.py` | P4-5: visual asset registry builder, P4-1: footnote index |
| `src/core/validation_service.py` | P4-7: rec quality, exec summary, visual registry, footnote checks |

### Touched but minimal:
| File | Changes |
|------|---------|
| `src/parsing_pipeline/layout_analysis_service.py` | P4-6: rotation detection (5-10 lines) |

---

## Generalisation Scorecard

| Feature | CAG-specific? | Works on other docs? |
|---------|--------------|---------------------|
| Footnote capture | No | Any PDF with Docling Footnote labels |
| Box X.X detection | No | World Bank, EU audit, OECD reports all use numbered boxes |
| Multi-strategy rec extraction | Minimal | Verb patterns universal; section detection uses configurable `section_type_patterns` |
| Exec summary citation parser | Pattern is generic | `(Paragraph X.X)` format used in government/legal docs globally |
| Visual asset registry | No | Any document with tables/figures |
| Rotation detection | No | Any landscape PDF page |
| Visual subtype classification | No | Keyword-based, works on any document |

**CAG-specific elements** (confined to regex patterns, easily swapped):
- `GoI/NHAI/FCI/CBDT` in target entity patterns (P4-3)
- `"What the Performance Audit report says"` in exec summary section patterns (P4-4)

These are in lists, not logic. Adding a new document type = adding patterns to lists.

---

## Validation Criteria

Run diagnostics on all 14 reports. Phase 4 passes when:

| Metric | Target |
|--------|--------|
| Recommendations extracted | >90% recall vs manual count on 5 sample reports |
| Exec summary found | In ≥12/14 reports |
| Citation resolution rate | >60% of (Paragraph X.X) citations resolved to chunk IDs |
| Footnotes captured | >0 in reports that have them |
| Visual registry populated | 100% of reports have tables/figures listed |
| Box elements detected | >0 in reports with "Box X.X" patterns |
| No regression in RAG readiness score | ≥91.6 average (current baseline) |
