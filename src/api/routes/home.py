"""
Home page endpoints — stats, facets, featured rails, and surprise-me.

Phase B: Real implementation using report_service and entity_service.
Phase E: Cached for performance (§15, §18.1).

CACHE INVALIDATION (§18.1):
After ingesting new reports, clear home page caches by calling:
    from src.api.services.report_service import invalidate_aggregates
    invalidate_aggregates()

This clears stats and trending caches to ensure fresh data.
For now, restarting the API process also clears caches (they're in-memory).
"""

from fastapi import APIRouter
from typing import List
import random
import logging

from ..models import (
    HomeStats,
    HomeFacets,
    HomeFeatured,
    EntitySummary,
    ReportSummary,
)

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/stats", response_model=HomeStats)
async def get_stats():
    """
    Aggregate statistics for home page hero.

    Returns counts of reports, entities, findings, charts, tables, and date range.
    """
    from ..services.report_service import get_home_stats

    return get_home_stats()


@router.get("/facets", response_model=HomeFacets)
async def get_facets():
    """
    All facet values for filtering (tiers, states, years, ministries, entities, categories).
    """
    from ..services.report_service import get_home_facets

    return get_home_facets()


@router.get("/featured", response_model=HomeFeatured)
async def get_featured():
    """
    Featured content for home page rails (top ministries, entities, recent reports, deep dives).
    """
    from ..services.report_service import get_home_featured

    return get_home_featured()


@router.get("/trending", response_model=List[dict])
async def get_trending():
    """
    Trending searches (last 7 days, anonymized).

    Phase D implementation: queries query_logs table with privacy guards.
    Returns empty list if query_logs table doesn't exist yet.
    """
    from ..services.report_service import get_trending_searches

    return get_trending_searches()


@router.get("/surprise/report", response_model=ReportSummary)
async def surprise_report():
    """
    Random report from the registry (§10.1).
    """
    from ..services.report_service import get_all_reports

    reports = get_all_reports()

    if not reports:
        # Fallback if no reports loaded
        return ReportSummary(
            id="no_reports",
            title="No reports available",
            report_no="",
            ministry="",
            sector="",
            year=0,
            findings_count=0,
            monetary_impact=None,
            status="unknown",
            filename="",
            report_type=None,
            government_body_type="union",
            state_name=None,
            department=None,
            audit_category="compliance",
            ingested_at=None,
        )

    return random.choice(reports)


@router.get("/surprise/entity", response_model=EntitySummary)
async def surprise_entity():
    """
    Random entity weighted by mention count (§10.2).
    """
    from src.entity_graph.entity_service import get_entity_service

    entity_service = get_entity_service()

    if not entity_service:
        # Fallback if entity service unavailable
        logger.warning("Entity service not available for surprise_entity")
        return EntitySummary(
            id=0,
            canonical_name="Entity service unavailable",
            entity_type="unknown",
            primary_tier="union",
            aliases=[],
            first_seen_year=None,
            last_seen_year=None,
            mention_count=0,
            finding_count=0,
            report_count=0,
        )

    entity_dict = entity_service.random_weighted_entity(min_mentions=10)

    if not entity_dict:
        # Fallback if no entities found
        logger.warning("No entities found with min_mentions=10")
        return EntitySummary(
            id=0,
            canonical_name="No entities available",
            entity_type="unknown",
            primary_tier="union",
            aliases=[],
            first_seen_year=None,
            last_seen_year=None,
            mention_count=0,
            finding_count=0,
            report_count=0,
        )

    return EntitySummary(
        id=entity_dict["id"],
        canonical_name=entity_dict["canonical_name"],
        entity_type=entity_dict["entity_type"],
        primary_tier=entity_dict["primary_tier"],
        aliases=entity_dict["aliases"],
        first_seen_year=entity_dict["first_seen_year"],
        last_seen_year=entity_dict["last_seen_year"],
        mention_count=entity_dict["mention_count"],
        finding_count=entity_dict["finding_count"],
        report_count=entity_dict["report_count"],
    )
