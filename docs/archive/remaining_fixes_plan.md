# Remaining Fixes — Implementation Plan

## P0: Hierarchy Sync Timing Bug

**Problem:** `_update_child_hierarchy()` copies parent hierarchy before it's fully built. 1,286 Bharatmala children missing `level_2`, 224 Direct Tax children have stale `level_1`.

**File:** `src/parsing_pipeline/modules/hierarchy_enricher.py`

**Fix:** Add a post-processing pass at the END of the main `enrich()` method, after all parent creation and child reassignment is complete. This runs once and force-syncs every child to its final parent.

Find the end of the `enrich()` method (the public entry point that calls `_detect_sections()`, `_create_sub_parent()`, `_update_child_hierarchy()` etc. and returns the enriched data). After all existing enrichment logic, before the return:

```python
# ── POST-PROCESS: Force-sync child hierarchies to final parent state ──
# This fixes timing issues where _update_child_hierarchy() ran before
# parent hierarchy was fully built (e.g., missing inherited levels).
parent_lookup_final = {p.get("chunk_id"): p for p in all_parents}
synced = 0
for child in child_chunks:
    pid = child.get("parent_chunk_id", "")
    parent = parent_lookup_final.get(pid)
    if not parent:
        continue
    parent_h = parent.get("hierarchy", {})
    if child.get("hierarchy") != parent_h:
        child["hierarchy"] = parent_h.copy()
        if isinstance(child.get("metadata"), dict):
            child["metadata"]["hierarchy"] = parent_h.copy()
        synced += 1
if synced > 0:
    print(f"  Hierarchy post-sync: fixed {synced} child↔parent mismatches")
```

Where `all_parents` is the complete list of parents (original scaffolding + newly created enricher parents) and `child_chunks` is the list of child dicts being enriched. Adapt variable names to match the method's locals.

**Expected result:** 0 mismatches for both reports.

---

## P1: Verb Recs — Section-Type Filter

**Problem:** 23/26 remaining Bharatmala verb recs are false positives — quotes from policy documents, legal provisions, and contract clauses in non-recommendation sections.

**File:** `src/enrichment/recommendation_extractor.py`

**Fix:** In `_extract_verb_based()`, reject chunks whose parent section is classified as a non-recommendation section type. The section type is inferable from the chunk's hierarchy.

Add to `_extract_verb_based()`, right after the existing `if chunk.get("content_type") in ("table_markdown", "image_caption"): continue` guard:

```python
# P1 FIX: Reject verb matches from sections that quote rules, not make recommendations
hierarchy = chunk.get("hierarchy", {})
section_context = " ".join(str(v).lower() for v in hierarchy.values())
if any(indicator in section_context for indicator in [
    "annexure", "appendix", "abbreviation", "glossary",
    "audit criteria", "audit scope", "audit methodology",
    "preface", "acknowledgement",
]):
    continue
```

Also add a second filter after the pattern match succeeds (inside the `if match:` block, alongside the existing past-tense/observation/position filters):

```python
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
```

**Expected result:** Bharatmala verb recs drop from 26 → ~3. Direct Tax largely unaffected (its verb recs already reference CBDT directives correctly).

---

## P2: Direct Tax Depth-3 Loss (Investigation)

**Problem:** OLD had 9 chunks at depth 3, V2 has 0.

**Not a code fix — investigation only.** Run this after P0 sync fix is applied:

```python
# Check if P0 sync fix restores depth 3
from collections import Counter
depths = Counter(len(c["hierarchy"]) for c in child_chunks)
print(f"Depth distribution: {dict(sorted(depths.items()))}")
# If still 0 at depth 3, check if enricher detects L3 sections for Direct Tax
```

The P0 sync fix may resolve this automatically — if enricher parents have 3-level hierarchies that weren't propagating to children due to the timing bug, syncing will restore them. If not, it's a minor issue (1.2% of chunks) likely caused by the enricher's section detection not finding L3-level headings in Direct Tax's formatting.

---

## Files Modified

| File | Fix | Lines |
|------|-----|-------|
| `hierarchy_enricher.py` | P0: Add post-sync pass at end of `enrich()` | ~15 lines |
| `recommendation_extractor.py` | P1: Section-type + legal-quote filters in `_extract_verb_based()` | ~20 lines |

## Verification

```bash
# After applying both fixes, re-run pipeline, then:
python3 -c "
import json
from collections import Counter
data = json.load(open('data/processed/REPORT_chunks.json'))
children = data['child_chunks']
parents = {p['chunk_id']: p for p in data['parent_chunks']}

# P0: Should be 0
mismatches = sum(1 for c in children if c['hierarchy'] != parents[c['parent_chunk_id']]['hierarchy'])
print(f'Hierarchy mismatches: {mismatches}')

# P2: Check depth 3
depths = Counter(len(c['hierarchy']) for c in children)
print(f'Depths: {dict(sorted(depths.items()))}')
"

python3 -c "
import json
from collections import Counter
data = json.load(open('data/processed/REPORT_enriched.json'))
recs = data['semantic_enrichment']['recommendations']
strats = Counter(r['extraction_strategy'] for r in recs)
print(f'Recs: {len(recs)}, {dict(strats)}')
# Bharatmala: expect ~44 (41 numbered + ~3 verb)
# Direct Tax: expect ~15
"
```
