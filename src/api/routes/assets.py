"""
Assets endpoints - Charts and Tables extraction.

Provides endpoints for retrieving extracted charts and tables from reports.
These endpoints support the frontend Charts and Tables tabs.

Endpoints:
- GET /reports/{report_id}/charts - Get all charts from a report
- GET /reports/{report_id}/tables - Get all tables from a report
- GET /reports/{report_id}/charts/{chart_id} - Get specific chart details
- GET /reports/{report_id}/tables/{table_id} - Get specific table details
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Optional
import logging

from ..models import ChartsResponse, TablesResponse, ChartItem, TableItem
from ..services.asset_service import extract_charts, extract_tables, get_cache_stats
from ..services.report_service import get_report_by_id
from src.api.utils.table_utils import disambiguate_table_names, extract_table_preview

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/{report_id}/charts", response_model=ChartsResponse)
async def get_report_charts(
    report_id: str,
    page: Optional[int] = Query(None, description="Filter by page number (1-indexed)"),
    chart_type: Optional[str] = Query(None, description="Filter by chart type (bar, line, pie, area)"),
    limit: int = Query(50, ge=1, le=100, description="Maximum number of charts to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination")
):
    """
    Get all charts/figures from a report.
    
    Returns a list of charts with:
    - Title (e.g., "Figure 2.1: Trend of GDP")
    - Type (bar, line, pie, area, unknown)
    - Section reference
    - Page number (1-indexed)
    - AI-generated analysis/description
    
    Use the page number with the PDF viewer to navigate to the chart.
    
    **Query Parameters:**
    - `page`: Filter charts on a specific page (1-indexed)
    - `chart_type`: Filter by chart type (bar, line, pie, area)
    - `limit`: Maximum results (default 50)
    - `offset`: Pagination offset
    
    **Example Response:**
    ```json
    {
        "charts": [
            {
                "id": "chart-1",
                "title": "Figure 2.1: Trend of GDP at Constant and Current Prices",
                "type": "bar",
                "section": "Chapter 2: Overview of Union Finances",
                "page": 21,
                "analysis": "The image shows a bar chart depicting..."
            }
        ],
        "total": 29,
        "report_id": "2025_16_CAG_Report..."
    }
    ```
    """
    # Verify report exists
    report = get_report_by_id(report_id)
    if not report:
        raise HTTPException(
            status_code=404, 
            detail=f"Report '{report_id}' not found"
        )
    
    try:
        # Extract charts
        charts = extract_charts(report_id)
        
        # Apply filters
        if page is not None:
            charts = [c for c in charts if c.page == page]
        
        if chart_type:
            charts = [c for c in charts if c.type.value == chart_type.lower()]
        
        # Get total before pagination
        total = len(charts)
        
        # Apply pagination
        charts = charts[offset:offset + limit]
        
        return ChartsResponse(
            charts=charts,
            total=total,
            report_id=report_id
        )
        
    except Exception as e:
        logger.error(f"Error extracting charts from {report_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error extracting charts: {str(e)}"
        )


@router.get("/{report_id}/tables", response_model=TablesResponse)
async def get_report_tables(
    report_id: str,
    page: Optional[int] = Query(None, description="Filter by page number (1-indexed)"),
    min_rows: Optional[int] = Query(None, ge=1, description="Minimum number of rows"),
    min_columns: Optional[int] = Query(None, ge=1, description="Minimum number of columns"),
    limit: int = Query(50, ge=1, le=100, description="Maximum number of tables to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination")
):
    """
    Get all tables from a report.
    
    Returns a list of tables with:
    - Title (e.g., "Table 2.1: Budget vs Actuals")
    - Section reference  
    - Page number (1-indexed)
    - Dimensions (rows × columns)
    - Column headers (if extractable)
    - Brief analysis
    
    Use the page number with the PDF viewer to navigate to the table.
    
    **Query Parameters:**
    - `page`: Filter tables on a specific page (1-indexed)
    - `min_rows`: Filter by minimum row count
    - `min_columns`: Filter by minimum column count
    - `limit`: Maximum results (default 50)
    - `offset`: Pagination offset
    
    **Example Response:**
    ```json
    {
        "tables": [
            {
                "id": "table-1",
                "title": "Table 2.1: Budget vs Actuals FY 2023-24",
                "section": "Chapter 2: Overview of Union Finances",
                "page": 22,
                "rows": 17,
                "columns": 12,
                "analysis": "Table containing financial data...",
                "headers": ["SI. No.", "Particulars", "BE", "RE", "Actuals"]
            }
        ],
        "total": 107,
        "report_id": "2025_16_CAG_Report..."
    }
    ```
    """
    # Verify report exists
    report = get_report_by_id(report_id)
    if not report:
        raise HTTPException(
            status_code=404,
            detail=f"Report '{report_id}' not found"
        )
    
    try:
        # Extract tables
        tables = extract_tables(report_id)

        # Convert Pydantic models to dicts for processing
        tables_dicts = [t.model_dump() if hasattr(t, 'model_dump') else t for t in tables]

        # Add preview data to each table
        for table in tables_dicts:
            structured_data = table.get("structured_data")
            table["preview"] = extract_table_preview(structured_data)

        # Disambiguate duplicate names
        tables_dicts = disambiguate_table_names(tables_dicts)

        # Update title with display_caption if it exists
        for table in tables_dicts:
            if "display_caption" in table:
                table["title"] = table["display_caption"]

        # Apply filters
        if page is not None:
            tables_dicts = [t for t in tables_dicts if t.get("page") == page]

        if min_rows is not None:
            tables_dicts = [t for t in tables_dicts if t.get("rows", 0) >= min_rows]

        if min_columns is not None:
            tables_dicts = [t for t in tables_dicts if t.get("columns", 0) >= min_columns]

        # Get total before pagination
        total = len(tables_dicts)

        # Apply pagination
        tables_dicts = tables_dicts[offset:offset + limit]

        return TablesResponse(
            tables=tables_dicts,
            total=total,
            report_id=report_id
        )
        
    except Exception as e:
        logger.error(f"Error extracting tables from {report_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error extracting tables: {str(e)}"
        )


@router.get("/{report_id}/charts/{chart_id}", response_model=ChartItem)
async def get_chart_detail(report_id: str, chart_id: str):
    """
    Get details for a specific chart.
    
    Returns full chart information including analysis.
    The `chart_id` is in the format "chart-N" where N is the sequential number.
    """
    report = get_report_by_id(report_id)
    if not report:
        raise HTTPException(status_code=404, detail=f"Report '{report_id}' not found")
    
    charts = extract_charts(report_id)
    
    for chart in charts:
        if chart.id == chart_id:
            return chart
    
    raise HTTPException(status_code=404, detail=f"Chart '{chart_id}' not found in report")


@router.get("/{report_id}/tables/{table_id}", response_model=TableItem)
async def get_table_detail(report_id: str, table_id: str):
    """
    Get details for a specific table.
    
    Returns full table information including headers and analysis.
    The `table_id` is in the format "table-N" where N is the sequential number.
    """
    report = get_report_by_id(report_id)
    if not report:
        raise HTTPException(status_code=404, detail=f"Report '{report_id}' not found")
    
    tables = extract_tables(report_id)
    
    for table in tables:
        if table.id == table_id:
            return table
    
    raise HTTPException(status_code=404, detail=f"Table '{table_id}' not found in report")


@router.get("/{report_id}/assets/summary")
async def get_assets_summary(report_id: str):
    """
    Get a summary of all assets (charts and tables) in a report.
    
    Useful for showing counts in the UI tabs before loading full data.
    """
    report = get_report_by_id(report_id)
    if not report:
        raise HTTPException(status_code=404, detail=f"Report '{report_id}' not found")
    
    charts = extract_charts(report_id)
    tables = extract_tables(report_id)
    
    # Group by section
    chart_sections = {}
    for c in charts:
        section = c.section.split(" > ")[0] if " > " in c.section else c.section
        chart_sections[section] = chart_sections.get(section, 0) + 1
    
    table_sections = {}
    for t in tables:
        section = t.section.split(" > ")[0] if " > " in t.section else t.section
        table_sections[section] = table_sections.get(section, 0) + 1
    
    # Chart type distribution
    chart_types = {}
    for c in charts:
        chart_types[c.type.value] = chart_types.get(c.type.value, 0) + 1
    
    return {
        "report_id": report_id,
        "total_charts": len(charts),
        "total_tables": len(tables),
        "charts_by_section": chart_sections,
        "tables_by_section": table_sections,
        "chart_types": chart_types,
        "page_range": {
            "charts": {
                "min": min(c.page for c in charts) if charts else None,
                "max": max(c.page for c in charts) if charts else None
            },
            "tables": {
                "min": min(t.page for t in tables) if tables else None,
                "max": max(t.page for t in tables) if tables else None
            }
        }
    }
