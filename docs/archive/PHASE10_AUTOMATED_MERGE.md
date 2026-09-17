# Phase 10: Automated LLM Overview Merge

## Overview

The LLM overview merge process is now **fully automated** as part of the Phase 10 batch processing pipeline. When you run `process_results`, it automatically merges LLM-extracted data into the final overview files.

## Architecture

### Shared Merge Utility
- **Location**: `src/batch_pipeline/merge_utils.py`
- **Purpose**: Provides reusable merge logic for both automated and manual workflows
- **Key Functions**:
  - `find_llm_overview_file()` - Fuzzy matching to find LLM files (handles truncated names)
  - `merge_llm_overview_data()` - Merges LLM fields into main overview

### Usage Patterns

#### 1. Automated (Recommended)
Used during normal batch processing workflow:

```bash
# Submit batch jobs for Phase 10
python -m src.batch_pipeline.submit_jobs

# Check status (wait for completion)
python -m src.batch_pipeline.check_status --watch

# Process results - AUTOMATICALLY MERGES LLM DATA
python -m src.batch_pipeline.process_results
```

**What happens during `process_results`**:
1. Downloads batch results from Anthropic API
2. Processes overview extraction results → `data/batch_jobs/overviews/{report_id}_overview_llm.json`
3. Processes summary generation results → `data/batch_jobs/summaries/{report_id}_summaries.json`
4. **Automatically merges LLM data** using fuzzy matching
5. Creates final overview files → `data/processed/{report_id}_overview.json`

#### 2. Manual (Optional)
Use the standalone script for single reports or re-processing:

```bash
# Single report
python scripts/merge_llm_overview.py {report_id}

# All reports
python scripts/merge_llm_overview.py -all
```

**When to use manual mode**:
- Re-processing a single report after fixing LLM data
- Testing merge logic changes
- Recovering from partial failures

## Output Format

After merge, each `{report_id}_overview.json` contains:

```json
{
  "basic_info": { ... },
  "table_of_contents": [ ... ],
  "findings_summary": { ... },
  "findings_list": [ ... ],
  "recommendations": [ ... ],

  // LLM-extracted fields (merged automatically)
  "audit_scope": {
    "period": { "start": "...", "end": "...", "description": "..." },
    "geographic_coverage": ["..."],
    "sample_size": { "total": 0, "description": "..." },
    "entities_covered": ["..."]
  },
  "audit_objectives": ["...", "..."],
  "topics_covered": [
    {
      "name": "...",
      "description": "...",
      "sections": ["..."],
      "page_start": 0,
      "page_end": 0
    }
  ],
  "glossary_terms": [
    {
      "abbreviation": "...",
      "term": "...",
      "definition": "...",
      "category": "..."
    }
  ],

  "_metadata": {
    "generated_at": "2026-02-20T...",
    "source_json": "data/processed/{report_id}_chunks.json",
    "llm_extraction_available": true,
    "llm_extraction_path": "data/batch_jobs/overviews/{hash}_{report_id}_overview_llm.json",
    "llm_merged_at": "2026-02-20T...",
    "llm_fields_merged": 4,
    "summaries_available": true,
    "summaries_path": "data/batch_jobs/summaries/{report_id}_summaries.json",
    "phase": "10"
  }
}
```

## Fuzzy Matching Algorithm

The merge utility handles truncated filenames from batch processing:

1. **Exact match**: Look for full report_id in filename
2. **Partial match**: Try progressively shorter prefixes (e.g., `2025_04_CAG_Report_on_Union...`)
3. **Year + Report number**: Match on `2025_04` pattern

This ensures LLM files with truncated names (e.g., `ov_82ba644c_2025_04_CAG_Report_on_Union_Government_Accounts_2022_overview_llm.json`) are correctly matched to full report IDs.

## Merge Statistics

The automated merge tracks and reports:
- **Files processed**: Total overview files created
- **LLM merges**: How many reports had LLM data available
- **Field coverage**: Average number of fields merged (out of 4: scope, objectives, topics, glossary)
- **Summaries**: Which reports have AI-generated summaries

Example output:
```
🔄 Creating Final Overview Files...
   Output: data/processed/
------------------------------------------------------------
  ✅ 2025_04_CAG_Report_on_Union_Government_Account... [LLM:✓ 4/4 SUM:✓]
  ✅ 2023_19_CAG_Performance_Audit_of_Implementati... [LLM:✓ 4/4 SUM:✓]
  ✅ 2025_14_Compliance_Audit_on_Direct_taxes_for_... [LLM:✓ 4/4 SUM:✓]

   Overview files created: 14, failed: 0
   LLM data merged: 14/14 reports (avg 4.0/4 fields)
```

## Benefits of Automated Approach

1. **Zero manual steps** - No need to remember to run merge script
2. **Consistent workflow** - Same logic for automated and manual processing
3. **Detailed tracking** - Merge statistics in batch processing logs
4. **Error recovery** - Can re-run manual merge if needed
5. **Maintainable** - Single source of truth for merge logic

## Troubleshooting

### Issue: LLM data not merged
**Check**:
1. Did batch jobs complete? Run `python -m src.batch_pipeline.check_status`
2. Are LLM files present? Check `data/batch_jobs/overviews/`
3. Does the metadata show `llm_extraction_available: false`?

**Solution**: Re-run `python -m src.batch_pipeline.process_results --force`

### Issue: Only some fields merged
**Check**: The `_metadata.llm_fields_merged` count (should be 4)

**Possible causes**:
- LLM extraction failed for some fields (null in LLM file)
- Batch processing error
- Prompt issues during extraction

**Solution**: Check the LLM overview file directly for null fields

### Issue: Summaries not available
**Check**: The `_metadata.summaries_available` flag

**Possible causes**:
- Summary batch job failed
- Summary generation returned errors

**Solution**: Check `data/batch_jobs/summaries/` and batch processing logs

## Migration Notes

**Before** (manual process):
```bash
# After batch processing
python -m src.batch_pipeline.process_results

# THEN manually run merge
python scripts/merge_llm_overview.py -all
```

**After** (automated):
```bash
# After batch processing - merge happens automatically
python -m src.batch_pipeline.process_results

# Done! Overview files are ready with LLM data merged
```

## Related Files

- `src/batch_pipeline/merge_utils.py` - Shared merge logic
- `src/batch_pipeline/process_results.py` - Automated batch processing (lines 511-575)
- `scripts/merge_llm_overview.py` - Manual merge script (uses same utilities)
- `src/api/routes/overview.py` - API endpoint serving merged data
