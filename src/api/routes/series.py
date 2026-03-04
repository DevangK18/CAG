"""
Time Series API endpoints.

Simplified version that reuses existing streaming_wrapper functions.
"""

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from typing import Optional, List
from pydantic import BaseModel, Field
import json
import logging

from ..models import ChatResponse, Citation, ResponseStyle
from ..rate_limit import limiter, RATE_LIMIT_CHAT

router = APIRouter()
logger = logging.getLogger(__name__)


# =============================================================================
# MODELS
# =============================================================================


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


# =============================================================================
# REGISTRY HELPERS
# =============================================================================


def _get_registry():
    """Get the report registry with fallback to report_service."""
    try:
        import sys
        from pathlib import Path

        # Path calculation:
        # This file: services/api/routes/series.py
        # rag_pipeline: services/rag_pipeline/
        THIS_FILE = Path(__file__).resolve()
        ROUTES_DIR = THIS_FILE.parent  # services/api/routes/
        API_DIR = ROUTES_DIR.parent  # services/api/
        SERVICES_DIR = API_DIR.parent  # services/
        RAG_PIPELINE_DIR = SERVICES_DIR / "rag_pipeline"  # services/rag_pipeline/

        if RAG_PIPELINE_DIR.exists():
            if str(RAG_PIPELINE_DIR) not in sys.path:
                sys.path.insert(0, str(RAG_PIPELINE_DIR))

            from report_registry import get_registry

            registry = get_registry()

            # Auto-load if not loaded
            if not registry.is_loaded():
                from ..config import settings

                registry.load_from_json_dir(settings.PROCESSED_DIR)

            return registry
        else:
            logger.warning(f"rag_pipeline not found at {RAG_PIPELINE_DIR}")
            return None
    except Exception as e:
        logger.warning(f"Could not get registry: {e}")
        return None


def _get_series_from_reports():
    """
    Build series data from report_service as fallback.
    """
    import re
    from ..services.report_service import get_all_reports

    reports = get_all_reports()

    series_data = {
        "union_govt_accounts": {
            "name": "Union Government Accounts (Financial Audit)",
            "description": "Annual financial audit of Union Government accounts",
            "pattern": r"Union.?Government.?Accounts|Accounts.?of.?the.?Union.?Government",
            "reports": [],
        },
        "frbm_compliance": {
            "name": "FRBM Act Compliance Audit",
            "description": "Fiscal Responsibility and Budget Management Act compliance",
            "pattern": r"Fiscal.?Responsibility|FRBM",
            "reports": [],
        },
        "direct_taxes_audit": {
            "name": "Direct Taxes Compliance Audit",
            "description": "Compliance audit on Direct Taxes",
            "pattern": r"Direct.?[Tt]axes",
            "exclude": r"Performance.?Audit|Co-?operative",
            "reports": [],
        },
    }

    for report in reports:
        title = report.title
        report_id = report.id

        for series_id, config in series_data.items():
            # Check exclude pattern first
            if "exclude" in config and re.search(
                config["exclude"], title, re.IGNORECASE
            ):
                continue

            if re.search(config["pattern"], title, re.IGNORECASE):
                # Extract audit year from title
                year_match = re.search(r"(\d{4})-(\d{2,4})", title)
                if year_match:
                    audit_year = f"{year_match.group(1)}-{year_match.group(2)}"
                else:
                    # Try filename pattern
                    year_match = re.search(r"(\d{4})(\d{2})(?:_|\.pdf|$)", report_id)
                    if year_match:
                        audit_year = f"{year_match.group(1)}-{year_match.group(2)}"
                    else:
                        audit_year = ""

                series_data[series_id]["reports"].append(
                    {
                        "report_id": report_id,
                        "report_title": title,
                        "audit_year": audit_year,
                        "report_year": report.year,
                        "filename": report.filename,
                    }
                )
                break

    # Sort reports by audit year
    for series_id in series_data:
        series_data[series_id]["reports"].sort(key=lambda x: x["audit_year"])

    return series_data


def _get_all_series_data():
    """Get series data from registry or fallback to report_service."""
    registry = _get_registry()

    if registry and registry.is_loaded():
        # Use registry
        series_list = []
        for series in registry.get_all_series():
            reports = registry.get_reports_in_series(series.series_id)
            series_list.append(
                {
                    "series_id": series.series_id,
                    "name": series.name,
                    "description": series.description,
                    "reports": [
                        {
                            "report_id": r.report_id,
                            "report_title": r.report_title,
                            "audit_year": r.audit_year,
                            "report_year": r.report_year,
                            "filename": r.filename,
                        }
                        for r in reports
                    ],
                }
            )
        return series_list
    else:
        # Fallback: build from report_service
        logger.info("Using fallback series detection from report_service")
        series_data = _get_series_from_reports()
        return [
            {
                "series_id": sid,
                "name": data["name"],
                "description": data["description"],
                "reports": data["reports"],
            }
            for sid, data in series_data.items()
            if data["reports"]  # Only include series with reports
        ]


def _get_series_by_id(series_id: str):
    """Get a specific series by ID."""
    all_series = _get_all_series_data()
    for series in all_series:
        if series["series_id"] == series_id:
            return series
    return None


# =============================================================================
# ENDPOINTS
# =============================================================================


@router.get("", response_model=SeriesListResponse)
async def list_series():
    """
    List all available time series.
    """
    try:
        series_data = _get_all_series_data()

        series_list = [
            TimeSeriesInfo(
                series_id=s["series_id"],
                name=s["name"],
                description=s["description"],
                reports=[SeriesReportSummary(**r) for r in s["reports"]],
                years_covered=[
                    r["audit_year"] for r in s["reports"] if r["audit_year"]
                ],
            )
            for s in series_data
        ]

        return SeriesListResponse(series=series_list, total=len(series_list))

    except Exception as e:
        logger.error(f"Error listing series: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{series_id}", response_model=TimeSeriesInfo)
async def get_series(series_id: str):
    """Get details for a specific time series."""
    try:
        series = _get_series_by_id(series_id)

        if not series:
            all_series = _get_all_series_data()
            available = [s["series_id"] for s in all_series]
            raise HTTPException(
                status_code=404,
                detail=f"Series '{series_id}' not found. Available: {available}",
            )

        return TimeSeriesInfo(
            series_id=series["series_id"],
            name=series["name"],
            description=series["description"],
            reports=[SeriesReportSummary(**r) for r in series["reports"]],
            years_covered=[
                r["audit_year"] for r in series["reports"] if r["audit_year"]
            ],
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting series {series_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{series_id}/query", response_model=ChatResponse)
@limiter.limit(RATE_LIMIT_CHAT)
async def query_series(request: Request, series_id: str, body: SeriesQueryRequest):
    """
    Query across all reports in a time series (synchronous).

    Rate limited to prevent LLM API abuse.
    """
    try:
        series = _get_series_by_id(series_id)

        if not series:
            raise HTTPException(
                status_code=404, detail=f"Series '{series_id}' not found"
            )

        # Get report IDs from series
        report_ids = [r["report_id"] for r in series["reports"]]

        if not report_ids:
            raise HTTPException(
                status_code=404, detail=f"No reports found in series '{series_id}'"
            )

        # DEBUG: Log the report_ids being used
        logger.info(f"Series query for {series_id}")
        logger.info(f"Report IDs: {report_ids}")

        # Use existing generate_sync from streaming_wrapper
        from ..services.streaming_wrapper import generate_sync

        # Calculate total top_k based on reports
        total_top_k = body.top_k_per_report * len(report_ids)

        result = generate_sync(
            query=body.query,
            style=body.style.value,
            report_ids=report_ids,
            top_k=total_top_k,
        )

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error querying series {series_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{series_id}/query/stream")
@limiter.limit(RATE_LIMIT_CHAT)
async def query_series_stream(request: Request, series_id: str, body: SeriesQueryRequest):
    """
    Query across all reports in a time series (streaming SSE).

    Rate limited to prevent LLM API abuse.
    """
    try:
        series = _get_series_by_id(series_id)

        if not series:
            raise HTTPException(
                status_code=404, detail=f"Series '{series_id}' not found"
            )

        # Get report IDs from series
        report_ids = [r["report_id"] for r in series["reports"]]

        if not report_ids:
            raise HTTPException(
                status_code=404, detail=f"No reports found in series '{series_id}'"
            )

        # DEBUG: Log the report_ids being used
        logger.info(f"=== SERIES STREAM QUERY ===")
        logger.info(f"Series: {series_id}")
        logger.info(f"Query: {body.query}")
        logger.info(f"Report IDs ({len(report_ids)}): {report_ids}")

        # Import generate_stream from streaming_wrapper
        from ..services.streaming_wrapper import generate_stream

        # Calculate total top_k
        total_top_k = body.top_k_per_report * len(report_ids)
        logger.info(f"Total top_k: {total_top_k}")

        async def event_generator():
            try:
                # Add series metadata to first event
                series_meta = {
                    "series_id": series_id,
                    "series_name": series["name"],
                    "years": [
                        r["audit_year"] for r in series["reports"] if r["audit_year"]
                    ],
                    "report_count": len(report_ids),
                    "report_ids": report_ids,  # Include for debugging
                }
                yield f"data: {json.dumps({'type': 'series_info', 'data': series_meta})}\n\n"

                # Use existing generate_stream
                async for event in generate_stream(
                    query=body.query,
                    style=body.style.value,
                    report_ids=report_ids,
                    top_k=total_top_k,
                ):
                    # Log if we got no results
                    if (
                        event.get("type") == "token"
                        and "couldn't find" in event.get("data", "").lower()
                    ):
                        logger.warning(
                            f"No results found for series query with report_ids: {report_ids}"
                        )

                    yield f"data: {json.dumps(event)}\n\n"

            except Exception as e:
                logger.error(f"Stream error: {e}", exc_info=True)
                yield f"data: {json.dumps({'type': 'error', 'data': str(e)})}\n\n"

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Error starting stream for series {series_id}: {e}", exc_info=True
        )
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{series_id}/reports")
async def list_series_reports(series_id: str):
    """List all reports in a time series."""
    try:
        series = _get_series_by_id(series_id)

        if not series:
            raise HTTPException(
                status_code=404, detail=f"Series '{series_id}' not found"
            )

        return {
            "series_id": series_id,
            "series_name": series["name"],
            "reports": series["reports"],
            "total": len(series["reports"]),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Error listing reports for series {series_id}: {e}", exc_info=True
        )
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{series_id}/debug")
async def debug_series(series_id: str):
    """
    Debug endpoint to check what report_ids are in the series
    and whether they exist in Qdrant.
    """
    try:
        series = _get_series_by_id(series_id)

        if not series:
            raise HTTPException(
                status_code=404, detail=f"Series '{series_id}' not found"
            )

        report_ids = [r["report_id"] for r in series["reports"]]

        # Try to check Qdrant
        qdrant_check = {}
        try:
            from ..services.streaming_wrapper import get_rag_service

            rag = get_rag_service()
            if rag:
                # Try a test query with each report_id
                for rid in report_ids:
                    result = rag.retrieval.retrieve(
                        "test query", top_k=1, filters={"report_id": rid}
                    )
                    qdrant_check[rid] = {
                        "found": result.total_candidates > 0,
                        "candidates": result.total_candidates,
                    }
        except Exception as e:
            qdrant_check = {"error": str(e)}

        return {
            "series_id": series_id,
            "series_name": series["name"],
            "report_ids": report_ids,
            "report_count": len(report_ids),
            "qdrant_check": qdrant_check,
            "reports": series["reports"],
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error debugging series {series_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
