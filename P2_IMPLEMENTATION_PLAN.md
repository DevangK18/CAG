# P2 Implementation Plan

**Created:** 2026-05-30
**Revised:** 2026-05-30 (Revision 2)
**Status:** Plan Only — Awaiting Approval
**Prerequisites:** P0 shipped and verified (P0_VERIFICATION_REPORT.md)

### Revision 2 Changes

1. **P2-19 REDESIGNED:** Removed unsafe diagnostic patterns (`^\d`, `^[a-z]`) that would delete legitimate parents like "1.1 Introduction" with 0 children. Now uses only explicit assembly-artifact patterns. Added cross-reference resolver to downstream consumer check.

2. **P2-17 REDESIGNED:** Fixed layering issue — normalization now applies to both text_extractor.py (child content) AND toc_reconciliation_service.py (parent toc_entry from Docling). Fixed regex bug that conflated "CHAPTER IT"→II vs "CHAPTER ITI"→III.

3. **Risk upgraded:** P2-19 risk changed from Low to Medium due to data loss potential if patterns are too broad.

---

## Executive Summary

Five P2 polish items targeting data quality improvements. All are independent and can be implemented in parallel. Total estimated effort: **9-14 hours** (revised up from 8-12h due to P2-17 layering fix).

| Item | Description | Effort | Risk |
|------|-------------|--------|------|
| P2-17 | OCR header normalization | 3-4h | Low |
| P2-18 | Blank-page extraction pre-check | 1-2h | Low |
| P2-19 | Empty-parent cleanup | 2-3h | **Medium** |
| P2-20 | footnote_index type fix | 1h | Low |
| P2-21 | Temporal extraction guards | 2-3h | Low |

**Implementation Order:** P2-20 → P2-18 → P2-21 → P2-17 → P2-19

---

## P2-17: OCR Header Normalization

### Diagnosis Verification

**Analysis claim:** OCR corrupts Roman numerals in chapter headers — "CHAPTER ITI" instead of "CHAPTER III", "144 CFC" instead of "14th CFC".

**Code verification:**
- `src/parsing_pipeline/modules/ocr_service.py:53-149` — OCR subprocess wrapper, no post-processing
- No OCR output normalization exists anywhere in the pipeline
- OCR'd text flows directly to Docling/pdfplumber extraction

**Confirmation:** ✅ Bug exists as described. Root cause is Tesseract/ocrmypdf output — no post-OCR normalization pass exists.

**Source of corruption:** Tesseract OCR. The pipeline uses ocrmypdf which wraps Tesseract. Roman numeral confusion (I/l, II/11/Il, III/ITI) is a known Tesseract limitation on scanned documents with non-standard fonts.

### Proposed Approach

Create a new `OcrNormalizer` class to post-process OCR output with context-aware Roman numeral correction:

```python
# src/parsing_pipeline/modules/ocr_normalizer.py

class OcrNormalizer:
    """Post-OCR text normalization for common OCR errors."""

    # Chapter Roman numeral corrections
    # IMPORTANT: Separate patterns for each corruption type
    CHAPTER_ROMAN_CORRECTIONS = [
        # Order matters: longer patterns first to avoid partial matches
        (r"CHAPTER\s+ITI\b", "CHAPTER III"),      # ITI → III (three I's misread)
        (r"CHAPTER\s+IT\b", "CHAPTER II"),        # IT → II (two I's misread)
        (r"CHAPTER\s+Il\b", "CHAPTER II"),        # Il → II (I + lowercase L)
        (r"CHAPTER\s+VIIl\b", "CHAPTER VIII"),    # VIIl → VIII
        (r"CHAPTER\s+VIl\b", "CHAPTER VII"),      # VIl → VII
        (r"CHAPTER\s+IVl\b", "CHAPTER IV"),       # IVl → IV
        (r"CHAPTER\s+Xl\b", "CHAPTER XI"),        # Xl → XI
        (r"CHAPTER\s+XIl\b", "CHAPTER XII"),      # XIl → XII
    ]

    # Ordinal corrections (Finance Commission context)
    ORDINAL_CORRECTIONS = [
        (r"(\d)44\s+CFC", r"\g<1>4th CFC"),       # 144 CFC → 14th CFC
        (r"(\d)st\s+CFC", r"\1st CFC"),
        (r"(\d)nd\s+CFC", r"\1nd CFC"),
        (r"(\d)rd\s+CFC", r"\1rd CFC"),
    ]

    def normalize_headers(self, text: str) -> str:
        """Apply OCR corrections to text."""
        result = text
        for pattern, replacement in self.CHAPTER_ROMAN_CORRECTIONS:
            result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
        for pattern, replacement in self.ORDINAL_CORRECTIONS:
            result = re.sub(pattern, replacement, result)
        return result
```

**Layering fix (Revision 2):** OCR text flows through two independent paths:
1. **Child content path:** text_extractor.py extracts page text → becomes chunk content
2. **Parent toc_entry path:** Docling extracts section headers → becomes parent toc_entry via toc_reconciliation_service

Both paths need normalization. Option A alone misses the parent path.

**Integration points:**
1. **text_extractor.py** — Normalize extracted text before it becomes chunk content
2. **toc_reconciliation_service.py** — Normalize `toc_entry` field during reconciliation (catches Docling-sourced headers)

**Why not normalize at Docling output?** Docling is a third-party library; post-processing its output in toc_reconciliation_service is cleaner than patching Docling internals.

### Affected Files

| File | Lines | Change |
|------|-------|--------|
| `src/parsing_pipeline/modules/ocr_normalizer.py` | NEW | Create normalizer class |
| `src/parsing_pipeline/extractors/text_extractor.py` | ~50-60 | Apply normalization after extraction (child content) |
| `src/parsing_pipeline/modules/toc_reconciliation_service.py` | ~80-100 | Apply normalization to toc_entry (parent headers) |

### Test Plan (14 tests)

1. **Failing case from analysis:**
   - `test_chapter_iti_corrected` — "CHAPTER ITI" → "CHAPTER III"
   - `test_chapter_it_corrected` — "CHAPTER IT" → "CHAPTER II" (distinct from ITI!)
   - `test_144_cfc_corrected` — "144 CFC" → "14th CFC"

2. **Normal cases:**
   - `test_correct_chapter_unchanged` — "CHAPTER III" stays "CHAPTER III"
   - `test_non_chapter_text_unchanged` — Regular text not modified

3. **Edge cases:**
   - `test_chapter_il_corrected` — "CHAPTER Il" → "CHAPTER II" (I + lowercase L)
   - `test_chapter_vii_l_corrected` — "CHAPTER VIl" → "CHAPTER VII"
   - `test_mixed_case_chapter` — "Chapter ITI" → "Chapter III"
   - `test_chapter_with_title` — "CHAPTER ITI Overview" → "CHAPTER III Overview"
   - `test_no_false_positives_on_similar_patterns` — "ITERATION" not modified
   - `test_empty_and_null_input` — Handles empty/null gracefully

4. **Layering tests (Revision 2):**
   - `test_toc_entry_normalized` — Parent toc_entry "CHAPTER ITI" → "CHAPTER III"
   - `test_child_content_normalized` — Child chunk content normalized independently

### Open Questions

1. ~~**Does normalization need to be PDF-aware?**~~ **RESOLVED (Revision 2):** No. Text-level normalization in both paths (text_extractor + toc_reconciliation_service) covers all cases.

2. **Should we track normalization counts?** Could emit a trace event `ocr_normalization_applied` with count of corrections — useful for debugging but not critical.

3. **Which reports have this issue?** Analysis cites CG_2025_1 (scanned). Need to verify the OCR'd text in that JSON to confirm pattern frequency.

### Effort Estimate

**3-4 hours** — Simple regex-based normalizer, but two integration points (text_extractor + toc_reconciliation_service) add testing overhead.

---

## P2-18: Blank-Page Extraction Pre-Check

### Diagnosis Verification

**Analysis claim:** Layout-detected Table blocks on pages with <50 chars of text waste Tier-3 Gemini calls. UK page 104 cited.

**Code verification:**
- `src/parsing_pipeline/modules/triage_service.py:17` — `BLANK_PAGE_THRESHOLD = 20`
- `src/parsing_pipeline/modules/content_extraction_service.py:240-400` — `_route_block()` routes Table blocks without checking page text density
- No pre-check for blank pages before extraction

**Confirmation:** ✅ Bug exists as described. No page-level text density check before table extraction.

### Proposed Approach

Add a pre-check in `_route_block()` before routing Table blocks:

```python
# In content_extraction_service.py _route_block() method

# P2-18: Skip extraction on blank pages
BLANK_PAGE_EXTRACTION_THRESHOLD = 50  # chars

def _route_block(self, block, pdf_path, page_num, report_id, is_scanned, trace_emitter=None):
    label = block.get("label", "")

    # P2-18: Pre-check for blank page (Table blocks only)
    if label == "Table":
        page_text_length = self._get_page_text_length(pdf_path, page_num)
        if page_text_length < self.BLANK_PAGE_EXTRACTION_THRESHOLD:
            # Emit trace and skip
            if trace_emitter:
                trace_emitter.emit_decision(
                    "6", "blank_page_skip", "skipped",
                    ["extract", "skipped"],
                    f"Page {page_num} has {page_text_length} chars < {self.BLANK_PAGE_EXTRACTION_THRESHOLD}"
                )
            return None  # Skip extraction

    # Continue with normal routing...

def _get_page_text_length(self, pdf_path: str, page_num: int) -> int:
    """Get character count for a page (cached per PDF)."""
    # Use fitz for quick text length check
    ...
```

**Caching consideration:** Multiple Table blocks on the same page shouldn't trigger repeated PDF opens. Cache page text lengths per PDF.

### Affected Files

| File | Lines | Change |
|------|-------|--------|
| `src/parsing_pipeline/modules/content_extraction_service.py` | 240-270 | Add pre-check, caching method |

### Test Plan (8 tests)

1. **Failing case from analysis:**
   - `test_blank_page_table_skipped` — Table on page with 30 chars skipped

2. **Normal cases:**
   - `test_normal_page_table_extracted` — Table on page with 500 chars extracted
   - `test_non_table_block_not_checked` — Picture/Figure blocks not affected

3. **Edge cases:**
   - `test_threshold_boundary_50_chars` — Page with exactly 50 chars
   - `test_threshold_boundary_49_chars` — Page with 49 chars skipped
   - `test_multiple_tables_same_blank_page` — Only one page check per PDF
   - `test_scanned_vs_native_behavior` — Both PDF types handled
   - `test_trace_emitted_on_skip` — Verify trace emission

### Open Questions

1. **Should this check apply to Picture/Figure blocks too?** Analysis mentions only Table, but the same logic could apply.

2. **Is 50 chars the right threshold?** Triage uses 20 chars for blank page detection. Should align with triage or use a separate threshold?

3. **Performance impact of page text length check?** fitz text extraction is fast, but caching is important.

### Effort Estimate

**1-2 hours** — Simple pre-check with caching. Low complexity.

---

## P2-19: Empty-Parent Cleanup Post-Phase 7

### Diagnosis Verification

**Analysis claim:** UK 33/167 and Food_grains 21/163 parents have 0 children, matching assembly-artifact name patterns.

**Code verification:**
- `src/parsing_pipeline/modules/toc_reconciliation_service.py:44-53` — P0-02's `NOISE_PATTERNS` exist
- `src/parsing_pipeline/modules/assembly_service.py:196-206` — `_serialize_parent_chunks()` called without cleanup
- No post-Phase 7 empty-parent cleanup exists

**Existing patterns from P0-02 (toc_reconciliation_service.py:44-53):**
```python
NOISE_PATTERNS = [
    r"^\([Pp]aragraphs?\s+[\d.]+\)",  # "(Paragraph 3.2)"
    r"^\([Ss]ource:?\s.*\)$",          # "(Source: Records...)"
    r"^Report\s+No\.\s+\d+\s+of",      # Running header
    r"^Page\s+\d+$",                    # Page number
    r"^[a-z]\.\s+",                     # List item "a. ..."
    r"^\([ivxlcdm]+\)\s+",              # "(i) ...", "(iv) ..."
    r"^\d+$",                            # Just a number
    r"^-+$",                             # Just dashes
]
```

**⚠️ REVISION 2: Dropped unsafe diagnostic patterns**

The original plan proposed borrowing patterns from `scripts/run_baseline_diagnostics.py`:
```python
# UNSAFE — DO NOT USE AS DELETION PATTERNS
r"^\d",       # starts with number — would delete "1.1 Introduction"!
r"^[a-z]",    # starts lowercase — would delete "section A"!
```

These are **diagnostic flag patterns** meant to surface suspicious entries during analysis, not deletion patterns. Using them at runtime would silently delete legitimate parents like "1.1 Introduction" or "3.2 Financial Analysis" that happen to have 0 children due to mis-parenting bugs elsewhere. The `child_count==0` guard doesn't protect against this — it enables the data loss.

**Confirmation:** ✅ Bug exists. Empty-parent cleanup needs to happen after Phase 7 but before assembly output, using **explicit and narrow** artifact patterns only.

### Proposed Approach (Revision 2)

Add `_cleanup_empty_parents()` method in `assembly_service.py` with **conservative, explicit patterns**:

```python
# In assembly_service.py

# P2-19: Assembly artifact patterns for empty-parent cleanup
# IMPORTANT: These must be EXPLICIT patterns for known assembly artifacts.
# DO NOT add broad patterns like r"^\d" or r"^[a-z]" — those would delete
# legitimate parents like "1.1 Introduction" that have 0 children due to
# mis-parenting elsewhere.
ASSEMBLY_ARTIFACT_PATTERNS = [
    # File merger labels: "01_Cover", "15_Separator" (digit-underscore-capital required)
    re.compile(r"^\d+_[A-Z]"),
    # State code prefixes from merged files: "WBOCW_123"
    re.compile(r"^[A-Z]{2,}_\d+"),
    # Explicit placeholder pages
    re.compile(r"^Blank\s+Page$", re.I),
    re.compile(r"^Cover$", re.I),
    re.compile(r"^Separator$", re.I),
    re.compile(r"^Title\s+Page$", re.I),
]

# Also inherit P0-02's NOISE_PATTERNS (paragraph refs, source citations, etc.)
# These are safe because they're narrow and don't match real section titles.

def _cleanup_empty_parents(
    self,
    parent_chunks: List[ParentChunk],
    child_chunks: List[ChildChunk],
    trace_emitter=None,
) -> List[ParentChunk]:
    """
    P2-19: Remove parents with 0 children that match assembly-artifact patterns.

    Runs after Phase 7 (parent-child assignment) and P0-04 (chapter promotion).

    IMPORTANT: Only removes parents matching EXPLICIT artifact patterns.
    Parents with legitimate titles (e.g., "1.1 Introduction") are PRESERVED
    even if they have 0 children — that's a signal of mis-parenting elsewhere,
    not a cleanup target.
    """
    # Build child count per parent
    child_counts = {}
    for child in child_chunks:
        pid = child.parent_chunk_id
        child_counts[pid] = child_counts.get(pid, 0) + 1

    cleaned = []
    removed = []
    for parent in parent_chunks:
        count = child_counts.get(parent.chunk_id, 0)
        if count == 0 and self._is_assembly_artifact(parent.toc_entry):
            removed.append(parent.toc_entry)
        else:
            cleaned.append(parent)

    if removed and trace_emitter:
        trace_emitter.emit_sample("8", "empty_parents_removed",
            [{"toc_entry": t} for t in removed[:5]])
        trace_emitter.emit(
            "8", "empty_parent_cleanup",
            {"removed_count": len(removed), "remaining": len(cleaned)}
        )

    return cleaned
```

**Pattern safety analysis (Revision 2):**

| Pattern | Example Match | Example Non-Match | Safe? |
|---------|---------------|-------------------|-------|
| `^\d+_[A-Z]` | "01_Cover", "15_Separator" | "1.1 Introduction", "3 Results" | ✅ Yes |
| `^[A-Z]{2,}_\d+` | "WBOCW_123", "MH_456" | "Chapter 1", "Section A" | ✅ Yes |
| `^Blank\s+Page$` | "Blank Page" | "Blank Page Detection" | ✅ Yes |
| `^Cover$` | "Cover" | "Coverage Analysis" | ✅ Yes |
| ~~`^\d`~~ | ~~"01_Cover"~~ | ~~"1.1 Introduction"~~ | ❌ UNSAFE |
| ~~`^[a-z]`~~ | ~~"a. item"~~ | ~~"section 3.1"~~ | ❌ UNSAFE |

**Execution order verification:**
1. P0-02 noise rejection runs in Phase 5.5 (toc_reconciliation_service) — **before** parent creation
2. P0-04 chapter L1 promotion runs in Phase 5.5 — **before** parent creation
3. Phase 7 assigns children to parents
4. **P2-19 cleanup runs here** — after Phase 7, before serialization

This order is correct: cleanup runs after parents have been populated by Phase 7.

### Affected Files

| File | Lines | Change |
|------|-------|--------|
| `src/parsing_pipeline/modules/assembly_service.py` | 196-206, NEW | Add cleanup method, call before serialize |

### Downstream Consumer Check (Revision 2)

| Consumer | Field Used | Impact |
|----------|------------|--------|
| `src/rag_pipeline/indexer.py:141-168` | `parent_chunks` | Fewer parents indexed — **POSITIVE** |
| `src/rag_pipeline/qdrant_service.py:242-254` | `parent_chunks` | Fewer parents stored — **POSITIVE** |
| `src/rag_pipeline/embedding_service.py:615-626` | `parent_chunks` | Fewer parent lookups — **POSITIVE** |
| `src/api/services/report_service.py` | (indirect) | No direct use |
| `src/parsing_pipeline/modules/enrichment/cross_reference_resolver.py` | `parent_chunks` | **⚠️ BREAKING if overly broad** |

**Cross-reference resolver impact (Revision 2):**
If a finding cites "section 5.3" and that parent gets deleted, citation resolution breaks. The conservative patterns in Revision 2 avoid this: `^\d+_[A-Z]` won't match "5.3 Revenue Analysis", so legitimate section references remain resolvable.

**Conclusion:** With Revision 2's narrow patterns, all downstream consumers benefit. Overly broad patterns (now removed) would have caused citation resolution failures.

### Test Plan (12 tests, Revision 2)

1. **Failing case from analysis:**
   - `test_blank_page_parent_removed` — Parent "Blank Page" with 0 children removed
   - `test_file_merger_label_removed` — Parent "15_Separator" with 0 children removed
   - `test_state_code_prefix_removed` — Parent "WBOCW_123" with 0 children removed

2. **Normal cases:**
   - `test_chapter_parent_preserved` — "Chapter 1" with children preserved
   - `test_empty_non_artifact_preserved` — "Executive Summary" with 0 children preserved

3. **Safety tests (Revision 2 — critical):**
   - `test_numbered_section_preserved` — "1.1 Introduction" with 0 children **PRESERVED** (not deleted!)
   - `test_numbered_parent_with_zero_children_preserved` — "3 Results" with 0 children **PRESERVED**
   - `test_lowercase_section_preserved` — "section A" with 0 children **PRESERVED**

4. **Edge cases:**
   - `test_multiple_artifact_parents_removed` — Multiple artifact parents cleaned
   - `test_noise_pattern_inheritance` — P0-02 patterns also trigger cleanup
   - `test_artifact_with_children_preserved` — "01_Cover" with children stays (has content)
   - `test_trace_emitted_on_cleanup` — Verify trace emission

### Open Questions

1. ~~**Should we preserve any assembly artifacts?**~~ **RESOLVED (Revision 2):** Artifact parents WITH children are preserved. Only empty artifact parents are removed.

2. ~~**Is there a minimum children threshold?**~~ **RESOLVED (Revision 2):** Stick to 0 children only. Parents with 1-2 children might have legitimate content even if the name looks like an artifact.

3. **Should we emit a red flag for empty non-artifact parents?** A parent like "5.3 Revenue Analysis" with 0 children suggests mis-parenting elsewhere. Could emit `empty_legitimate_parent` red flag for diagnostic purposes.

### Effort Estimate

**2-3 hours** — Pattern matching and list filtering. Main complexity is verifying execution order and edge cases.

---

## P2-20: footnote_index Type Fix

### Diagnosis Verification

**Analysis claim:** Spec says `footnote_index` should be dict, but JSON emits `[]` (empty list).

**Code verification:**
- `docs/guides/PARSING_PIPELINE.md:1140-1142`:
  ```json
  "footnote_index": {
    "1": {"chunk_id": "...", "content": "...", "page": 15}
  }
  ```
- `src/parsing_pipeline/modules/assembly_service.py:540-572`:
  ```python
  def _build_footnote_index(self, child_chunks: List[Dict]) -> List[Dict[str, Any]]:
      """..."""
      footnotes = []
      ...
      return footnotes
  ```

**Confirmation:** ✅ Bug exists. Return type is `List[Dict]`, spec says `Dict[str, Dict]`.

### Proposed Approach

Change return type and structure to match spec:

```python
def _build_footnote_index(self, child_chunks: List[Dict]) -> Dict[str, Dict[str, Any]]:
    """
    P4-1: Build footnote index as dict keyed by footnote number.

    Returns: {"1": {...}, "2": {...}} instead of [{...}, {...}]
    """
    footnotes = {}

    for chunk in child_chunks:
        if chunk.get("content_type") != "footnote":
            continue

        footnote_num = self._extract_footnote_number(chunk.get("content", ""))
        if footnote_num is None:
            footnote_num = f"auto_{len(footnotes) + 1}"  # Fallback for unnumbered

        footnotes[footnote_num] = {
            "chunk_id": chunk.get("chunk_id"),
            "content": chunk["content"],
            "page_physical": chunk.get("source_page_physical"),
            "page_logical": chunk.get("source_page_logical"),
            "parent_section": chunk.get("hierarchy", {}),
        }

    return footnotes
```

### Affected Files

| File | Lines | Change |
|------|-------|--------|
| `src/parsing_pipeline/modules/assembly_service.py` | 540-572 | Change return type and structure |

### Downstream Consumer Check

| Consumer | Usage | Impact |
|----------|-------|--------|
| `docs/archive/phase4_plan.md:1168` | `footnotes = report_data.get("footnote_index", [])` | **BREAKING** — needs update to `{}` |

**Fix required:** Update default from `[]` to `{}` in any consumer code.

**Grep for consumers:**
```bash
grep -r "footnote_index" src/
```
Result: No direct API/RAG consumers found. Only assembly_service produces this field.

### Test Plan (6 tests)

1. **Failing case from analysis:**
   - `test_returns_dict_not_list` — `assert isinstance(result, dict)`

2. **Normal cases:**
   - `test_footnote_keyed_by_number` — `"1"` key exists for `[Footnote 1]`
   - `test_multiple_footnotes_keyed` — Multiple footnotes have unique keys

3. **Edge cases:**
   - `test_no_footnotes_returns_empty_dict` — `{}` not `[]`
   - `test_unnumbered_footnote_gets_auto_key` — `"auto_1"` key for `[Footnote]`
   - `test_duplicate_footnote_numbers_handled` — Later entry overwrites (or error?)

### Open Questions

1. **What if two footnotes have the same number?** Overwrite, append suffix, or error? Recommend: overwrite with warning.

2. **Should `auto_N` keys be used for unnumbered footnotes?** Or should we reject/skip them?

### Effort Estimate

**1 hour** — Simple type change. Low risk since no API/RAG consumers read this field directly.

---

## P2-21: Temporal Extraction Guards

### Diagnosis Verification

**Analysis claim:**
1. `reference_years` included 2025/2026/2027 for a 2022 report (Food_grains)
2. `audit_period.end_year=2021` for "2021-22" (should be 2022)

**Code verification:**
- `src/parsing_pipeline/modules/enrichment/temporal_extractor.py:81-105`:
  ```python
  def extract_reference_years(self, text: str) -> List[int]:
      years = set()
      ...
      if 2000 <= base <= 2030:
          years.add(base)
      ...
      return sorted(years)
  ```
  No `report_year` validation — accepts any year 2000-2030.

- `src/parsing_pipeline/modules/enrichment/temporal_extractor.py:55-57`:
  ```python
  def _normalize_fy_year(self, base: str, suffix: str) -> int:
      """Convert '2019' + '20' → 2019, or '2019' + '2020' → 2019."""
      return int(base)
  ```
  Returns start year, but for fiscal year "2021-22", the **end year** should be 2022.

- `src/parsing_pipeline/modules/semantic_enrichment_service.py:252-266`:
  - `temporal_coverage = self._temporal_extractor.extract_temporal_metadata(...)`
  - `report_metadata` is available at line 111 but not passed to temporal extractor

**Confirmation:** ✅ Both bugs exist.
1. No upper bound validation against `report_year`
2. Fiscal year parsing returns start year, not end year

### Proposed Approach

1. **Add `report_year` parameter** to `extract_temporal_metadata()` and `extract_reference_years()`:

```python
def extract_reference_years(self, text: str, report_year: Optional[int] = None) -> List[int]:
    """Extract years, optionally bounded by report_year."""
    years = set()
    ...
    # P2-21: Filter future years relative to report
    if report_year:
        years = {y for y in years if y <= report_year + 1}  # Allow +1 for publication lag

    return sorted(years)
```

2. **Fix fiscal year end-year parsing** in `_normalize_fy_year()`:

```python
def _normalize_fy_year_end(self, base: str, suffix: str) -> int:
    """Convert '2021' + '22' → 2022 (the end year of fiscal 2021-22)."""
    base_int = int(base)
    if len(suffix) == 2:
        # "2021-22" → 2022
        century = str(base_int)[:2]
        return int(century + suffix)
    else:
        # "2021-2022" → 2022
        return int(suffix)
```

3. **Update callers** in `semantic_enrichment_service.py`:

```python
# Line 252-266
report_year = report_metadata.get("report_year")

temporal_coverage = self._temporal_extractor.extract_temporal_metadata(
    child_chunks,
    [s.model_dump() for s in section_classifications],
    report_year=report_year,  # P2-21
)

for finding in findings:
    finding.reference_years = self._temporal_extractor.extract_reference_years(
        finding.text,
        report_year=report_year,  # P2-21
    )
```

### Affected Files

| File | Lines | Change |
|------|-------|--------|
| `src/parsing_pipeline/modules/enrichment/temporal_extractor.py` | 55-57, 81-105, 120-183 | Add bounds, fix FY parsing |
| `src/parsing_pipeline/modules/semantic_enrichment_service.py` | 252-266 | Pass report_year |

### Downstream Consumer Check

| Consumer | Field Used | Impact |
|----------|------------|--------|
| `src/core/data_contracts.py:400` | `reference_years` | Cleaner data — **POSITIVE** |
| `src/core/data_contracts.py:396` | `audit_period` | Correct end_year — **POSITIVE** |

No API/RAG consumers read these fields directly for filtering. Impact is data quality improvement.

### Test Plan (12 tests)

1. **Failing case from analysis:**
   - `test_future_years_filtered_by_report_year` — 2025/2026/2027 removed for 2022 report
   - `test_fy_end_year_correct` — "2021-22" → `end_year=2022`

2. **Normal cases:**
   - `test_years_within_report_year_preserved` — 2020, 2021 kept for 2022 report
   - `test_report_year_plus_one_allowed` — 2023 allowed for 2022 report (publication lag)
   - `test_fy_range_extraction` — "2019-20 to 2022-23" → start=2019, end=2023

3. **Edge cases:**
   - `test_no_report_year_no_filtering` — `report_year=None` preserves all
   - `test_fy_full_year_format` — "2021-2022" → end_year=2022
   - `test_fy_single_year` — "2022" → 2022 (not fiscal)
   - `test_years_exactly_at_boundary` — report_year=2022, refs include 2022
   - `test_empty_text_returns_empty` — No years in text
   - `test_multiple_fy_ranges` — Multiple fiscal ranges parsed correctly
   - `test_calendar_vs_fiscal_distinction` — "April 2021 to March 2022" vs "2021-22"

### Open Questions

1. **Should `report_year + 1` be configurable?** Some reports discuss future projections. Current plan: allow +1, flag +2 as red flag.

2. **How to handle multi-year reports?** A report covering 2019-2023 shouldn't filter out 2023 references. May need `audit_period` awareness.

3. **What about historical references?** "Since 1991" — these are valid. Lower bound should remain 2000 (sanity) but not require `> report_year - N`.

### Effort Estimate

**2-3 hours** — Moderate complexity due to fiscal year edge cases and integration with semantic_enrichment_service.

---

## Implementation Order

| Order | Item | Rationale |
|-------|------|-----------|
| 1 | **P2-20** | Pure schema fix, 1 hour, unblocks any downstream consumer that crashes on wrong type. Zero risk. |
| 2 | **P2-18** | Simple pre-check, 1-2 hours, immediately reduces wasted Gemini calls. No dependencies. |
| 3 | **P2-21** | Temporal fixes, 2-3 hours. Should run before P2-19 in case temporal data affects cleanup decisions. |
| 4 | **P2-17** | OCR normalization, 3-4 hours. Independent of other items, but benefits from P2-21's report_year availability. Two integration points (text_extractor + toc_reconciliation_service). |
| 5 | **P2-19** | Empty-parent cleanup, 2-3 hours. Runs last because it depends on Phase 7 completion and should run after all other enrichments. |

**Parallel execution:** P2-20, P2-18, and P2-21 have no dependencies and can be implemented in parallel by different developers. P2-17 can also run in parallel but touches toc_reconciliation_service.py which P2-19 depends on indirectly (for NOISE_PATTERNS import).

---

## Verification Gates

Post-implementation checks:

1. **P2-17:** Run on CG_2025_1 JSON — no "CHAPTER ITI" or "CHAPTER IT" in parent `toc_entry` fields (both child content AND parent headers normalized)
2. **P2-18:** Re-run UK_2025_06 — page 104 Table block should be skipped (check trace)
3. **P2-19 (Revision 2):**
   - UK and Food_grains parent counts should drop by ~20-30 after cleanup
   - **CRITICAL:** Verify NO parents matching `^\d+\.\d+` (e.g., "1.1 Introduction") were removed
   - Grep removed entries in trace — should only see "Blank Page", "01_Cover", etc.
4. **P2-20:** `jq '.footnote_index | type'` returns `"object"` not `"array"`
5. **P2-21:** Food_grains `reference_years` should not include >2022; `audit_period.end_year` should be 2022 for "2021-22"

---

## Risk Assessment (Revision 2)

| Risk | Mitigation |
|------|------------|
| P2-17 false positives | Narrow patterns to "CHAPTER" context only; test on non-CAG text |
| **P2-19 removes valid parents** | **Revision 2:** Use ONLY explicit artifact patterns (`^\d+_[A-Z]`, `^Blank\s+Page$`, etc.). Dropped broad diagnostic patterns (`^\d`, `^[a-z]`). Safety tests verify "1.1 Introduction" preserved. |
| P2-19 breaks citation resolution | **Revision 2:** Conservative patterns don't match "section 5.3" style references. Cross-reference resolver added to consumer check. |
| P2-21 over-filtering | Allow report_year + 1; make filter optional |

**Overall risk:** Low for P2-17, P2-18, P2-20, P2-21. **Medium for P2-19** — data loss potential if patterns broaden without safety tests. Revision 2 patterns are conservative; recommend code review before merging.
