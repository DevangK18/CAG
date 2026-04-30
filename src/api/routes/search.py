"""
Smart search endpoint — unified interface for reports, entities, findings, etc.

Phase C implementation: Real search service integration.
Dispatches to search_service with parallel channel handlers.
"""

import logging
from fastapi import APIRouter, Request, HTTPException

from ..models import GroupedSearchResults
from ..rate_limit import limiter, RATE_LIMIT_CHAT

logger = logging.getLogger(__name__)
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

    Returns grouped results by channel with top_hit determination for smart-Enter routing.
    """
    # Get search service from app state
    search_service = getattr(request.app.state, 'search_service', None)

    if search_service is None:
        # Fallback: return empty results if search service not initialized
        logger.warning("Search service not available")
        return GroupedSearchResults(
            reports=[],
            ministries=[],
            entities=[],
            findings=[],
            glossary=[],
            top_hit_channel=None,
            top_hit_score=None,
        )

    # Validate channel parameter
    valid_channels = {'all', 'reports', 'ministries', 'entities', 'findings', 'glossary'}
    if type not in valid_channels:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid channel type '{type}'. Must be one of: {', '.join(valid_channels)}"
        )

    # Get query logger for observability (§12)
    query_logger = getattr(request.app.state, 'query_logger', None)

    try:
        # Execute search with optional observability logging
        if query_logger:
            # Log the search query (QueryLogContext is a sync context manager)
            ctx = query_logger.start_query(
                interaction_mode="home_search",
                query_text=q,
                style=None,
            )
            ctx.__enter__()
            try:
                results = await search_service.search(
                    query=q,
                    channel=type,
                    limit_per_channel=limit,
                )

                # Record channel hit counts for analytics
                channel_counts = {
                    'reports': len(results.reports),
                    'ministries': len(results.ministries),
                    'entities': len(results.entities),
                    'findings': len(results.findings),
                    'glossary': len(results.glossary),
                }

                # If ctx has record_search method, call it
                if hasattr(ctx, 'record_search'):
                    ctx.record_search(channel_counts=channel_counts)
                elif hasattr(ctx, 'set_extra'):
                    ctx.set_extra('channel_counts', channel_counts)

                ctx.__exit__(None, None, None)
                return results
            except Exception as e:
                ctx.__exit__(type(e), e, e.__traceback__)
                raise
        else:
            # No query logger — just run the search
            return await search_service.search(
                query=q,
                channel=type,
                limit_per_channel=limit,
            )

    except Exception as e:
        logger.error(f"Search failed: {e}", exc_info=True)
        # Return empty results on error rather than 500
        return GroupedSearchResults(
            reports=[],
            ministries=[],
            entities=[],
            findings=[],
            glossary=[],
            top_hit_channel=None,
            top_hit_score=None,
        )
