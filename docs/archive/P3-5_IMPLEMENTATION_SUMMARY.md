# P3-5: Annexure-Finding Linking - Implementation Summary

**Status:** ✅ COMPLETED (2026-02-14)
**Tests:** 25/25 passing (100%)
**Cost:** $0.00 (algorithmic only)

## Overview

Implemented bidirectional linking between findings/paragraphs and supporting annexure sections. Detects annexure references in body text, resolves them to actual annexure parent chunks, and creates link records for traceability and evidence verification.

## What Was Implemented

### 1. Data Model Extension

**File:** `src/core/data_contracts.py`

Added `annexure_links` field to `SemanticEnrichment` model:

```python
# P3-5: Annexure-finding links (line ~307)
annexure_links: List[Dict[str, Any]] = Field(
    default_factory=list,
    description="Links from findings/paragraphs to annexure sections"
)
```

**Link Structure:**
```python
{
    "source_chunk_id": "chunk_123",
    "source_type": "finding" | "paragraph",
    "target_annexure_ref": "Annexure-A",
    "target_annexure_norm": "annexure_a",
    "target_parent_chunk_id": "annexure_a_parent",
    "reference_text": "Details are given in Annexure-A",
    "resolved": True,
    "finding_id": "finding_456"  # Optional, only for findings
}
```

### 2. AnnexureLinker Service

**File:** `src/enrichment/annexure_linker.py` (127 lines)

#### Key Methods

1. **`_normalize_annexure_id(raw: str) -> str`**
   - Normalizes various formats to canonical form
   - Examples: "Annexure - A" → "annexure_a", "APPENDIX B" → "appendix_b"
   - Handles spaces, hyphens, colons

2. **`_find_annexure_parents(parent_chunks: List[Dict]) -> Dict[str, Dict]`**
   - Builds index of annexure/appendix parent chunks
   - Returns: `{"annexure_a_details_of_expenditure": parent_chunk_dict, ...}`

3. **`link_annexures(child_chunks, parent_chunks, findings) -> List[Dict]`**
   - Scans all child chunks for annexure references
   - Matches references to annexure parents (exact + fuzzy)
   - Tracks finding attribution
   - Returns list of link records

#### Reference Detection Patterns

**Pattern Categories (11 total):**

1. **Explicit "details given" pattern:**
   - `"Details are given in Annexure-A"`
   - `"Details provided at Appendix-II"`

2. **"As per" pattern:**
   - `"As per Annexure-A"`
   - `"Vide Annexure-II"`

3. **Parenthetical pattern:**
   - `"(Annexure-A)"`
   - `"(Appendix-I)"`

4. **General "in" pattern:**
   - `"Revenue data in Annexure B"`
   - `"Details in Appendix-I"`

5. **Conjunctive pattern:**
   - `"Annexure-A and Annexure B"`
   - `"Appendix-I or Appendix-II"`

**Pattern Features:**
- Case-insensitive matching
- Handles Roman numerals (I, II, III, IV, V, etc.)
- Supports numeric suffixes (Annexure 3.1, Annexure-A-1)
- Avoids capturing trailing punctuation
- Deduplicates overlapping matches

#### Resolution Strategy

**Step 1: Exact Match**
- Check if normalized reference appears in any normalized annexure parent ID
- Example: `"annexure_a"` matches `"annexure_a_details_of_expenditure"`

**Step 2: Fuzzy Match (Fallback)**
- Remove trailing digits from reference
- Example: `"annexure_3_1"` → `"annexure_"` → matches `"annexure_..."`

**Step 3: Unresolved**
- If no match found, mark as `resolved: False`
- Still creates link record for audit trail

### 3. Pipeline Integration

**File:** `src/parsing_pipeline/modules/semantic_enrichment_service.py`

Added import and initialization:

```python
# Import (line ~44)
from src.enrichment.annexure_linker import AnnexureLinker

# Initialize in __init__ (line ~455)
self._annexure_linker = AnnexureLinker()

# Link annexures during enrichment (line ~537)
annexure_links = self._annexure_linker.link_annexures(
    child_chunks, parent_chunks,
    [f.to_dict() for f in findings]
)

# Include in enrichment output (line ~571)
return SemanticEnrichment(
    # ...existing fields...
    annexure_links=annexure_links,
)
```

### 4. Comprehensive Testing

**File:** `tests/parsing_pipeline/unit/test_annexure_linker_unit.py` (435 lines, 25 tests)

**Test Categories:**
- **ID normalization (3)**: Basic, numeric, complex IDs
- **Parent indexing (3)**: Basic, case-insensitive, no annexures
- **Reference detection (6)**: All pattern types (details given, as per, vide, parenthetical, appendix, multiple)
- **Resolution (5)**: Exact match, fuzzy match, unresolved, normalized comparison, data structure
- **Finding attribution (2)**: Finding vs paragraph source types
- **Edge cases (6)**: No annexures, no references, empty chunks, truncation, case variations, Roman numerals

## Key Features

### Pattern Matching

**Example Detections:**

| Input Text | Pattern Matched | Captured Reference |
|------------|----------------|-------------------|
| "Details are given in Annexure-A." | Explicit details | Annexure-A |
| "Loss of ₹100 crore as per Annexure-B" | As per | Annexure-B |
| "Methodology (Appendix-I)" | Parenthetical | Appendix-I |
| "Revenue in Annexure B and Annexure C" | General + Conjunction | Annexure B, Annexure C |
| "See Annexure-II for details" | As per | Annexure-II |

### Fuzzy Resolution

**Example Matches:**

| Reference | Parent TOC Entry | Match Type |
|-----------|-----------------|------------|
| "Annexure-A" | "Annexure-A: Details of Expenditure" | Exact substring |
| "Annexure B" | "Annexure B - Revenue Data" | Exact substring |
| "Annexure 3.1" | "Annexure 3: Financial Statements" | Fuzzy (base ref) |
| "Appendix-I" | "Appendix-I: Methodology" | Exact |

### Deduplication Logic

**Problem:** Overlapping patterns can match the same reference multiple times.

**Solution:** Track `(chunk_id, normalized_ref)` pairs in a set, skip duplicates.

**Example:**
```
Text: "Details are given in Annexure-A"
Pattern 1: "details...given...in Annexure-A" → captures "Annexure-A" ✓
Pattern 2: "in Annexure-A" → captures "Annexure-A" (skipped, duplicate)
Result: Only 1 link created
```

## Impact

### Evidence Traceability
- **Finding verification**: Each finding linked to supporting annexure data
- **Cross-referencing**: Navigate from finding to detailed tables/data
- **Audit trail**: Track which annexures support which findings

### Use Cases

1. **RAG retrieval**: When finding is retrieved, also retrieve linked annexure data
2. **Fact-checking**: Verify finding claims against annexure evidence
3. **Analytics**: Identify most-cited annexures per report
4. **UI navigation**: Provide "View Annexure" links in finding details

### Statistics

**Expected Coverage:**
- **Resolved links**: 80-90% (most annexures are present in document)
- **Unresolved links**: 10-20% (external annexures, typos, alternate naming)
- **Links per report**: 5-50 (varies by report complexity)

## Example Output

```json
{
  "report_id": "report_123",
  "findings": [...],
  "annexure_links": [
    {
      "source_chunk_id": "chunk_456",
      "source_type": "finding",
      "finding_id": "finding_789",
      "target_annexure_ref": "Annexure-A",
      "target_annexure_norm": "annexure_a",
      "target_parent_chunk_id": "annexure_a_parent",
      "reference_text": "Details are given in Annexure-A",
      "resolved": true
    },
    {
      "source_chunk_id": "chunk_789",
      "source_type": "paragraph",
      "target_annexure_ref": "Annexure-Z",
      "target_annexure_norm": "annexure_z",
      "target_parent_chunk_id": null,
      "reference_text": "See Annexure-Z",
      "resolved": false
    }
  ]
}
```

## Statistics

- **Lines of code**: 127 (AnnexureLinker) + 12 (integration) = 139 lines
- **Test coverage**: 435 lines, 25 tests (100% passing)
- **Performance**: O(n × m × p) where n=chunks, m=patterns, p=parent_chunks
  - Typical: ~1000 chunks × 11 patterns × 5 annexures = ~55k pattern matches
  - Optimized with early termination and set-based deduplication
- **Cost**: $0.00 (algorithmic only, no API calls)

## Files Created

- `src/enrichment/annexure_linker.py` (127 lines)
- `tests/parsing_pipeline/unit/test_annexure_linker_unit.py` (435 lines)

## Files Modified

- `src/core/data_contracts.py` (+4 lines: field definition)
- `src/parsing_pipeline/modules/semantic_enrichment_service.py` (+12 lines: import + integration)

## Next Steps

### Immediate
- ✅ P3-5 COMPLETE

### Future Enhancements
- **Page-level linking**: Resolve page number references ("see page 42")
- **Table-level linking**: Resolve table references ("Table 3.2")
- **Paragraph-level linking**: Resolve paragraph references ("Para 4.1.2")
- **Confidence scoring**: Score link quality based on pattern type and resolution method
- **Bidirectional lookup**: Index for fast lookup from annexure → findings that cite it

---

**Implementation Date:** 2026-02-14
**Implemented By:** Claude Sonnet 4.5
**Associated Plan:** `/docs/plans/phase3_plan.md` (P3-5 specification)
