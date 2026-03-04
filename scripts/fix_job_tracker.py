#!/usr/bin/env python3
"""
Fix corrupted job tracker by recreating it with known batch IDs.

Run this from your CAG project root:
    python fix_job_tracker.py
"""

import json
from pathlib import Path
from datetime import datetime

# Configuration - update these with your actual batch IDs from Claude Console
OVERVIEW_BATCH_ID = "msgbatch_01T8hexGjUtu3XkExzXFb11e"  # 1/1 completed
SUMMARY_BATCH_ID = "msgbatch_01E5fPdnFZmxjex1rZxTqLyd"   # 5/5 completed

# Report ID (from your file)
REPORT_ID = "2025_04_CAG_Report_on_Union_Government_Accounts_202223_Financial_Audit"

# Paths
JOBS_DIR = Path("data/batch_jobs/jobs")
JOBS_DIR.mkdir(parents=True, exist_ok=True)

# Create timestamp
timestamp = "20260202_010348"  # Use the existing timestamp

# Create the job tracker
tracker = {
    "job_id": f"phase10_{timestamp}",
    "job_timestamp": timestamp,
    "created_at": "2026-02-02T01:03:48",
    "status": "ready_for_processing",  # Both batches are done
    
    "overview_batch": {
        "batch_id": OVERVIEW_BATCH_ID,
        "status": "ended",
        "completed_at": "2026-02-02T01:03:00"
    },
    "summary_batch": {
        "batch_id": SUMMARY_BATCH_ID,
        "status": "ended", 
        "completed_at": "2026-02-02T01:03:00"
    },
    
    "reports": {
        REPORT_ID: {
            "overview_extracted": False,
            "summaries_generated": []
        }
    },
    
    "output_paths": {
        "job_tracker": f"jobs/job_{timestamp}.json",
        "id_mapping": f"jobs/job_{timestamp}_mapping.json",
        "overviews_dir": "overviews/",
        "summaries_dir": "summaries/"
    },
    
    "completed_at": None
}

# Create the ID mapping
id_mapping = {
    f"ov_{''.join(format(ord(c), '02x') for c in REPORT_ID[:4])}_{REPORT_ID[:50]}": REPORT_ID,
}

# Add summary variant mappings
variant_codes = {"executive": "ex", "journalist": "jo", "deep_dive": "dd", "simple": "si", "policy": "po"}
for variant, code in variant_codes.items():
    import hashlib
    hash_part = hashlib.md5(REPORT_ID.encode()).hexdigest()[:8]
    prefix = f"sm_{code}"
    max_len = 54 - len(prefix)
    custom_id = f"{prefix}_{hash_part}_{REPORT_ID[:max_len]}"
    id_mapping[custom_id] = {"report_id": REPORT_ID, "variant": variant}

# Also add overview mapping with correct hash
import hashlib
hash_part = hashlib.md5(REPORT_ID.encode()).hexdigest()[:8]
ov_custom_id = f"ov_{hash_part}_{REPORT_ID[:51]}"
id_mapping[ov_custom_id] = REPORT_ID

# Save files
tracker_path = JOBS_DIR / f"job_{timestamp}.json"
mapping_path = JOBS_DIR / f"job_{timestamp}_mapping.json"

with open(tracker_path, "w") as f:
    json.dump(tracker, f, indent=2)
print(f"✅ Created job tracker: {tracker_path}")

with open(mapping_path, "w") as f:
    json.dump(id_mapping, f, indent=2)
print(f"✅ Created ID mapping: {mapping_path}")

print(f"\nNow run:")
print(f"  poetry run python -m services.batch_pipeline.check_status")
print(f"  poetry run python -m services.batch_pipeline.process_results")
