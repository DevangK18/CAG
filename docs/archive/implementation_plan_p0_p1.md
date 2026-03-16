# Implementation Plan: P0 Structured Table Data + P1 Recommendation Over-Extraction

## P0: Structured Table Data Missing from Output JSON

### Root Cause (verified)

`assembly_service.py` → `_serialize_child_chunks()` (line 280-348) manually builds the output dict from `ChildChunk` fields but **never includes `structured_data`**. The data flows correctly through the entire pipeline up to this point:

```
StructuredTableExtractor.extract() → StructuredTable object ✓
ExtractedContent.structured_data = table.model_dump() ✓
ChunkingService line 483: ChildChunk(structured_data=...) ✓
AssemblyService._serialize_child_chunks(): ← DROPS IT HERE
```

Both reports show 0/100 and 0/61 table chunks with `structured_data` in output.

### Fix: 1 file, 1 edit

**File:** `src/parsing_pipeline/modules/assembly_service.py`

**Edit:** In `_serialize_child_chunks()`, add `structured_data` to the chunk_dict.

Find the block that builds `chunk_dict` (around line 301-344). After the `"metadata"` block, add the structured_data field. The logic:

```python
# In _serialize_child_chunks(), after the "metadata" dict is built and closed:

# P0-1: Include structured table data for queryable tables
if child.structured_data is not None:
    chunk_dict["structured_data"] = child.structured_data
```

Place this AFTER line ~344 (the `enriched_chunks.append(chunk_dict)` call should come after this new block).

**Why not inside `metadata`?** The `_build_visual_asset_registry()` method (line 563) already reads `chunk.get("structured_data")` at the top level, so it must be a top-level key to maintain consistency.

### Verification

After fix, re-run pipeline on either report, then:
```python
tables = [c for c in data["child_chunks"] if c["content_type"] == "table_markdown"]
has_sd = sum(1 for t in tables if t.get("structured_data"))
print(f"{has_sd}/{len(tables)} tables have structured_data")
# Expected: >0 (likely 60-90% depending on how many tables have valid markdown)
```

Also confirm `visual_asset_registry.tables[*].has_structured_data` shows `true` for those tables.

---

## P1: Recommendation Over-Extraction

### Root Cause (verified with data)

**Bharatmala:** 148 recs extracted (report has 41 actual recommendations).
- 41 numbered (correct — "Recommendation No. 1" through "Recommendation No. 41")
- 107 verb-based (false positives — audit observations that use "should/may/must")
- 0 structural

**Direct Tax:** 56 recs extracted.
- 14 structural (7 have no action verbs — introductory paragraphs from rec sections)
- 42 verb-based (mix of real recs and observations)
- 0 numbered

Three sub-problems:

1. **Verb strategy is indiscriminate** — any paragraph with "Ministry should..." matches, even when it's an audit *observation* about past behaviour, not a forward-looking recommendation
2. **Structural strategy too permissive** — admits paragraphs >150 chars even without action verbs (the `has_action` gate is bypassed for long text)
3. **No global deduplication or sanity bounds** — numbered recs + verb recs from the *same* executive summary text can both survive since the 80-char prefix dedup doesn't catch paraphrased overlap

### Fix Strategy: 3 targeted changes in `recommendation_extractor.py`

All edits in: `src/enrichment/recommendation_extractor.py`

---

#### Fix 1: Tighten verb strategy — reject past-tense observations

**Method:** `_extract_verb_based()` (line 282)

The verb patterns currently match both forward-looking recommendations ("Ministry should ensure...") and backward-looking observations ("Ministry should have ensured...", "The Government should have taken steps..."). Past-tense modal constructions are audit findings, not recommendations.

**Add a rejection gate** after the pattern match succeeds (around line 293-310):

```python
def _extract_verb_based(self, child_chunks, report_id):
    recs = []
    for chunk in child_chunks:
        if chunk.get("content_type") in ("table_markdown", "image_caption"):
            continue
        content = chunk.get("content", "")

        for pattern in self._verb:
            match = pattern.search(content)
            if match:
                rec_text = content.strip()
                if len(rec_text) < 30:
                    continue

                # NEW: Reject past-tense observations (findings, not recommendations)
                # "should have done", "may have been", "must have resulted"
                if re.search(
                    r'\b(?:should|may|must|could)\s+have\s+(?:been|done|taken|ensured|completed|resulted|prevented)',
                    rec_text, re.IGNORECASE
                ):
                    continue

                # NEW: Reject chunks that are clearly audit observations
                # Key signal: "Audit observed/noticed/found that..." framing
                if re.search(
                    r'\b(?:Audit|CAG|We)\s+(?:observed|noticed|found|noted)\b',
                    rec_text, re.IGNORECASE
                ):
                    continue

                # NEW: Require the recommendation verb to appear in the
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
                break  # One rec per chunk
    return recs
```

---

#### Fix 2: Tighten structural strategy — require action verbs always

**Method:** `_extract_from_sections()` (line 210)

Current code (line 237): `if not has_action and len(content) < 150: continue` — this lets through ANY paragraph >150 chars, even introductory text like "This chapter discusses 194 high-value cases..."

**Change:** Always require at least one action verb, regardless of length.

```python
# REPLACE the current has_action gate (lines 232-238):

# Skip non-recommendation text (introductory paragraphs)
has_action = bool(re.search(
    r'\b(?:should|may\s+consider|must|needs?\s+to|is\s+required|ensure|'
    r'recommend(?:s|ed)?|review|strengthen|take\s+(?:steps|action|measures)|'
    r'initiate|improve|complete|institute|expedite|fix)\b',
    content, re.IGNORECASE
))
if not has_action:
    continue  # CHANGED: Always skip, regardless of length
```

---

#### Fix 3: Add numbered-aware dedup — suppress verb recs when numbered recs exist

**Method:** `extract_all()` (line 111)

When a report has explicit numbered recommendations (like Bharatmala's 41), the verb strategy mostly catches the same recommendations restated in the executive summary or body text. Add a heuristic: if numbered recs cover the topic well, cap/suppress verb extraction.

**Add after strategy 3 runs, before enrichment (around line 177):**

```python
# ──────────────────────────────────────────────────────────
# Strategy 4: Global dedup and sanity check
# ──────────────────────────────────────────────────────────

# If we found numbered recs, verb recs are likely duplicates restated elsewhere.
# Apply stricter overlap detection: reject verb recs whose text substantially 
# overlaps with any numbered rec (shared 5+ word sequences).
if numbered_recs:
    all_recs = self._deduplicate_against_numbered(all_recs, numbered_recs)
```

**New method to add:**

```python
def _deduplicate_against_numbered(
    self, all_recs: List[ExtractedRecommendation],
    numbered_recs: List[ExtractedRecommendation],
) -> List[ExtractedRecommendation]:
    """
    Remove verb/structural recs that substantially overlap with numbered recs.
    
    Numbered recs are highest confidence — if a verb rec covers the same
    content (shares a 6+ word phrase), it's a restated duplicate.
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
```

---

### Expected Impact

| Report | Before | After (estimated) |
|--------|-------:|---------:|
| Bharatmala | 148 (41 numbered + 107 verb) | ~45–55 (41 numbered + 4–14 unique verb) |
| Direct Tax | 56 (14 structural + 42 verb) | ~20–30 (7 structural + 13–23 verb) |

The numbered extraction for Bharatmala is already correct and stays untouched.

---

## Files Changed Summary

| File | Change | Risk |
|------|--------|------|
| `assembly_service.py` | Add `structured_data` to serialized output | Minimal — additive only |
| `recommendation_extractor.py` | Tighten verb filter, fix structural gate, add numbered dedup | Medium — test both report types |

## Testing Checklist

```bash
# After applying fixes, re-run pipeline on both reports, then:

# P0: Structured data
python3 -c "
import json
data = json.load(open('data/processed/REPORT_chunks.json'))
tables = [c for c in data['child_chunks'] if c['content_type']=='table_markdown']
has_sd = sum(1 for t in tables if t.get('structured_data'))
print(f'structured_data: {has_sd}/{len(tables)} tables')
registry = data.get('visual_asset_registry', {})
has_sd_reg = sum(1 for t in registry.get('tables',[]) if t.get('has_structured_data'))
print(f'registry has_structured_data: {has_sd_reg}')
"

# P1: Recommendation count
python3 -c "
import json
from collections import Counter
data = json.load(open('data/processed/REPORT_enriched.json'))
recs = data['semantic_enrichment']['recommendations']
strategies = Counter(r['extraction_strategy'] for r in recs)
print(f'Total: {len(recs)}, breakdown: {dict(strategies)}')
# Bharatmala: expect ~45-55 total
# Direct Tax: expect ~20-30 total
"
```
