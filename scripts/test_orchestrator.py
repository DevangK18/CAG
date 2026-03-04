"""
Test script to verify the chaining of ManifestIngestionService -> TriageService -> ScaffoldingService.

This demonstrates the first three stages of the parsing DAG.
Usage: python test_orchestrator.py
"""

import asyncio
import sys
from pathlib import Path

# Add src to sys.path for imports
sys.path.insert(0, str(Path(__file__).parent))

from modules.manifest_ingestion_service import ManifestIngestionService
from modules.triage_service import TriageService
from modules.scaffolding_service import ScaffoldingService


async def test_orchestration():
    """Test orchestration from Manifest -> Triage."""
    # Use the actual manifest file
    manifest_path = Path("../../../CAG-Union Audit Reports.xlsx").resolve()

    print(
        "=== Testing ManifestIngestionService -> TriageService -> ScaffoldingService Orchestration ==="
    )
    print("Three-phase pipeline integration test")
    print()

    if not manifest_path.exists():
        print(f"Manifest file not found: {manifest_path}")
        return

    # Phase 1: Manifest Ingestion
    print("Phase 1: Manifest Ingestion")
    print("-" * 30)
    manifest_service = ManifestIngestionService(raw_data_dir="data/raw")

    try:
        tasks = await manifest_service.process_manifest(str(manifest_path))

        successful_tasks = [
            t for t in tasks if t.processing_status != "failed_download"
        ]
        failed_tasks = [t for t in tasks if t.processing_status == "failed_download"]

        print(f"Total reports: {len(tasks)}")
        print(f"Successful downloads: {len(successful_tasks)}")
        print(f"Failed downloads: {len(failed_tasks)}")

        if failed_tasks:
            print("\nFailed downloads:")
            for task in failed_tasks:
                print(f"  - {task.report_id}: {task.error_log}")

    except Exception as e:
        print(f"Manifest ingestion failed: {e}")
        return

    # Phase 2: Triage on successful tasks
    print("\nPhase 2: Triage Classification")
    print("-" * 30)

    if not successful_tasks:
        print("No successful tasks to triage")
        return

    triage_service = TriageService()
    triaged_native = []
    triaged_scanned = []

    for i, task in enumerate(successful_tasks, 1):
        print(f"Triage {i}/{len(successful_tasks)}: {task.report_id}")
        result = triage_service.triage_document(task)

        if result.classification == "native_text":
            triaged_native.append(result)
        elif result.classification == "scanned":
            triaged_scanned.append(result)
        else:
            print(f"  ERROR: No classification for {task.report_id}")
            if result.error_log:
                print(f"  Reason: {result.error_log}")

        print(f"  Result: {result.classification} -> {result.processing_status}")

    print("\nTriage Summary:")
    print(f"  Native Text: {len(triaged_native)}")
    print(f"  Scanned: {len(triaged_scanned)}")

    # Show sample results
    if triaged_native:
        print(f"\nSample native text report: {triaged_native[0].report_id}")
    if triaged_scanned:
        print(f"Sample scanned report: {triaged_scanned[0].report_id}")

    # Phase 3: Scaffolding on successfully triaged tasks
    print("\nPhase 3: Document Scaffolding")
    print("-" * 30)

    if not (triaged_native + triaged_scanned):
        print("No successfully triaged tasks to scaffold")
        return

    scaffolded_tasks = triaged_native + triaged_scanned
    scaffolding_service = ScaffoldingService()

    scaffold_complete = []
    scaffold_partial = []
    scaffold_minimal = []
    scaffold_failed = []

    for i, task in enumerate(scaffolded_tasks, 1):
        print(f"Scaffolding {i}/{len(scaffolded_tasks)}: {task.report_id}")
        result = scaffolding_service.build_scaffold(task)

        if result.processing_status == "scaffold_complete":
            scaffold_complete.append(result)
        elif result.processing_status == "scaffold_minimal":
            scaffold_minimal.append(result)
        elif result.processing_status == "scaffold_partial":
            scaffold_partial.append(result)
        else:
            scaffold_failed.append(result)

        print(f"  Result: {result.processing_status}")

        # Show scaffold details
        toc_count = len(result.scaffold.get("toc", []))
        pages_count = len(result.scaffold.get("page_map", {}))
        print(f"  Scaffold: ToC={toc_count} entries, Pages={pages_count}")

    print("\nScaffolding Summary:")
    print(f"  Complete: {len(scaffold_complete)}")
    print(f"  Minimal (ToC only): {len(scaffold_minimal)}")
    print(f"  Partial (Pages only): {len(scaffold_partial)}")
    print(f"  Failed: {len(scaffold_failed)}")

    # Show sample scaffold results
    if scaffold_complete:
        sample = scaffold_complete[0]
        toc_count = len(sample.scaffold.get("toc", []))
        print(
            f"\nSample complete scaffold ({sample.report_id}): ToC with {toc_count} entries"
        )

    total_success = len(triaged_native) + len(triaged_scanned)
    scaffold_success = (
        len(scaffold_complete) + len(scaffold_minimal) + len(scaffold_partial)
    )

    print(
        f"\nOverall Success Rate (through scaffolding): {scaffold_success}/{len(successful_tasks)} ({scaffold_success / len(successful_tasks) * 100:.1f}%)"
    )

    return {
        "phase1_success": len(successful_tasks),
        "phase1_failed": len(failed_tasks),
        "phase2_native": len(triaged_native),
        "phase2_scanned": len(triaged_scanned),
        "phase3_complete": len(scaffold_complete),
        "phase3_minimal": len(scaffold_minimal),
        "phase3_partial": len(scaffold_partial),
        "phase3_failed": len(scaffold_failed),
        "total_reports": len(tasks),
    }


async def main():
    """Main entry point."""
    print(f"Running orchestration test from: {Path.cwd()}")
    result = await test_orchestration()

    if result:
        print("\n=== Test Complete ===")
        print(f"Processed {result['total_reports']} total reports")
        print(
            f"Download success rate: {(result['phase1_success'] / result['total_reports']) * 100:.1f}%"
        )
        print(
            f"Triage success rate: {((result['phase2_native'] + result['phase2_scanned']) / result['phase1_success']) * 100:.1f}%"
        )
        scaffold_success = (
            result.get("phase3_complete", 0)
            + result.get("phase3_minimal", 0)
            + result.get("phase3_partial", 0)
        )
        print(
            f"Scaffolding success rate: {scaffold_success / result['phase1_success'] * 100:.1f}% "
            f"(C:{result.get('phase3_complete', 0)} M:{result.get('phase3_minimal', 0)} P:{result.get('phase3_partial', 0)} F:{result.get('phase3_failed', 0)})"
        )


if __name__ == "__main__":
    asyncio.run(main())
