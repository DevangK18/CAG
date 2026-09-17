# P3-4: Confidence Propagation - Implementation Summary

**Status:** ✅ COMPLETED (2026-02-14)
**Tests:** 20/20 passing (100%)
**Cost:** $0.00 (algorithmic only)

## Overview

Implemented composite confidence scoring for all child chunks, combining layout confidence, TOC quality, and content quality heuristics. This provides a quantitative measure of extraction reliability for downstream filtering and quality assessment.

## What Was Implemented

### 1. Data Model Extension

**File:** `src/core/data_contracts.py`

Added `extraction_confidence` field to `ChildChunk` model:

```python
# P3-4: Composite extraction confidence (line ~137)
extraction_confidence: Optional[float] = Field(
    default=None,
    description="Composite confidence (0-1) combining layout, TOC, and enrichment quality"
)
```

### 2. Confidence Computation Method

**File:** `src/parsing_pipeline/modules/assembly_service.py` (lines 323-391)

Created `_compute_chunk_confidence()` method with weighted composite scoring:

**Formula:**
```
composite_confidence = (layout_score × 0.4) + (toc_score × 0.3) + (content_score × 0.3)
```

**Factors:**

1. **Layout Confidence (40% weight)**
   - Source: Docling layout detection confidence
   - Default: 0.5 if unavailable
   - Capped at 1.0

2. **TOC Quality (30% weight)**
   - Source: Scaffolding service TOC quality score
   - Normalized: score / 100.0
   - Capped at 1.0

3. **Content Quality (30% weight)**
   - Base score: 1.0
   - Applies multiplicative penalties:
     - Short content (<20 chars): ×0.5
     - High number-to-word ratio (>2): ×0.7 (table fragments)
     - Generic image captions: ×0.3
     - Orphan assignment (>50 page span): ×0.6

**Output:** Float rounded to 3 decimal places (0.000-1.000)

### 3. Pipeline Integration

**File:** `src/parsing_pipeline/modules/assembly_service.py` (lines 196-201)

Integrated confidence computation into the assembly pipeline:

```python
# Extract TOC quality from scaffold
toc_quality = 75.0  # Default
if task.scaffold and isinstance(task.scaffold, dict):
    toc_quality = task.scaffold.get("toc_quality_score", 75.0)

# Compute confidence for all child chunks
for chunk in assembled_data["child_chunks"]:
    chunk["extraction_confidence"] = self._compute_chunk_confidence(
        chunk, assembled_data["parent_chunks"], toc_quality
    )
```

### 4. Comprehensive Testing

**File:** `tests/parsing_pipeline/unit/test_confidence_computation_unit.py` (330 lines, 20 tests)

**Test Categories:**
- **Layout confidence tests (3)**: High/low/missing layout confidence
- **TOC quality tests (3)**: High/low/capped TOC quality
- **Content quality tests (6)**: Short content, table fragments, image captions, orphan assignment
- **Composite scoring tests (3)**: Perfect/poor scores, rounding
- **Edge cases (5)**: Empty content, no parent, parent not found, invalid page range, compound penalties

## Key Features

### Content Quality Heuristics

1. **Short Content Detection**
   - Penalty: ×0.5
   - Threshold: <20 characters
   - Rationale: Very short chunks likely extraction artifacts

2. **Table Fragment Detection**
   - Penalty: ×0.7
   - Threshold: Number-to-word ratio >2
   - Rationale: High numeric density suggests table fragments misclassified as paragraphs

3. **Generic Image Caption Detection**
   - Penalty: ×0.3
   - Patterns: "the image shows", "black background", "logo and text"
   - Rationale: Generic Florence-2 captions have low semantic value

4. **Orphan Assignment Detection**
   - Penalty: ×0.6
   - Threshold: Parent chunk spans >50 pages
   - Rationale: Wide parent span indicates possible misassignment

### Composite Scoring Examples

| Scenario | Layout | TOC | Content | Composite | Interpretation |
|----------|--------|-----|---------|-----------|----------------|
| Perfect extraction | 1.0 | 1.0 | 1.0 | 1.0 | High confidence |
| Good extraction | 0.95 | 0.8 | 1.0 | 0.92 | Very reliable |
| Short content | 0.5 | 0.8 | 0.5 | 0.59 | Moderate confidence |
| Table fragment | 0.5 | 0.8 | 0.7 | 0.65 | Moderate confidence |
| Generic caption | 0.5 | 0.8 | 0.3 | 0.53 | Low confidence |
| Poor all around | 0.2 | 0.3 | 0.5 | 0.32 | Very low confidence |

## Impact

### Quality Assessment
- **Enables filtering**: Downstream services can filter chunks by confidence threshold
- **Quality metrics**: Corpus-level statistics on extraction quality
- **Debugging aid**: Identifies problematic chunks for investigation

### Use Cases

1. **RAG retrieval filtering**: Exclude low-confidence chunks from search results
2. **QA prioritization**: Focus manual QA on low-confidence chunks
3. **Re-extraction targeting**: Identify chunks that need re-processing
4. **Corpus statistics**: Report-level quality metrics (e.g., "87% of chunks >0.7 confidence")

## Example Output

```json
{
  "chunk_id": "chunk_123",
  "content": "The audit observed irregularities in procurement...",
  "content_type": "paragraph",
  "extraction_confidence": 0.852,
  "metadata": {
    "extraction": {
      "layout_confidence": 0.92
    }
  },
  "parent_chunk_id": "parent_45"
}
```

## Statistics

- **Lines of code**: 68 (computation method) + 5 (integration) = 73 lines
- **Test coverage**: 330 lines, 20 tests (100% passing)
- **Performance**: O(1) per chunk, negligible overhead
- **Cost**: $0.00 (algorithmic only, no API calls)

## Files Created

- `tests/parsing_pipeline/unit/test_confidence_computation_unit.py` (330 lines)

## Files Modified

- `src/core/data_contracts.py` (+4 lines: field definition)
- `src/parsing_pipeline/modules/assembly_service.py` (+73 lines: method + integration)

## Next Steps

### Immediate
- ✅ P3-4 COMPLETE

### Future Enhancements
- **Adaptive thresholds**: Learn optimal thresholds per report type
- **ML-based scoring**: Train model on manual QA labels
- **Feature expansion**: Add more heuristics (e.g., OCR character confidence, table cell count)

---

**Implementation Date:** 2026-02-14
**Implemented By:** Claude Sonnet 4.5
**Associated Plan:** `/docs/plans/phase3_plan.md` (P3-4 specification)
