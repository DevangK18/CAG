"""
Report listing and detail endpoints.
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Optional
from ..models import ReportsListResponse, ReportDetail
from ..services.report_service import (
    get_all_reports,
    get_report_by_id,
    get_reports_by_sector,
    get_reports_by_year
)

router = APIRouter()


@router.get("", response_model=ReportsListResponse)
async def list_reports(
    sector: Optional[str] = None,
    year: Optional[int] = None,
    government_body_type: Optional[str] = Query(None, description="Filter by tier: union, state, local_body"),
    state_name: Optional[str] = Query(None, description="Filter by state name"),
    audit_category: Optional[str] = Query(None, description="Filter by audit category")
):
    """
    List all available reports with optional filtering.

    Query params:
    - sector: Filter by sector (e.g., "Infrastructure", "Healthcare")
    - year: Filter by year (e.g., 2023, 2024)
    - government_body_type: Filter by tier (union, state, local_body)
    - state_name: Filter by state name
    - audit_category: Filter by audit category
    """
    if sector:
        reports = get_reports_by_sector(sector)
    elif year:
        reports = get_reports_by_year(year)
    else:
        reports = get_all_reports()

    # Apply additional tier-based filters
    if government_body_type:
        reports = [r for r in reports if r.government_body_type == government_body_type]

    if state_name:
        reports = [r for r in reports if r.state_name and r.state_name.lower() == state_name.lower()]

    if audit_category:
        reports = [r for r in reports if r.audit_category == audit_category]

    return ReportsListResponse(reports=reports, total=len(reports))


@router.get("/filters")
async def get_report_filters():
    """
    Get available filter options with counts for each tier field.

    Returns aggregated counts for:
    - government_body_types (union, state, local_body)
    - states (alphabetically sorted)
    - audit_categories (sorted by count descending)
    """
    reports = get_all_reports()

    # Aggregate counts
    body_type_counts = {}
    state_counts = {}
    category_counts = {}

    for report in reports:
        # Count government body types
        body_type = report.government_body_type
        body_type_counts[body_type] = body_type_counts.get(body_type, 0) + 1

        # Count states (only for non-union reports with state_name)
        if report.state_name:
            state = report.state_name
            state_counts[state] = state_counts.get(state, 0) + 1

        # Count audit categories
        category = report.audit_category
        category_counts[category] = category_counts.get(category, 0) + 1

    # Format government body types with labels
    body_type_labels = {
        "union": "Union",
        "state": "State",
        "local_body": "Local Bodies"
    }

    government_body_types = [
        {
            "value": body_type,
            "label": body_type_labels.get(body_type, body_type.title()),
            "count": count
        }
        for body_type, count in body_type_counts.items()
    ]

    # Format states (alphabetically sorted)
    states = [
        {"value": state, "count": count}
        for state, count in sorted(state_counts.items())
    ]

    # Format audit categories (sorted by count descending)
    audit_categories = [
        {"value": category, "count": count}
        for category, count in sorted(category_counts.items(), key=lambda x: x[1], reverse=True)
    ]

    return {
        "government_body_types": government_body_types,
        "states": states,
        "audit_categories": audit_categories
    }


@router.get("/{report_id}", response_model=ReportDetail)
async def get_report(report_id: str):
    """
    Get detailed information about a specific report.
    
    Includes:
    - Executive summary
    - Key findings (up to 10)
    - Recommendations (up to 10)
    - Metadata (ministry, sector, year, etc.)
    """
    report = get_report_by_id(report_id)
    if not report:
        raise HTTPException(status_code=404, detail=f"Report '{report_id}' not found")
    return report


@router.get("/{report_id}/pdf-url")
async def get_pdf_url(report_id: str):
    """
    Get the URL to load the PDF for a report.
    
    Returns the relative URL path that can be used with the static file server.
    """
    report = get_report_by_id(report_id)
    if not report:
        raise HTTPException(status_code=404, detail=f"Report '{report_id}' not found")
    
    return {
        "pdf_url": f"/api/files/{report.filename}",
        "filename": report.filename,
        "pages": report.pages
    }
