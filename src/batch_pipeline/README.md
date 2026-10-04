# Phase 10: Overview & Summary Generation

Phase 10a runs at the end of `python -m src.parsing_pipeline.main`. All calls go to
Gemini on Vertex AI through `src.core.gemini_client` (GCP project billing, ADC
credentials) and complete within the run, so the job IDs are `gemini_sync_<timestamp>`.

Outputs, under `data/batch_jobs/`:

```
jobs/          job trackers and custom-ID mappings
overviews/     {report_id}_overview_llm.json
summaries/     {report_id}_summaries.json   (executive, journalist, deep_dive, simple, policy)
hierarchical/  {report_id}_hierarchical.json (chapter and section summaries)
```

The CLIs below re-run Phase 10a for reports that are already processed.

## CLI Commands Reference

### Submit Jobs
```bash
# Submit for all reports in data/processed/
python -m src.batch_pipeline.submit_jobs

# Submit for specific directory
python -m src.batch_pipeline.submit_jobs --dir path/to/jsons

# Submit specific files
python -m src.batch_pipeline.submit_jobs --files report1.json report2.json

# Overview only (skip summaries)
python -m src.batch_pipeline.submit_jobs --overview-only

# Summary only (skip overview)
python -m src.batch_pipeline.submit_jobs --summary-only

# Dry run (see what would be submitted)
python -m src.batch_pipeline.submit_jobs --dry-run
```

### Check Status
```bash
# Check latest job
python -m src.batch_pipeline.check_status

# Watch continuously until complete
python -m src.batch_pipeline.check_status --watch

# Custom polling interval (default: 60 seconds)
python -m src.batch_pipeline.check_status --watch --interval 30

# Check specific job
python -m src.batch_pipeline.check_status --job data/batch_jobs/job_20250131_120000.json

# List all jobs
python -m src.batch_pipeline.check_status --list
```

### Process Results
```bash
# Process latest job
python -m src.batch_pipeline.process_results

# Process specific job
python -m src.batch_pipeline.process_results --job data/batch_jobs/job_20250131.json

# Force reprocess completed job
python -m src.batch_pipeline.process_results --force
```

---

## Output Files

### Overview Files
Location: `data/processed/{report_id}_overview.json`

Contains:
- `basic_info`: Report metadata
- `table_of_contents`: TOC with page numbers
- `findings_summary`: Totals and breakdowns
- `findings_list`: All findings with details
- `recommendations`: All recommendations
- `audit_scope`: Period, coverage, entities (LLM extracted)
- `audit_objectives`: List of objectives (LLM extracted)
- `topics_covered`: Neutral topic names (LLM extracted)
- `glossary_terms`: Abbreviations and definitions (LLM extracted)

### Summary Files
Location: `data/batch_jobs/{report_id}_summaries.json`

Contains 5 variants:
- `executive`: Executive Brief for decision-makers
- `journalist`: News-style for general public
- `deep_dive`: Academic analysis for researchers
- `simple`: Plain language for everyone
- `policy`: Action-oriented for government officials

---
