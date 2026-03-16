#!/usr/bin/env python3
"""
Utility functions for merging LLM-extracted overview data.

Used by both:
- process_results.py (automated batch processing)
- scripts/merge_llm_overview.py (manual single-report processing)
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Optional


def find_llm_overview_file(report_id: str, overviews_dir: Path) -> Optional[Path]:
    """
    Find the LLM overview file using fuzzy matching for truncated names.

    Args:
        report_id: Full report ID
        overviews_dir: Directory containing LLM overview files

    Returns:
        Path to matching LLM overview file, or None if not found
    """
    if not overviews_dir.exists():
        return None

    # List all files in the directory
    all_files = list(overviews_dir.glob("*_overview_llm.json"))

    if len(all_files) == 0:
        return None

    # Strategy 1: Exact match
    for f in all_files:
        if report_id in f.name:
            return f

    # Strategy 2: Match on key parts of the report ID
    # Extract key identifiers: year, report number, ministry
    report_parts = report_id.split("_")

    # Try to find common substrings
    # e.g., "2025_04_CAG_Report_on_Union_Government_Accounts"
    for length in range(len(report_parts), 3, -1):
        partial_id = "_".join(report_parts[:length])
        for f in all_files:
            if partial_id in f.name:
                return f

    # Strategy 3: Match on year and report number pattern
    # Look for "2025_04" pattern
    year_report_pattern = "_".join(report_parts[:2]) if len(report_parts) >= 2 else None
    if year_report_pattern:
        for f in all_files:
            if year_report_pattern in f.name:
                return f

    return None


def merge_llm_overview_data(
    report_id: str,
    main_overview: dict,
    overviews_dir: Path,
    summaries_dir: Path,
    verbose: bool = False
) -> tuple[dict, dict]:
    """
    Merge LLM-extracted data into the main overview.

    Args:
        report_id: Report identifier
        main_overview: Base overview data (from JSON extraction)
        overviews_dir: Directory containing LLM overview files
        summaries_dir: Directory containing summary files
        verbose: Whether to print detailed merge info

    Returns:
        Tuple of (updated_overview, merge_stats)
        merge_stats contains: {
            "llm_file_found": bool,
            "fields_merged": int,
            "summaries_available": bool
        }
    """
    merge_stats = {
        "llm_file_found": False,
        "fields_merged": 0,
        "summaries_available": False,
        "llm_file_path": None
    }

    # Find LLM overview file (handles truncated names)
    llm_overview_path = find_llm_overview_file(report_id, overviews_dir)

    if llm_overview_path is None:
        if verbose:
            print(f"   ⚠️  No LLM overview file found for {report_id}")
        return main_overview, merge_stats

    merge_stats["llm_file_found"] = True
    merge_stats["llm_file_path"] = str(llm_overview_path)

    # Load LLM overview
    try:
        with open(llm_overview_path, "r", encoding="utf-8") as f:
            llm_overview = json.load(f)
    except Exception as e:
        if verbose:
            print(f"   ❌ Failed to load LLM overview: {e}")
        return main_overview, merge_stats

    # Fields to merge from LLM extraction
    llm_fields = ["audit_scope", "audit_objectives", "topics_covered", "glossary_terms"]

    # Merge LLM fields
    for field in llm_fields:
        if field in llm_overview and llm_overview[field] is not None:
            main_overview[field] = llm_overview[field]
            merge_stats["fields_merged"] += 1

            if verbose:
                # Show what was merged
                if isinstance(llm_overview[field], list):
                    print(f"      ✓ {field}: {len(llm_overview[field])} items")
                elif isinstance(llm_overview[field], dict):
                    print(f"      ✓ {field}: dict with {len(llm_overview[field])} keys")
                else:
                    print(f"      ✓ {field}")

    # Update metadata
    if "_metadata" not in main_overview:
        main_overview["_metadata"] = {}

    main_overview["_metadata"]["llm_extraction_available"] = merge_stats["fields_merged"] > 0
    main_overview["_metadata"]["llm_extraction_path"] = merge_stats["llm_file_path"]
    main_overview["_metadata"]["llm_merged_at"] = datetime.now().isoformat()
    main_overview["_metadata"]["llm_fields_merged"] = merge_stats["fields_merged"]

    # Check for summaries
    summaries_path = summaries_dir / f"{report_id}_summaries.json"
    merge_stats["summaries_available"] = summaries_path.exists()
    main_overview["_metadata"]["summaries_available"] = merge_stats["summaries_available"]
    main_overview["_metadata"]["summaries_path"] = (
        str(summaries_path) if merge_stats["summaries_available"] else None
    )

    return main_overview, merge_stats
