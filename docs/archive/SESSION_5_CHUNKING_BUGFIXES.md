# Session 5: Chunking Service Bug Fixes — Parent Selection + Debug Logging

> **Model:** Sonnet | **Estimated effort:** 20-30 min | **Lines changed:** ~25-30
> **Pre-requisite:** Read `TOC_IMPROVEMENT_CONTEXT.md` first
> **File:** `services/parsing_pipeline/src/parsing_pipeline/modules/chunking_service.py`

---

## Context

Two bugs in the parent-child assignment logic in `chunking_service.py`. Bug 1 causes incorrect parent assignment for content that appears above section headers on a page. Bug 3 silently hides assignment failures, making broken reports impossible to debug.

These should be fixed BEFORE running the full pipeline with the new TOC improvements (Sessions 1-4), so you can verify the improvements are working correctly.

---

## Bug 1: `parents_from_before[0]` Picks Wrong Parent (Line 592-594)

### Problem

In `_find_best_parent_for_page()`, when content appears ABOVE all section headers on a page (e.g., a continuation paragraph from the previous section), the code falls back to:

```python
if best_parent is None and parents_from_before:
    best_parent = parents_from_before[0]  # ← Picks FIRST, not BEST
```

`parents_from_before` is a list filtered from `candidates`, which comes from the page index. The order is insertion order — NOT sorted by specificity. So `[0]` could be a level-1 chapter parent when a more specific level-2 section parent is also in the list.

### Example of the Bug

Page 15 has section "2.4 Conclusions" starting at Y=200. A paragraph sits at Y=80 (above the header — it's a continuation from section "2.3 Findings" which started on page 13).

`candidates` for page 15 might be:
- Parent A: "Chapter II Audit Findings" (level 1, pages 10-28)
- Parent B: "2.3 Financial Irregularities" (level 2, pages 13-15)  
- Parent C: "2.4 Conclusions" (level 2, pages 15-20, Y=200)

The Y-filter correctly excludes Parent C (its Y=200 is below content Y=80). But `parents_from_before` = [Parent A, Parent B] and `[0]` picks Parent A (level 1) when Parent B (level 2) is the correct, more specific match.

### Fix

Replace lines 591-594 with:

```python
                # If no section on this page starts before content, use most specific
                # parent from a previous page
                if best_parent is None and parents_from_before:
                    # Pick the deepest-level (most specific) parent among previous-page candidates
                    # On ties, prefer the one whose page range starts closest to this page
                    parents_from_before.sort(
                        key=lambda p: (-p.toc_level, -(p.page_range_physical[0]))
                    )
                    best_parent = parents_from_before[0]
```

### Key Details
- Sort by `-toc_level` first: level 2 beats level 1 (more specific)
- Tiebreak by `-start_page`: the parent starting on page 13 beats one starting on page 10 (closer = more likely the correct section)
- This is the same specificity principle used in the `sort_key` at line 602, just applied to the fallback path

---

## Bug 3: No Logging for Fallback Parent Assignment (Lines 446-458)

### Problem

When `_find_best_parent_for_page()` returns `None`, the child is silently assigned to `parent_chunks[0]` (the very first parent, usually "Preface" or "Chapter I"). There's no logging, no counter, no way to know this happened unless you manually inspect the output JSON.

This makes it impossible to:
- Know how many children have broken assignments
- Identify which pages/content types are failing
- Verify that TOC improvements actually reduced the failure rate

### Fix

Replace lines 446-458 in `_create_child_chunks()` with:

```python
            # Track fallback assignments for diagnostics
            fallback_count = 0  # ← Add this BEFORE the loop (around line 430)

            # ... inside the loop:

            if parent_chunk:
                parent_chunk_id = parent_chunk.chunk_id
                # PHASE 1 FIX: Inherit the FULL hierarchy from parent
                hierarchy = parent_chunk.hierarchy.copy()
            else:
                # Fallback: assign to first parent
                parent_chunk_id = (
                    parent_chunks[0].chunk_id if parent_chunks else "unknown"
                )
                hierarchy = (
                    parent_chunks[0].hierarchy.copy()
                    if parent_chunks
                    else {"level_1": "Document"}
                )
                fallback_count += 1
                print(
                    f"  ⚠️ Fallback assignment: page {extracted_content.source_page_physical}, "
                    f"type={extracted_content.content_type} → {parent_chunks[0].toc_entry if parent_chunks else 'unknown'}"
                )
```

And AFTER the loop (before the return), add:

```python
        if fallback_count > 0:
            print(
                f"  ⚠️ {fallback_count}/{len(task.extracted_content)} children "
                f"({fallback_count/len(task.extracted_content)*100:.1f}%) assigned via fallback"
            )

        return child_chunks
```

### Key Details
- Initialize `fallback_count = 0` before the for-loop at line 431
- Print per-item warning inside the else branch (lines 450-458)
- Print summary after the loop, before return
- Use ⚠️ emoji prefix for easy grep/scanning in pipeline output
- Include page number and content_type for debugging which pages are problematic
- The percentage tells you at a glance if your TOC improvements are working (should decrease after Sessions 1-4)

---

## Testing

### Verify Bug 1 Fix

The best test is a real report where you know a child was misassigned. But for a unit test:

```python
def test_parents_from_before_picks_deepest():
    """Bug 1: When content is above all headers on a page, pick deepest parent from prior pages."""
    service = ChunkingService()
    
    # Create parents: Chapter (L1, pages 10-28) and Section (L2, pages 13-15)
    parent_chapter = ParentChunk(
        chunk_id="chapter", report_id="test",
        hierarchy={"level_1": "Chapter II"},
        page_range_physical=(10, 28), page_range_logical=("10", "28"),
        toc_entry="Chapter II", toc_level=1,
    )
    parent_section = ParentChunk(
        chunk_id="section", report_id="test",
        hierarchy={"level_1": "Chapter II", "level_2": "2.3 Findings"},
        page_range_physical=(13, 15), page_range_logical=("13", "15"),
        toc_entry="2.3 Findings", toc_level=2,
        start_y_position=None,  # Started on page 13, no Y for page 15
    )
    parent_next = ParentChunk(
        chunk_id="next_section", report_id="test",
        hierarchy={"level_1": "Chapter II", "level_2": "2.4 Conclusions"},
        page_range_physical=(15, 20), page_range_logical=("15", "20"),
        toc_entry="2.4 Conclusions", toc_level=2,
        start_y_position=200.0,  # Starts at Y=200 on page 15
    )
    
    parents = [parent_chapter, parent_section, parent_next]
    page_index = service._build_page_parent_index(parents)
    
    # Content at Y=80 on page 15 (above 2.4's Y=200)
    result = service._find_best_parent_for_page(
        15, parents, page_index, content_bbox=[50, 80, 500, 100]
    )
    
    # Should pick "2.3 Findings" (level 2), NOT "Chapter II" (level 1)
    assert result.chunk_id == "section"
```

### Run All Tests
```bash
python -m pytest tests/ -v -k "chunking"
```

---

## Verification Checklist

- [ ] Bug 1: `parents_from_before` is sorted by `(-toc_level, -start_page)` before `[0]` selection
- [ ] Bug 3: `fallback_count` initialized before loop, incremented in else branch
- [ ] Bug 3: Per-item warning printed with page number and content type
- [ ] Bug 3: Summary printed after loop with count and percentage
- [ ] All existing tests pass: `python -m pytest tests/ -v`
- [ ] Pipeline output now shows fallback stats (run on test report to verify)
