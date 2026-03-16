#!/usr/bin/env python3
"""
Add multi-tier fields to existing Union data in data/processed/union/.

This script assumes files have already been moved to:
- data/processed/union/
- data/raw/union/

It adds the following fields to JSON files IN PLACE:
- government_body_type: "union"
- state_name: null
- department: null
- audit_category: <inferred from report_type>
- report_subtype: null

Usage:
    python scripts/migrate_union_data.py                # Dry run (preview)
    python scripts/migrate_union_data.py --execute      # Execute migration
"""

import json
from pathlib import Path
from typing import Dict, Tuple
import argparse


def infer_audit_category(report_type: str) -> str:
    """
    Infer audit_category from report_type field.

    Args:
        report_type: Report type string (e.g., "Performance Audit")

    Returns:
        Audit category: compliance, performance, financial, revenue, or commercial
    """
    if not report_type or report_type == "Unknown":
        return "compliance"

    report_type_lower = report_type.lower()

    # Check FRBM before compliance (FRBM Compliance Audit → financial)
    if "frbm" in report_type_lower or "financial" in report_type_lower:
        return "financial"
    elif "performance" in report_type_lower:
        return "performance"
    elif "revenue" in report_type_lower:
        return "revenue"
    elif "commercial" in report_type_lower or "pse" in report_type_lower:
        return "commercial"
    elif "compliance" in report_type_lower:
        return "compliance"
    else:
        return "compliance"  # Safe default


def update_chunks_json(
    file_path: Path,
    dry_run: bool = False
) -> Tuple[bool, int]:
    """
    Update a *_chunks.json file with tier fields IN PLACE.

    Returns:
        (success, chunks_updated_count)
    """
    try:
        # Load existing JSON
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Add tier fields to report_metadata
        if "report_metadata" not in data:
            print(f"  WARNING: {file_path.name} missing report_metadata, skipping")
            return False, 0

        report_metadata = data["report_metadata"]
        report_type = report_metadata.get("report_type", "Unknown")

        # Add new tier fields
        tier_fields = {
            "government_body_type": "union",
            "state_name": None,
            "department": None,
            "audit_category": infer_audit_category(report_type),
            "report_subtype": None,
        }

        report_metadata.update(tier_fields)

        # Add tier fields to each child chunk
        chunks_count = 0
        if "child_chunks" in data and isinstance(data["child_chunks"], list):
            for chunk in data["child_chunks"]:
                chunk.update(tier_fields)
                chunks_count += 1

        # Add tier fields to each parent chunk
        if "parent_chunks" in data and isinstance(data["parent_chunks"], list):
            for chunk in data["parent_chunks"]:
                chunk.update(tier_fields)

        # Write back to same file
        if dry_run:
            print(f"  [DRY RUN] Would update: {file_path.name}")
            print(f"            Audit category: {tier_fields['audit_category']}")
            print(f"            Child chunks: {chunks_count}")
        else:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            print(f"  Updated: {file_path.name} ({chunks_count} child chunks)")

        return True, chunks_count

    except Exception as e:
        print(f"  ERROR updating {file_path.name}: {e}")
        return False, 0


def update_overview_json(
    file_path: Path,
    dry_run: bool = False
) -> bool:
    """
    Update a *_overview.json file with tier fields IN PLACE.

    Returns:
        success
    """
    try:
        # Load existing JSON
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Add tier fields to basic_info
        if "basic_info" not in data:
            print(f"  WARNING: {file_path.name} missing basic_info, skipping")
            return False

        basic_info = data["basic_info"]
        report_type = basic_info.get("report_type", "Unknown")

        # Add new tier fields
        tier_fields = {
            "government_body_type": "union",
            "state_name": None,
            "department": None,
            "audit_category": infer_audit_category(report_type),
            "report_subtype": None,
        }

        basic_info.update(tier_fields)

        # Write back to same file
        if dry_run:
            print(f"  [DRY RUN] Would update: {file_path.name}")
            print(f"            Audit category: {tier_fields['audit_category']}")
        else:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            print(f"  Updated: {file_path.name}")

        return True

    except Exception as e:
        print(f"  ERROR updating {file_path.name}: {e}")
        return False


def update_json_files(dry_run: bool = False) -> Dict[str, int]:
    """
    Update all JSON files in data/processed/union/ with tier fields.

    Returns:
        Dictionary with update stats
    """
    print("=" * 80)
    print("STEP 1: UPDATE JSON FILES IN data/processed/union/")
    print("=" * 80)

    union_dir = Path("data/processed/union")

    stats = {
        "chunks_files": 0,
        "overview_files": 0,
        "other_files": 0,
        "total_child_chunks": 0,
        "failed": 0,
    }

    if not union_dir.exists():
        print(f"  ERROR: {union_dir} directory not found!")
        print("  Please ensure files have been moved to data/processed/union/ first.")
        print()
        return stats

    # Find all JSON files in union dir
    json_files = [f for f in union_dir.glob("*.json") if f.is_file()]

    if not json_files:
        print(f"  No JSON files found in {union_dir}")
        print()
        return stats

    print(f"Found {len(json_files)} JSON files in {union_dir}\n")

    for json_file in sorted(json_files):
        filename = json_file.name

        # Skip manifest.json (handled separately)
        if filename == "manifest.json":
            continue

        # Update based on file type
        if filename.endswith("_chunks.json"):
            success, chunks_count = update_chunks_json(json_file, dry_run)
            if success:
                stats["chunks_files"] += 1
                stats["total_child_chunks"] += chunks_count
            else:
                stats["failed"] += 1

        elif filename.endswith("_overview.json"):
            success = update_overview_json(json_file, dry_run)
            if success:
                stats["overview_files"] += 1
            else:
                stats["failed"] += 1

        else:
            # Other JSON files - count but don't modify
            stats["other_files"] += 1

    print()
    print("JSON Update Summary:")
    print(f"  Chunks files:     {stats['chunks_files']}")
    print(f"  Overview files:   {stats['overview_files']}")
    print(f"  Other files:      {stats['other_files']} (not modified)")
    print(f"  Total child chunks updated: {stats['total_child_chunks']}")
    if stats["failed"] > 0:
        print(f"  FAILED:           {stats['failed']}")
    print()

    return stats


def update_manifest(dry_run: bool = False) -> bool:
    """
    Update manifest.json with tier fields IN PLACE.

    Returns:
        success
    """
    print("=" * 80)
    print("STEP 2: UPDATE MANIFEST")
    print("=" * 80)

    manifest_path = Path("data/processed/union/manifest.json")

    if not manifest_path.exists():
        print(f"  No manifest.json found at {manifest_path}")
        print()
        return False

    try:
        # Load manifest
        with open(manifest_path, 'r', encoding='utf-8') as f:
            manifest = json.load(f)

        # Update each report entry
        updated_count = 0

        if "reports" in manifest and isinstance(manifest["reports"], list):
            for report in manifest["reports"]:
                # Add tier fields
                report_type = report.get("report_type", "Unknown")
                tier_fields = {
                    "government_body_type": "union",
                    "state_name": None,
                    "department": None,
                    "audit_category": infer_audit_category(report_type),
                    "report_subtype": None,
                }
                report.update(tier_fields)
                updated_count += 1

        if dry_run:
            print(f"  [DRY RUN] Would update {updated_count} report entries in manifest.json")
        else:
            # Write back to same file
            with open(manifest_path, 'w', encoding='utf-8') as f:
                json.dump(manifest, f, indent=2, ensure_ascii=False)
            print(f"  Updated {updated_count} report entries in manifest.json")

        print()
        return True

    except Exception as e:
        print(f"  ERROR updating manifest: {e}")
        print()
        return False


def verify_updates() -> bool:
    """
    Verify updates by checking for tier fields in sample files.

    Returns:
        True if verification passed
    """
    print("=" * 80)
    print("VERIFICATION")
    print("=" * 80)

    union_dir = Path("data/processed/union")

    if not union_dir.exists():
        print(f"  ERROR: {union_dir} not found")
        return False

    # Find sample files
    chunks_files = list(union_dir.glob("*_chunks.json"))
    overview_files = list(union_dir.glob("*_overview.json"))

    print(f"Files in {union_dir}:")
    print(f"  *_chunks.json files:   {len(chunks_files)}")
    print(f"  *_overview.json files: {len(overview_files)}")
    print()

    # Sample verification - check first chunks file
    if chunks_files:
        sample_file = chunks_files[0]
        try:
            with open(sample_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # Check report_metadata
            if "report_metadata" in data:
                metadata = data["report_metadata"]
                has_tier_fields = all(
                    key in metadata
                    for key in ["government_body_type", "state_name", "department", "audit_category", "report_subtype"]
                )

                if has_tier_fields:
                    print(f"✓ Tier fields found in {sample_file.name}:")
                    print(f"    government_body_type: {metadata['government_body_type']}")
                    print(f"    audit_category:       {metadata['audit_category']}")
                else:
                    print(f"✗ Tier fields MISSING in {sample_file.name}")
                    return False

            # Check child chunks
            if "child_chunks" in data and len(data["child_chunks"]) > 0:
                chunk = data["child_chunks"][0]
                has_chunk_fields = all(
                    key in chunk
                    for key in ["government_body_type", "state_name", "department", "audit_category", "report_subtype"]
                )

                if has_chunk_fields:
                    print(f"✓ Tier fields found in child chunks")
                else:
                    print(f"✗ Tier fields MISSING in child chunks")
                    return False

        except Exception as e:
            print(f"✗ Error verifying {sample_file.name}: {e}")
            return False

    print()
    print("✓ Verification PASSED")
    return True


def main():
    """Main update workflow."""
    parser = argparse.ArgumentParser(
        description="Add multi-tier fields to Union data in data/processed/union/",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/migrate_union_data.py                 # Dry run (preview)
  python scripts/migrate_union_data.py --execute       # Execute updates
        """
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Execute updates (default is dry-run)"
    )

    args = parser.parse_args()
    dry_run = not args.execute

    print()
    print("=" * 80)
    print("ADD MULTI-TIER FIELDS TO UNION DATA")
    print("=" * 80)
    if dry_run:
        print("MODE: DRY RUN (preview only, no changes will be made)")
        print("Run with --execute to perform actual updates")
    else:
        print("MODE: EXECUTE (will update files IN PLACE)")
    print("=" * 80)
    print()

    # Step 1: Update JSON files
    json_stats = update_json_files(dry_run)

    # Step 2: Update manifest
    manifest_success = update_manifest(dry_run)

    # Step 3: Verify (only if executed)
    if args.execute:
        print()
        verification_passed = verify_updates()
        print()

    # Final summary
    print()
    print("=" * 80)
    print("UPDATE COMPLETE")
    print("=" * 80)
    print(f"Chunks files:      {json_stats['chunks_files']}")
    print(f"Overview files:    {json_stats['overview_files']}")
    print(f"Other JSON files:  {json_stats['other_files']}")
    print(f"Child chunks:      {json_stats['total_child_chunks']}")
    print()

    if dry_run:
        print("This was a DRY RUN. No files were modified.")
        print("Run with --execute to perform the updates.")
    else:
        print("Updates executed successfully!")
        print()
        print("All JSON files in data/processed/union/ have been updated with:")
        print("  - government_body_type: 'union'")
        print("  - state_name: null")
        print("  - department: null")
        print("  - audit_category: <inferred from report_type>")
        print("  - report_subtype: null")
    print()


if __name__ == "__main__":
    main()
