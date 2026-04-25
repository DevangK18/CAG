#!/usr/bin/env python3
"""
CLI: Process completed batch results and create final output files.

This script:
1. Downloads results from completed Anthropic batches
2. Parses LLM responses for overview extraction
3. Parses LLM responses for summary variants
4. Merges JSON-extracted data with LLM-extracted data
5. Creates final output files in organized folder structure

Output Structure:
    data/batch_jobs/
    ├── jobs/
    │   └── job_YYYYMMDD_HHMMSS.json (updated with completion status)
    ├── overviews/
    │   └── {report_id}_overview_llm.json
    └── summaries/
        └── {report_id}_summaries.json

    data/processed/
    └── {report_id}_overview.json (merged final overview)

Usage:
    python -m services.batch_pipeline.process_results
    python -m services.batch_pipeline.process_results --job data/batch_jobs/jobs/job_20250131.json
    python -m services.batch_pipeline.process_results --force
"""

import argparse
import json
import re
import sys
from pathlib import Path
from datetime import datetime

# Load environment variables
from dotenv import load_dotenv

load_dotenv()


def clean_json_response(content: str) -> str:
    """Clean LLM response to extract valid JSON."""
    if not content:
        return content

    # Remove markdown code blocks
    if "```json" in content:
        match = re.search(r"```json\s*(.*?)\s*```", content, re.DOTALL)
        if match:
            return match.group(1).strip()

    if "```" in content:
        match = re.search(r"```\s*(.*?)\s*```", content, re.DOTALL)
        if match:
            return match.group(1).strip()

    # Try to find JSON object
    content = content.strip()
    if content.startswith("{") and content.endswith("}"):
        return content

    # Look for JSON object in the content
    match = re.search(r"\{[\s\S]*\}", content)
    if match:
        return match.group(0)

    return content


def extract_overview_from_json(json_path: Path) -> dict:
    """
    Extract all JSON-available overview fields (Phase 10A - FREE).
    This extracts data that's already in the chunks JSON.
    """
    with open(json_path) as f:
        data = json.load(f)

    meta = data.get("report_metadata", {})
    enrichment = data.get("semantic_enrichment", {})
    stats = enrichment.get("statistics", {})
    findings_stats = stats.get("findings", {})

    return {
        "basic_info": {
            "report_id": meta.get("report_id"),
            "report_number": meta.get("report_no"),
            "report_year": meta.get("report_year"),
            "title": meta.get("report_title"),
            "ministry": meta.get("ministry"),
            "department": meta.get("department"),
            "sector": meta.get("sector"),
            "report_type": meta.get("report_type"),
            "publication_date": meta.get("publication_date"),
            "source_url": meta.get("source_url"),
            "source_filename": meta.get("source_filename"),
            # Tier-aware fields
            "government_body_type": meta.get("government_body_type", "union"),
            "state_name": meta.get("state_name"),
            "audit_category": meta.get("audit_category"),
        },
        "table_of_contents": [
            {
                "id": c.get("chunk_id"),
                "title": c.get("toc_entry"),
                "level": c.get("toc_level"),
                "page_start": c.get("page_range_physical", [0])[0],
                "page_end": c.get("page_range_physical", [0, 0])[-1],
                "hierarchy": c.get("hierarchy"),
            }
            for c in data.get("parent_chunks", [])
        ],
        "findings_summary": {
            "total_count": findings_stats.get("total_count", 0),
            "total_monetary_crore": findings_stats.get("total_monetary_crore", 0),
            "by_severity": findings_stats.get("by_severity", {}),
            "by_type": findings_stats.get("by_type", {}),
        },
        "findings_list": [
            {
                "id": f.get("finding_id"),
                "severity": f.get("severity"),
                "type": f.get("finding_type"),
                "amount_crore": f.get("total_amount_inr", 0) / 10000000,
                "chapter": f.get("chapter"),
                "section": f.get("section"),
                "page": f.get("page"),
                "text": f.get("text"),
                "summary": f.get("summary"),
            }
            for f in enrichment.get("findings", [])
        ],
        "recommendations": [
            {
                "id": r.get("recommendation_id"),
                "text": r.get("text"),
                "summary": r.get("summary"),
                "chapter": r.get("chapter"),
                "page": r.get("page"),
            }
            for r in enrichment.get("recommendations", [])
        ],
        "section_classifications": enrichment.get("section_classifications", []),
        "entities": enrichment.get("entities", {}),
        # Placeholders for LLM-extracted fields
        "audit_scope": None,
        "audit_objectives": None,
        "topics_covered": None,
        "glossary_terms": None,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Process completed Phase 10 batch results"
    )
    parser.add_argument(
        "--job",
        type=str,
        help="Path to specific job tracker file (default: most recent)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Process even if batches not marked as complete",
    )
    parser.add_argument(
        "--skip-overview",
        action="store_true",
        help="Skip processing overview batch results",
    )
    parser.add_argument(
        "--skip-summary",
        action="store_true",
        help="Skip processing summary batch results",
    )
    parser.add_argument(
        "--enrichment",
        action="store_true",
        help="Process P2-1 enrichment results instead of Phase 10",
    )
    parser.add_argument(
        "--chart-extraction",
        action="store_true",
        help="Process P2-2 chart extraction results instead of Phase 10",
    )

    args = parser.parse_args()

    # ENRICHMENT MODE: Process enrichment results
    if args.enrichment:
        from .enrichment.enrichment_service import EnrichmentService

        enrichment_service = EnrichmentService()

        # Find enrichment job tracker
        if args.job:
            job_id = Path(args.job).stem
        else:
            # Get most recent enrichment job
            job_files = sorted(enrichment_service.enrichment_dir.glob("enrichment_*.json"), reverse=True)
            job_files = [f for f in job_files if not f.name.endswith("_mapping.json") and not f.name.endswith("_enrichment.json")]
            job_id = job_files[0].stem if job_files else None

        if not job_id:
            print("❌ No enrichment job tracker found.")
            print("   Run 'python -m src.batch_pipeline.submit_jobs --enrichment' first.")
            sys.exit(1)

        # Load tracker to check status
        tracker_path = enrichment_service.enrichment_dir / f"{job_id}.json"
        with open(tracker_path) as f:
            tracker = json.load(f)

        if tracker["status"] not in ["ready_for_processing", "completed"] and not args.force:
            print("❌ Enrichment job not ready for processing.")
            print(f"   Status: {tracker['status']}")
            print("   Run 'python -m src.batch_pipeline.check_status --enrichment' to check progress.")
            print("   Or use --force to process anyway.")
            sys.exit(1)

        print("=" * 60)
        print("PHASE 2 - P2-1: PROCESS ENRICHMENT RESULTS")
        print("=" * 60)
        print(f"\nJob ID: {job_id}")
        print(f"Status: {tracker['status']}")

        # Process results
        try:
            summary = enrichment_service.process_enrichment_results(job_id)

            print("\n" + "=" * 60)
            print("✅ ENRICHMENT PROCESSING COMPLETE")
            print("=" * 60)
            print(f"\nTotal successes: {summary['success']}")
            print(f"Total failures: {summary['failed']}")
            print(f"\nPer-report results:")
            for report_summary in summary['reports']:
                print(f"  • {report_summary['report_id']}")
                print(f"    Success: {report_summary['success']}, Errors: {report_summary['errors']}")
                print(f"    File: {report_summary['output_file']}")
        except Exception as e:
            print(f"\n❌ Error processing results: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)

        return

    # CHART EXTRACTION MODE: Process chart extraction results
    if args.chart_extraction:
        from .enrichment.chart_extractor import ChartExtractorService

        chart_service = ChartExtractorService()

        # Find chart extraction job tracker
        if args.job:
            job_id = Path(args.job).stem
        else:
            # Get most recent chart extraction job
            job_files = sorted(chart_service.chart_extraction_dir.glob("chart_extraction_*.json"), reverse=True)
            job_files = [f for f in job_files if not f.name.endswith("_mapping.json") and not f.name.endswith("_charts.json")]
            job_id = job_files[0].stem if job_files else None

        if not job_id:
            print("❌ No chart extraction job tracker found.")
            print("   Run 'python -m src.batch_pipeline.submit_jobs --chart-extraction' first.")
            sys.exit(1)

        # Load tracker to check status
        tracker_path = chart_service.chart_extraction_dir / f"{job_id}.json"
        with open(tracker_path) as f:
            tracker = json.load(f)

        if tracker["status"] not in ["ready_for_processing", "completed"] and not args.force:
            print("❌ Chart extraction job not ready for processing.")
            print(f"   Status: {tracker['status']}")
            print("   Run 'python -m src.batch_pipeline.check_status --chart-extraction' to check progress.")
            print("   Or use --force to process anyway.")
            sys.exit(1)

        print("=" * 60)
        print("PHASE 2 - P2-2: PROCESS CHART EXTRACTION RESULTS")
        print("=" * 60)
        print(f"\nJob ID: {job_id}")
        print(f"Status: {tracker['status']}")

        # Process results
        try:
            summary = chart_service.process_chart_results(job_id)

            print("\n" + "=" * 60)
            print("✅ CHART EXTRACTION PROCESSING COMPLETE")
            print("=" * 60)
            print(f"\nResults Summary:")
            print(f"   Successful: {summary.get('success', 0)}")
            print(f"   Errors: {summary.get('errors', 0)}")
            print(f"   Low Confidence: {summary.get('low_confidence', 0)}")
            print(f"   Reports Updated: {summary.get('reports_updated', 0)}")
            print(f"   Chart Chunks Updated: {summary.get('chunks_updated', 0)}")

            print(f"\n📁 Output Files:")
            print(f"   Updated JSONs: data/processed/*_chunks.json")
            print(f"   Chart Results: data/batch_jobs/chart_extraction/{{report_id}}_charts.json")

            print(f"\n💡 Next Steps:")
            print(f"   - Updated child_chunks now have structured_data for charts")
            print(f"   - Charts are queryable via API endpoints")
            print(f"   - Use RAG pipeline to re-index updated reports")

        except Exception as e:
            print(f"\n❌ Error processing results: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)

        return

    # PHASE 10 MODE: Original batch results processing
    # Import here to avoid loading anthropic during --help
    from .batch_service import BatchService

    service = BatchService()

    # Find job tracker
    if args.job:
        tracker_path = Path(args.job)
    else:
        tracker_path = service.get_latest_job()

    if not tracker_path or not tracker_path.exists():
        print("❌ No job tracker found.")
        print("   Run 'python -m services.batch_pipeline.submit_jobs' first.")
        print(f"   Expected location: data/batch_jobs/jobs/job_*.json")
        sys.exit(1)

    with open(tracker_path) as f:
        tracker = json.load(f)

    # Set the job timestamp for ID mapping lookups
    job_timestamp = tracker.get("job_timestamp")
    service._current_job_timestamp = job_timestamp

    print("=" * 60)
    print("PHASE 10: PROCESS BATCH RESULTS")
    print("=" * 60)
    print(f"\nJob: {tracker['job_id']}")
    print(f"Reports: {len(tracker['reports'])}")
    print(f"Status: {tracker['status']}")

    # Check if ready
    if (
        tracker["status"] not in ["ready_for_processing", "completed"]
        and not args.force
    ):
        print(f"\n⚠️  Job status is '{tracker['status']}', not ready for processing.")
        print("   Use --force to process anyway (may have incomplete results).")
        print("   Or run 'check_status --watch' to wait for completion.")
        sys.exit(1)

    if tracker["status"] == "completed" and not args.force:
        print(f"\n✅ Job already completed at {tracker.get('completed_at')}")
        print("   Use --force to reprocess.")
        return

    # ═══════════════════════════════════════════════════════════════════════
    # PROCESS OVERVIEW RESULTS
    # ═══════════════════════════════════════════════════════════════════════

    overview_success = 0
    overview_failed = 0

    if not args.skip_overview and tracker["overview_batch"]["batch_id"] != "N/A":
        print("\n" + "-" * 40)
        print("📋 Processing Overview Extraction Results...")
        print(f"   Output: {service.overviews_dir}/")
        print("-" * 40)

        try:
            overview_results = service.get_batch_results(
                tracker["overview_batch"]["batch_id"], job_timestamp
            )
        except Exception as e:
            print(f"❌ Failed to get overview results: {e}")
            overview_results = []

        for result in overview_results:
            report_id = result.get("report_id", result["custom_id"])

            if result["error"]:
                print(f"  ❌ {report_id[:50]}...: {result['error'][:50]}...")
                overview_failed += 1
                continue

            try:
                # Parse JSON from LLM response
                content = clean_json_response(result["content"])
                overview_data = json.loads(content)

                # Save LLM extraction result to overviews folder
                output_path = service.get_overview_output_path(report_id)
                with open(output_path, "w") as f:
                    json.dump(overview_data, f, indent=2, ensure_ascii=False)

                print(f"  ✅ {report_id[:50]}...")
                overview_success += 1

                # Update tracker
                if report_id in tracker["reports"]:
                    tracker["reports"][report_id]["overview_extracted"] = True

            except json.JSONDecodeError as e:
                print(f"  ❌ {report_id[:50]}...: JSON parse error - {str(e)[:30]}")
                # Save raw response for debugging
                debug_path = service.overviews_dir / f"{report_id}_overview_raw.txt"
                with open(debug_path, "w") as f:
                    f.write(result["content"] or "No content")
                print(f"      Raw response saved to: {debug_path.name}")
                overview_failed += 1

        print(
            f"\n   Overview extraction: {overview_success} success, {overview_failed} failed"
        )
    else:
        print("\n📋 Skipping overview batch (not submitted or --skip-overview)")

    # ═══════════════════════════════════════════════════════════════════════
    # PROCESS SUMMARY RESULTS
    # ═══════════════════════════════════════════════════════════════════════

    summary_success = 0
    summary_partial = 0
    summary_failed = 0

    if not args.skip_summary and tracker["summary_batch"]["batch_id"] != "N/A":
        print("\n" + "-" * 40)
        print("📝 Processing Summary Generation Results...")
        print(f"   Output: {service.summaries_dir}/")
        print("-" * 40)

        try:
            summary_results = service.get_batch_results(
                tracker["summary_batch"]["batch_id"], job_timestamp
            )
        except Exception as e:
            print(f"❌ Failed to get summary results: {e}")
            summary_results = []

        # Group by report
        summaries_by_report = {}

        for result in summary_results:
            report_id = result.get("report_id", result["custom_id"])
            variant = result.get("variant")

            if not variant:
                continue

            if report_id not in summaries_by_report:
                summaries_by_report[report_id] = {"variants": {}, "errors": []}

            if result["error"]:
                summaries_by_report[report_id]["errors"].append(
                    {"variant": variant, "error": result["error"]}
                )
            else:
                content = result["content"] or ""
                summaries_by_report[report_id]["variants"][variant] = {
                    "content": content,
                    "word_count": len(content.split()),
                    "thinking_used": result.get("thinking") is not None,
                }

        # Save summaries for each report to summaries folder
        for report_id, data in summaries_by_report.items():
            output_path = service.get_summary_output_path(report_id)

            summary_doc = {
                "report_id": report_id,
                "generated_at": datetime.now().isoformat(),
                "variants": data["variants"],
                "variant_count": len(data["variants"]),
                "errors": data["errors"] if data["errors"] else None,
            }

            with open(output_path, "w") as f:
                json.dump(summary_doc, f, indent=2, ensure_ascii=False)

            # Update tracker
            if report_id in tracker["reports"]:
                tracker["reports"][report_id]["summaries_generated"] = list(
                    data["variants"].keys()
                )

            # Categorize result
            n_variants = len(data["variants"])
            short_id = report_id[:45] + "..." if len(report_id) > 45 else report_id

            if n_variants == 5:
                print(f"  ✅ {short_id}: 5/5 variants")
                summary_success += 1
            elif n_variants > 0:
                print(f"  ⚠️  {short_id}: {n_variants}/5 variants")
                summary_partial += 1
            else:
                print(f"  ❌ {short_id}: 0/5 variants")
                summary_failed += 1

        print(
            f"\n   Summaries: {summary_success} complete, {summary_partial} partial, {summary_failed} failed"
        )
    else:
        print("\n📝 Skipping summary batch (not submitted or --skip-summary)")

    # ═══════════════════════════════════════════════════════════════════════
    # MERGE INTO FINAL OVERVIEW FILES (with improved LLM merge)
    # ═══════════════════════════════════════════════════════════════════════

    from .merge_utils import merge_llm_overview_data

    print("\n" + "-" * 40)
    print("🔄 Creating Final Overview Files...")
    print(f"   Output: {service.processed_dir}/")
    print("-" * 40)

    merge_success = 0
    merge_failed = 0
    llm_merged_count = 0
    llm_fields_total = 0

    for report_id in tracker["reports"].keys():
        # Find source chunks JSON (searches tier subdirectories)
        chunks_path = service.find_chunks_path(report_id)

        if not chunks_path or not chunks_path.exists():
            print(f"  ⚠️  {report_id[:40]}...: chunks.json not found")
            merge_failed += 1
            continue

        # Detect tier for output path
        tier = service.get_tier_from_chunks(chunks_path)

        # Extract from JSON (Phase 10A - free data)
        overview = extract_overview_from_json(chunks_path)

        # Add base metadata (include tier info)
        overview["_metadata"] = {
            "generated_at": datetime.now().isoformat(),
            "source_json": str(chunks_path),
            "phase": "10",
            "government_body_type": tier,
        }

        # Merge LLM-extracted fields using improved merge logic
        overview, merge_stats = merge_llm_overview_data(
            report_id,
            overview,
            service.overviews_dir,
            service.summaries_dir,
            verbose=False  # Set to True for detailed output
        )

        # Track merge statistics
        if merge_stats["llm_file_found"]:
            llm_merged_count += 1
            llm_fields_total += merge_stats["fields_merged"]

        # Save final overview to processed directory (tier-aware)
        output_path = service.get_final_overview_path(report_id, tier)
        with open(output_path, "w") as f:
            json.dump(overview, f, indent=2, ensure_ascii=False)

        short_id = report_id[:45] + "..." if len(report_id) > 45 else report_id
        llm_marker = "✓" if merge_stats["llm_file_found"] else "○"
        sum_marker = "✓" if merge_stats["summaries_available"] else "○"
        fields_info = f"{merge_stats['fields_merged']}/4" if merge_stats["llm_file_found"] else "0/4"
        print(f"  ✅ {short_id} [LLM:{llm_marker} {fields_info} SUM:{sum_marker}]")
        merge_success += 1

    print(f"\n   Overview files created: {merge_success}, failed: {merge_failed}")
    if llm_merged_count > 0:
        avg_fields = llm_fields_total / llm_merged_count
        print(f"   LLM data merged: {llm_merged_count}/{merge_success} reports (avg {avg_fields:.1f}/4 fields)")

    # ═══════════════════════════════════════════════════════════════════════
    # UPDATE TRACKER & FINAL SUMMARY
    # ═══════════════════════════════════════════════════════════════════════

    tracker["status"] = "completed"
    tracker["completed_at"] = datetime.now().isoformat()

    with open(tracker_path, "w") as f:
        json.dump(tracker, f, indent=2)

    print("\n" + "=" * 60)
    print("✅ PHASE 10 PROCESSING COMPLETE!")
    print("=" * 60)

    print(f"\n📊 Summary:")
    print(
        f"   Overview extraction: {overview_success} success, {overview_failed} failed"
    )
    print(
        f"   Summary generation:  {summary_success + summary_partial} success/partial, {summary_failed} failed"
    )
    print(f"   Final overview files: {merge_success} created")

    print(f"\n📁 Output Locations:")
    print(
        f"   LLM Overviews:   {service.overviews_dir}/{{report_id}}_overview_llm.json"
    )
    print(f"   Summaries:       {service.summaries_dir}/{{report_id}}_summaries.json")
    print(f"   Final Overviews: {service.processed_dir}/{{report_id}}_overview.json")

    print(f"\n🔧 To use in API:")
    print(f"   GET /reports/{{report_id}}/overview")
    print(f"   GET /reports/{{report_id}}/summaries")
    print(f"   GET /reports/{{report_id}}/summaries/{{variant}}")


if __name__ == "__main__":
    main()
