#!/usr/bin/env python3
"""
CLI: Check status of Phase 10 batch jobs.

Usage:
    python -m src.batch_pipeline.check_status
    python -m src.batch_pipeline.check_status --job data/batch_jobs/jobs/job_20250131_120000.json
    python -m src.batch_pipeline.check_status --watch
    python -m src.batch_pipeline.check_status --watch --interval 30
    python -m src.batch_pipeline.check_status --list
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

    args = parser.parse_args()

    # Imported here to keep --help fast
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
        print("   Run 'python -m src.batch_pipeline.submit_jobs' first.")
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
            print("  python -m src.batch_pipeline.process_results")
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
