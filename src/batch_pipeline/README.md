# Phase 10: Overview & Summary Generation

## Quick Setup Guide

### 1. Copy Files to Your Project

Copy the `batch_pipeline` folder to your `services/` directory:

```
CAG/
├── services/
│   ├── batch_pipeline/          ← COPY THIS ENTIRE FOLDER
│   │   ├── __init__.py
│   │   ├── batch_service.py
│   │   ├── phase10_service.py
│   │   ├── prompts/
│   │   │   ├── __init__.py
│   │   │   ├── overview_extraction.py
│   │   │   └── summary_variants.py
│   │   ├── submit_jobs.py
│   │   ├── check_status.py
│   │   └── process_results.py
│   │
│   ├── api/
│   │   └── routes/
│   │       ├── overview.py      ← ADD THIS FILE
│   │       └── summaries.py     ← ADD THIS FILE
│   │
│   ├── parsing_pipeline/        (existing)
│   └── rag_pipeline/            (existing)
```

### 2. Create Data Directory

```bash
mkdir -p data/batch_jobs
```

### 3. Verify Anthropic API Key

Make sure your `.env` file has:
```
ANTHROPIC_API_KEY=sk-ant-...
```

### 4. Run Phase 10 on Existing Reports

```bash
# Step 1: Submit batch jobs
python -m services.batch_pipeline.submit_jobs

# Step 2: Check status (batches typically complete in 1-2 hours)
python -m services.batch_pipeline.check_status --watch

# Step 3: Process results when complete
python -m services.batch_pipeline.process_results
```

---

## CLI Commands Reference

### Submit Jobs
```bash
# Submit for all reports in data/processed/
python -m services.batch_pipeline.submit_jobs

# Submit for specific directory
python -m services.batch_pipeline.submit_jobs --dir path/to/jsons

# Submit specific files
python -m services.batch_pipeline.submit_jobs --files report1.json report2.json

# Overview only (skip summaries)
python -m services.batch_pipeline.submit_jobs --overview-only

# Summary only (skip overview)
python -m services.batch_pipeline.submit_jobs --summary-only

# Dry run (see what would be submitted)
python -m services.batch_pipeline.submit_jobs --dry-run
```

### Check Status
```bash
# Check latest job
python -m services.batch_pipeline.check_status

# Watch continuously until complete
python -m services.batch_pipeline.check_status --watch

# Custom polling interval (default: 60 seconds)
python -m services.batch_pipeline.check_status --watch --interval 30

# Check specific job
python -m services.batch_pipeline.check_status --job data/batch_jobs/job_20250131_120000.json

# List all jobs
python -m services.batch_pipeline.check_status --list
```

### Process Results
```bash
# Process latest job
python -m services.batch_pipeline.process_results

# Process specific job
python -m services.batch_pipeline.process_results --job data/batch_jobs/job_20250131.json

# Force reprocess completed job
python -m services.batch_pipeline.process_results --force
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

## API Endpoints

### Register Routes in main.py

Add to your `services/api/main.py`:

```python
from routes import overview, summaries

# In app setup:
app.include_router(overview.router)
app.include_router(summaries.router)
```

### Available Endpoints

**Overview:**
- `GET /reports/{report_id}/overview` - Complete overview
- `GET /reports/{report_id}/toc` - Table of Contents
- `GET /reports/{report_id}/findings` - Filterable findings
- `GET /reports/{report_id}/topics` - Topics covered
- `GET /reports/{report_id}/glossary` - Glossary terms
- `GET /reports/{report_id}/audit-scope` - Audit scope details
- `GET /reports/{report_id}/objectives` - Audit objectives
- `GET /reports/{report_id}/recommendations` - Recommendations

**Summaries:**
- `GET /reports/{report_id}/summaries` - List available variants
- `GET /reports/{report_id}/summaries/{variant}` - Get specific variant
- `GET /reports/{report_id}/summaries/random` - Surprise Me feature

---

## Cost Estimate

With Extended Thinking + Batch API (50% off):

| Component | Per Report | 14 Reports |
|-----------|------------|------------|
| Overview extraction | ~$0.04 | ~$0.56 |
| Executive summary | ~$0.05 | ~$0.70 |
| Journalist's Take | ~$0.25 | ~$3.50 |
| Deep Dive | ~$0.35 | ~$4.90 |
| Simple Explainer | ~$0.04 | ~$0.56 |
| Policy Brief | ~$0.05 | ~$0.70 |
| **TOTAL** | **~$0.78** | **~$10.92** |

---

## Integrating with Full Pipeline

To auto-submit Phase 10 when new reports are processed, add the code from
`MAIN_PY_INTEGRATION.py` to the end of your `services/parsing_pipeline/main.py`.

This makes Phase 10 automatic for new reports while keeping it separate for
existing reports (which you run via CLI).

---

## Troubleshooting

### "No *_chunks.json files found"
- Check that your JSON files are in `data/processed/`
- Files must end with `_chunks.json`

### "Anthropic API key not found"
- Ensure `ANTHROPIC_API_KEY` is in your `.env` file
- Make sure python-dotenv is loading it

### "Batch still processing after hours"
- Batch API guarantees completion within 24 hours
- Most batches complete in 1-2 hours
- Use `--watch` to monitor continuously

### JSON parse errors in process_results
- Raw response is saved to `{report_id}_overview_raw.txt`
- Check the raw file to see what the LLM returned
- May need to adjust prompts for edge cases

### Missing variants in summaries
- Check `errors` field in the summaries JSON
- Some reports may have insufficient data for certain variants
