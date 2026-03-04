"""
Health check endpoint.
"""

from fastapi import APIRouter
from pydantic import BaseModel
from ..models import HealthResponse
from ..services.streaming_wrapper import get_rag_service
from ..services.report_service import get_reports_count

router = APIRouter()


class BasicHealthResponse(BaseModel):
    """Simple health check response without external dependencies."""
    status: str


@router.get("/health", response_model=BasicHealthResponse)
async def health_check():
    """
    Basic health check for Docker/k8s healthchecks.

    Returns 200 OK without checking external services (Qdrant, etc.)
    to prevent restart loops during cold starts.

    For detailed status including RAG service and reports, use /health/detailed
    """
    return BasicHealthResponse(status="healthy")


@router.get("/health/detailed", response_model=HealthResponse)
async def detailed_health_check():
    """
    Detailed health check with service status.

    Returns status of:
    - API server
    - RAG service initialization
    - Number of reports loaded

    Note: May be slower during cold starts when Qdrant is initializing.
    """
    rag = get_rag_service()
    return HealthResponse(
        status="healthy",
        rag_service="initialized" if rag else "not_initialized",
        reports_loaded=get_reports_count()
    )
