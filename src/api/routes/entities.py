"""
Entity graph HTTP endpoints (Phase 12).
"""

from fastapi import APIRouter, HTTPException, Request, Query, Response
from typing import Optional

from src.entity_graph.entity_service import get_entity_service
from ..rate_limit import limiter, RATE_LIMIT_CHAT  # reuse existing

router = APIRouter()


def _require_service():
    service = get_entity_service()
    if not service:
        raise HTTPException(
            status_code=503,
            detail="Entity graph not enabled. Set ENTITY_GRAPH_DSN and run canonicalize+index.",
        )
    return service


@router.get("/search")
@limiter.limit(RATE_LIMIT_CHAT)
async def search_entities(
    request: Request,
    response: Response,
    q: str = Query(..., min_length=2, max_length=200),
    entity_type: Optional[str] = None,
    primary_tier: Optional[str] = None,
    limit: int = Query(10, le=50),
):
    """Search entities by name or alias."""
    service = _require_service()
    return {
        "results": service.search_entities(q, entity_type, primary_tier, limit),
    }


@router.get("/{entity_id}")
@limiter.limit(RATE_LIMIT_CHAT)
async def get_entity(request: Request, response: Response, entity_id: int):
    service = _require_service()
    ent = service.get_entity(entity_id)
    if not ent:
        raise HTTPException(404, "Entity not found")
    return ent


@router.get("/{entity_id}/mentions")
@limiter.limit(RATE_LIMIT_CHAT)
async def get_mentions(
    request: Request,
    response: Response,
    entity_id: int,
    finding_type: Optional[str] = None,
    audit_year: Optional[str] = None,
    government_body_type: Optional[str] = None,
    limit: int = Query(100, le=500),
):
    service = _require_service()
    return {
        "mentions": service.get_mentions(
            entity_id, finding_type, audit_year, government_body_type, limit
        )
    }


@router.get("/{entity_id}/reports")
@limiter.limit(RATE_LIMIT_CHAT)
async def get_reports_for_entity(request: Request, response: Response, entity_id: int):
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"GET /entities/{entity_id}/reports called")
    service = _require_service()
    report_ids = service.get_reports_for_entity(entity_id)
    logger.info(f"GET /entities/{entity_id}/reports returning {len(report_ids)} report_ids")
    return {"report_ids": report_ids}


@router.get("/{entity_id}/related")
@limiter.limit(RATE_LIMIT_CHAT)
async def get_related(request: Request, response: Response, entity_id: int, limit: int = Query(20, le=100)):
    service = _require_service()
    return {"related": service.get_related_entities(entity_id, limit)}


@router.get("/{entity_id}/findings")
@limiter.limit(RATE_LIMIT_CHAT)
async def get_findings(
    request: Request,
    response: Response,
    entity_id: int,
    min_amount_crore: Optional[float] = None,
    severity: Optional[str] = None,
    limit: int = Query(50, le=200),
):
    service = _require_service()
    return {
        "findings": service.get_findings_for_entity(
            entity_id, min_amount_crore, severity, limit
        )
    }
