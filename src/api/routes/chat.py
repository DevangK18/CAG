"""
Chat endpoints - both synchronous and streaming.
"""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
import json
import logging

from ..models import ChatRequest, ChatResponse
from ..services.streaming_wrapper import (
    get_rag_service,
    generate_stream,
    generate_sync,
    generate_agentic_stream,
    generate_agentic_sync,  # NEW — see fix in streaming_wrapper.py below
)
from ..rate_limit import limiter, RATE_LIMIT_CHAT

router = APIRouter()
logger = logging.getLogger(__name__)


# Headers shared by all streaming routes
SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",  # Disable nginx buffering
}


@router.post("", response_model=ChatResponse)
@limiter.limit(RATE_LIMIT_CHAT)
async def chat_sync(request: Request, body: ChatRequest):
    """Synchronous chat endpoint. Returns complete response at once."""
    rag = get_rag_service()
    if not rag:
        raise HTTPException(status_code=503, detail="RAG service not initialized")

    try:
        result = generate_sync(
            query=body.query,
            style=body.style.value,
            report_ids=body.report_ids,
            top_k=body.top_k,
        )
        return result
    except Exception as e:
        logger.error(f"Chat error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/stream")
@limiter.limit(RATE_LIMIT_CHAT)
async def chat_stream(request: Request, body: ChatRequest):
    """Server-Sent Events (SSE) streaming endpoint."""
    rag = get_rag_service()
    if not rag:
        raise HTTPException(status_code=503, detail="RAG service not initialized")

    async def event_generator():
        try:
            async for event in generate_stream(
                query=body.query,
                style=body.style.value,
                report_ids=body.report_ids,
                top_k=body.top_k,
            ):
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as e:
            logger.error(f"Stream error: {e}", exc_info=True)
            error_event = {"type": "error", "data": str(e)}
            yield f"data: {json.dumps(error_event)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


# =============================================================================
# Phase 11: Agentic endpoints
# =============================================================================


@router.post("/agentic", response_model=ChatResponse)
@limiter.limit(RATE_LIMIT_CHAT)
async def chat_agentic_sync(request: Request, body: ChatRequest):
    """Agentic (multi-hop) chat endpoint. Synchronous."""
    rag = get_rag_service()
    if not rag:
        raise HTTPException(status_code=503, detail="RAG service not initialized")
    if not rag.agentic_service:
        raise HTTPException(
            status_code=503,
            detail="Agentic service is not enabled. Set agentic.enabled=True in config.",
        )

    try:
        result = generate_agentic_sync(
            query=body.query,
            style=body.style.value,
            report_ids=body.report_ids,
            top_k=body.top_k,
        )
        return result
    except Exception as e:
        logger.error(f"Agentic chat error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/agentic/stream")
@limiter.limit(RATE_LIMIT_CHAT)
async def chat_agentic_stream(request: Request, body: ChatRequest):
    """Agentic streaming chat endpoint."""
    rag = get_rag_service()
    if not rag:
        raise HTTPException(status_code=503, detail="RAG service not initialized")
    if not rag.agentic_service:
        raise HTTPException(
            status_code=503,
            detail="Agentic service is not enabled. Set agentic.enabled=True in config.",
        )

    async def event_generator():
        try:
            async for event in generate_agentic_stream(
                query=body.query,
                style=body.style.value,
                report_ids=body.report_ids,
                top_k=body.top_k,
            ):
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as e:
            logger.error(f"Agentic stream error: {e}", exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'data': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )
