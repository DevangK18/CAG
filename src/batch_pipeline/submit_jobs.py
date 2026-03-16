#!/usr/bin/env python3
"""
CLI: Submit Phase 10 batch jobs for existing JSON chunk files.

Usage:
    python -m services.batch_pipeline.submit_jobs
    python -m services.batch_pipeline.submit_jobs --dir data/processed
    python -m services.batch_pipeline.submit_jobs --files report1.json report2.json
    python -m services.batch_pipeline.submit_jobs --overview-only
    python -m services.batch_pipeline.submit_jobs --summary-only
    python -m services.batch_pipeline.submit_jobs --dry-run
"""

import argparse
import sys
from pathlib import Path
from datetime import datetime

# Load environment variables
from dotenv import load_dotenv

load_dotenv()


def main():
    parser = argparse.ArgumentParser(
        description="Submit Phase 10 batch jobs for CAG report processing"
    )
    parser.add_argument(
        "--dir",
        type=str,
        default="data/processed",
        help="Directory containing *_chunks.json files (default: data/processed)",
    )
    parser.add_argument(
        "--files", nargs="+", help="Specific JSON files to process (overrides --dir)"
    )
    parser.add_argument(
        "--overview-only",
        action="store_true",
        help="Only submit overview extraction batch (skip summaries)",
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Only submit summary generation batch (skip overview)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be submitted without actually submitting",
    )
    parser.add_argument(
        "--enrichment",
        action="store_true",
        help="Submit P2-1 LLM enrichment batch (finding extraction) instead of Phase 10",
    )
    parser.add_argument(
        "--chart-extraction",
        action="store_true",
        help="Submit P2-2 chart extraction batch (Claude Vision) instead of Phase 10",
    )
    parser.add_argument(
        "--report-type",
        type=str,
        default="general",
        choices=["compliance", "performance", "financial", "general"],
        help="Report type for enrichment routing (default: general)",
    )
    parser.add_argument(
        "--force-reextract",
        action="store_true",
        help="For chart extraction: Re-extract charts even if structured_data exists",
    )

    args = parser.parse_args()

    # Find JSON files
    if args.files:
        json_files = [Path(f) for f in args.files]
        # Validate files exist
        missing = [f for f in json_files if not f.exists()]
        if missing:
            print(f"❌ Files not found: {missing}")
            sys.exit(1)
    else:
        json_dir = Path(args.dir)
        if not json_dir.exists():
            print(f"❌ Directory not found: {json_dir}")
            sys.exit(1)
        json_files = sorted(json_dir.glob("*_chunks.json"))

    if not json_files:
        print("❌ No *_chunks.json files found!")
        print(f"   Searched in: {args.dir if not args.files else 'specified files'}")
        sys.exit(1)

    # Display what we found
    print("=" * 60)
    if args.enrichment:
        print("PHASE 2 - P2-1: SUBMIT ENRICHMENT BATCH")
    elif args.chart_extraction:
        print("PHASE 2 - P2-2: SUBMIT CHART EXTRACTION BATCH")
    else:
        print("PHASE 10: SUBMIT BATCH JOBS")
    print("=" * 60)
    print(f"\nFound {len(json_files)} reports to process:")

    for i, f in enumerate(json_files):
        marker = "  •" if i < 10 else "   "
        print(f"{marker} {f.name}")
        if i == 9 and len(json_files) > 10:
            print(f"    ... and {len(json_files) - 10} more")
            break

    if args.dry_run:
        print("\n🔍 DRY RUN - No batches will be submitted")
        print(f"\nWould submit:")
        if not args.summary_only:
            print(f"  • Overview extraction: {len(json_files)} requests")
        if not args.overview_only:
            print(
                f"  • Summary generation: {len(json_files) * 5} requests ({len(json_files)} reports × 5 variants)"
            )
        return

    # ENRICHMENT MODE: Submit P2-1 LLM enrichment batch
    if args.enrichment:
        from .enrichment.enrichment_service import EnrichmentService

        print("\n" + "-" * 40)
        print("📤 Submitting P2-1 Enrichment Batch...")
        print("-" * 40)

        enrichment_service = EnrichmentService()
        job_id = enrichment_service.submit_enrichment_batch(
            json_files,
            skip_already_enriched=True,
            report_type=args.report_type
        )

        print("\n" + "=" * 60)
        print("✅ ENRICHMENT BATCH SUBMITTED SUCCESSFULLY")
        print("=" * 60)
        print(f"\nJob ID: {job_id}")
        print(f"Report Type: {args.report_type}")
        print(f"\n📁 Output Structure:")
        print(f"   Job Tracker:  data/batch_jobs/enrichment/{job_id}.json")
        print(f"   ID Mapping:   data/batch_jobs/enrichment/{job_id}_mapping.json")
        print(f"   Results:      data/batch_jobs/enrichment/{{report_id}}_enrichment.json")
        print("\n" + "-" * 40)
        print("Next steps:")
        print("-" * 40)
        print("  1. Check status:")
        print("     poetry run python -m src.batch_pipeline.check_status --enrichment")
        print("")
        print("  2. When complete, process results:")
        print("     poetry run python -m src.batch_pipeline.process_results --enrichment")
        return

    # CHART EXTRACTION MODE: Submit P2-2 chart extraction batch
    if args.chart_extraction:
        from .enrichment.chart_extractor import ChartExtractorService

        print("\n" + "-" * 40)
        print("📤 Submitting P2-2 Chart Extraction Batch...")
        print("-" * 40)

        chart_service = ChartExtractorService()
        job_id = chart_service.submit_chart_extraction_batch(
            json_files,
            skip_existing=(not args.force_reextract),
            force_reextract=args.force_reextract
        )

        if not job_id:
            print("\n⚠️  No charts to extract")
            return

        print("\n" + "=" * 60)
        print("✅ CHART EXTRACTION BATCH SUBMITTED SUCCESSFULLY")
        print("=" * 60)
        print(f"\nJob ID: {job_id}")
        print(f"\n📁 Output Structure:")
        print(f"   Job Tracker:  data/batch_jobs/chart_extraction/{job_id}.json")
        print(f"   ID Mapping:   data/batch_jobs/chart_extraction/{job_id}_mapping.json")
        print(f"   Results:      data/batch_jobs/chart_extraction/{{report_id}}_charts.json")
        print("\n" + "-" * 40)
        print("Next steps:")
        print("-" * 40)
        print("  1. Check status:")
        print("     poetry run python -m src.batch_pipeline.check_status --chart-extraction")
        print("")
        print("  2. Or watch continuously:")
        print("     poetry run python -m src.batch_pipeline.check_status --chart-extraction --watch")
        print("")
        print("  3. When complete, process results:")
        print("     poetry run python -m src.batch_pipeline.process_results --chart-extraction")
        return

    # PHASE 10 MODE: Original overview/summary batches
    # Import here to avoid loading anthropic client during --help
    from .batch_service import BatchService

    # Initialize service
    service = BatchService()

    # Generate job timestamp upfront so both batches use the same mapping file
    job_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    service._current_job_timestamp = job_timestamp

    overview_batch_id = None
    summary_batch_id = None

    # Submit batches
    if not args.summary_only:
        print("\n" + "-" * 40)
        print("📤 Submitting Overview Extraction Batch...")
        print("-" * 40)
        try:
            overview_batch_id = service.submit_overview_batch(json_files, job_timestamp)
        except Exception as e:
            print(f"❌ Failed to submit overview batch: {e}")
            if not args.overview_only:
                print("   Continuing with summary batch...")

    if not args.overview_only:
        print("\n" + "-" * 40)
        print("📤 Submitting Summary Generation Batch...")
        print("-" * 40)
        try:
            summary_batch_id = service.submit_summary_batch(json_files, job_timestamp)
        except Exception as e:
            print(f"❌ Failed to submit summary batch: {e}")

    # Create job tracker if at least one batch was submitted
    if overview_batch_id or summary_batch_id:
        report_ids = [f.stem.replace("_chunks", "") for f in json_files]
        tracker_path = service.create_job_tracker(
            overview_batch_id=overview_batch_id or "N/A",
            summary_batch_id=summary_batch_id or "N/A",
            report_ids=report_ids,
        )

        print("\n" + "=" * 60)
        print("✅ BATCH JOBS SUBMITTED SUCCESSFULLY")
        print("=" * 60)
        print(f"\nJob Timestamp: {job_timestamp}")
        print(f"Overview Batch ID: {overview_batch_id or 'N/A (skipped)'}")
        print(f"Summary Batch ID:  {summary_batch_id or 'N/A (skipped)'}")
        print(f"\n📁 Output Structure:")
        print(f"   Job Tracker:  data/batch_jobs/jobs/job_{job_timestamp}.json")
        print(f"   ID Mapping:   data/batch_jobs/jobs/job_{job_timestamp}_mapping.json")
        print(f"   Overviews:    data/batch_jobs/overviews/")
        print(f"   Summaries:    data/batch_jobs/summaries/")
        print("\n" + "-" * 40)
        print("Next steps:")
        print("-" * 40)
        print("  1. Check status:")
        print("     poetry run python -m services.batch_pipeline.check_status")
        print("")
        print("  2. Or watch continuously:")
        print("     poetry run python -m services.batch_pipeline.check_status --watch")
        print("")
        print("  3. When complete, process results:")
        print("     poetry run python -m services.batch_pipeline.process_results")
    else:
        print("\n❌ No batches were submitted successfully.")
        sys.exit(1)


if __name__ == "__main__":
    main()
