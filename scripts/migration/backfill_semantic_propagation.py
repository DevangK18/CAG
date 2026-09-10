#!/usr/bin/env python3
"""
Backfill Semantic Enrichment Propagation
==========================================

Retroactively applies semantic enrichment propagation to existing
processed JSON files. This ensures existing data has finding_type,
severity, is_recommendation, etc. populated at the chunk level.

Run: python scripts/backfill_semantic_propagation.py
     python scripts/backfill_semantic_propagation.py --dry-run
     python scripts/backfill_semantic_propagation.py --reports 2023_07 UK_2025_06

This script is idempotent - running it multiple times is safe.
"""

import argparse
import json
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.parsing_pipeline.modules.assembly_service import (
    propagate_semantic_enrichment_to_chunks,
)


def process_report(json_path: Path, dry_run: bool = False) -> dict:
    """
    Process a single report JSON file.

    Args:
        json_path: Path to the _chunks.json file
        dry_run: If True, don't save changes

    Returns:
        Statistics dict
    """
    stats = {
        "path": str(json_path),
        "status": "unknown",
        "findings": 0,
        "recommendations": 0,
        "entities": 0,
        "chunks_updated": 0,
    }

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        stats["status"] = f"error_reading: {e}"
        return stats

    # Check if semantic_enrichment exists
    if "semantic_enrichment" not in data:
        stats["status"] = "no_semantic_enrichment"
        return stats

    # Check if propagation already done (sample check)
    child_chunks = data.get("child_chunks", [])
    if not child_chunks:
        stats["status"] = "no_child_chunks"
        return stats

    # Count chunks that already have finding_type
    already_propagated = sum(
        1 for c in child_chunks
        if c.get("structured_data", {}).get("finding_type")
        or c.get("structured_data", {}).get("is_recommendation")
    )

    if already_propagated > 0:
        stats["status"] = "already_propagated"
        stats["chunks_updated"] = already_propagated
        return stats

    # Apply propagation
    findings, recs, entities = propagate_semantic_enrichment_to_chunks(
        child_chunks,
        data["semantic_enrichment"],
    )

    stats["findings"] = findings
    stats["recommendations"] = recs
    stats["entities"] = entities
    stats["chunks_updated"] = findings + recs

    if findings == 0 and recs == 0:
        stats["status"] = "no_enrichment_data"
        return stats

    # Save if not dry run
    if not dry_run:
        try:
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            stats["status"] = "updated"
        except Exception as e:
            stats["status"] = f"error_saving: {e}"
    else:
        stats["status"] = "dry_run"

    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Backfill semantic enrichment propagation to existing reports"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be updated without making changes",
    )
    parser.add_argument(
        "--reports",
        nargs="*",
        help="Filter to specific report IDs (partial match)",
    )
    parser.add_argument(
        "--data-dir",
        default="data/processed",
        help="Path to processed data directory",
    )

    args = parser.parse_args()

    data_dir = PROJECT_ROOT / args.data_dir

    print("=" * 70)
    print("SEMANTIC ENRICHMENT PROPAGATION BACKFILL")
    print("=" * 70)
    print(f"Data directory: {data_dir}")
    print(f"Dry run: {args.dry_run}")
    if args.reports:
        print(f"Filter reports: {args.reports}")
    print()

    # Find all chunk files
    chunk_files = []
    for tier in ["union", "state", "local_body"]:
        tier_dir = data_dir / tier
        if tier_dir.exists():
            chunk_files.extend(tier_dir.glob("*_chunks.json"))

    # Filter if specified
    if args.reports:
        filtered = []
        for f in chunk_files:
            for report_filter in args.reports:
                if report_filter in f.stem:
                    filtered.append(f)
                    break
        chunk_files = filtered

    print(f"Found {len(chunk_files)} report files\n")

    # Process each file
    results = {
        "updated": [],
        "already_propagated": [],
        "no_enrichment_data": [],
        "no_semantic_enrichment": [],
        "errors": [],
        "dry_run": [],
    }

    total_findings = 0
    total_recs = 0
    total_entities = 0

    for i, json_path in enumerate(sorted(chunk_files), 1):
        print(f"[{i:3d}/{len(chunk_files)}] {json_path.stem[:50]}...", end=" ")

        stats = process_report(json_path, dry_run=args.dry_run)

        if stats["status"] == "updated" or stats["status"] == "dry_run":
            print(f"✓ F:{stats['findings']} R:{stats['recommendations']} E:{stats['entities']}")
            results[stats["status"]].append(stats)
            total_findings += stats["findings"]
            total_recs += stats["recommendations"]
            total_entities += stats["entities"]
        elif stats["status"] == "already_propagated":
            print(f"- Already propagated ({stats['chunks_updated']} chunks)")
            results["already_propagated"].append(stats)
        elif stats["status"] == "no_enrichment_data":
            print("- No findings/recs to propagate")
            results["no_enrichment_data"].append(stats)
        elif stats["status"] == "no_semantic_enrichment":
            print("⚠ No semantic_enrichment key")
            results["no_semantic_enrichment"].append(stats)
        else:
            print(f"✗ {stats['status']}")
            results["errors"].append(stats)

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    if args.dry_run:
        print(f"Would update:            {len(results['dry_run'])}")
    else:
        print(f"Updated:                 {len(results['updated'])}")
    print(f"Already propagated:      {len(results['already_propagated'])}")
    print(f"No enrichment data:      {len(results['no_enrichment_data'])}")
    print(f"No semantic_enrichment:  {len(results['no_semantic_enrichment'])}")
    print(f"Errors:                  {len(results['errors'])}")
    print()
    print(f"Total findings propagated:        {total_findings}")
    print(f"Total recommendations propagated: {total_recs}")
    print(f"Total entity annotations:         {total_entities}")

    if args.dry_run:
        print("\n⚠ DRY RUN - No files were modified")
        print("Run without --dry-run to apply changes")


if __name__ == "__main__":
    main()
