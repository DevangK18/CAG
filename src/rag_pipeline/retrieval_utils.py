"""
Retrieval utilities shared between agentic and comparative paths.

Includes:
- merge_retrieval_results: Merges multiple RetrievalResults
- merge_filters: Merges explicit and auto-detected filters
- has_explicit_report_filter: Checks for report_id in filters
"""

import logging
from copy import copy
from typing import List, Dict, Any, Optional

try:
    from .models import RetrievalResult, ParentContext, RetrievedChunk
except ImportError:
    from models import RetrievalResult, ParentContext, RetrievedChunk

logger = logging.getLogger(__name__)


# =============================================================================
# FILTER UTILITIES
# =============================================================================


def merge_filters(
    explicit: Optional[Dict[str, Any]],
    auto: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Merge explicit (user-provided) filters with auto-detected filters.

    Explicit filters always win; auto-detected filters fill gaps.

    Args:
        explicit: Filters explicitly passed by caller (e.g., from API request)
        auto: Filters auto-detected from query text

    Returns:
        Merged filter dict (never None, may be empty)
    """
    result: Dict[str, Any] = {}

    # Add auto-detected filters first (lower priority)
    if auto:
        result.update(auto)

    # Explicit filters overwrite auto-detected (higher priority)
    if explicit:
        result.update(explicit)

    return result


def has_explicit_report_filter(filters: Optional[Dict[str, Any]]) -> bool:
    """
    Check if filters contain an explicit report_id filter.

    When report_id is specified, auto-filter extraction should be skipped
    since the user has already narrowed to a specific report.

    Args:
        filters: Filter dict to check

    Returns:
        True if report_id is present in filters
    """
    if not filters:
        return False
    return "report_id" in filters


# =============================================================================
# RETRIEVAL RESULT MERGING
# =============================================================================


def merge_retrieval_results(retrievals: List[RetrievalResult]) -> RetrievalResult:
    """
    Merge multiple RetrievalResults into one.

    Deduplicates by chunk_id; keeps highest-scored copy per chunk.
    Re-groups by parent.

    Used by:
    - AgenticRAGService for sub-query merging
    - ask_comparative() for cross-report merging (Phase 12)
    """
    if not retrievals:
        return RetrievalResult(
            query="",
            total_candidates=0,
            total_after_rerank=0,
            parents=[],
            filters_applied={},
            reranker_used="none",
            search_type="merged_empty",
        )

    seen_chunks: dict = {}  # chunk_id -> RetrievedChunk
    parent_map: dict = {}   # parent_chunk_id -> ParentContext (copy)

    for result in retrievals:
        for parent in result.parents:
            if parent.chunk_id not in parent_map:
                p_copy = copy(parent)
                p_copy.children = []
                parent_map[parent.chunk_id] = p_copy

            for child in parent.children:
                if child.chunk_id not in seen_chunks:
                    seen_chunks[child.chunk_id] = child
                    parent_map[parent.chunk_id].children.append(child)
                else:
                    existing = seen_chunks[child.chunk_id]
                    if child.score > existing.score:
                        existing.score = child.score

    parents_list = [p for p in parent_map.values() if p.children]
    parents_list.sort(key=lambda p: -max(c.score for c in p.children))

    return RetrievalResult(
        query=retrievals[0].query,
        total_candidates=sum(r.total_candidates for r in retrievals),
        total_after_rerank=len(seen_chunks),
        parents=parents_list,
        filters_applied=retrievals[0].filters_applied if retrievals else {},
        reranker_used=retrievals[0].reranker_used if retrievals else "none",
        search_type="merged",
    )
