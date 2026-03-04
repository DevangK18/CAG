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
    generate_sync
)
from ..rate_limit import limiter, RATE_LIMIT_CHAT

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("", response_model=ChatResponse)
@limiter.limit(RATE_LIMIT_CHAT)
async def chat_sync(request: Request, body: ChatRequest):
    """
    Synchronous chat endpoint.

    Returns complete response at once.
    Good for testing and simple integrations.

    Rate limited to prevent LLM API abuse.
    Limit: configured via RATE_LIMIT_CHAT env var.

    Request body:
    - query: The question to ask
    - style: Response style (concise, executive, analytical, etc.)
    - report_ids: Optional list of report IDs to filter
    - top_k: Number of chunks to retrieve (default 10)
    """
    rag = get_rag_service()
    if not rag:
        raise HTTPException(status_code=503, detail="RAG service not initialized")

    try:
        result = generate_sync(
            query=body.query,
            style=body.style.value,
            report_ids=body.report_ids,
            top_k=body.top_k
        )
        return result
    except Exception as e:
        logger.error(f"Chat error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/stream")
@limiter.limit(RATE_LIMIT_CHAT)
async def chat_stream(request: Request, body: ChatRequest):
    """
    Server-Sent Events (SSE) streaming endpoint.

    Rate limited to prevent LLM API abuse.
    Limit: configured via RATE_LIMIT_CHAT env var.
    Note: Rate limit is checked BEFORE streaming starts.
    Once request passes, the entire stream is allowed.

    Event sequence:
    1. {"type": "citation_map", "data": {...}}  - Sent FIRST with all citations
    2. {"type": "token", "data": "..."}         - Streamed tokens (many events)
    3. {"type": "done", "data": null}           - Stream complete

    On error:
    {"type": "error", "data": "error message"}

    The citation_map is sent before any tokens so the frontend can:
    - Store citation metadata immediately
    - Look up citations as they appear in streamed text
    - Link citations to PDF pages without parsing file paths from text
    """
    rag = get_rag_service()
    if not rag:
        raise HTTPException(status_code=503, detail="RAG service not initialized")

    async def event_generator():
        try:
            async for event in generate_stream(
                query=body.query,
                style=body.style.value,
                report_ids=body.report_ids,
                top_k=body.top_k
            ):
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as e:
            logger.error(f"Stream error: {e}", exc_info=True)
            error_event = {"type": "error", "data": str(e)}
            yield f"data: {json.dumps(error_event)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"  # Disable nginx buffering
        }
    )
