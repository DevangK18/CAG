"""
P0-06: Canonicalize Report IDs

Migrates report files from legacy format (non-zero-padded) to canonical format:
    Legacy:    2025_4_title.pdf, 2025_4_title_chunks.json
    Canonical: 2025_04_title.pdf, 2025_04_title_chunks.json

Also updates internal references within JSON files.

Usage:
    python scripts/canonicalize_report_ids.py [--data-dir data] [--dry-run]

Examples:
    # Preview changes (dry run)
    python scripts/canonicalize_report_ids.py --dry-run

    # Apply migration
    python scripts/canonicalize_report_ids.py
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import List, Dict, Tuple, Optional

# Pattern to match legacy format: year_singledigit_title
# e.g., 2025_4_Performance_Audit or OD_2025_4_Compliance
LEGACY_PATTERN = re.compile(
    r"^((?:[A-Z]{2}_)?)"        # Optional state code prefix
    r"(\d{4})_"                  # Year
    r"([1-9])_"                  # Single digit (1-9, not starting with 0)
    r"(.+)$"                     # Rest of filename
)


def is_legacy_format(filename: str) -> bool:
    """Check if filename uses legacy (non-zero-padded) format."""
    return bool(LEGACY_PATTERN.match(filename))


def to_canonical_format(filename: str) -> Optional[str]:
    """
    Convert legacy filename to canonical format.

    Args:
        filename: Legacy filename (without extension)

    Returns:
        Canonical filename if conversion needed, None otherwise
    """
    match = LEGACY_PATTERN.match(filename)
    if not match:
        return None

    prefix, year, num, rest = match.groups()
    # Zero-pad the number
    canonical = f"{prefix}{year}_{num.zfill(2)}_{rest}"
    return canonical


def find_legacy_files(data_dir: Path) -> List[Tuple[Path, Path]]:
    """
    Find all files with legacy report IDs.

    Args:
        data_dir: Base data directory

    Returns:
        List of (legacy_path, canonical_path) tuples
    """
    migrations = []

    # Search in all subdirectories
    for subdir in ["raw/union", "raw/state", "raw/local_body",
                   "processed/union", "processed/state", "processed/local_body",
                   "processed"]:  # Also check root processed
        search_dir = data_dir / subdir
        if not search_dir.exists():
            continue

        for file in search_dir.iterdir():
            if file.is_file():
                stem = file.stem
                # Remove common suffixes to get the base report ID
                for suffix in ["_chunks", "_enriched", "_trace", "_summary"]:
                    if stem.endswith(suffix):
                        stem = stem[:-len(suffix)]
                        break

                if is_legacy_format(stem):
                    canonical_stem = to_canonical_format(stem)
                    if canonical_stem:
                        # Reconstruct full filename with original suffix
                        original_suffix = file.stem[len(stem):]
                        canonical_name = f"{canonical_stem}{original_suffix}{file.suffix}"
                        canonical_path = file.parent / canonical_name

                        # Only add if canonical doesn't already exist
                        if not canonical_path.exists():
                            migrations.append((file, canonical_path))

    return migrations


def update_json_references(file_path: Path, old_id: str, new_id: str) -> bool:
    """
    Update report_id references within a JSON file.

    Args:
        file_path: Path to JSON file
        old_id: Legacy report ID
        new_id: Canonical report ID

    Returns:
        True if file was modified, False otherwise
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Check if old_id appears in the file
        if old_id not in content:
            return False

        # Simple string replacement for report_id values
        # This handles "report_id": "2025_4_..." patterns
        modified = content.replace(f'"{old_id}', f'"{new_id}')
        modified = modified.replace(f"'{old_id}", f"'{new_id}")

        if modified != content:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(modified)
            return True

        return False
    except Exception as e:
        print(f"  Warning: Could not update {file_path}: {e}")
        return False


def extract_report_id(filename: str) -> str:
    """Extract report ID from filename (remove suffixes and extension)."""
    stem = Path(filename).stem
    for suffix in ["_chunks", "_enriched", "_trace", "_summary"]:
        if stem.endswith(suffix):
            return stem[:-len(suffix)]
    return stem


def main():
    parser = argparse.ArgumentParser(
        description="Canonicalize report IDs (P0-06 migration)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Preview changes
  python scripts/canonicalize_report_ids.py --dry-run

  # Apply migration
  python scripts/canonicalize_report_ids.py

  # Custom data directory
  python scripts/canonicalize_report_ids.py --data-dir /path/to/data
        """
    )
    parser.add_argument(
        "--data-dir",
        default="data",
        help="Base data directory (default: data)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without modifying files"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show detailed output"
    )

    args = parser.parse_args()
    data_dir = Path(args.data_dir)

    if not data_dir.exists():
        print(f"Error: Data directory not found: {data_dir}")
        sys.exit(1)

    print(f"P0-06: Canonicalize Report IDs")
    print(f"{'='*60}")
    print(f"Data directory: {data_dir}")
    print(f"Mode: {'DRY RUN' if args.dry_run else 'LIVE'}")
    print()

    # Find all legacy files
    print("Scanning for legacy format files...")
    migrations = find_legacy_files(data_dir)

    if not migrations:
        print("No legacy format files found. All files are already canonical.")
        return

    print(f"Found {len(migrations)} files to migrate\n")

    # Group by directory for cleaner output
    by_dir: Dict[Path, List[Tuple[Path, Path]]] = {}
    for old, new in migrations:
        dir_path = old.parent
        if dir_path not in by_dir:
            by_dir[dir_path] = []
        by_dir[dir_path].append((old, new))

    renamed_count = 0
    updated_refs_count = 0

    for dir_path, files in sorted(by_dir.items()):
        print(f"\nDirectory: {dir_path.relative_to(data_dir)}")
        print("-" * 40)

        for old_path, new_path in files:
            old_id = extract_report_id(old_path.name)
            new_id = extract_report_id(new_path.name)

            print(f"  RENAME: {old_path.name}")
            print(f"      -> {new_path.name}")

            if not args.dry_run:
                # Rename the file
                old_path.rename(new_path)
                renamed_count += 1

                # If it's a JSON file, update internal references
                if new_path.suffix == '.json':
                    if update_json_references(new_path, old_id, new_id):
                        print(f"      (updated internal references)")
                        updated_refs_count += 1
            else:
                renamed_count += 1

    # Summary
    print(f"\n{'='*60}")
    print("Summary:")
    print(f"  Files to rename: {renamed_count}")
    if not args.dry_run:
        print(f"  Internal refs updated: {updated_refs_count}")

    if args.dry_run:
        print(f"\nThis was a dry run. Run without --dry-run to apply changes.")


if __name__ == "__main__":
    main()
