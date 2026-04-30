"""
Smart search endpoint — unified interface for reports, entities, findings, etc.

Phase A scaffold: Stub endpoint returns empty results.
Real implementation dispatches to search_service in Phase C.
"""

from fastapi import APIRouter, Request
from typing import Optional

from ..models import GroupedSearchResults
from ..rate_limit import limiter, RATE_LIMIT_CHAT

router = APIRouter()


@router.get("", response_model=GroupedSearchResults)
@limiter.limit(RATE_LIMIT_CHAT)
async def search(
    request: Request,
    q: str,
    type: str = "all",
    limit: int = 5,
):
    """
    Unified search across reports, ministries, entities, findings, and glossary.

    Query parameters:
    - q: Search query (required)
    - type: Channel to search ('all', 'reports', 'ministries', 'entities', 'findings', 'glossary')
    - limit: Max results per channel (default 5)

    Stub: returns empty results across all channels.
    Real implementation: multiplexes to search_service with parallel channel handlers.
    """
    return GroupedSearchResults(
        reports=[],
        ministries=[],
        entities=[],
        findings=[],
        glossary=[],
        top_hit_channel=None,
        top_hit_score=None,
    )
