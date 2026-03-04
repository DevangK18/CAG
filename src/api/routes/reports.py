"""
Report listing and detail endpoints.
"""

from fastapi import APIRouter, HTTPException
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
    year: Optional[int] = None
):
    """
    List all available reports with optional filtering.
    
    Query params:
    - sector: Filter by sector (e.g., "Infrastructure", "Healthcare")
    - year: Filter by year (e.g., 2023, 2024)
    """
    if sector:
        reports = get_reports_by_sector(sector)
    elif year:
        reports = get_reports_by_year(year)
    else:
        reports = get_all_reports()
    
    return ReportsListResponse(reports=reports, total=len(reports))


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
