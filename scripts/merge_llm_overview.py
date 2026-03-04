#!/usr/bin/env python3
"""
Merge LLM-extracted overview data into the main overview file.

Fixed version that handles truncated filenames from batch processing.

This script now uses shared merge utilities from src/batch_pipeline/merge_utils.py
to ensure consistency with automated batch processing.
"""

import json
import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import merge utilities directly (avoiding __init__.py)
import importlib.util
spec = importlib.util.spec_from_file_location("merge_utils", "src/batch_pipeline/merge_utils.py")
merge_utils = importlib.util.module_from_spec(spec)
spec.loader.exec_module(merge_utils)

merge_llm_overview_data = merge_utils.merge_llm_overview_data
find_llm_overview_file = merge_utils.find_llm_overview_file


def _find_llm_overview_file_wrapper(report_id: str) -> Path | None:
    """
    Find the LLM overview file using fuzzy matching (wrapper for shared utility).

    This adds verbose output for manual script usage.
    """
    overviews_dir = Path("data/batch_jobs/overviews")

    if not overviews_dir.exists():
        print(f"❌ Overviews directory not found: {overviews_dir}")
        return None

    # List all files in the directory
    all_files = list(overviews_dir.glob("*_overview_llm.json"))
    print(f"   Found {len(all_files)} LLM overview files in {overviews_dir}")

    if len(all_files) == 0:
        return None

    # Use shared utility function
    result = find_llm_overview_file(report_id, overviews_dir)

    if result:
        print(f"   ✅ Found match: {result.name}")
    else:
        print(f"   ❌ No matching LLM overview file found")
        print(f"   Report ID: {report_id}")
        print(f"   Available files:")
        for f in all_files[:5]:  # Show first 5
            print(f"      - {f.name}")
        if len(all_files) > 5:
            print(f"      ... and {len(all_files) - 5} more")

    return result


def merge_llm_overview(report_id: str):
    """Merge LLM-extracted data into the main overview file."""

    # Paths
    processed_dir = Path("data/processed")
    overviews_dir = Path("data/batch_jobs/overviews")
    summaries_dir = Path("data/batch_jobs/summaries")

    main_overview_path = processed_dir / f"{report_id}_overview.json"

    # Check main overview exists
    if not main_overview_path.exists():
        print(f"❌ Main overview not found: {main_overview_path}")
        return False

    # Find LLM overview file (handles truncated names)
    print(f"🔍 Looking for LLM overview file...")
    llm_overview_path = _find_llm_overview_file_wrapper(report_id)

    if llm_overview_path is None:
        print("\n❌ LLM overview file not found.")
        print("   Run Phase 10 batch processing first to generate LLM extractions.")
        return False

    # Load main overview
    print(f"\n📖 Loading main overview: {main_overview_path.name}")
    with open(main_overview_path, "r", encoding="utf-8") as f:
        main_overview = json.load(f)

    print(f"📖 Loading LLM overview: {llm_overview_path.name}")

    # Use shared merge utility with verbose output
    print(f"\n🔄 Merging LLM fields...")

    # Temporarily enable verbose mode for field-by-field output
    import io
    import contextlib

    # Capture detailed merge output
    original_overview = main_overview.copy()
    main_overview, merge_stats = merge_llm_overview_data(
        report_id,
        main_overview,
        overviews_dir,
        summaries_dir,
        verbose=True  # Show detailed merge info
    )

    # Show summary of merge
    if merge_stats["fields_merged"] == 0:
        print(f"   ⚠️  No fields merged (all were null/missing)")

    # Save merged overview
    print(f"\n💾 Saving merged overview...")
    with open(main_overview_path, "w", encoding="utf-8") as f:
        json.dump(main_overview, f, indent=2, ensure_ascii=False)

    print(f"✅ Saved to: {main_overview_path}")

    # Print summary
    print("\n" + "=" * 60)
    print("📊 MERGED DATA SUMMARY")
    print("=" * 60)

    if main_overview.get("audit_scope"):
        scope = main_overview["audit_scope"]
        print(f"\n🎯 Audit Scope:")
        print(f"   Period: {scope.get('period', {}).get('description', 'N/A')}")
        entities = scope.get("entities_covered", [])
        print(f"   Entities: {len(entities)} covered")
        if entities:
            for e in entities[:3]:
                print(f"      • {e}")
            if len(entities) > 3:
                print(f"      ... and {len(entities) - 3} more")

    if main_overview.get("audit_objectives"):
        objectives = main_overview["audit_objectives"]
        print(f"\n📋 Audit Objectives: {len(objectives)}")
        for i, obj in enumerate(objectives[:3], 1):
            text = obj[:70] + "..." if len(obj) > 70 else obj
            print(f"   {i}. {text}")
        if len(objectives) > 3:
            print(f"   ... and {len(objectives) - 3} more")

    if main_overview.get("topics_covered"):
        topics = main_overview["topics_covered"]
        print(f"\n📚 Topics Covered: {len(topics)}")
        for topic in topics[:5]:
            print(f"   • {topic.get('name', 'Unknown')}")
        if len(topics) > 5:
            print(f"   ... and {len(topics) - 5} more")

    if main_overview.get("glossary_terms"):
        terms = main_overview["glossary_terms"]
        print(f"\n📖 Glossary: {len(terms)} terms")
        for term in terms[:5]:
            abbr = term.get("abbreviation", "?")
            name = term.get("term", "Unknown")
            print(f"   • {abbr} = {name}")
        if len(terms) > 5:
            print(f"   ... and {len(terms) - 5} more")

    print("\n" + "=" * 60)

    return True


def merge_all_reports():
    """Merge LLM overview data for all reports."""
    processed_dir = Path("data/processed")

    # Find all overview files
    overview_files = list(processed_dir.glob("*_overview.json"))

    if not overview_files:
        print("❌ No overview files found in data/processed/")
        return False

    print(f"📚 Found {len(overview_files)} overview files\n")
    print("=" * 60 + "\n")

    # Track results
    results = {
        "success": [],
        "failed": [],
        "skipped": []
    }

    # Process each report
    for i, overview_file in enumerate(overview_files, 1):
        # Extract report_id from filename
        report_id = overview_file.stem.replace("_overview", "")

        print(f"\n[{i}/{len(overview_files)}] Processing: {report_id}")
        print("-" * 60)

        try:
            success = merge_llm_overview(report_id)
            if success:
                results["success"].append(report_id)
            else:
                results["skipped"].append(report_id)
        except Exception as e:
            print(f"❌ Error: {e}")
            results["failed"].append(report_id)

    # Print summary
    print("\n\n" + "=" * 60)
    print("📊 BATCH PROCESSING SUMMARY")
    print("=" * 60 + "\n")

    print(f"✅ Successfully merged: {len(results['success'])}")
    if results['success']:
        for report_id in results['success']:
            print(f"   • {report_id[:60]}...")

    if results['skipped']:
        print(f"\n⚠️  Skipped (no LLM data): {len(results['skipped'])}")
        for report_id in results['skipped']:
            print(f"   • {report_id[:60]}...")

    if results['failed']:
        print(f"\n❌ Failed: {len(results['failed'])}")
        for report_id in results['failed']:
            print(f"   • {report_id[:60]}...")

    print("\n" + "=" * 60)

    total_processed = len(results['success']) + len(results['skipped']) + len(results['failed'])
    success_rate = (len(results['success']) / total_processed * 100) if total_processed > 0 else 0

    print(f"\n📈 Success rate: {success_rate:.1f}% ({len(results['success'])}/{total_processed})")

    if results['success']:
        print("\n🎉 Done! Restart the backend and refresh the frontend to see the updates.")

    return len(results['success']) > 0


def main():
    # Check for -all or --all flag
    if len(sys.argv) >= 2 and sys.argv[1] in ["-all", "--all"]:
        print("🔄 Merging LLM overview data for ALL reports\n")
        success = merge_all_reports()

        if not success:
            print("\n❌ Batch merge failed or no reports processed.")
            sys.exit(1)

    elif len(sys.argv) < 2:
        # Default to the test report
        report_id = (
            "2025_04_CAG_Report_on_Union_Government_Accounts_202223_Financial_Audit"
        )
        print(f"No report_id provided, using default:\n{report_id}\n")
        print(f"💡 Tip: Use '-all' flag to process all reports at once\n")
        print("=" * 60 + "\n")

        success = merge_llm_overview(report_id)

        if success:
            print("\n🎉 Done! Restart the backend and refresh the frontend.")
        else:
            print("\n❌ Merge failed.")
            sys.exit(1)

    else:
        # Single report mode
        report_id = sys.argv[1]
        print(f"🔄 Merging LLM overview data\n")
        print("=" * 60 + "\n")

        success = merge_llm_overview(report_id)

        if success:
            print("\n🎉 Done! Restart the backend and refresh the frontend.")
        else:
            print("\n❌ Merge failed.")
            sys.exit(1)


if __name__ == "__main__":
    main()
