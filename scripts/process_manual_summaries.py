#!/usr/bin/env python3
"""
Process manually downloaded batch summary results.

This script processes the batch_results_msgbatch_01WKNsycTQDuUyWnoFyYn3p9.jsonl file
that was manually downloaded from the Claude console.
"""

import json
from pathlib import Path
from datetime import datetime

# File paths
BATCH_RESULTS_FILE = Path("batch_results_msgbatch_01WKNsycTQDuUyWnoFyYn3p9.jsonl")
MAPPING_FILE = Path("data/batch_jobs/jobs/job_20260218_204109_mapping.json")
SUMMARIES_DIR = Path("data/batch_jobs/summaries")
JOB_TRACKER_FILE = Path("data/batch_jobs/jobs/job_20260218_204109.json")

# Ensure output directory exists
SUMMARIES_DIR.mkdir(parents=True, exist_ok=True)

# Load ID mapping
with open(MAPPING_FILE) as f:
    id_mapping = json.load(f)

# Load job tracker
with open(JOB_TRACKER_FILE) as f:
    tracker = json.load(f)

# Process batch results
summaries_by_report = {}
processed_count = 0
error_count = 0

print("=" * 70)
print("PROCESSING MANUAL BATCH SUMMARY RESULTS")
print("=" * 70)
print(f"\nInput: {BATCH_RESULTS_FILE}")
print(f"Output: {SUMMARIES_DIR}/")
print()

with open(BATCH_RESULTS_FILE) as f:
    for line_num, line in enumerate(f, start=1):
        if not line.strip():
            continue

        try:
            result = json.loads(line)
            custom_id = result.get("custom_id", "")

            # Look up report_id and variant from mapping
            mapped = id_mapping.get(custom_id, custom_id)
            if isinstance(mapped, dict):
                report_id = mapped.get("report_id", custom_id)
                variant = mapped.get("variant")
            else:
                report_id = mapped
                variant = None

            if not variant:
                print(f"⚠️  Line {line_num}: No variant found for {custom_id}")
                continue

            # Initialize report entry
            if report_id not in summaries_by_report:
                summaries_by_report[report_id] = {"variants": {}, "errors": []}

            # Check result type
            result_obj = result.get("result", {})
            if result_obj.get("type") == "succeeded":
                # Extract text content
                message = result_obj.get("message", {})
                content_blocks = message.get("content", [])

                text_content = ""
                thinking_used = False

                for block in content_blocks:
                    if block.get("type") == "thinking":
                        thinking_used = True
                    elif block.get("type") == "text":
                        text_content = block.get("text", "")

                if text_content:
                    summaries_by_report[report_id]["variants"][variant] = {
                        "content": text_content,
                        "word_count": len(text_content.split()),
                        "thinking_used": thinking_used,
                    }
                    processed_count += 1
                    print(f"  ✅ {report_id[:45]}... | {variant:12s} | {len(text_content):6,} chars")
                else:
                    summaries_by_report[report_id]["errors"].append({
                        "variant": variant,
                        "error": "No text content in response"
                    })
                    error_count += 1
                    print(f"  ❌ {report_id[:45]}... | {variant:12s} | No content")

            elif result_obj.get("type") == "errored":
                error_msg = result_obj.get("error", {}).get("message", "Unknown error")
                summaries_by_report[report_id]["errors"].append({
                    "variant": variant,
                    "error": error_msg
                })
                error_count += 1
                print(f"  ❌ {report_id[:45]}... | {variant:12s} | {error_msg[:30]}...")

        except Exception as e:
            error_count += 1
            print(f"  ❌ Line {line_num}: Error parsing - {str(e)[:50]}")

# Save summaries for each report
print()
print("-" * 70)
print("CREATING SUMMARY FILES")
print("-" * 70)

saved_count = 0
for report_id, data in summaries_by_report.items():
    output_path = SUMMARIES_DIR / f"{report_id}_summaries.json"

    summary_doc = {
        "report_id": report_id,
        "generated_at": datetime.now().isoformat(),
        "variants": data["variants"],
        "variant_count": len(data["variants"]),
        "errors": data["errors"] if data["errors"] else None,
    }

    with open(output_path, "w") as f:
        json.dump(summary_doc, f, indent=2, ensure_ascii=False)

    # Update job tracker
    if report_id in tracker["reports"]:
        tracker["reports"][report_id]["summaries_generated"] = list(data["variants"].keys())

    n_variants = len(data["variants"])
    short_id = report_id[:45] + "..." if len(report_id) > 45 else report_id

    if n_variants == 5:
        print(f"  ✅ {short_id}: 5/5 variants")
    elif n_variants > 0:
        print(f"  ⚠️  {short_id}: {n_variants}/5 variants")
    else:
        print(f"  ❌ {short_id}: 0/5 variants")

    saved_count += 1

# Update job tracker
with open(JOB_TRACKER_FILE, "w") as f:
    json.dump(tracker, f, indent=2)

print()
print("=" * 70)
print("✅ PROCESSING COMPLETE")
print("=" * 70)
print(f"\nSummaries processed: {processed_count}")
print(f"Errors: {error_count}")
print(f"Reports: {len(summaries_by_report)}")
print(f"Files created: {saved_count}")
print()
print(f"📁 Output:")
print(f"   {SUMMARIES_DIR}/*_summaries.json")
print()
print(f"🔧 Next steps:")
print(f"   - Run: python -m src.batch_pipeline.process_results")
print(f"   - This will merge summaries into final overview files")
