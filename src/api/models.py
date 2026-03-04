"""
Request and response models for the API.

Includes models for:
- Chat/RAG endpoints
- Report listing/details
- Charts and Tables extraction (NEW)

v3.2: Fixed ResponseStyle enum to match frontend exactly
"""

from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from enum import Enum


class ResponseStyle(str, Enum):
    """
    Response style options - MUST match frontend exactly.

    Frontend sends: 'executive' | 'concise' | 'detailed' | 'technical' | 'comparative' | 'adaptive'

    v3.2 FIX: Changed CONVERSATIONAL->DETAILED, ANALYTICAL->TECHNICAL, REPORT->COMPARATIVE
    """

    CONCISE = "concise"
    DETAILED = "detailed"  # v3.2: was CONVERSATIONAL
    EXECUTIVE = "executive"
    TECHNICAL = "technical"  # v3.2: was ANALYTICAL
    COMPARATIVE = "comparative"  # v3.2: was REPORT
    ADAPTIVE = "adaptive"


class ChartType(str, Enum):
    """Types of charts that can be detected."""

    BAR = "bar"
    LINE = "line"
    PIE = "pie"
    AREA = "area"
    TABLE_CHART = "table_chart"  # For tabular visualizations
    UNKNOWN = "unknown"


# ============================================================================
# REQUEST MODELS
# ============================================================================


class ChatRequest(BaseModel):
    """Request body for chat endpoints."""

    query: str = Field(
        ..., min_length=1, max_length=2000, description="The question to ask"
    )
    style: ResponseStyle = Field(
        default=ResponseStyle.ADAPTIVE, description="Response style"
    )
    report_ids: Optional[List[str]] = Field(
        default=None, description="Filter to specific reports"
    )
    top_k: int = Field(
        default=10, ge=1, le=50, description="Number of chunks to retrieve"
    )


# ============================================================================
# RESPONSE MODELS - Citations & Chat
# ============================================================================


class Citation(BaseModel):
    """A citation linking to a source document."""

    citation_key: str  # e.g., "Section 3.2.1, p.36"
    report_id: str  # e.g., "2023_07_NHAI_Toll"
    report_title: str  # e.g., "NHAI Toll Operations..."
    filename: str  # e.g., "2023_07_NHAI_Toll.pdf"
    section: str  # e.g., "Section 3.2.1"
    page_logical: str  # Page number as shown in PDF (e.g., "36")
    page_physical: int  # Actual PDF page index (0-based for react-pdf)
    score: Optional[float] = None
    finding_type: Optional[str] = None
    severity: Optional[str] = None
    amount_crore: Optional[float] = None


class ChatResponse(BaseModel):
    """Response for synchronous chat endpoint."""

    answer: str
    citations: List[Citation]
    sources_used: int
    model_used: str


# ============================================================================
# RESPONSE MODELS - Reports
# ============================================================================


class ReportSummary(BaseModel):
    """Brief report info for listing."""

    id: str
    title: str
    report_no: str
    ministry: str
    sector: str
    year: int
    findings_count: int
    monetary_impact: Optional[str] = None
    status: str
    filename: str
    report_type: Optional[str] = None


class ReportDetail(BaseModel):
    """Full report info for detail view."""

    id: str
    title: str
    report_no: str
    ministry: str
    sector: str
    year: int
    pages: int
    filename: str
    status: str
    executive_summary: str
    key_findings: List[str]
    recommendations: List[str]
    monetary_impact: Optional[str] = None
    findings_count: int
    report_type: Optional[str] = None


class ReportsListResponse(BaseModel):
    """Response for GET /reports."""

    reports: List[ReportSummary]
    total: int


# ============================================================================
# RESPONSE MODELS - Charts & Tables (NEW)
# ============================================================================


class ChartItem(BaseModel):
    """
    Represents a chart/figure extracted from a report.

    Used by frontend Charts tab to display chart cards with navigation.
    """

    id: str  # Unique identifier, e.g., "chart-1"
    title: str  # Chart title, e.g., "Figure 2.1: Trend of GDP"
    type: ChartType  # Chart type: bar, line, pie, area
    section: str  # Section reference, e.g., "Chapter 2: Overview"
    page: int  # Physical page number (1-indexed for display)
    analysis: str  # AI-generated analysis/description of the chart

    # Optional fields for future enhancements
    thumbnail_url: Optional[str] = None  # URL to thumbnail image
    bbox: Optional[List[float]] = None  # Bounding box [x0, y0, x1, y1]
    source_chunk_id: Optional[str] = None  # Reference to source chunk

    # P2-2: Structured chart data fields
    has_structured_data: bool = False  # True if chart data extracted
    extracted_series_count: Optional[int] = None  # Number of data series extracted
    time_periods: Optional[List[str]] = None  # Years/fiscal years covered
    entities: Optional[List[str]] = None  # Ministries, states, schemes mentioned
    monetary_unit: Optional[str] = None  # Currency unit if financial chart
    extraction_confidence: Optional[float] = None  # Confidence score 0.0-1.0


class TableItem(BaseModel):
    """
    Represents a table extracted from a report.

    Used by frontend Tables tab to display table cards with navigation.
    """

    id: str  # Unique identifier, e.g., "table-1"
    title: str  # Table title/caption
    section: str  # Section reference
    page: int  # Physical page number (1-indexed for display)
    rows: int  # Number of data rows
    columns: int  # Number of columns
    analysis: str  # AI-generated analysis of the table

    # Optional fields
    headers: Optional[List[str]] = None  # Column headers if extractable
    data_preview: Optional[List[List[str]]] = None  # First few rows (future)
    bbox: Optional[List[float]] = None  # Bounding box
    source_chunk_id: Optional[str] = None  # Reference to source chunk
    structured_data: Optional[Dict[str, Any]] = None  # Structured table data for preview
    preview: Optional[Dict[str, Any]] = None  # Mini-preview for card display


class ChartsResponse(BaseModel):
    """Response for GET /reports/{id}/charts."""

    charts: List[ChartItem]
    total: int
    report_id: str


class TablesResponse(BaseModel):
    """Response for GET /reports/{id}/tables."""

    tables: List[TableItem]
    total: int
    report_id: str


# ============================================================================
# RESPONSE MODELS - TimeSeries Reports
# ============================================================================


class SeriesReportSummary(BaseModel):
    """A report within a time series."""

    report_id: str
    report_title: str
    audit_year: str
    report_year: int
    filename: str


class TimeSeriesInfo(BaseModel):
    """Information about a time series."""

    series_id: str
    name: str
    description: str
    reports: List[SeriesReportSummary]
    years_covered: List[str]


class SeriesListResponse(BaseModel):
    """Response for GET /series."""

    series: List[TimeSeriesInfo]
    total: int


class SeriesQueryRequest(BaseModel):
    """Request for querying across a time series."""

    query: str = Field(..., min_length=1, max_length=2000)
    style: ResponseStyle = Field(default=ResponseStyle.ADAPTIVE)
    compare_years: bool = Field(default=True)
    top_k_per_report: int = Field(default=5, ge=1, le=20)


# ============================================================================
# RESPONSE MODELS - Health
# ============================================================================


class HealthResponse(BaseModel):
    """Response for health check."""

    status: str
    rag_service: str
    reports_loaded: int
    version: str = "2.0.0"
