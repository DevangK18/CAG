# Hierarchy Regression: Root Cause Analysis

## Evidence Summary

| Metric | Bharatmala | Direct Tax |
|--------|:----------:|:----------:|
| Scaffolding parents created | **5** | **37** |
| Enricher parents created | **466** | **263** |
| Children assigned to enricher parents | 1,751 / 1,778 (98.5%) | 737 / 746 (98.8%) |
| Children with hierarchy ≠ their parent's hierarchy | **1,766 / 1,778 (99.3%)** | similar |

The enricher IS working — it detects hundreds of sub-sections and reassigns children correctly. But the children's `hierarchy` dict is never updated to match. This is why the output looks flat.

---

## Three Interacting Bugs

### Bug 1: Scaffolding Accepts Sparse Embedded Bookmarks

**File:** `scaffolding_service.py`, line 368
**Change:** `embed_toc_min_entries` lowered from `5` → `3`

```python
# scaffolding_service.py line 368
def __init__(self,
    embed_toc_min_entries: int = 3,  # PHASE 1 FIX: Lowered from 5
    ...
```

**What happens:** Bharatmala's PDF has only ~3 embedded bookmarks: `Preface (L1)`, `Executive Summary (L2)`, `Annexures (L2)`. The old pipeline (threshold=5) **rejected** these as too sparse and fell through to the heuristic TOC generator, which produced a rich 200+ entry TOC across 4 levels by analyzing font sizes.

The new pipeline (threshold=3) **accepts** these 3 bookmarks as the full TOC. The heuristic path is never reached. Result: the entire document scaffolding is just 3 entries.

**Impact:** ChunkingService creates only 3-5 ParentChunks. The "Annexures" parent covers pages 4–263 (the entire document), so 99.5% of children get assigned to it with hierarchy `{level_1: "Preface", level_2: "Annexures"}`.

**Fix:**
```python
# Option A: Restore threshold
embed_toc_min_entries: int = 5

# Option B (better): Add quality check — require bookmarks to have 
# meaningful page coverage, not just entry count
def _validate_embedded_toc(self, toc, total_pages):
    if len(toc) < 5:  # Need enough entries
        return False
    levels = {entry[0] for entry in toc}
    if len(levels) < 2:  # Need depth
        return False
    # NEW: Check page coverage
    pages = {entry[2] for entry in toc if len(entry) >= 3}
    coverage = len(pages) / max(total_pages, 1)
    if coverage < 0.1:  # Bookmarks must cover >10% of pages
        return False
    return True
```

---

### Bug 2: Hierarchy Enricher Writes to Wrong Field (THE CRITICAL BUG)

**File:** `hierarchy_enricher.py`, lines 700–713
**Method:** `_update_child_hierarchy()`

```python
# hierarchy_enricher.py lines 700-713
def _update_child_hierarchy(self, child, new_parent_id, parent_lookup, new_parents):
    ...
    # BUG: Writes to child["metadata"]["hierarchy"]
    if "metadata" not in child:
        child["metadata"] = {}
    if "hierarchy" not in child["metadata"]:
        child["metadata"]["hierarchy"] = {}
    
    new_hierarchy = new_parent.get("hierarchy", {})
    if isinstance(new_hierarchy, dict):
        for key, value in new_hierarchy.items():
            child["metadata"]["hierarchy"][key] = value  # ← WRONG LOCATION
```

**What happens:** The enricher detects 466 sub-sections for Bharatmala (chapters, numbered sections like 1.1, 1.2, etc.), creates proper parent dicts, and reassigns 1,751 children via `child["parent_chunk_id"]`. The `parent_chunk_id` update succeeds.

But the hierarchy update goes to `child["metadata"]["hierarchy"]` — a nested location that the assembly service **never reads**. The assembly reads `child["hierarchy"]` (top-level key), which still contains the original sparse scaffolding value: `{level_1: "Preface", level_2: "Annexures"}`.

**Proof:** 1,766/1,778 children have `child.hierarchy ≠ parent.hierarchy`. Children point to enricher parents with rich hierarchy, but their own hierarchy field was never updated.

**Fix:**
```python
def _update_child_hierarchy(self, child, new_parent_id, parent_lookup, new_parents):
    new_parent = None
    for p in new_parents:
        if p.get("chunk_id") == new_parent_id:
            new_parent = p
            break
    
    if not new_parent:
        return
    
    # FIX: Write to top-level "hierarchy" field (what assembly reads)
    new_hierarchy = new_parent.get("hierarchy", {})
    if isinstance(new_hierarchy, dict):
        child["hierarchy"] = new_hierarchy.copy()  # ← CORRECT LOCATION
    
    # Also update metadata for consistency
    if "metadata" not in child or not isinstance(child.get("metadata"), dict):
        child["metadata"] = {}
    child["metadata"]["hierarchy"] = new_hierarchy.copy()
```

---

### Bug 3: Enricher Inherits Broken Base Hierarchy from Mega-Parents

**File:** `hierarchy_enricher.py`, lines 588–623
**Method:** `_create_sub_parent()`

```python
# hierarchy_enricher.py line 606
parent_hierarchy = parent.get("hierarchy", {})
if not isinstance(parent_hierarchy, dict):
    parent_hierarchy = {}
hierarchy = parent_hierarchy.copy()          # Copies {level_1: "Preface", level_2: "Annexures"}
hierarchy[f"level_{section.level}"] = section.title  # Overwrites ONE level
```

**What happens:** When the enricher detects "Chapter 1" (L1) inside the mega-parent "Annexures" (L2), it builds the new parent's hierarchy by copying the mega-parent's hierarchy and adding its own level:

```
Base (from "Annexures" parent): {level_1: "Preface", level_2: "Annexures"}
Enricher adds level_1:          {level_1: "Chapter 1", level_2: "Annexures"}  ← WRONG!
```

The result says Chapter 1 is under "Annexures" at level_2, which is nonsensical. The correct hierarchy should be `{level_1: "Chapter 1"}` only — the enricher should NOT inherit from the mega-parent when it's creating a HIGHER or EQUAL level section.

Similarly for "1.1 About Ministry..." (detected at L2):
```
Base: {level_1: "Preface", level_2: "Annexures"}
Add level_2: {level_1: "Preface", level_2: "1.1 About Ministry..."}
```

Level_1 should be "Chapter 1", not "Preface". The enricher blindly inherits the scaffolding parent's hierarchy instead of building ancestry from its OWN detected structure.

**Fix:**
```python
def _create_sub_parent(self, section, parent, report_id):
    ...
    # FIX: Build hierarchy from detected section structure, not mega-parent
    parent_hierarchy = parent.get("hierarchy", {})
    
    # Only inherit levels ABOVE the detected section's level
    # AND only if they make structural sense
    hierarchy = {}
    for key, value in parent_hierarchy.items():
        level_num = int(key.split("_")[1])
        if level_num < section.level:
            hierarchy[key] = value
    
    # Add the detected section at its level
    hierarchy[f"level_{section.level}"] = section.title
    ...
```

Additionally, the enricher should build a proper parent chain from its OWN detected sections (e.g., if it detects both "Chapter 1" at L1 and "1.1 Overview" at L2, the L2 section should reference the L1 section, not the scaffolding mega-parent).

---

## Bug Interaction Diagram

```
ScaffoldingService                 ChunkingService              HierarchyEnricher
      │                                  │                            │
      │  3 sparse TOC entries            │                            │
      │  (Preface, Exec Summary,         │                            │
      │   Annexures)                     │                            │
      ├─────────────────────────────────►│                            │
      │  BUG 1: accepts sparse           │                            │
      │  bookmarks (threshold=3)         │  Creates 5 ParentChunks    │
      │                                  │  with mega-page-ranges     │
      │                                  │                            │
      │                                  │  Children inherit sparse   │
      │                                  │  hierarchy from parents:   │
      │                                  │  {L1:"Preface",            │
      │                                  │   L2:"Annexures"}          │
      │                                  │                            │
      │                                  ├───────────────────────────►│
      │                                  │                            │
      │                                  │  Enricher detects 466      │
      │                                  │  sub-sections ✓            │
      │                                  │  Creates new parents ✓     │
      │                                  │  Reassigns children ✓      │
      │                                  │                            │
      │                                  │  BUG 2: writes hierarchy   │
      │                                  │  to metadata.hierarchy     │
      │                                  │  (assembly reads hierarchy)│
      │                                  │                            │
      │                                  │  BUG 3: new parents have   │
      │                                  │  {L1:"Chapter 1",          │
      │                                  │   L2:"Annexures"} ← wrong  │
      │                                  │                            │
      │                                  │◄───────────────────────────┤
      │                                  │                            │
      │                    Assembly uses child["hierarchy"]           │
      │                    which was NEVER UPDATED                    │
      │                    Output: {L1:"Preface", L2:"Annexures"}     │
      │                    for 99.5% of chunks                        │
```

---

## Fix Priority

| # | Bug | Severity | Fix Effort | Impact |
|---|-----|----------|-----------|--------|
| 1 | **Enricher writes to wrong field** | P0 CRITICAL | 5 min | Fixes hierarchy for both reports immediately. The enricher already detects correct sub-sections. |
| 2 | **Enricher inherits mega-parent hierarchy** | P0 HIGH | 30 min | Without this, even after fix #1, hierarchies contain nonsense like `{L1: "Chapter 1", L2: "Annexures"}` |
| 3 | **Sparse bookmark acceptance** | P1 MEDIUM | 15 min | Restore threshold=5 OR add page-coverage quality check. Reduces reliance on enricher. |

**Fix order:** Apply #1 first (instant win), then #2, then #3. After #1 alone, the 466 enricher-detected sections will propagate to children — restoring section-level granularity even if the scaffolding TOC is sparse.

---

## How to Verify Fixes

After applying fixes, re-run pipeline and check:

```python
# Test 1: Hierarchy depth (should be 3-4 levels, not 1-2)
from collections import Counter
depths = Counter()
for c in child_chunks:
    depths[len(c["hierarchy"])] += 1
print(depths)  # Should show {3: ~900, 4: ~300, 2: ~400, 1: ~100}

# Test 2: Concentration (should be <15%, not 99.5%)
parents = Counter(c["parent_chunk_id"] for c in child_chunks)
max_conc = parents.most_common(1)[0][1] / len(child_chunks)
print(f"Max concentration: {max_conc:.1%}")  # Should be <15%

# Test 3: Hierarchy matches parent (should be 100%, not 0.7%)
mismatches = sum(1 for c in child_chunks 
    if c["hierarchy"] != parent_map[c["parent_chunk_id"]]["hierarchy"])
print(f"Mismatches: {mismatches}")  # Should be 0
```
