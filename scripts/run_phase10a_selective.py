"""
Run Phase 10a (Overview & Summary Generation) on specific reports.

This script submits only the specified reports to the Claude Batch API
for overview extraction and summary generation (5 variants).

Phase 10a consists of three batch jobs:
1. Overview extraction (always)
2. Summary variants - 5 styles (always)
3. Hierarchical summaries - RAPTOR chapter/section (optional, for efficient RAG)

Usage:
    python scripts/run_phase10a_selective.py
    python scripts/run_phase10a_selective.py --include-hierarchical
    python scripts/run_phase10a_selective.py --report-ids "2025_04,2025_08" --include-hierarchical
"""

import argparse
from pathlib import Path
from src.batch_pipeline.batch_service import BatchService


def run_phase10a_for_reports(report_ids: list[str], include_hierarchical: bool = False):
    """
    Run Phase 10a for specific reports.

    Args:
        report_ids: List of report IDs to process
        include_hierarchical: Include RAPTOR hierarchical summaries (chapter/section level)
    """
    print("=" * 70)
    print("PHASE 10a: OVERVIEW & SUMMARY GENERATION (Selective)")
    if include_hierarchical:
        print("         + RAPTOR HIERARCHICAL SUMMARIES")
    print("=" * 70)
    print()

    # Find JSON files for the specified reports
    json_files = []
    processed_dir = Path("data/processed")

    # Search in tier subdirectories
    for report_id in report_ids:
        found = False
        for tier in ["union", "state", "local_body"]:
            json_path = processed_dir / tier / f"{report_id}_chunks.json"
            if json_path.exists():
                json_files.append(json_path)
                print(f"✓ Found: {report_id} ({tier})")
                found = True
                break
        if not found:
            # Try flat structure
            json_path = processed_dir / f"{report_id}_chunks.json"
            if json_path.exists():
                json_files.append(json_path)
                print(f"✓ Found: {report_id}")
            else:
                print(f"✗ Missing: {report_id}")

    print()
    print(f"Total reports to process: {len(json_files)}")
    print()

    if not json_files:
        print("⚠️  No valid JSON files found. Exiting.")
        return

    # Initialize BatchService
    service = BatchService()

    # Submit batches
    print("Submitting to Claude Batch API...")
    print("  - Overview extraction (executive summaries)")
    print("  - 5 summary variants (executive, journalist, deep_dive, simple, policy)")
    if include_hierarchical:
        print("  - Hierarchical summaries (chapter + section level for RAPTOR)")
    print()

    try:
        # Generate consistent job timestamp
        from datetime import datetime
        job_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        print(f"Job Timestamp: {job_timestamp}")
        print()

        # Submit overview batch with timestamp
        overview_batch_id = service.submit_overview_batch(json_files, job_timestamp=job_timestamp)
        print(f"✓ Overview Batch ID: {overview_batch_id}")

        # Submit summary batch with same timestamp
        summary_batch_id = service.submit_summary_batch(json_files, job_timestamp=job_timestamp)
        print(f"✓ Summary Batch ID:  {summary_batch_id}")

        # Submit hierarchical batch (optional)
        hierarchical_batch_id = None
        if include_hierarchical:
            hierarchical_batch_id = service.submit_hierarchical_batch(json_files, job_timestamp=job_timestamp)
            print(f"✓ Hierarchical Batch ID: {hierarchical_batch_id}")

        # Create job tracker
        report_ids_list = [f.stem.replace("_chunks", "") for f in json_files]
        tracker_path = service.create_job_tracker(
            overview_batch_id=overview_batch_id,
            summary_batch_id=summary_batch_id,
            report_ids=report_ids_list,
            hierarchical_batch_id=hierarchical_batch_id,
        )

        print()
        print("=" * 70)
        print("✅ PHASE 10a BATCHES SUBMITTED SUCCESSFULLY")
        print("=" * 70)
        print()
        print(f"Job Tracker: {tracker_path}")
        print()
        print("Next steps:")
        print("  1. Wait for batch processing (usually 1-2 hours)")
        print("  2. Check status: python -m src.batch_pipeline.check_status")
        print("  3. Process results: python -m src.batch_pipeline.process_results")
        print()

    except Exception as e:
        print()
        print(f"❌ Error submitting batches: {str(e)}")
        print()
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run Phase 10a (Overview & Summary Generation) on specific reports"
    )
    parser.add_argument(
        "--report-ids",
        type=str,
        default=None,
        help="Comma-separated list of report IDs to process",
    )
    parser.add_argument(
        "--include-hierarchical",
        action="store_true",
        help="Include RAPTOR hierarchical summaries (chapter/section level)",
    )

    args = parser.parse_args()

    # Default reports if none specified
    if args.report_ids:
        reports_to_process = [r.strip() for r in args.report_ids.split(",")]
    else:
        # The 5 new reports missing summaries (default)
        reports_to_process = [
            "2025_08_Compliance_Audit_on_on__the_Activities_of_Indian_National_Centre_for_Ocean_Infor",
            "2025_20_Performance_Audit_on_on_Skill_Development_under_Pradhan_Mantri_Kaushal_Vikas_Yoj",
            "2025_26_Compliance_Audit_on_on_Development_of_MultiFunctional_Complexes_and_Commercial_s",
            "2025_35_Performance_Audit_on_Operational_Performance_of_NLC_India_Limited_Ministry_of_Co",
            "2025_38_Performance_Audit_of_Blast_Furnace_in_Steel_Authority_of_India_Limited",
        ]

    run_phase10a_for_reports(
        reports_to_process,
        include_hierarchical=args.include_hierarchical,
    )
