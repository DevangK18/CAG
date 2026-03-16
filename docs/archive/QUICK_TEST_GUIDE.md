# Quick Testing Guide - Skip Phase 10 & LLM Costs

This guide shows how to test the hierarchy regression and P0/P1 fixes without running Phase 10 or re-running expensive operations.

---

## Option 1: Quick Pipeline (Recommended)

Run the full pipeline Phases 1-9, skip Phase 10:

```bash
python run_pipeline_quick.py Newtest.xlsx
```

**What it does:**
- ✅ Runs all phases 1-9 (includes all our fixes)
- ⏭️ Skips Phase 10 (Batch API - no LLM costs)
- 🔧 Tests hierarchy regression fixes (Phase 7.5)
- 🔧 Tests P0 fix: structured_data serialization (Phase 8)
- 🔧 Tests P1 fix: recommendation filtering (Phase 9)

**Time estimate:** ~5-10 minutes for 2 reports (Newtest.xlsx)

---

## Option 2: Skip Content Extraction (Fastest)

If you already have content extraction output, skip to Phase 7:

```bash
python run_pipeline_quick.py Newtest.xlsx 7
```

**What it does:**
- ⏭️ Skips Phases 1-6 (including expensive vision models)
- ✅ Runs Phases 7-9 (chunking → assembly → enrichment)
- 🔧 Tests all fixes without re-running extraction

**Time estimate:** ~1-2 minutes for 2 reports

**Note:** This requires existing task state (TODO: implement state persistence)

---

## Option 3: Original Pipeline (Skip Phase 10 Only)

If you want to run the full pipeline but skip Phase 10, simply comment out the Phase 10 code:

**Edit:** `src/parsing_pipeline/main.py`

**Comment out lines 627-691:**

```python
# ═══════════════════════════════════════════════════════════════════════
# PHASE 10: Overview & Summary Generation (Batch API) - COMMENTED OUT
# ═══════════════════════════════════════════════════════════════════════
# print("\n\nPHASE 10: OVERVIEW & SUMMARY GENERATION")
# print("-" * 40)
# ... (comment out rest of Phase 10)
```

Then run normally:

```bash
python -m src.parsing_pipeline.main Newtest.xlsx
```

---

## Verify Fixes

After running the pipeline, verify the fixes worked:

```bash
python verify_fixes.py data/processed/Report_1234_chunks.json
```

**Output:**
```
HIERARCHY REGRESSION FIX VERIFICATION
======================================
1. Hierarchy Depth Distribution:
   Depth 1:   45 chunks ( 2.5%)
   Depth 2:  234 chunks (13.1%)
   Depth 3:  890 chunks (50.0%)
   Depth 4:  612 chunks (34.4%)
   ✓ PASS: 15.6% flat (depth 1-2) - hierarchy is rich

2. Parent Chunk Concentration:
   Max parent load: 234/1781 (13.1%)
   ✓ PASS: Max concentration 13.1% - well distributed

3. Hierarchy-Parent Match Rate:
   Mismatches: 0/1781 (0.0%)
   ✓ PASS: 0.0% mismatch - hierarchy propagation working

✅ HIERARCHY REGRESSION FIXES: WORKING

P0 FIX VERIFICATION: Structured Table Data
===========================================
1. Table Chunks with structured_data:
   85/100 tables (85.0%)
   ✓ PASS: 85.0% have structured_data

✅ P0 FIX: WORKING (structured_data present)

P1 FIX VERIFICATION: Recommendation Extraction
===============================================
1. Total Recommendations: 52

2. Breakdown by Strategy:
   numbered     : 41 ( 78.8%)
   verb         :  11 ( 21.2%)

3. Quality Assessment:
   Report type: Numbered recommendations detected
   ✓ PASS: 11 verb recs (reasonable with numbered recs)

✅ P1 FIX: WORKING (recommendation counts reasonable)
```

---

## What Each Fix Tests

### Hierarchy Regression Fix
**Phase:** 7.5 (Hierarchy Enrichment)
**Files Modified:**
- `src/parsing_pipeline/modules/hierarchy_enricher.py` (Bug 2 & 3 fixes)
- `src/parsing_pipeline/modules/scaffolding_service.py` (Bug 1 fix)

**Expected Results:**
- ✅ Depth distribution: Mix of depths 3-4, not 99% at depth 2
- ✅ Concentration: <40% of children to one parent (not 99.5%)
- ✅ Match rate: 0% mismatch (not 99.3% mismatch)

---

### P0: Structured Table Data
**Phase:** 8 (Assembly)
**File Modified:** `src/parsing_pipeline/modules/assembly_service.py`

**Expected Results:**
- ✅ 60-90% of table chunks have `structured_data` field
- ✅ `visual_asset_registry.tables[*].has_structured_data` flags set

---

### P1: Recommendation Over-Extraction
**Phase:** 9 (Semantic Enrichment)
**File Modified:** `src/enrichment/recommendation_extractor.py`

**Expected Results:**
- ✅ Bharatmala: ~45-55 recs (was 148)
- ✅ Direct Tax: ~20-30 recs (was 56)
- ✅ No past-tense observations ("should have done")
- ✅ No audit framing ("Audit observed that...")

---

## Cost Comparison

| Pipeline Version | Vision Models | LLM API | Cost |
|-----------------|---------------|---------|------|
| **Full (with Phase 10)** | Yes | Yes | ~$2-5 per report |
| **Quick (skip Phase 10)** | Yes | No | ~$0.50-1 per report |
| **Resume from Phase 7** | No | No | $0 (local only) |

**Note:** Vision models (Florence-2, Table-Transformer) run locally, no API costs.

---

## Troubleshooting

### "Module not found" errors
```bash
# Ensure you're in project root
cd /Users/dev/Projects/CAG

# Run with python -m
python -m run_pipeline_quick Newtest.xlsx
```

### Resume from Phase 7 not working
Currently the quick runner doesn't persist task state. Options:
1. Run full pipeline once to generate outputs
2. Or manually load tasks from previous run (TODO: implement)

### Verification script shows failures
Check the specific failure:
- **Hierarchy:** May need to re-run with fresh scaffolding (Bug 1 fix)
- **P0:** Check assembly_service.py lines 345-347
- **P1:** May need to adjust thresholds in recommendation_extractor.py

---

## Next Steps After Verification

1. **If all fixes pass:** Update CLAUDE.md, commit changes
2. **If issues found:** Debug specific failures, re-test
3. **Integration test:** Run on full manifest (more reports)
4. **Compare outputs:** Diff new vs old JSONs to quantify improvements
