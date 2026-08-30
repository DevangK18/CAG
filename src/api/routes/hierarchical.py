"""
Hierarchical (RAPTOR) summaries endpoint.

Item 6: Expose hierarchical summaries indexed in Qdrant.
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Optional

from ..models import HierarchicalSummary, HierarchicalResponse
from ..services.streaming_wrapper import get_rag_service

router = APIRouter()


@router.get("/reports/{report_id}/hierarchical", response_model=HierarchicalResponse)
async def get_hierarchical_summaries(
    report_id: str,
    level: Optional[int] = Query(
        None, ge=1, le=2, description="Hierarchy level: 1=section, 2=chapter"
    ),
    limit: int = Query(20, ge=1, le=50, description="Maximum summaries to return"),
):
    """
    Get hierarchical (RAPTOR) summaries for a report.

    These are pre-computed chapter and section-level summaries that provide
    a high-level overview of the report content.

    Args:
        report_id: The report identifier
        level: Optional filter by hierarchy level (1=section, 2=chapter)
        limit: Maximum number of summaries to return

    Returns:
        HierarchicalResponse with list of summaries
    """
    rag = get_rag_service()
    if not rag or not rag.qdrant:
        raise HTTPException(
            status_code=503, detail="Qdrant service not available"
        )

    # Build filter
    filters = {"report_id": report_id}
    if level:
        filters["hierarchy_level"] = level
    # Match any hierarchical content type
    filters["content_type"] = ["chapter_summary", "section_summary"]

    try:
        results = rag.qdrant.scroll_by_filter(filters, limit=limit)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to retrieve hierarchical summaries: {e}"
        )

    summaries = [
        HierarchicalSummary(
            chunk_id=r.get("chunk_id", ""),
            title=r.get("title", ""),
            summary=r.get("content", ""),
            level=r.get("hierarchy_level", 0),
            parent_chunk_id=r.get("parent_chunk_id"),
        )
        for r in results
    ]

    return HierarchicalResponse(
        report_id=report_id,
        summaries=summaries,
        total=len(summaries),
    )
