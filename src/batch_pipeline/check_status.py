#!/usr/bin/env python3
"""
CLI: Check status of Phase 10 batch jobs.

Usage:
    python -m services.batch_pipeline.check_status
    python -m services.batch_pipeline.check_status --job data/batch_jobs/jobs/job_20250131_120000.json
    python -m services.batch_pipeline.check_status --watch
    python -m services.batch_pipeline.check_status --watch --interval 30
    python -m services.batch_pipeline.check_status --list
"""

import argparse
import json
import sys
import time
from pathlib import Path
from datetime import datetime

# Load environment variables
from dotenv import load_dotenv

load_dotenv()


def format_time(iso_string: str | None) -> str:
    """Format ISO timestamp for display."""
    if not iso_string:
        return "N/A"
    try:
        if isinstance(iso_string, datetime):
            return iso_string.strftime("%Y-%m-%d %H:%M:%S")
        dt = datetime.fromisoformat(str(iso_string).replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except:
        return str(iso_string)


def main():
    parser = argparse.ArgumentParser(description="Check status of Phase 10 batch jobs")
    parser.add_argument(
        "--job",
        type=str,
        help="Path to specific job tracker file (default: most recent)",
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Continuously watch status until all batches complete",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=60,
        help="Polling interval in seconds for --watch mode (default: 60)",
    )
    parser.add_argument(
        "--list", action="store_true", help="List all job tracker files"
    )
    parser.add_argument(
        "--enrichment",
        action="store_true",
        help="Check status of P2-1 enrichment jobs instead of Phase 10",
    )
    parser.add_argument(
        "--chart-extraction",
        action="store_true",
        help="Check status of P2-2 chart extraction jobs instead of Phase 10",
    )

    args = parser.parse_args()

    # ENRICHMENT MODE: Check enrichment job status
    if args.enrichment:
        from .enrichment.enrichment_service import EnrichmentService
        enrichment_service = EnrichmentService()

        # List enrichment jobs if requested
        if args.list:
            job_files = sorted(enrichment_service.enrichment_dir.glob("enrichment_*.json"), reverse=True)
            # Filter out mapping files
            job_files = [f for f in job_files if not f.name.endswith("_mapping.json") and not f.name.endswith("_enrichment.json")]

            if not job_files:
                print("No enrichment job tracker files found.")
                print(f"   Expected location: {enrichment_service.enrichment_dir}/enrichment_*.json")
                return

            print("=" * 60)
            print("PHASE 2 - P2-1: ENRICHMENT JOB FILES")
            print("=" * 60)
            print(f"\n📁 Location: {enrichment_service.enrichment_dir}/")

            for jf in job_files:
                with open(jf) as f:
                    data = json.load(f)
                status = data.get("status", "unknown")
                created = format_time(data.get("created_at"))
                reports = len(data.get("reports_processed", []))

                print(f"\n  📄 {jf.name}")
                print(f"     Status: {status.upper()}")
                print(f"     Created: {created}")
                print(f"     Reports: {reports}")
            return

        # Find enrichment job tracker
        if args.job:
            tracker_path = Path(args.job)
        else:
            # Get most recent enrichment job
            job_files = sorted(enrichment_service.enrichment_dir.glob("enrichment_*.json"), reverse=True)
            job_files = [f for f in job_files if not f.name.endswith("_mapping.json") and not f.name.endswith("_enrichment.json")]
            tracker_path = job_files[0] if job_files else None

        if not tracker_path or not tracker_path.exists():
            print("❌ No enrichment job tracker found.")
            print("   Run 'python -m src.batch_pipeline.submit_jobs --enrichment' first.")
            print(f"   Expected location: {enrichment_service.enrichment_dir}/enrichment_*.json")
            sys.exit(1)

        print("=" * 60)
        print("PHASE 2 - P2-1: ENRICHMENT JOB STATUS")
        print("=" * 60)
        print(f"\nJob Tracker: {tracker_path}")

        iteration = 0
        while True:
            iteration += 1

            # Get job ID from path
            job_id = tracker_path.stem

            # Update and get status
            try:
                tracker = enrichment_service.get_enrichment_status(job_id)
            except Exception as e:
                print(f"\n❌ Error checking status: {e}")
                if args.watch:
                    print(f"   Retrying in {args.interval} seconds...")
                    time.sleep(args.interval)
                    continue
                else:
                    sys.exit(1)

            # Clear screen for watch mode
            if args.watch and iteration > 1:
                print("\n" + "=" * 60)

            # Display status
            print("\n" + "-" * 40)
            print(f"Job ID: {tracker['job_id']}")
            print(f"Overall Status: {tracker['status'].upper()}")
            print(f"Created: {format_time(tracker.get('created_at'))}")
            print("-" * 40)

            # OpenAI batch status
            ob = tracker["openai_batch"]
            print(f"\n🤖 OpenAI Enrichment Batch")
            if ob["status"] == "skipped":
                print("   Status: SKIPPED")
            else:
                batch_id_short = (
                    ob["batch_id"][:30] + "..."
                    if ob["batch_id"] and len(ob["batch_id"]) > 30
                    else ob["batch_id"]
                )
                print(f"   Batch ID: {batch_id_short}")
                print(f"   Status: {ob['status'].upper()}")
                print(f"   Requests: {ob['request_count']}")
                if ob.get("progress"):
                    prog = ob["progress"]
                    print(f"   Progress: {prog.get('completed', 0)}/{prog.get('total', 0)}")

            # Anthropic batch status
            ab = tracker["anthropic_batch"]
            print(f"\n🔷 Anthropic Complex Analysis Batch")
            if ab["status"] == "skipped":
                print("   Status: SKIPPED")
            else:
                batch_id_short = (
                    ab["batch_id"][:30] + "..."
                    if ab["batch_id"] and len(ab["batch_id"]) > 30
                    else ab["batch_id"]
                )
                print(f"   Batch ID: {batch_id_short}")
                print(f"   Status: {ab['status'].upper()}")
                print(f"   Requests: {ab['request_count']}")
                if ab.get("progress"):
                    prog = ab["progress"]
                    print(f"   Progress: {prog.get('completed', 0)}/{prog.get('total', 0)}")

            # Report count
            report_count = len(tracker.get("reports_processed", []))
            print(f"\n📊 Reports: {report_count}")

            # Check if done
            if tracker["status"] == "ready_for_processing":
                print("\n" + "=" * 60)
                print("✅ ALL BATCHES COMPLETE - READY FOR PROCESSING")
                print("=" * 60)
                print("\nNext step:")
                print("  python -m src.batch_pipeline.process_results --enrichment")
                break

            if tracker["status"] == "completed":
                print("\n" + "=" * 60)
                print("✅ JOB ALREADY COMPLETED")
                print("=" * 60)
                print(f"Completed at: {format_time(tracker.get('completed_at'))}")
                break

            # If not watching, exit
            if not args.watch:
                print("\n" + "-" * 40)
                print("💡 Tip: Use --watch to continuously monitor until complete")
                print(f"        Batch API typically completes within 1-2 hours")
                break

            # Watch mode - wait and retry
            print(f"\n⏳ Waiting {args.interval} seconds before next check...")
            print(f"   Press Ctrl+C to stop watching")

            try:
                time.sleep(args.interval)
            except KeyboardInterrupt:
                print("\n\n👋 Stopped watching. Job is still processing.")
                print("   Run this command again to check status.")
                break

        return

    # CHART EXTRACTION MODE: Check chart extraction job status
    if args.chart_extraction:
        from .enrichment.chart_extractor import ChartExtractorService
        chart_service = ChartExtractorService()

        # List chart extraction jobs if requested
        if args.list:
            job_files = sorted(chart_service.chart_extraction_dir.glob("chart_extraction_*.json"), reverse=True)
            # Filter out mapping and result files
            job_files = [f for f in job_files if not f.name.endswith("_mapping.json") and not f.name.endswith("_charts.json")]

            if not job_files:
                print("No chart extraction job tracker files found.")
                print(f"   Expected location: {chart_service.chart_extraction_dir}/chart_extraction_*.json")
                return

            print("=" * 60)
            print("PHASE 2 - P2-2: CHART EXTRACTION JOB FILES")
            print("=" * 60)
            print(f"\n📁 Location: {chart_service.chart_extraction_dir}/")

            for jf in job_files:
                with open(jf) as f:
                    data = json.load(f)
                status = data.get("status", "unknown")
                created = format_time(data.get("created_at"))
                charts = data.get("request_count", 0)

                print(f"\n  📄 {jf.name}")
                print(f"     Status: {status.upper()}")
                print(f"     Created: {created}")
                print(f"     Charts: {charts}")
            return

        # Find chart extraction job tracker
        if args.job:
            tracker_path = Path(args.job)
        else:
            # Get most recent chart extraction job
            job_files = sorted(chart_service.chart_extraction_dir.glob("chart_extraction_*.json"), reverse=True)
            job_files = [f for f in job_files if not f.name.endswith("_mapping.json") and not f.name.endswith("_charts.json")]
            tracker_path = job_files[0] if job_files else None

        if not tracker_path or not tracker_path.exists():
            print("❌ No chart extraction job tracker found.")
            print("   Run 'python -m src.batch_pipeline.submit_jobs --chart-extraction' first.")
            print(f"   Expected location: {chart_service.chart_extraction_dir}/chart_extraction_*.json")
            sys.exit(1)

        print("=" * 60)
        print("PHASE 2 - P2-2: CHART EXTRACTION JOB STATUS")
        print("=" * 60)
        print(f"\nJob Tracker: {tracker_path}")

        iteration = 0
        while True:
            iteration += 1

            # Get job ID from path
            job_id = tracker_path.stem

            # Update and get status
            try:
                tracker = chart_service.get_chart_extraction_status(job_id)
            except Exception as e:
                print(f"\n❌ Error checking status: {e}")
                if args.watch:
                    print(f"   Retrying in {args.interval} seconds...")
                    time.sleep(args.interval)
                    continue
                else:
                    sys.exit(1)

            # Clear screen for watch mode
            if args.watch and iteration > 1:
                print("\n" + "=" * 60)

            # Display status
            print("\n" + "-" * 40)
            print(f"Job ID: {tracker['job_id']}")
            print(f"Overall Status: {tracker['status'].upper()}")
            print(f"Created: {format_time(tracker.get('created_at'))}")
            print(f"Model: {tracker.get('model', 'N/A')}")
            print("-" * 40)

            # Batch status
            batch_id = tracker.get("batch_id")
            if batch_id:
                batch_id_short = (
                    batch_id[:30] + "..."
                    if len(batch_id) > 30
                    else batch_id
                )
                print(f"\n🎨 Chart Extraction Batch (Claude Vision)")
                print(f"   Batch ID: {batch_id_short}")
                batch_status = tracker.get("batch_status", "unknown")
                print(f"   Status: {batch_status.upper()}")
                print(f"   Charts Submitted: {tracker.get('request_count', 0)}")

                if tracker.get("request_counts"):
                    rc = tracker["request_counts"]
                    total = rc.get("total", 0)
                    succeeded = rc.get("succeeded", 0)
                    errored = rc.get("errored", 0)
                    processing = rc.get("processing", 0)

                    print(f"   Progress:")
                    print(f"      Succeeded: {succeeded}/{total}")
                    if errored > 0:
                        print(f"      Errors: {errored}")
                    if processing > 0:
                        print(f"      Processing: {processing}")

            # Statistics
            if tracker.get("statistics"):
                stats = tracker["statistics"]
                print(f"\n📊 Statistics:")
                print(f"   Reports Processed: {stats.get('total_reports', 0)}")
                print(f"   Total Charts: {stats.get('total_charts', 0)}")
                print(f"   Charts Extracted: {stats.get('charts_to_extract', 0)}")
                print(f"   Charts Skipped (existing): {stats.get('charts_skipped_existing', 0)}")

            # Check if done
            if tracker["status"] == "ready_for_processing":
                print("\n" + "=" * 60)
                print("✅ BATCH COMPLETE - READY FOR PROCESSING")
                print("=" * 60)
                print("\nNext step:")
                print("  python -m src.batch_pipeline.process_results --chart-extraction")
                break

            if tracker["status"] == "completed":
                print("\n" + "=" * 60)
                print("✅ JOB ALREADY COMPLETED")
                print("=" * 60)
                print(f"Completed at: {format_time(tracker.get('completed_at'))}")

                if tracker.get("summary"):
                    summ = tracker["summary"]
                    print(f"\nResults:")
                    print(f"   Successful: {summ.get('success', 0)}")
                    print(f"   Errors: {summ.get('errors', 0)}")
                    print(f"   Low Confidence: {summ.get('low_confidence', 0)}")
                    print(f"   Reports Updated: {summ.get('reports_updated', 0)}")
                    print(f"   Chunks Updated: {summ.get('chunks_updated', 0)}")
                break

            # If not watching, exit
            if not args.watch:
                print("\n" + "-" * 40)
                print("💡 Tip: Use --watch to continuously monitor until complete")
                print(f"        Batch API typically completes within 1-2 hours")
                break

            # Watch mode - wait and retry
            print(f"\n⏳ Waiting {args.interval} seconds before next check...")
            print(f"   Press Ctrl+C to stop watching")

            try:
                time.sleep(args.interval)
            except KeyboardInterrupt:
                print("\n\n👋 Stopped watching. Job is still processing.")
                print("   Run this command again to check status.")
                break

        return

    # PHASE 10 MODE: Original batch status checking
    # Import here to avoid loading anthropic during --help
    from .batch_service import BatchService

    service = BatchService()

    # List all jobs if requested
    if args.list:
        job_files = sorted(service.jobs_dir.glob("job_*.json"), reverse=True)
        # Filter out mapping files
        job_files = [f for f in job_files if not f.name.endswith("_mapping.json")]

        if not job_files:
            print("No job tracker files found.")
            print(f"   Expected location: {service.jobs_dir}/job_*.json")
            return

        print("=" * 60)
        print("PHASE 10: JOB TRACKER FILES")
        print("=" * 60)
        print(f"\n📁 Location: {service.jobs_dir}/")

        for jf in job_files:
            with open(jf) as f:
                data = json.load(f)
            status = data.get("status", "unknown")
            created = format_time(data.get("created_at"))
            reports = len(data.get("reports", {}))

            # Check for corresponding mapping file
            mapping_exists = (service.jobs_dir / f"{jf.stem}_mapping.json").exists()

            print(f"\n  📄 {jf.name}")
            print(f"     Status: {status.upper()}")
            print(f"     Created: {created}")
            print(f"     Reports: {reports}")
            print(f"     Mapping: {'✓' if mapping_exists else '✗'}")
        return

    # Find job tracker
    if args.job:
        tracker_path = Path(args.job)
    else:
        tracker_path = service.get_latest_job()

    if not tracker_path or not tracker_path.exists():
        print("❌ No job tracker found.")
        print("   Run 'python -m services.batch_pipeline.submit_jobs' first.")
        print(f"   Expected location: {service.jobs_dir}/job_*.json")
        print("   Or specify a job file with --job")
        sys.exit(1)

    print("=" * 60)
    print("PHASE 10: BATCH JOB STATUS")
    print("=" * 60)
    print(f"\nJob Tracker: {tracker_path}")

    iteration = 0
    while True:
        iteration += 1

        # Update and get status
        try:
            tracker = service.update_job_status(tracker_path)
        except Exception as e:
            print(f"\n❌ Error checking status: {e}")
            if args.watch:
                print(f"   Retrying in {args.interval} seconds...")
                time.sleep(args.interval)
                continue
            else:
                sys.exit(1)

        # Clear screen for watch mode (after first iteration)
        if args.watch and iteration > 1:
            print("\n" + "=" * 60)

        # Display status
        print("\n" + "-" * 40)
        print(f"Job ID: {tracker['job_id']}")
        print(f"Overall Status: {tracker['status'].upper()}")
        print(f"Created: {format_time(tracker.get('created_at'))}")
        print("-" * 40)

        # Overview batch status
        ob = tracker["overview_batch"]
        print(f"\n📋 Overview Extraction Batch")
        if ob["batch_id"] == "N/A":
            print("   Status: SKIPPED")
        else:
            batch_id_short = (
                ob["batch_id"][:30] + "..."
                if len(ob["batch_id"]) > 30
                else ob["batch_id"]
            )
            print(f"   Batch ID: {batch_id_short}")
            print(f"   Status: {ob['status'].upper()}")
            if ob.get("completed_at"):
                print(f"   Completed: {format_time(ob['completed_at'])}")

        # Summary batch status
        sb = tracker["summary_batch"]
        print(f"\n📝 Summary Generation Batch")
        if sb["batch_id"] == "N/A":
            print("   Status: SKIPPED")
        else:
            batch_id_short = (
                sb["batch_id"][:30] + "..."
                if len(sb["batch_id"]) > 30
                else sb["batch_id"]
            )
            print(f"   Batch ID: {batch_id_short}")
            print(f"   Status: {sb['status'].upper()}")
            if sb.get("completed_at"):
                print(f"   Completed: {format_time(sb['completed_at'])}")

        # Report count
        report_count = len(tracker.get("reports", {}))
        print(f"\n📊 Reports: {report_count}")

        # Output paths info
        if "output_paths" in tracker:
            print(f"\n📁 Output Structure:")
            print(f"   Overviews: {service.overviews_dir}/")
            print(f"   Summaries: {service.summaries_dir}/")

        # Check if done
        if tracker["status"] == "ready_for_processing":
            print("\n" + "=" * 60)
            print("✅ ALL BATCHES COMPLETE - READY FOR PROCESSING")
            print("=" * 60)
            print("\nNext step:")
            print("  python -m services.batch_pipeline.process_results")
            break

        if tracker["status"] == "completed":
            print("\n" + "=" * 60)
            print("✅ JOB ALREADY COMPLETED")
            print("=" * 60)
            print(f"Completed at: {format_time(tracker.get('completed_at'))}")
            break

        # If not watching, exit
        if not args.watch:
            print("\n" + "-" * 40)
            print("💡 Tip: Use --watch to continuously monitor until complete")
            print(f"        Batch API typically completes within 1-2 hours")
            break

        # Watch mode - wait and retry
        print(f"\n⏳ Waiting {args.interval} seconds before next check...")
        print(f"   Press Ctrl+C to stop watching")

        try:
            time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\n\n👋 Stopped watching. Job is still processing.")
            print("   Run this command again to check status.")
            break


if __name__ == "__main__":
    main()
