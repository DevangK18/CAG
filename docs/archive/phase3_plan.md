# Phase 3: Semantic Quality & Cross-Chunk Intelligence

## Execution Order

```
P3-1  Entity Extraction Hardening         (standalone, no deps)
P3-2  Image Caption Replacement            (standalone, no deps)
P3-3  Temporal Metadata Extraction         (standalone, no deps)
P3-4  Confidence Propagation               (needs: data_contracts changes first)
P3-5  Annexure-Finding Linking             (needs: P3-3 temporal fields, P3-4 confidence fields)
P3-6  Cross-Chunk Reference Resolution     (needs: P3-5 linking infra)
P3-7  Validation Service Expansion         (needs: all above, runs last)
```

Recommended parallel tracks:
- **Track A**: P3-1 → P3-5 → P3-6
- **Track B**: P3-2 + P3-3 + P3-4 (independent)
- **Track C**: P3-7 (after all others merge)

---

## P3-1: Entity Extraction Hardening

**Problem**: `([\w\s]+(?:Corporation|Authority|Board|Commission|Council))` matches sentence fragments like "the aforementioned Corporation" or "said that the Municipal Corporation". Current len cap is 100 chars (line 931) — far too generous.

**Files to modify**:
- `src/enrichment/semantic_enrichment_service.py`

### 1.1 Replace ENTITY_PATTERNS (lines 363-377)

```python
ENTITY_PATTERNS = {
    "schemes": [
        # Require capital letter start, cap at 60 chars
        r"(?:the\s+)?([A-Z][\w\s]{2,55}(?:Scheme|Programme|Program|Mission|Yojana|Abhiyan))",
        r"(?:under\s+(?:the\s+)?)([A-Z][\w\s]{2,55}(?:Scheme|Programme|Program|Mission|Yojana))",
        # Explicit acronym-in-parens pattern: "Pradhan Mantri Gram Sadak Yojana (PMGSY)"
        r"([A-Z][\w\s]{5,55})\s*\([A-Z]{2,8}\)",
    ],
    "ministries": [
        r"(Ministry\s+of\s+[A-Z][\w\s&]{2,40}?)(?:\s*[\(\),\.]|$)",
        r"(Department\s+of\s+[A-Z][\w\s&]{2,40}?)(?:\s*[\(\),\.]|$)",
    ],
    "organizations": [
        r"((?:Indian\s+)?Railways?)",
        r"(INCOIS|ISRO|DRDO|CPWD|PWD|NHAI|ONGC|BHEL|SAIL|HAL|AAI|FCI)",
        # Require 2+ capitalized words before suffix, max 60 chars
        r"((?:[A-Z][a-z]+\s+){1,5}(?:Corporation|Authority|Board|Commission|Council))",
    ],
}
```

Key changes:
- `[A-Z]` start requirement eliminates fragments starting with lowercase/articles
- `{2,55}` / `{2,40}` caps replace the unbounded `[\w\s]+`
- Organization pattern requires capitalized words, not arbitrary `[\w\s]+`
- Added common CAG acronyms to the explicit list

### 1.2 Add entity post-processing filter (new method, after line 935)

```python
# Verb stems that indicate a captured sentence fragment, not an entity
ENTITY_REJECT_VERBS = {
    "was", "were", "is", "are", "has", "had", "have", "been",
    "said", "noted", "observed", "stated", "found", "reported",
    "recommended", "suggested", "directed", "instructed",
    "mentioned", "indicated", "revealed", "submitted",
    "failed", "did", "does", "could", "should", "would",
    "the", "that", "this", "which", "where", "when",
}

def _clean_entity(self, raw: str) -> Optional[str]:
    """
    Post-process a raw entity match. Returns None if garbage.
    """
    cleaned = " ".join(raw.split()).strip()

    # Length bounds
    if len(cleaned) < 4 or len(cleaned) > 60:
        return None

    # Must start with uppercase
    if not cleaned[0].isupper():
        return None

    # Reject if first word is a common verb/article (sentence fragment)
    first_word = cleaned.split()[0].lower()
    if first_word in self.ENTITY_REJECT_VERBS:
        return None

    # Reject if >6 words (likely a sentence fragment, not a proper name)
    if len(cleaned.split()) > 6:
        return None

    # Reject if contains sentence-ending punctuation mid-string
    if re.search(r'[.!?]\s+[A-Z]', cleaned):
        return None

    return cleaned
```

### 1.3 Update `_extract_entities` (line 911) to use filter

Replace the inner loop body (lines 926-932):

```python
for match in matches:
    if isinstance(match, tuple):
        match = match[0]
    cleaned = self._clean_entity(match)
    if cleaned:
        entities[entity_type].add(cleaned)
```

Same change in `_extract_entities_from_text` (lines 944-949).

### 1.4 Add entity deduplication by substring

After the per-type extraction loop in `_extract_entities`, add normalization:

```python
# Deduplicate: if "National Highways Authority" and "National Highways Authority of India"
# both exist, keep the longer one
for entity_type in entities:
    deduped = set()
    sorted_ents = sorted(entities[entity_type], key=len, reverse=True)
    for ent in sorted_ents:
        ent_lower = ent.lower()
        if not any(ent_lower in existing.lower() for existing in deduped):
            deduped.add(ent)
    entities[entity_type] = deduped
```

---

## P3-2: Image Caption Replacement

**Problem**: Florence-2 captions are generic visual descriptions ("black background with logo and text"). 100% useless for RAG.

**Solution**: Replace Florence-2 captions with **contextual captions** derived from surrounding chunks. No ML model change needed.

**Files to modify**:
- `src/enrichment/semantic_enrichment_service.py` (add method)
- `src/parsing_pipeline/assembly_service.py` (call it during assembly)

**Files to create**:
- `src/enrichment/contextual_caption_service.py`

### 2.1 Create `contextual_caption_service.py`

```python
"""
Contextual Caption Service: Replaces generic Florence-2 image captions
with semantically meaningful captions derived from document context.

Strategy:
1. Find the image chunk's position (page, bbox)
2. Look at surrounding text chunks (same page, ±1 page)
3. Look for explicit figure references ("as shown in Figure 3.1")
4. Build a caption from: section hierarchy + preceding paragraph + figure reference
"""

import re
from typing import List, Dict, Optional, Tuple


class ContextualCaptionService:

    # Patterns for explicit figure/chart references in body text
    FIGURE_REF_PATTERNS = [
        r"(?:as\s+)?(?:shown|depicted|illustrated|given|presented)\s+in\s+"
        r"(?:the\s+)?(?:Figure|Fig\.|Chart|Graph|Diagram|Map)\s*[\d.]+",
        r"(?:Figure|Fig\.|Chart|Graph|Diagram|Map)\s*[\d.]+\s+"
        r"(?:shows?|depicts?|illustrates?|presents?|gives?)\s+(.{10,120}?)(?:\.|$)",
        r"(?:refer|see)\s+(?:to\s+)?(?:Figure|Fig\.|Chart|Graph|Diagram|Map)\s*[\d.]+",
    ]

    # Patterns to extract figure number from caption text
    FIGURE_NUM_PATTERN = re.compile(
        r"(?:Figure|Fig\.|Chart|Graph|Diagram|Map)\s*([\d.]+)", re.IGNORECASE
    )

    GENERIC_CAPTION_INDICATORS = [
        "the image shows",
        "the image contains",
        "the image displays",
        "black background",
        "white background",
        "logo and text",
        "a table with",
        "a chart with",
    ]

    def __init__(self):
        self._ref_patterns = [
            re.compile(p, re.IGNORECASE) for p in self.FIGURE_REF_PATTERNS
        ]

    def is_generic_caption(self, caption: str) -> bool:
        """Check if a caption is a generic Florence-2 description."""
        caption_lower = caption.lower().strip()
        return any(indicator in caption_lower for indicator in self.GENERIC_CAPTION_INDICATORS)

    def generate_contextual_caption(
        self,
        image_chunk: Dict,
        all_chunks: List[Dict],
        parent_chunks: List[Dict],
    ) -> str:
        """
        Generate a contextual caption for an image chunk.

        Returns: New caption string, or original if context insufficient.
        """
        original_caption = image_chunk.get("content", "")
        image_page = image_chunk.get("source_page_physical", -1)
        image_bbox = image_chunk.get("metadata", {}).get("location", {}).get("bbox", [])
        image_y = image_bbox[1] if len(image_bbox) >= 2 else 0

        # Step 1: Get section context from hierarchy
        hierarchy = image_chunk.get("hierarchy", {})
        section_context = " > ".join(
            hierarchy[k] for k in sorted(hierarchy.keys()) if hierarchy[k]
        )

        # Step 2: Find text chunks on same page, sorted by Y position
        same_page_chunks = [
            c for c in all_chunks
            if c.get("source_page_physical") == image_page
            and c.get("content_type") in ("paragraph", "list", "header")
            and c.get("chunk_id") != image_chunk.get("chunk_id")
        ]
        same_page_chunks.sort(
            key=lambda c: c.get("metadata", {}).get("location", {}).get("bbox", [0, 0])[1]
        )

        # Step 3: Find the closest preceding text chunk
        preceding_text = ""
        for chunk in reversed(same_page_chunks):
            chunk_bbox = chunk.get("metadata", {}).get("location", {}).get("bbox", [0, 9999])
            if chunk_bbox[1] < image_y:
                preceding_text = chunk.get("content", "")[:200]
                break

        # Step 4: Check if the preceding text has a figure reference with description
        figure_description = self._extract_figure_description(preceding_text)

        # Step 5: Also check the chunk immediately after the image
        following_text = ""
        for chunk in same_page_chunks:
            chunk_bbox = chunk.get("metadata", {}).get("location", {}).get("bbox", [0, 0])
            if chunk_bbox[1] > image_y:
                following_text = chunk.get("content", "")[:200]
                break

        # Step 6: Also scan ±1 page for figure references
        if not figure_description:
            nearby_chunks = [
                c for c in all_chunks
                if abs(c.get("source_page_physical", -99) - image_page) <= 1
                and c.get("content_type") == "paragraph"
            ]
            for c in nearby_chunks:
                desc = self._extract_figure_description(c.get("content", ""))
                if desc:
                    figure_description = desc
                    break

        # Step 7: Build contextual caption
        parts = []

        if section_context:
            parts.append(f"[{section_context}]")

        if figure_description:
            parts.append(figure_description)
        elif preceding_text:
            # Use first sentence of preceding paragraph as context
            first_sentence = re.split(r'(?<=[.!?])\s+', preceding_text)[0]
            if len(first_sentence) > 20:
                parts.append(f"Visual related to: {first_sentence}")

        if not parts:
            # Last resort: keep original but tag it
            return f"[Image in {section_context or 'document'}] {original_caption}"

        return " ".join(parts)

    def _extract_figure_description(self, text: str) -> Optional[str]:
        """Extract figure description from text that references a figure."""
        for pattern in self._ref_patterns:
            match = pattern.search(text)
            if match:
                # If the pattern captured a description group, use it
                if match.lastindex and match.lastindex >= 1:
                    return match.group(1).strip()
                # Otherwise return the full match as context
                return match.group(0).strip()
        return None

    def replace_generic_captions(
        self,
        child_chunks: List[Dict],
        parent_chunks: List[Dict],
    ) -> Tuple[int, int]:
        """
        Batch-replace generic captions across all child chunks.
        Modifies child_chunks in place.

        Returns: (total_images, replaced_count)
        """
        image_chunks = [
            c for c in child_chunks
            if c.get("content_type") == "image_caption"
        ]
        replaced = 0

        for img in image_chunks:
            if self.is_generic_caption(img.get("content", "")):
                new_caption = self.generate_contextual_caption(
                    img, child_chunks, parent_chunks
                )
                img["content"] = new_caption
                img["_caption_source"] = "contextual"  # Track provenance
                replaced += 1

        return len(image_chunks), replaced
```

### 2.2 Integration point in `assembly_service.py`

In `assemble_document` (line 135), after building `assembled_data` but before `_write_json`, add:

```python
# P3-2: Replace generic image captions with contextual ones
from src.enrichment.contextual_caption_service import ContextualCaptionService
caption_service = ContextualCaptionService()
total_images, replaced = caption_service.replace_generic_captions(
    assembled_data["child_chunks"],
    assembled_data["parent_chunks"],
)
if replaced > 0:
    print(f"  P3-2: Replaced {replaced}/{total_images} generic image captions")
```

---

## P3-3: Temporal Metadata Extraction

**Problem**: Only `report_year` exists. No audit period, no reference years, no temporal range per finding.

**Files to modify**:
- `src/core/data_contracts.py` (new fields)
- `src/enrichment/semantic_enrichment_service.py` (extraction logic)
- `src/parsing_pipeline/assembly_service.py` (writeback)

**Files to create**:
- `src/enrichment/temporal_extractor.py`

### 3.1 New data contract fields

Add to `ChildChunk` (after line 130):
```python
# P3-3: Temporal metadata
temporal_references: Optional[List[Dict[str, Any]]] = Field(
    default=None,
    description="Extracted temporal references: [{type, start_year, end_year, raw_text}]"
)
```

Add to `Finding` (after line 219):
```python
# P3-3: Temporal context for the finding
audit_period: Optional[Dict[str, int]] = Field(
    default=None,
    description="{'start_year': 2019, 'end_year': 2023} - period the finding covers"
)
reference_years: List[int] = Field(
    default_factory=list,
    description="All years explicitly mentioned in the finding text"
)
```

Add to `SemanticEnrichment` (after line 283):
```python
# P3-3: Document-level temporal metadata
temporal_coverage: Optional[Dict[str, Any]] = Field(
    default=None,
    description="{'audit_period': {start, end}, 'reference_years': [...], 'previous_audit_refs': [...]}"
)
```

### 3.2 Create `temporal_extractor.py`

```python
"""
Temporal Extractor: Extracts audit periods, reference years, and
temporal context from CAG report text.
"""

import re
from typing import List, Dict, Optional, Tuple, Any


class TemporalExtractor:

    # Audit period patterns (document-level, usually in introduction/scope)
    AUDIT_PERIOD_PATTERNS = [
        # "covering the period 2019-20 to 2022-23"
        r"(?:covering|for)\s+(?:the\s+)?period\s+(\d{4})[-–](\d{2,4})\s+to\s+(\d{4})[-–](\d{2,4})",
        # "during 2019-20 to 2022-23"
        r"during\s+(\d{4})[-–](\d{2,4})\s+to\s+(\d{4})[-–](\d{2,4})",
        # "from 2019-20 to 2022-23"
        r"from\s+(\d{4})[-–](\d{2,4})\s+to\s+(\d{4})[-–](\d{2,4})",
        # "for the years 2019-20 to 2022-23"
        r"(?:for|during)\s+(?:the\s+)?years?\s+(\d{4})[-–](\d{2,4})\s+to\s+(\d{4})[-–](\d{2,4})",
        # "period from April 2019 to March 2023"
        r"period\s+from\s+\w+\s+(\d{4})\s+to\s+\w+\s+(\d{4})",
    ]

    # Individual year-range patterns (chunk-level)
    YEAR_RANGE_PATTERN = re.compile(
        r"(\d{4})[-–](\d{2,4})", re.IGNORECASE
    )

    # Standalone year
    YEAR_PATTERN = re.compile(r"\b((?:19|20)\d{2})\b")

    # Previous audit references
    PREVIOUS_AUDIT_PATTERNS = [
        r"(?:outstanding|pending)\s+(?:paras?|observations?|audit\s+observations?)\s+"
        r"(?:from|of|since)\s+(?:the\s+)?(?:year\s+)?(\d{4})",
        r"(?:earlier|previous|prior)\s+(?:audit|report)\s+(?:of|for|in)\s+(\d{4})",
        r"(?:Report\s+No\.?\s*\d+\s+of\s+)(\d{4})",
        r"(?:ATN|Action\s+Taken\s+Note).*?(\d{4})",
    ]

    def __init__(self):
        self._audit_period_patterns = [
            re.compile(p, re.IGNORECASE) for p in self.AUDIT_PERIOD_PATTERNS
        ]
        self._prev_audit_patterns = [
            re.compile(p, re.IGNORECASE) for p in self.PREVIOUS_AUDIT_PATTERNS
        ]

    def _normalize_fy_year(self, base: str, suffix: str) -> int:
        """Convert '2019' + '20' → 2019, or '2019' + '2020' → 2019."""
        return int(base)

    def extract_audit_period(self, full_text: str) -> Optional[Dict[str, int]]:
        """
        Extract the document-level audit period from intro/scope text.

        Returns: {"start_year": 2019, "end_year": 2023} or None
        """
        for pattern in self._audit_period_patterns:
            match = pattern.search(full_text)
            if match:
                groups = match.groups()
                if len(groups) >= 4:
                    start_year = int(groups[0])
                    end_year = int(groups[2])
                    if 2000 <= start_year <= 2030 and 2000 <= end_year <= 2030:
                        return {"start_year": start_year, "end_year": end_year}
                elif len(groups) == 2:
                    start_year = int(groups[0])
                    end_year = int(groups[1])
                    if 2000 <= start_year <= 2030 and 2000 <= end_year <= 2030:
                        return {"start_year": start_year, "end_year": end_year}
        return None

    def extract_reference_years(self, text: str) -> List[int]:
        """Extract all years mentioned in a text block."""
        years = set()

        # Year ranges: "2019-20" → 2019
        for match in self.YEAR_RANGE_PATTERN.finditer(text):
            base = int(match.group(1))
            if 2000 <= base <= 2030:
                years.add(base)
                # Also add the end year
                suffix = match.group(2)
                if len(suffix) == 2:
                    end = int(str(base)[:2] + suffix)
                else:
                    end = int(suffix)
                if 2000 <= end <= 2030:
                    years.add(end)

        # Standalone years
        for match in self.YEAR_PATTERN.finditer(text):
            year = int(match.group(1))
            if 2000 <= year <= 2030:
                years.add(year)

        return sorted(years)

    def extract_previous_audit_refs(self, text: str) -> List[Dict[str, Any]]:
        """Extract references to previous audits/reports."""
        refs = []
        for pattern in self._prev_audit_patterns:
            for match in pattern.finditer(text):
                year = int(match.group(1))
                if 2000 <= year <= 2030:
                    refs.append({
                        "year": year,
                        "raw_text": match.group(0).strip()[:100],
                    })
        return refs

    def extract_temporal_metadata(
        self,
        child_chunks: List[Dict],
        section_classifications: Optional[List[Dict]] = None,
    ) -> Dict[str, Any]:
        """
        Extract document-level temporal coverage.

        Scans introduction/scope sections first for audit period,
        then aggregates all years across all chunks.

        Returns: {
            "audit_period": {"start_year": 2019, "end_year": 2023} or None,
            "reference_years": [2018, 2019, 2020, ...],
            "previous_audit_refs": [{"year": 2018, "raw_text": "..."}],
        }
        """
        # Priority: scan intro/scope sections for audit period
        intro_text = ""
        if section_classifications:
            intro_section_types = {"introduction", "audit_scope", "audit_objectives", "executive_summary"}
            intro_chunk_ids = {
                sc.get("chunk_id") or sc.get("section_title", "")
                for sc in section_classifications
                if sc.get("section_type") in intro_section_types
            }
            # Gather text from chunks whose parent matches intro sections
            for chunk in child_chunks:
                pid = chunk.get("parent_chunk_id", "")
                if pid in intro_chunk_ids:
                    intro_text += " " + chunk.get("content", "")
        else:
            # Fallback: use first 20 chunks
            for chunk in child_chunks[:20]:
                intro_text += " " + chunk.get("content", "")

        audit_period = self.extract_audit_period(intro_text)

        # If not found in intro, scan all chunks
        if not audit_period:
            full_text = " ".join(c.get("content", "") for c in child_chunks[:50])
            audit_period = self.extract_audit_period(full_text)

        # Aggregate all reference years
        all_years = set()
        all_prev_refs = []
        for chunk in child_chunks:
            content = chunk.get("content", "")
            all_years.update(self.extract_reference_years(content))
            all_prev_refs.extend(self.extract_previous_audit_refs(content))

        # Deduplicate previous refs by year
        seen_years = set()
        unique_refs = []
        for ref in all_prev_refs:
            if ref["year"] not in seen_years:
                seen_years.add(ref["year"])
                unique_refs.append(ref)

        return {
            "audit_period": audit_period,
            "reference_years": sorted(all_years),
            "previous_audit_refs": unique_refs,
        }

    def annotate_chunk_temporal(self, chunk: Dict) -> List[Dict[str, Any]]:
        """
        Extract temporal references for a single chunk.
        Returns list of {"type": "year_range"|"standalone_year", "start_year": X, "end_year": Y, "raw_text": ...}
        """
        content = chunk.get("content", "")
        refs = []

        for match in self.YEAR_RANGE_PATTERN.finditer(content):
            base = int(match.group(1))
            suffix = match.group(2)
            end = int(str(base)[:2] + suffix) if len(suffix) == 2 else int(suffix)
            if 2000 <= base <= 2030:
                refs.append({
                    "type": "year_range",
                    "start_year": base,
                    "end_year": end,
                    "raw_text": match.group(0),
                })

        return refs
```

### 3.3 Integration in `semantic_enrichment_service.py`

In `enrich_document` (after step 6, line 510), add:

```python
# 7. P3-3: Extract temporal metadata
from src.enrichment.temporal_extractor import TemporalExtractor
temporal_extractor = TemporalExtractor()
temporal_coverage = temporal_extractor.extract_temporal_metadata(
    child_chunks, [s.to_dict() for s in section_classifications]
)
print(f"  Temporal: audit_period={temporal_coverage.get('audit_period')}, "
      f"ref_years={len(temporal_coverage.get('reference_years', []))}")

# Annotate findings with temporal context
for finding in findings:
    finding.reference_years = temporal_extractor.extract_reference_years(finding.text)
    if temporal_coverage.get("audit_period"):
        finding.audit_period = temporal_coverage["audit_period"]
```

And in the `SemanticEnrichment` return (line 520), add:
```python
temporal_coverage=temporal_coverage,
```

### 3.4 Integration in `assembly_service.py`

In `_serialize_child_chunks` (line 229), add temporal field to chunk_dict:

```python
# P3-3: Add temporal references
"temporal_references": temporal_extractor.annotate_chunk_temporal(child.dict())
    if child.content_type == "paragraph" else None,
```

Better approach: do the temporal annotation in `assemble_document` as a batch pass over all child chunks before serialization, similar to caption replacement.

---

## P3-4: Confidence Propagation

**Problem**: Layout confidence, TOC quality, and enrichment confidence exist in isolation. Final JSON has no composite reliability score.

**Files to modify**:
- `src/core/data_contracts.py` (add `extraction_confidence` to ChildChunk)
- `src/parsing_pipeline/assembly_service.py` (compute composite score)

### 4.1 Add to `ChildChunk` (after line 130):

```python
# P3-4: Composite extraction confidence
extraction_confidence: Optional[float] = Field(
    default=None,
    description="Composite confidence (0-1) combining layout, TOC, and enrichment quality"
)
```

### 4.2 Create confidence computation in assembly

Add method to `AssemblyService`:

```python
def _compute_chunk_confidence(
    self,
    child: Dict,
    parent_chunks: List[Dict],
    toc_quality_score: float,
) -> float:
    """
    Compute composite confidence for a child chunk.

    Factors:
    1. Layout confidence (from Docling): weight 0.4
    2. TOC quality (document-level): weight 0.3
    3. Content quality heuristic: weight 0.3

    Returns: float 0.0-1.0
    """
    # Factor 1: Layout confidence
    layout_conf = child.get("metadata", {}).get("extraction", {}).get(
        "layout_confidence", None
    )
    if layout_conf is None:
        layout_score = 0.5  # Unknown = neutral
    else:
        layout_score = min(1.0, layout_conf)

    # Factor 2: TOC quality (normalized to 0-1)
    toc_score = min(1.0, toc_quality_score / 100.0)

    # Factor 3: Content quality heuristic
    content = child.get("content", "")
    content_score = 1.0

    # Penalize very short content
    if len(content.strip()) < 20:
        content_score *= 0.5

    # Penalize high ratio of numbers to words (likely table fragment)
    words = re.findall(r'[a-zA-Z]{2,}', content)
    numbers = re.findall(r'\d+', content)
    if numbers and len(numbers) > len(words) * 2:
        content_score *= 0.7

    # Penalize image captions that are still generic
    if child.get("content_type") == "image_caption":
        if any(ind in content.lower() for ind in ["the image shows", "black background"]):
            content_score *= 0.3

    # Penalize orphan-like assignment (parent has very wide page range)
    parent_id = child.get("parent_chunk_id")
    if parent_id:
        parent = next((p for p in parent_chunks if p.get("chunk_id") == parent_id), None)
        if parent:
            page_range = parent.get("page_range_physical", [0, 0])
            if isinstance(page_range, (list, tuple)) and len(page_range) == 2:
                span = page_range[1] - page_range[0]
                if span > 50:  # Parent covers 50+ pages = likely poor assignment
                    content_score *= 0.6

    # Weighted composite
    composite = (
        layout_score * 0.4
        + toc_score * 0.3
        + content_score * 0.3
    )

    return round(composite, 3)
```

### 4.3 Call in `assemble_document`

After building `assembled_data`, add batch confidence computation:

```python
# P3-4: Compute extraction confidence for all chunks
toc_quality = task.scaffold.get("toc_quality_score", 75.0) if task.scaffold else 75.0
for chunk in assembled_data["child_chunks"]:
    chunk["extraction_confidence"] = self._compute_chunk_confidence(
        chunk, assembled_data["parent_chunks"], toc_quality
    )
```

This requires `toc_quality_score` to be stored in the scaffold during TOC extraction. Add to `IntelligentTOCService.extract_toc` return path — store `metrics.score()` in the task scaffold.

---

## P3-5: Annexure-Finding Linking

**Problem**: Annexures are just TOC sections. No link from "Details in Annexure-A" to the actual annexure content.

**Files to create**:
- `src/enrichment/annexure_linker.py`

**Files to modify**:
- `src/enrichment/semantic_enrichment_service.py` (call it)
- `src/core/data_contracts.py` (add link fields)

### 5.1 Add to `SemanticEnrichment` (after `entities` field):

```python
# P3-5: Annexure-finding links
annexure_links: List[Dict[str, Any]] = Field(
    default_factory=list,
    description="Links from findings/paragraphs to annexure sections"
)
```

### 5.2 Create `annexure_linker.py`

```python
"""
Annexure Linker: Identifies references to annexures/appendices in body text
and creates bidirectional links between findings and their supporting annexure data.
"""

import re
from typing import List, Dict, Tuple, Optional


class AnnexureLinker:

    # Patterns to detect annexure references in body text
    ANNEXURE_REF_PATTERNS = [
        # "Details are given in Annexure-A" / "Annexure-I" / "Annexure 3.1"
        r"(?:details?\s+(?:are\s+)?(?:given|provided|shown|placed)\s+(?:in|at)\s+)"
        r"(Annexure[-\s]*[A-Z0-9][\w.-]*)",
        # "as per Annexure-A" / "vide Annexure-II"
        r"(?:as\s+per|vide|refer|see)\s+(Annexure[-\s]*[A-Z0-9][\w.-]*)",
        # "(Annexure-A)" in parentheses
        r"\((Annexure[-\s]*[A-Z0-9][\w.-]*)\)",
        # Same patterns for Appendix
        r"(?:details?\s+(?:are\s+)?(?:given|provided|shown|placed)\s+(?:in|at)\s+)"
        r"(Appendix[-\s]*[A-Z0-9][\w.-]*)",
        r"(?:as\s+per|vide|refer|see)\s+(Appendix[-\s]*[A-Z0-9][\w.-]*)",
        r"\((Appendix[-\s]*[A-Z0-9][\w.-]*)\)",
    ]

    def __init__(self):
        self._ref_patterns = [
            re.compile(p, re.IGNORECASE) for p in self.ANNEXURE_REF_PATTERNS
        ]

    def _normalize_annexure_id(self, raw: str) -> str:
        """Normalize 'Annexure - A', 'Annexure-A', 'ANNEXURE A' → 'annexure_a'."""
        cleaned = raw.strip().lower()
        cleaned = re.sub(r'[\s-]+', '_', cleaned)
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
            "target_annexure_id": "annexure_a",
            "target_parent_chunk_id": "...",
            "reference_text": "Details are given in Annexure-A",
            "finding_id": "..." (if source is a finding),
        }]
        """
        annexure_index = self._find_annexure_parents(parent_chunks)
        if not annexure_index:
            return []

        links = []
        finding_chunk_ids = {f.get("source_chunk_id") for f in findings if f.get("source_chunk_id")}

        for chunk in child_chunks:
            content = chunk.get("content", "")
            chunk_id = chunk.get("chunk_id", "")

            for pattern in self._ref_patterns:
                for match in pattern.finditer(content):
                    annexure_ref = match.group(1)
                    norm_ref = self._normalize_annexure_id(annexure_ref)

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
```

### 5.3 Integration in `semantic_enrichment_service.py`

After evidence linking (step 5, line 506), add:

```python
# 5b. P3-5: Link findings to annexures
from src.enrichment.annexure_linker import AnnexureLinker
annexure_linker = AnnexureLinker()
annexure_links = annexure_linker.link_annexures(
    child_chunks, parent_chunks,
    [f.to_dict() for f in findings]
)
resolved = sum(1 for l in annexure_links if l["resolved"])
print(f"  Annexure links: {len(annexure_links)} references, {resolved} resolved")
```

Add `annexure_links=annexure_links` to the SemanticEnrichment return.

---

## P3-6: Cross-Chunk Reference Resolution

**Problem**: "As discussed in Para 3.2.1 above" has no actual link to the chunk containing Para 3.2.1.

**Files to create**:
- `src/enrichment/cross_reference_resolver.py`

**Files to modify**:
- `src/enrichment/semantic_enrichment_service.py` (call it)
- `src/core/data_contracts.py` (add cross_references to SemanticEnrichment)

### 6.1 Add to `SemanticEnrichment`:

```python
# P3-6: Cross-chunk references
cross_references: List[Dict[str, Any]] = Field(
    default_factory=list,
    description="Resolved cross-chunk references (para refs, section refs, table refs)"
)
```

### 6.2 Create `cross_reference_resolver.py`

```python
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
                index[key] = {
                    "chunk_id": parent.get("chunk_id"),
                    "chunk_type": "parent",
                    "toc_entry": toc_entry[:80],
                    "page": parent.get("page_range_physical", [0])[0],
                }

            # Index chapter headings
            chapter_match = re.match(
                r"Chapter\s+([IVXivx]+|\d+)", toc_entry, re.IGNORECASE
            )
            if chapter_match:
                chapter_id = chapter_match.group(1).lower()
                index[f"chapter_{chapter_id}"] = {
                    "chunk_id": parent.get("chunk_id"),
                    "chunk_type": "parent",
                    "toc_entry": toc_entry[:80],
                    "page": parent.get("page_range_physical", [0])[0],
                }

        # Index table chunks
        for child in child_chunks:
            if child.get("content_type") == "table_markdown":
                content = child.get("content", "")
                # Try to extract table number from content or hierarchy
                hierarchy = child.get("hierarchy", {})
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
```

### 6.3 Integration

In `enrich_document`, after annexure linking:

```python
# 8. P3-6: Resolve cross-chunk references
from src.enrichment.cross_reference_resolver import CrossReferenceResolver
xref_resolver = CrossReferenceResolver()
cross_references = xref_resolver.resolve_references(child_chunks, parent_chunks)
resolved_xrefs = sum(1 for x in cross_references if x["resolved"])
print(f"  Cross-references: {len(cross_references)} found, {resolved_xrefs} resolved")
```

Add `cross_references=cross_references` to SemanticEnrichment return.

---

## P3-7: Validation Service Expansion

**Problem**: ValidationService only checks hierarchy, page order, TOC, metadata, and garbage. It doesn't validate any of the semantic enrichment quality.

**File to modify**: `src/core/validation_service.py`

### 7.1 Add new validation methods

```python
def _validate_entity_quality(self, enrichment: Dict) -> Dict[str, Any]:
    """
    Check entity extraction quality.
    Detects: too-long entities, duplicates, sentence fragments, low-count types.
    """
    entities = enrichment.get("entities", {})
    if not entities:
        return {"status": "EMPTY", "total_entities": 0, "issues": []}

    issues = []
    total = sum(len(v) for v in entities.values())

    for entity_type, entity_list in entities.items():
        # Check for suspiciously long entities (>60 chars = likely fragment)
        long_entities = [e for e in entity_list if len(e) > 60]
        if long_entities:
            issues.append({
                "type": "long_entity",
                "entity_type": entity_type,
                "count": len(long_entities),
                "examples": [e[:80] for e in long_entities[:3]],
            })

        # Check for entities starting with lowercase (should be zero after P3-1)
        lowercase_starts = [e for e in entity_list if e and e[0].islower()]
        if lowercase_starts:
            issues.append({
                "type": "lowercase_entity",
                "entity_type": entity_type,
                "count": len(lowercase_starts),
                "examples": lowercase_starts[:3],
            })

        # Check for near-duplicates (substring containment)
        for i, e1 in enumerate(entity_list):
            for e2 in entity_list[i+1:]:
                if e1.lower() in e2.lower() or e2.lower() in e1.lower():
                    issues.append({
                        "type": "near_duplicate",
                        "entity_type": entity_type,
                        "entities": [e1, e2],
                    })
                    break

    noise_rate = len(issues) / max(total, 1) * 100

    return {
        "total_entities": total,
        "by_type": {k: len(v) for k, v in entities.items()},
        "issues": issues[:20],
        "noise_rate": round(noise_rate, 2),
        "status": "OK" if noise_rate < 10 else "WARNING" if noise_rate < 25 else "CRITICAL",
    }


def _validate_finding_quality(self, enrichment: Dict) -> Dict[str, Any]:
    """
    Check finding/recommendation extraction quality.
    Detects: zero findings, low confidence, missing monetary values, orphan recommendations.
    """
    findings = enrichment.get("findings", [])
    recommendations = enrichment.get("recommendations", [])

    if not findings and not recommendations:
        return {"status": "EMPTY", "total_findings": 0, "total_recommendations": 0}

    issues = []

    # Check findings
    low_confidence = [f for f in findings if f.get("confidence", 0) < 0.3]
    no_monetary = [f for f in findings if not f.get("monetary_values")]
    no_type = [f for f in findings if f.get("finding_type") == "other"]

    if low_confidence:
        issues.append({
            "type": "low_confidence_findings",
            "count": len(low_confidence),
            "pct": round(len(low_confidence) / max(len(findings), 1) * 100, 1),
        })

    if len(no_type) > len(findings) * 0.5:
        issues.append({
            "type": "untyped_findings",
            "count": len(no_type),
            "pct": round(len(no_type) / max(len(findings), 1) * 100, 1),
        })

    # Check recommendations
    orphan_recs = [r for r in recommendations if not r.get("related_finding_ids")]
    if orphan_recs and len(orphan_recs) > len(recommendations) * 0.5:
        issues.append({
            "type": "orphan_recommendations",
            "count": len(orphan_recs),
            "pct": round(len(orphan_recs) / max(len(recommendations), 1) * 100, 1),
        })

    return {
        "total_findings": len(findings),
        "total_recommendations": len(recommendations),
        "low_confidence_findings": len(low_confidence),
        "untyped_findings": len(no_type),
        "orphan_recommendations": len(orphan_recs) if recommendations else 0,
        "issues": issues,
        "status": "OK" if len(issues) == 0 else "WARNING" if len(issues) < 3 else "CRITICAL",
    }


def _validate_caption_quality(self, children: List[Dict]) -> Dict[str, Any]:
    """Check that generic Florence-2 captions have been replaced."""
    images = [c for c in children if c.get("content_type") == "image_caption"]
    if not images:
        return {"total_images": 0, "generic_count": 0, "status": "N/A"}

    generic_indicators = ["the image shows", "the image contains", "black background"]
    generic = [
        c for c in images
        if any(ind in c.get("content", "").lower() for ind in generic_indicators)
    ]

    generic_rate = len(generic) / len(images) * 100

    return {
        "total_images": len(images),
        "generic_count": len(generic),
        "contextual_count": len(images) - len(generic),
        "generic_rate": round(generic_rate, 2),
        "status": "OK" if generic_rate < 20 else "WARNING" if generic_rate < 50 else "CRITICAL",
    }


def _validate_cross_references(self, enrichment: Dict) -> Dict[str, Any]:
    """Check cross-reference resolution rate."""
    xrefs = enrichment.get("cross_references", [])
    annexure_links = enrichment.get("annexure_links", [])

    if not xrefs and not annexure_links:
        return {"status": "N/A", "total_refs": 0}

    resolved_xrefs = sum(1 for x in xrefs if x.get("resolved"))
    resolved_annexures = sum(1 for a in annexure_links if a.get("resolved"))

    total = len(xrefs) + len(annexure_links)
    total_resolved = resolved_xrefs + resolved_annexures
    resolution_rate = (total_resolved / total * 100) if total > 0 else 0

    return {
        "total_cross_refs": len(xrefs),
        "resolved_cross_refs": resolved_xrefs,
        "total_annexure_links": len(annexure_links),
        "resolved_annexure_links": resolved_annexures,
        "overall_resolution_rate": round(resolution_rate, 2),
        "status": "OK" if resolution_rate > 60 else "WARNING" if resolution_rate > 30 else "LOW",
    }


def _validate_temporal(self, enrichment: Dict) -> Dict[str, Any]:
    """Check temporal metadata extraction."""
    temporal = enrichment.get("temporal_coverage", {})
    if not temporal:
        return {"status": "MISSING", "has_audit_period": False}

    has_period = temporal.get("audit_period") is not None
    ref_years = len(temporal.get("reference_years", []))
    prev_refs = len(temporal.get("previous_audit_refs", []))

    return {
        "has_audit_period": has_period,
        "reference_year_count": ref_years,
        "previous_audit_ref_count": prev_refs,
        "status": "OK" if has_period and ref_years > 0 else "PARTIAL" if ref_years > 0 else "MISSING",
    }
```

### 7.2 Update `validate_report` to call new checks

Add a parameter for enrichment data and call new validators:

```python
def validate_report(
    self, report_data: Dict[str, Any], enrichment_data: Optional[Dict] = None
) -> Dict[str, Any]:
    # ... existing checks 1-6 ...

    # 7-11: Semantic enrichment checks (P3-7)
    enrichment = enrichment_data or {}
    entity_stats = self._validate_entity_quality(enrichment)
    finding_stats = self._validate_finding_quality(enrichment)
    caption_stats = self._validate_caption_quality(child_chunks)
    xref_stats = self._validate_cross_references(enrichment)
    temporal_stats = self._validate_temporal(enrichment)

    return {
        # ... existing fields ...
        "entity_quality": entity_stats,
        "finding_quality": finding_stats,
        "caption_quality": caption_stats,
        "cross_references": xref_stats,
        "temporal": temporal_stats,
    }
```

### 7.3 Update `run_baseline_diagnostics.py`

Add aggregate metrics for the new checks. Print corpus-level summary:

```
SEMANTIC ENRICHMENT QUALITY:
  Entity noise rate:         avg X% across N reports
  Finding confidence:        avg X% low-confidence
  Generic caption rate:      X/Y images still generic
  Cross-ref resolution:      X% resolved
  Temporal coverage:         N/M reports have audit period
```

### 7.4 Update scoring

Add semantic quality to overall score. Adjust weights:

```python
# Updated weights (Phase 3)
# Hierarchy: 35% (was 45%)
# Page Order: 10%
# TOC Quality: 20% (was 25%)
# Metadata: 10%
# Content Quality: 10%
# Semantic Quality: 15% (NEW)
```

Semantic quality score computed from:
- Entity noise rate (0-100): `max(0, 100 - noise_rate * 2)`
- Finding quality: `100 if issues == 0 else 70 if issues < 3 else 40`
- Caption quality: `max(0, 100 - generic_rate)`
- Weighted: `entity * 0.4 + finding * 0.3 + caption * 0.3`

---

## Summary: Files Changed/Created

### New files (4):
| File | Purpose |
|------|---------|
| `src/enrichment/contextual_caption_service.py` | P3-2: Replace generic image captions |
| `src/enrichment/temporal_extractor.py` | P3-3: Audit period & year extraction |
| `src/enrichment/annexure_linker.py` | P3-5: Finding→annexure linking |
| `src/enrichment/cross_reference_resolver.py` | P3-6: Para/table/section reference resolution |

### Modified files (4):
| File | Changes |
|------|---------|
| `src/core/data_contracts.py` | New fields: temporal_references, audit_period, reference_years, annexure_links, cross_references, extraction_confidence, temporal_coverage |
| `src/enrichment/semantic_enrichment_service.py` | P3-1: entity patterns + filter. Integration calls for P3-3, P3-5, P3-6 |
| `src/parsing_pipeline/assembly_service.py` | P3-2: caption replacement call. P3-4: confidence computation |
| `src/core/validation_service.py` | P3-7: 5 new validation methods + updated scoring weights |

### Diagnostic runner update (1):
| File | Changes |
|------|---------|
| `run_baseline_diagnostics.py` | P3-7: Load enrichment JSON, pass to validator, print semantic quality summary |

---

## Validation Criteria (run after implementation)

Run `run_baseline_diagnostics.py` on all 14 reports. Phase 3 passes when:

| Metric | Target | Current |
|--------|--------|---------|
| Entity noise rate | <10% | ~40-60% estimated |
| Generic caption rate | <30% | 100% |
| Cross-ref resolution rate | >50% | 0% (not tracked) |
| Temporal: reports with audit_period | >80% | 0% (not extracted) |
| Annexure links resolved | >60% | 0% (not tracked) |
| Average extraction_confidence populated | 100% | 0% |
| Overall RAG readiness (10-report avg) | >92 | 91.6 |
