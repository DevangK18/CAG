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


# Key the overview batch stamps into <id>_overview_llm.json to mark its run.
RUN_MARKER_KEY = "_job_timestamp"


def find_llm_overview_file(report_id: str, overviews_dir: Path) -> Optional[Path]:
    """
    Find this report's LLM overview file by exact report ID.

    No prefix or substring fallback: state and local IDs share their first parts
    ("OD_2025_..."), so a fuzzy match picked another report's overview whenever
    this one's was missing (D-10a-05).

    Args:
        report_id: Full report ID
        overviews_dir: Directory containing LLM overview files

    Returns:
        Path to {report_id}_overview_llm.json, or None if it does not exist
    """
    path = Path(overviews_dir) / f"{report_id}_overview_llm.json"
    return path if path.is_file() else None


def merge_llm_overview_data(
    report_id: str,
    main_overview: dict,
    overviews_dir: Path,
    summaries_dir: Path,
    verbose: bool = False,
    run_marker: Optional[str] = None,
) -> tuple[dict, dict]:
    """
    Merge LLM-extracted data into the main overview.

    Args:
        report_id: Report identifier
        main_overview: Base overview data (from JSON extraction)
        overviews_dir: Directory containing LLM overview files
        summaries_dir: Directory containing summary files
        verbose: Whether to print detailed merge info
        run_marker: This run's job timestamp. When both it and the file's
            RUN_MARKER_KEY are set and differ, the file is from an earlier run
            and is not merged.

    Returns:
        Tuple of (updated_overview, merge_stats)
        merge_stats contains: {
            "llm_file_found": bool,
            "fields_merged": int,
            "summaries_available": bool,
            "stale": bool
        }
    """
    merge_stats = {
        "llm_file_found": False,
        "fields_merged": 0,
        "summaries_available": False,
        "llm_file_path": None,
        "stale": False,
    }

    llm_overview_path = find_llm_overview_file(report_id, overviews_dir)
    llm_overview = None

    if llm_overview_path is None:
        if verbose:
            print(f"   ⚠️  No LLM overview file found for {report_id}")
    else:
        merge_stats["llm_file_found"] = True
        merge_stats["llm_file_path"] = str(llm_overview_path)
        try:
            with open(llm_overview_path, "r", encoding="utf-8") as f:
                llm_overview = json.load(f)
        except Exception as e:
            if verbose:
                print(f"   ❌ Failed to load LLM overview: {e}")

    file_marker = llm_overview.get(RUN_MARKER_KEY) if isinstance(llm_overview, dict) else None
    if run_marker and file_marker and file_marker != run_marker:
        # Left over from an earlier run: this run's overview failed
        if verbose:
            print(f"   ⚠️  Stale LLM overview for {report_id} (run {file_marker})")
        merge_stats["stale"] = True
        llm_overview = None

    if not isinstance(llm_overview, dict):
        _record_llm_metadata(main_overview, merge_stats, None)
        _record_summaries(report_id, main_overview, merge_stats, summaries_dir)
        return main_overview, merge_stats

    # Fields to merge from LLM extraction
    llm_fields = [
        "audit_scope",
        "audit_objectives",
        "topics_covered",
        "glossary_terms",
        "normalized_entities",  # Phase 12: per-report entity normalization
    ]

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

    _record_llm_metadata(main_overview, merge_stats, file_marker)
    _record_summaries(report_id, main_overview, merge_stats, summaries_dir)
    return main_overview, merge_stats


def _record_llm_metadata(main_overview: dict, merge_stats: dict, file_marker: Optional[str]):
    meta = main_overview.setdefault("_metadata", {})
    merged = merge_stats["fields_merged"] > 0
    meta["llm_extraction_available"] = merged
    meta["llm_extraction_path"] = merge_stats["llm_file_path"] if merged else None
    meta["llm_extraction_run"] = file_marker if merged else None
    meta["llm_extraction_stale"] = merge_stats["stale"]
    meta["llm_merged_at"] = datetime.now().isoformat()
    meta["llm_fields_merged"] = merge_stats["fields_merged"]


def _record_summaries(report_id: str, main_overview: dict, merge_stats: dict, summaries_dir: Path):
    summaries_path = Path(summaries_dir) / f"{report_id}_summaries.json"
    merge_stats["summaries_available"] = summaries_path.exists()
    meta = main_overview.setdefault("_metadata", {})
    meta["summaries_available"] = merge_stats["summaries_available"]
    meta["summaries_path"] = str(summaries_path) if merge_stats["summaries_available"] else None
