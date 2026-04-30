"""
Home page endpoints — stats, facets, featured rails, and surprise-me.

Phase A scaffold: All endpoints return stub data structures.
Real implementation connects to report_service and entity_service in Phase B.
"""

from fastapi import APIRouter
from typing import List

from ..models import (
    HomeStats,
    HomeFacets,
    HomeFeatured,
    EntitySummary,
    ReportSummary,
)

router = APIRouter()


@router.get("/stats", response_model=HomeStats)
async def get_stats():
    """
    Aggregate statistics for home page hero.

    Returns counts of reports, entities, findings, charts, tables, and date range.
    Stub: all zeros and empty date range.
    """
    return HomeStats(
        total_reports=0,
        total_entities=0,
        total_ministries=0,
        total_mentions=0,
        total_findings=0,
        total_charts=0,
        total_tables=0,
        latest_ingest=None,
        year_range=(0, 0),
    )


@router.get("/facets", response_model=HomeFacets)
async def get_facets():
    """
    All facet values for filtering (tiers, states, years, ministries, entities, categories).

    Stub: all empty lists.
    """
    return HomeFacets(
        tiers=[],
        states=[],
        years=[],
        ministries=[],
        entities=[],
        audit_categories=[],
    )


@router.get("/featured", response_model=HomeFeatured)
async def get_featured():
    """
    Featured content for home page rails (top ministries, entities, recent reports, deep dives).

    Stub: all empty lists.
    """
    return HomeFeatured(
        top_ministries=[],
        top_entities=[],
        recent_reports=[],
        deep_dives=[],
        popular_starts=[],
    )


@router.get("/trending", response_model=List[dict])
async def get_trending():
    """
    Trending searches (last 7 days, anonymized).

    Phase B+ feature. Stub: empty list.
    """
    return []


@router.get("/surprise/report", response_model=ReportSummary)
async def surprise_report():
    """
    Random report from the registry.

    Stub: hardcoded placeholder report.
    """
    return ReportSummary(
        id="stub_report",
        title="Stub Report",
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


@router.get("/surprise/entity", response_model=EntitySummary)
async def surprise_entity():
    """
    Random entity weighted by mention count.

    Stub: hardcoded placeholder entity.
    """
    return EntitySummary(
        id=0,
        canonical_name="Stub Entity",
        entity_type="unknown",
        primary_tier="union",
        aliases=[],
        first_seen_year=None,
        last_seen_year=None,
        mention_count=0,
        finding_count=0,
        report_count=0,
    )
