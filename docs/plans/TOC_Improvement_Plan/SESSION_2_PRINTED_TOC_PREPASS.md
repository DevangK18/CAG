# Session 2: Printed TOC Pre-Pass — Raw Text Extraction Before Chunking

> **Model:** Sonnet | **Estimated effort:** 1-2 hours | **Lines changed:** ~80-100
> **Pre-requisite:** Read `TOC_IMPROVEMENT_CONTEXT.md` first

---

## Context

### The Chicken-Egg Problem
`toc_table_parser.py` has `parse_from_chunks()` which requires content chunks as input. But chunks are created in Phase 7, and TOC extraction happens in Phase 4. Currently, the table parser is only used as a fallback when bookmark-based and heuristic methods fail — and even then, it receives chunks that don't exist yet at scaffold time.

### The Fix
Add a **raw text pre-pass** at the beginning of `scaffolding_service.py:build_scaffold()` that:
1. Opens the PDF with PyMuPDF (`fitz`) — already a dependency
2. Extracts raw text from pages 1-15
3. Splits into lines
4. Feeds each line through `toc_table_parser._parse_toc_line()`
5. Uses the result as an additional TOC signal

This gives the printed TOC parser access to content BEFORE any chunking happens.

---

## Implementation

### File to modify: `scaffolding_service.py`

#### Step 1: Add import at top of file
```python
from src.parsing_pipeline.modules.toc_table_parser import TOCTableParser, TOCEntry
```

#### Step 2: Add new method to ScaffoldingService class

```python
def _extract_printed_toc(self, pdf_path: str, report_id: str = "unknown") -> tuple:
    """
    Pre-pass: Extract TOC by parsing raw text from early pages.
    
    Opens the PDF directly and feeds lines through TOCTableParser's
    regex patterns. This runs BEFORE any chunking, solving the 
    chicken-egg problem where the table parser needed chunks that
    don't exist yet.
    
    Args:
        pdf_path: Path to the PDF file
        report_id: Report identifier for logging
        
    Returns:
        Tuple of (toc_entries: List[List], confidence: float)
        toc_entries format: [[level, title, page_num], ...]
    """
    import fitz  # PyMuPDF
    
    parser = TOCTableParser()
    entries = []
    toc_started = False
    toc_ended = False
    
    try:
        doc = fitz.open(pdf_path)
        max_page = min(15, len(doc))  # Only scan first 15 pages
        
        for page_num in range(max_page):
            if toc_ended:
                break
                
            page = doc[page_num]
            text = page.get_text("text")
            lines = text.split("\n")
            
            for line in lines:
                line = line.strip()
                if not line or len(line) < 3:
                    continue
                
                # Detect TOC header
                if not toc_started:
                    line_lower = line.lower().strip()
                    if line_lower in ("contents", "table of contents", "index", "list of contents"):
                        toc_started = True
                        continue
                
                # Try to parse as TOC entry
                entry = parser._parse_toc_line(line)
                if entry:
                    entries.append(entry)
                elif toc_started and len(entries) >= 3:
                    # If we had a TOC going and hit non-TOC content,
                    # check if TOC has ended
                    if parser._is_toc_end(line):
                        toc_ended = True
                        break
        
        doc.close()
        
    except Exception as e:
        logger.warning(f"[{report_id}] Printed TOC pre-pass failed: {e}")
        return [], 0.0
    
    if len(entries) < 3:
        logger.debug(f"[{report_id}] Printed TOC pre-pass: only {len(entries)} entries (min 3)")
        return [], 0.0
    
    # Convert TOCEntry objects to standard format
    toc = [[e.level, e.title, e.page_num] for e in entries]
    
    # Calculate confidence
    confidence = parser._calculate_confidence(entries, [])
    
    logger.info(
        f"[{report_id}] Printed TOC pre-pass: {len(entries)} entries, "
        f"confidence={confidence:.2f}"
    )
    
    return toc, confidence
```

#### Step 3: Integrate into `build_scaffold()` method

Find the `build_scaffold()` method. Add the printed TOC pre-pass as an **additional signal** in the TOC extraction cascade. The integration point is AFTER the existing methods have been tried but BEFORE the final quality assessment.

Look for where the scaffold's `toc` is being finalized. Add logic like:

```python
# After existing TOC extraction methods...
# Try printed TOC pre-pass as supplementary signal
pdf_path = self._get_pdf_path(task)  # or however the PDF path is resolved
if pdf_path:
    printed_toc, printed_confidence = self._extract_printed_toc(pdf_path, task.report_id)
    
    if printed_toc and printed_confidence > 0.5:
        current_toc = scaffold.get("toc", [])
        current_quality = scaffold.get("toc_quality", 0)
        
        if not current_toc or current_quality < 40:
            # No existing TOC or very low quality — use printed TOC as primary
            scaffold["toc"] = printed_toc
            scaffold["toc_method"] = "printed_toc_prepass"
            scaffold["toc_quality"] = int(printed_confidence * 100)
            logger.info(f"[{task.report_id}] Using printed TOC pre-pass as primary ({len(printed_toc)} entries)")
        
        elif current_quality < 70 and len(printed_toc) > len(current_toc):
            # Medium quality existing TOC but printed has more entries — supplement
            # Merge: keep existing, add any printed entries not already present
            existing_titles = {entry[1].lower().strip() for entry in current_toc}
            new_entries = [
                entry for entry in printed_toc 
                if entry[1].lower().strip() not in existing_titles
            ]
            if new_entries:
                merged = current_toc + new_entries
                # Re-sort by page number
                merged.sort(key=lambda e: e[2])
                scaffold["toc"] = merged
                scaffold["toc_method"] = f"{scaffold.get('toc_method', 'unknown')}+printed_supplement"
                logger.info(f"[{task.report_id}] Supplemented TOC with {len(new_entries)} printed entries")
```

### Key details for the implementer

1. **PDF path resolution**: Look at how `build_scaffold()` currently gets the PDF path. It's likely `task.local_pdf_path` or `task.ocred_pdf_path`. Match the existing pattern — check `layout_analysis_service.py:_get_pdf_path()` for reference.

2. **Page number mapping**: The printed TOC contains LOGICAL page numbers (as printed: "1", "5", "iii"). But `scaffold.toc` uses 0-indexed PHYSICAL page numbers. You need to convert using `scaffold.page_map` (which maps physical → logical). Invert it to get logical → physical mapping. If no page_map exists yet at this point, try the PDF's own page labels or assume physical ≈ logical.

3. **Don't break the existing cascade**: The printed TOC pre-pass is an ADDITIONAL signal. If it finds nothing, the existing methods carry on unchanged.

4. **`_parse_toc_line` is a method on a TOCTableParser instance** — you need to instantiate the parser to use it. It takes a plain string and returns an Optional[TOCEntry].

5. **`_is_toc_end` and `_calculate_confidence`** are also instance methods on TOCTableParser.

---

## Testing

### Unit test: Add to existing test file for scaffolding

```python
def test_printed_toc_prepass_basic():
    """Test printed TOC extraction from raw text lines."""
    service = ScaffoldingService()
    # Use a known test PDF that has a printed TOC
    # Verify it returns entries in [[level, title, page], ...] format
    
def test_printed_toc_prepass_no_toc():
    """Test graceful handling when PDF has no printed TOC."""
    service = ScaffoldingService()
    # Use a PDF without TOC pages
    # Should return ([], 0.0)

def test_printed_toc_prepass_merge():
    """Test that printed TOC supplements low-quality existing TOC."""
    # Create a scaffold with toc_quality < 70
    # Verify merge adds new entries without duplicates
```

### Integration test
```bash
# Run on a few sample reports to verify quality
python -m pytest tests/ -v -k "scaffold"
```

---

## Verification Checklist

- [ ] `_extract_printed_toc()` returns `([], 0.0)` when no TOC found (not an error)
- [ ] Page numbers in output are physical (0-indexed), not logical
- [ ] Existing TOC extraction still works when printed TOC finds nothing
- [ ] Merge logic doesn't create duplicate entries
- [ ] All existing tests pass: `python -m pytest tests/ -v`
- [ ] Logged output shows printed TOC stats for debugging
