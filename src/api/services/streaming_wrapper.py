"""
Streaming wrapper for the RAG service.

IMPORTANT: This is a THIN adapter layer.
- NO prompt construction here
- NO question type detection here
- NO style-specific logic here

All business logic lives in rag_service.py.
This wrapper only:
1. Calls RAG service methods
2. Converts responses to SSE-compatible events
3. Handles async streaming from LLM providers
"""

import asyncio
import logging
from typing import Dict, List, Optional, Any, AsyncGenerator
from concurrent.futures import ThreadPoolExecutor

import sys
from pathlib import Path

# =============================================================================
# PATH SETUP - CRITICAL FOR RAG SERVICE IMPORT
# =============================================================================
# Directory structure:
#   CAG/
#   └── services/
#       ├── api/
#       │   └── services/
#       │       └── streaming_wrapper.py  <- We are here
#       └── rag_pipeline/                  <- We need to reach here (inside services!)
#           └── rag_service.py

# Calculate path to rag_pipeline (which is inside services/, NOT at project root)
THIS_FILE = Path(__file__).resolve()
SERVICES_API_SERVICES_DIR = THIS_FILE.parent  # services/api/services/
SERVICES_API_DIR = SERVICES_API_SERVICES_DIR.parent  # services/api/
SERVICES_DIR = SERVICES_API_DIR.parent  # services/
RAG_PIPELINE_DIR = SERVICES_DIR / "rag_pipeline"  # services/rag_pipeline/

# Debug logging
logging.info(f"streaming_wrapper.py location: {THIS_FILE}")
logging.info(f"Looking for rag_pipeline at: {RAG_PIPELINE_DIR}")

# Add rag_pipeline to Python path
if RAG_PIPELINE_DIR.exists():
    if str(RAG_PIPELINE_DIR) not in sys.path:
        sys.path.insert(0, str(RAG_PIPELINE_DIR))
    logging.info(f"SUCCESS: Added to path: {RAG_PIPELINE_DIR}")
else:
    logging.error(f"rag_pipeline directory not found at: {RAG_PIPELINE_DIR}")
    # Try alternate location at project root as fallback
    PROJECT_ROOT = SERVICES_DIR.parent
    ALT_RAG_PIPELINE_DIR = PROJECT_ROOT / "rag_pipeline"
    if ALT_RAG_PIPELINE_DIR.exists():
        if str(ALT_RAG_PIPELINE_DIR) not in sys.path:
            sys.path.insert(0, str(ALT_RAG_PIPELINE_DIR))
        logging.info(f"SUCCESS: Found at alternate location: {ALT_RAG_PIPELINE_DIR}")
        RAG_PIPELINE_DIR = ALT_RAG_PIPELINE_DIR

# =============================================================================
# RAG SERVICE IMPORTS
# =============================================================================
try:
    from rag_service import RAGService, ResponseStyle as RAGResponseStyle
    from models import RAGResponse, Citation as RAGCitation, RetrievalResult
    from report_registry import SeriesContext

    logging.info("RAG service modules imported successfully")
except ImportError as e:
    logging.error(f"Could not import RAG service modules: {e}")
    logging.error(f"Attempted path: {RAG_PIPELINE_DIR}")
    logging.error(f"sys.path: {sys.path[:5]}...")
    RAGService = None
    RAGResponseStyle = None
    RAGResponse = None
    RAGCitation = None
    RetrievalResult = None
    SeriesContext = None

from ..models import Citation as APICitation, ChatResponse
from .report_service import get_report_by_id

logger = logging.getLogger(__name__)

# Global RAG service instance
_rag_service = None

# Thread pool for running sync code
_executor = ThreadPoolExecutor(max_workers=4)


def initialize_rag_service():
    """Initialize the RAG service singleton."""
    global _rag_service
    if _rag_service is None and RAGService is not None:
        try:
            _rag_service = RAGService()
            logger.info("RAG service initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize RAG service: {e}", exc_info=True)
            _rag_service = None
    elif RAGService is None:
        logger.error("RAGService class not available - import failed")


def get_rag_service():
    """Get the RAG service instance."""
    return _rag_service


def _convert_citations(rag_citations: List) -> List[APICitation]:
    """
    Convert RAG service citations to API citations with full metadata.
    This is crucial for the frontend to link citations to PDF pages.
    """
    if not rag_citations:
        return []

    api_citations = []

    for c in rag_citations:
        # Get report details for filename
        report = get_report_by_id(c.report_id)
        filename = report.filename if report else f"{c.report_id}.pdf"
        report_title = report.title if report else c.report_id

        # Build citation key that matches what appears in the text
        # Format: "Section X.Y, p.ZZ" - must match LLM output format
        section = c.section or "Unknown Section"
        page = c.page
        citation_key = f"{section}, p.{page}"

        api_citations.append(
            APICitation(
                citation_key=citation_key,
                report_id=c.report_id,
                report_title=report_title,
                filename=filename,
                section=section,
                page_logical=str(page),
                page_physical=page,  # 1-based page number for react-pdf <Page pageNumber={}>
                score=c.score,
                finding_type=c.finding_type,
                severity=c.severity,
                amount_crore=c.amount_crore,
                # Item 7: Enhanced semantic fields
                entities_mentioned=c.entities_mentioned if c.entities_mentioned else None,
                section_type=c.section_type,
                is_recommendation=c.is_recommendation,
            )
        )

    return api_citations


def _build_citation_map(citations: List[APICitation]) -> Dict[str, Dict[str, Any]]:
    """
    Build a citation lookup map for the frontend.
    Key is the citation text that appears in the answer.
    """
    citation_map = {}

    for c in citations:
        # Primary key - exact format we instruct the LLM to use
        key = f"{c.section}, p.{c.page_logical}"

        value = {
            "report_id": c.report_id,
            "report_title": c.report_title,
            "filename": c.filename,
            "section": c.section,
            "page_logical": c.page_logical,
            "page_physical": c.page_physical,
            "finding_type": c.finding_type,
            "severity": c.severity,
            "amount_crore": c.amount_crore,
        }

        citation_map[key] = value

    return citation_map


async def _maybe_verify_groundedness(
    rag,
    answer: str,
    retrieval_result,
    loop,
) -> Optional[Dict[str, Any]]:
    """
    Run groundedness verification if enabled. Returns dict for emitting,
    or None if disabled/failed.

    Phase 13.
    """
    groundedness_service = getattr(rag, "groundedness_service", None)
    if groundedness_service is None:
        return None
    if not answer.strip():
        return None

    try:
        report = await loop.run_in_executor(
            _executor,
            lambda: groundedness_service.verify(answer, retrieval_result),
        )
        return report.to_dict()
    except Exception as e:
        logger.warning(f"Groundedness check failed: {e}", exc_info=True)
        return None


def generate_sync(
    query: str,
    style: str = "adaptive",
    report_ids: Optional[List[str]] = None,
    top_k: int = 10,
) -> ChatResponse:
    """
    Synchronous generation - returns complete response.
    Delegates entirely to RAGService.ask()
    """
    rag = get_rag_service()
    if not rag:
        raise RuntimeError("RAG service not initialized")

    # Map style string to enum
    style_enum = RAGResponseStyle(style)

    # Build filters
    # Note: Qdrant handles lists as MatchAny, single values as MatchValue
    filters = {}
    if report_ids:
        if len(report_ids) == 1:
            filters["report_id"] = report_ids[0]
        else:
            # Pass list directly - qdrant_service._build_filter handles it as MatchAny
            filters["report_id"] = report_ids

    # Delegate to RAG service - ALL logic is there
    response = rag.ask(
        question=query,
        filters=filters if filters else None,
        top_k=top_k,
        style=style_enum,
    )

    # Convert citations for API response
    citations = _convert_citations(response.citations)

    return ChatResponse(
        answer=response.answer,
        citations=citations,
        sources_used=response.sources_used,
        model_used=response.model_used,
        groundedness=response.groundedness,
        sota_features=response.sota_features,  # Item 1: SOTA RAG features
    )


async def generate_stream(
    query: str,
    style: str = "adaptive",
    report_ids: Optional[List[str]] = None,
    top_k: int = 10,
    client_session_id: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    Async streaming generation using SSE.

    Yields events:
    1. citation_map - All citations upfront (SENT FIRST)
    2. token - Individual tokens
    3. done - Stream complete
    """
    rag = get_rag_service()
    if not rag:
        yield {"type": "error", "data": "RAG service not initialized"}
        return

    # Initialize logging context
    log_ctx = None
    query_logger = getattr(rag, "query_logger", None)

    try:
        loop = asyncio.get_event_loop()
        style_enum = RAGResponseStyle(style)

        # Determine interaction mode for logging
        interaction_mode = "directory" if report_ids else "home"

        # Start query logging
        if query_logger:
            log_ctx = query_logger.start_query(
                query_text=query,
                interaction_mode=interaction_mode,
                report_ids_filter=report_ids,
                explicit_filters={"report_id": report_ids} if report_ids else None,
                style=style,
                client_session_id=client_session_id,
                user_agent=user_agent,
            )
            log_ctx = log_ctx.__enter__()
            log_ctx.start_phase("enhancement")

        # Build filters
        # Note: Qdrant handles lists as MatchAny, single values as MatchValue
        filters = {}
        if report_ids:
            if len(report_ids) == 1:
                filters["report_id"] = report_ids[0]
            else:
                # Pass list directly - qdrant_service._build_filter handles it as MatchAny
                filters["report_id"] = report_ids

        # Tier context lookup for query enhancement
        tier_context_for_enhancer = None
        if filters and "report_id" in filters:
            try:
                from report_registry import get_registry

                registry = get_registry()
                report_id = filters["report_id"]
                # Handle both single report_id and list of report_ids
                if isinstance(report_id, list):
                    report_id = report_id[0]  # Use first report for context
                report_info = registry.get_report(report_id)
                if report_info:
                    govt_type = (
                        getattr(report_info, "government_body_type", None) or "union"
                    )
                    if govt_type != "union":
                        tier_label = "State" if govt_type == "state" else "Local Body"
                        tier_context_for_enhancer = f"{tier_label} audit report"
                        state_name = getattr(report_info, "state_name", None)
                        if state_name:
                            tier_context_for_enhancer += f" from {state_name}"
                        department = getattr(report_info, "department", None)
                        if department and department.lower() not in (
                            "unknown",
                            "n/a",
                            "",
                        ):
                            tier_context_for_enhancer += f", department: {department}"
            except Exception as e:
                logger.warning(f"Failed to lookup tier context: {e}")

        # NEW: Run query enhancement first (in thread pool)
        enhancement = None
        if hasattr(rag, "query_enhancer") and rag.config.query_enhancement.enabled:
            enhancement = await loop.run_in_executor(
                _executor,
                lambda: rag.query_enhancer.enhance(
                    query, style=style, tier_context=tier_context_for_enhancer
                ),
            )

            # Apply recommended style
            if style == "adaptive" and enhancement and enhancement.recommended_style:
                try:
                    style_enum = RAGResponseStyle(enhancement.recommended_style)
                except ValueError:
                    pass

            # Use enhancement's top_k
            if enhancement:
                top_k = enhancement.top_k

        # Log enhancement
        if log_ctx:
            log_ctx.record_query_enhancement(enhancement)
            log_ctx.end_phase("enhancement")
            log_ctx.start_phase("retrieval")

        # Step 1: Run retrieval (sync, in thread pool)
        retrieval_result = await loop.run_in_executor(
            _executor,
            lambda: rag.retrieval.retrieve(
                query,
                top_k=top_k,
                filters=filters if filters else None,
                enhancement=enhancement,  # NEW parameter
            ),
        )

        # Log retrieval
        if log_ctx:
            log_ctx.end_phase("retrieval")
            include_full = (
                rag.config.observability.dev_debug
                if hasattr(rag.config, "observability")
                else False
            )
            log_ctx.record_retrieval(
                retrieval_result,
                reranker_used=retrieval_result.reranker_used,
                include_full_content=include_full,
            )
            log_ctx.record_merged_filters(filters)

        if retrieval_result.total_after_rerank == 0:
            if log_ctx:
                log_ctx.__exit__(None, None, None)
            yield {
                "type": "token",
                "data": "I couldn't find any relevant information in the CAG reports to answer this question.",
            }
            yield {"type": "done", "data": None}
            return

        # NEW: Passage reordering
        if rag.config.query_enhancement.enable_passage_reordering:
            retrieval_result.parents = rag._reorder_for_attention(
                retrieval_result.parents
            )

        # NEW: Context sufficiency check + emit caveat event
        context_sufficient = rag._check_context_sufficiency(retrieval_result)
        if log_ctx:
            log_ctx.record_context_sufficient(context_sufficient)
            log_ctx.start_phase("generation")
        if not context_sufficient:
            yield {"type": "caveat", "data": "low_relevance"}

        # Step 2: Build and send citation map FIRST
        rag_citations = rag.build_citations(retrieval_result)
        api_citations = _convert_citations(rag_citations)
        citation_map = _build_citation_map(api_citations)

        yield {"type": "citation_map", "data": citation_map}

        # Item 2: Emit search metadata event
        yield {
            "type": "metadata",
            "data": {
                "search_type": retrieval_result.search_type,
                "reranker_used": retrieval_result.reranker_used,
                "total_candidates": retrieval_result.total_candidates,
                "total_after_rerank": retrieval_result.total_after_rerank,
            }
        }

        # Item 3: Emit auto-applied filters event
        if retrieval_result.filters_applied:
            yield {"type": "filters", "data": retrieval_result.filters_applied}

        # Step 3: Get prepared prompts from RAG service — pass adaptive context length
        generation_inputs = await loop.run_in_executor(
            _executor,
            lambda: rag.prepare_generation_inputs(
                question=query,
                retrieval_result=retrieval_result,
                style=style_enum,
                question_type=enhancement.question_type if enhancement else None,
                max_context_chars=enhancement.max_context_chars
                if enhancement
                else None,
            ),
        )

        system_prompt = generation_inputs["system_prompt"]
        user_prompt = generation_inputs["user_prompt"]

        # Step 4: Stream from LLM (accumulate for Phase 13 groundedness)
        provider = rag.config.llm.provider.value
        accumulated_answer_parts: List[str] = []

        if provider == "claude":
            stream_iter = _stream_anthropic(rag, user_prompt, system_prompt)
        elif provider == "gemini":
            stream_iter = _stream_gemini(rag, user_prompt, system_prompt)
        else:
            stream_iter = _stream_openai(rag, user_prompt, system_prompt)

        async for token in stream_iter:
            accumulated_answer_parts.append(token)
            yield {"type": "token", "data": token}

        # Log generation completion
        if log_ctx:
            log_ctx.end_phase("generation")

        # Phase 13: Groundedness verification (runs after token stream completes)
        full_answer = "".join(accumulated_answer_parts)

        # Log generation details
        if log_ctx:
            log_ctx.record_generation(
                answer=full_answer,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                raw_response=full_answer,
                provider=provider,
                model=rag._get_model_name(),
            )
            log_ctx.start_phase("groundedness")

        groundedness_dict = await _maybe_verify_groundedness(
            rag,
            full_answer,
            retrieval_result,
            loop,
        )
        if groundedness_dict is not None:
            if log_ctx:
                log_ctx.end_phase("groundedness")
                log_ctx.record_groundedness(groundedness_dict)
            yield {"type": "groundedness", "data": groundedness_dict}
        elif log_ctx:
            log_ctx.end_phase("groundedness")

        # Complete logging
        if log_ctx:
            log_ctx.__exit__(None, None, None)

        yield {"type": "done", "data": None}

    except Exception as e:
        logger.error(f"Stream generation error: {e}", exc_info=True)
        if log_ctx:
            log_ctx.record_error(str(e))
            log_ctx.__exit__(None, None, None)
        yield {"type": "error", "data": str(e)}


def generate_agentic_sync(
    query: str,
    style: str = "adaptive",
    report_ids: Optional[List[str]] = None,
    top_k: int = 10,
    series_context: Optional["SeriesContext"] = None,
) -> ChatResponse:
    """
    Synchronous agentic generation. Delegates to AgenticRAGService.ask().
    Phase 11.

    Args:
        query: The user's question
        style: Response style preference
        report_ids: Optional list of report IDs to scope retrieval
        top_k: Number of chunks to retrieve
        series_context: Optional SeriesContext for temporal-aware decomposition
                       and synthesis (Phase B - Series × Agentic integration)
    """
    rag = get_rag_service()
    if not rag:
        raise RuntimeError("RAG service not initialized")
    if not rag.agentic_service:
        raise RuntimeError("Agentic service not enabled")

    style_enum = RAGResponseStyle(style)

    # Build filters (match generate_sync pattern)
    filters = {}
    if report_ids:
        if len(report_ids) == 1:
            filters["report_id"] = report_ids[0]
        else:
            filters["report_id"] = report_ids

    response = rag.agentic_service.ask(
        question=query,
        filters=filters if filters else None,
        top_k=top_k,
        style=style_enum,
        series_context=series_context,
    )

    citations = _convert_citations(response.citations)

    return ChatResponse(
        answer=response.answer,
        citations=citations,
        sources_used=response.sources_used,
        model_used=response.model_used,
        groundedness=response.groundedness,
        agentic_trace=response.agentic_trace,
        sota_features=response.sota_features,  # Item 1: SOTA RAG features
    )


async def generate_agentic_stream(
    query: str,
    style: str = "adaptive",
    report_ids: Optional[List[str]] = None,
    top_k: int = 10,
    client_session_id: Optional[str] = None,
    user_agent: Optional[str] = None,
    series_context: Optional["SeriesContext"] = None,
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    Agentic streaming. Emits same event types as generate_stream() plus:
    - "planning"       — decomposition result
    - "sub_query"      — each sub-query starting
    - "iteration"      — each retrieval iteration
    - "reformulation"  — when a query is rewritten
    - "synthesizing"   — final answer generation starting

    Phase 11.

    Args:
        query: The user's question
        style: Response style preference
        report_ids: Optional list of report IDs to scope retrieval
        top_k: Number of chunks to retrieve
        client_session_id: Session ID for logging
        user_agent: User agent for logging
        series_context: Optional SeriesContext for temporal-aware decomposition
                       and synthesis (Phase B - Series × Agentic integration)
    """
    rag = get_rag_service()
    if not rag:
        yield {"type": "error", "data": "RAG service not initialized"}
        return
    if not rag.agentic_service:
        yield {"type": "error", "data": "Agentic service not enabled"}
        return

    # Initialize logging context
    log_ctx = None
    query_logger = getattr(rag, "query_logger", None)

    try:
        loop = asyncio.get_event_loop()
        style_enum = RAGResponseStyle(style)

        # Build filters (match generate_stream pattern)
        filters = {}
        if report_ids:
            if len(report_ids) == 1:
                filters["report_id"] = report_ids[0]
            else:
                filters["report_id"] = report_ids
        filters_or_none = filters if filters else None

        # Start query logging
        if query_logger:
            log_ctx = query_logger.start_query(
                query_text=query,
                interaction_mode="home",  # Will be agentic
                report_ids_filter=report_ids,
                explicit_filters=filters_or_none,
                style=style,
                client_session_id=client_session_id,
                user_agent=user_agent,
            )
            log_ctx = log_ctx.__enter__()
            log_ctx.start_phase("enhancement")

        # Step 1: Plan (in thread pool — single LLM call)
        # Pass series_context for temporal-aware decomposition
        plan = await loop.run_in_executor(
            _executor,
            lambda: rag.agentic_service._decompose(query, series_context=series_context),
        )

        # Log enhancement phase
        if log_ctx:
            log_ctx.end_phase("enhancement")
            log_ctx.agentic_complexity = plan["complexity"]

        yield {
            "type": "planning",
            "data": {
                "complexity": plan["complexity"],
                "sub_queries": plan.get("sub_queries") or [],
                "reason": plan.get("reason", ""),
            },
        }

        # Simple path — delegate to regular streaming
        if plan["complexity"] == "simple":
            # Close agentic log context before delegating
            if log_ctx:
                log_ctx.__exit__(None, None, None)
                log_ctx = None
            async for event in generate_stream(
                query, style, report_ids, top_k, client_session_id, user_agent
            ):
                yield event
            return

        # Start retrieval phase for complex queries
        if log_ctx:
            log_ctx.start_phase("retrieval")

        # Build a trace object — agentic_service expects a real AgenticTrace
        from agentic_service import AgenticTrace

        trace = AgenticTrace(
            original_query=query,
            complexity=plan["complexity"],
            decomposition_reason=plan.get("reason", ""),
            sub_queries=plan.get("sub_queries") or [],
        )

        # Step 2: Run loop per sub-query (each runs in thread pool)
        sub_queries = trace.sub_queries[: rag.agentic_service.config.max_sub_queries]
        all_retrievals = []

        for i, sq in enumerate(sub_queries):
            yield {
                "type": "sub_query",
                "data": {"index": i, "query": sq, "total": len(sub_queries)},
            }

            sub_result = await loop.run_in_executor(
                _executor,
                lambda sq=sq: rag.agentic_service._run_subquery_loop(
                    sq, filters_or_none, trace
                ),
            )

            for refo in sub_result.reformulations:
                yield {
                    "type": "reformulation",
                    "data": {"sub_index": i, "new_query": refo},
                }

            yield {
                "type": "iteration",
                "data": {
                    "sub_index": i,
                    "iterations": sub_result.iterations,
                    "sufficient": sub_result.sufficient,
                    "num_chunks": sub_result.final_retrieval.total_after_rerank
                    if sub_result.final_retrieval
                    else 0,
                },
            }

            if sub_result.final_retrieval:
                all_retrievals.append(sub_result.final_retrieval)

        # Step 3: If nothing retrieved, bail
        if not all_retrievals:
            if log_ctx:
                log_ctx.record_agentic_trace(trace)
                log_ctx.__exit__(None, None, None)
            yield {
                "type": "token",
                "data": "I couldn't find sufficient information across the requested aspects. "
                "Try simpler questions or check that the topics are covered in the indexed reports.",
            }
            yield {"type": "done", "data": None}
            return

        # Step 4: Merge retrievals (in thread pool)
        merged = await loop.run_in_executor(
            _executor,
            lambda: rag.agentic_service._merge_retrievals(all_retrievals),
        )

        # Log retrieval results
        if log_ctx:
            log_ctx.end_phase("retrieval")
            include_full = (
                rag.config.observability.dev_debug
                if hasattr(rag.config, "observability")
                else False
            )
            log_ctx.record_retrieval(
                merged,
                reranker_used=merged.reranker_used,
                include_full_content=include_full,
            )
            log_ctx.start_phase("generation")

        # Step 5: Emit citation_map (match existing contract)
        rag_citations = rag.build_citations(merged)
        api_citations = _convert_citations(rag_citations)
        citation_map = _build_citation_map(api_citations)
        yield {"type": "citation_map", "data": citation_map}

        # Item 2: Emit search metadata event
        yield {
            "type": "metadata",
            "data": {
                "search_type": merged.search_type,
                "reranker_used": merged.reranker_used,
                "total_candidates": merged.total_candidates,
                "total_after_rerank": merged.total_after_rerank,
            }
        }

        # Item 3: Emit auto-applied filters event
        if merged.filters_applied:
            yield {"type": "filters", "data": merged.filters_applied}

        yield {"type": "synthesizing", "data": None}

        # Step 6: Build the synthesis prompt by calling existing rag_service helpers
        # Mirrors what AgenticRAGService._synthesize_answer does, but for streaming.
        generation_inputs = await loop.run_in_executor(
            _executor,
            lambda: rag.prepare_generation_inputs(
                question=query,
                retrieval_result=merged,
                style=style_enum,
            ),
        )

        sub_q_summary = "\n".join([f"- {sq}" for sq in sub_queries])
        # Import the synthesis addendum prompts
        from agentic_service import SYNTHESIS_SYSTEM_PROMPT_ADDITION, SERIES_SYNTHESIS_ADDITION

        enhanced_user_prompt = (
            generation_inputs["user_prompt"]
            + f"\n\n---\n\nThis question was decomposed into these sub-queries:\n{sub_q_summary}\n\n"
            + SYNTHESIS_SYSTEM_PROMPT_ADDITION
        )

        # Add series-specific synthesis instructions if context is available
        if series_context:
            enhanced_user_prompt += "\n" + SERIES_SYNTHESIS_ADDITION
            logger.info(
                f"Streaming synthesis with series context: {series_context.series_id}"
            )

        system_prompt = generation_inputs["system_prompt"]

        # Step 7: Stream tokens (REUSE existing helpers from this module)
        provider = rag.config.llm.provider.value
        accumulated_answer_parts: List[str] = []

        if provider == "claude":
            stream_iter = _stream_anthropic(rag, enhanced_user_prompt, system_prompt)
        elif provider == "gemini":
            stream_iter = _stream_gemini(rag, enhanced_user_prompt, system_prompt)
        else:
            stream_iter = _stream_openai(rag, enhanced_user_prompt, system_prompt)

        async for token in stream_iter:
            accumulated_answer_parts.append(token)
            yield {"type": "token", "data": token}

        # Log generation completion
        if log_ctx:
            log_ctx.end_phase("generation")

        # Step 8: Phase 13 groundedness verification (reuse helper)
        full_answer = "".join(accumulated_answer_parts)

        # Log generation
        if log_ctx:
            log_ctx.record_generation(
                answer=full_answer,
                system_prompt=system_prompt,
                user_prompt=enhanced_user_prompt,
                raw_response=full_answer,
                provider=provider,
                model=rag._get_model_name(),
            )
            log_ctx.start_phase("groundedness")

        groundedness_dict = await _maybe_verify_groundedness(
            rag,
            full_answer,
            merged,
            loop,
        )
        if groundedness_dict is not None:
            if log_ctx:
                log_ctx.end_phase("groundedness")
                log_ctx.record_groundedness(groundedness_dict)
            yield {"type": "groundedness", "data": groundedness_dict}
        elif log_ctx:
            log_ctx.end_phase("groundedness")

        # Log agentic trace
        if log_ctx:
            log_ctx.record_agentic_trace(trace)
            log_ctx.__exit__(None, None, None)

        # Step 9: Emit the agentic trace as a final metadata event
        yield {"type": "agentic_trace", "data": trace.to_dict()}

        yield {"type": "done", "data": None}

    except Exception as e:
        logger.error(f"Agentic stream error: {e}", exc_info=True)
        if log_ctx:
            log_ctx.record_error(str(e))
            log_ctx.__exit__(None, None, None)
        yield {"type": "error", "data": str(e)}


async def _stream_openai(
    rag, prompt: str, system_prompt: str
) -> AsyncGenerator[str, None]:
    """Stream tokens from OpenAI."""
    try:
        from openai import AsyncOpenAI
    except ImportError:
        yield "[Error: openai package not installed for async streaming]"
        return

    client = AsyncOpenAI(api_key=rag.config.openai_api_key)

    stream = await client.chat.completions.create(
        model=rag.config.llm.openai_model,
        max_tokens=rag.config.llm.max_tokens,
        temperature=rag.config.llm.temperature,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        stream=True,
    )

    async for chunk in stream:
        if chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content


async def _stream_anthropic(
    rag, prompt: str, system_prompt: str
) -> AsyncGenerator[str, None]:
    """Stream tokens from Anthropic (direct API or Vertex AI)."""
    # Check if Vertex AI is enabled
    try:
        from src.core.vertex_client import (
            is_vertex_ai_enabled,
            get_async_anthropic_client,
            get_vertex_model_name,
        )

        use_vertex = is_vertex_ai_enabled()
    except ImportError:
        use_vertex = False

    if use_vertex:
        # Use Vertex AI Claude
        try:
            client = get_async_anthropic_client()
            model = get_vertex_model_name(rag.config.llm.claude_model)
            logger.info(f"Streaming via Vertex AI Claude: {model}")

            async with client.messages.stream(
                model=model,
                max_tokens=rag.config.llm.max_tokens,
                system=system_prompt,
                messages=[{"role": "user", "content": prompt}],
            ) as stream:
                async for text in stream.text_stream:
                    yield text
        except Exception as e:
            logger.error(f"Vertex AI Claude streaming error: {e}")
            yield f"[Error: Vertex AI Claude streaming failed: {e}]"
    else:
        # Direct Anthropic API
        try:
            from anthropic import AsyncAnthropic
        except ImportError:
            yield "[Error: anthropic package not installed for async streaming]"
            return

        client = AsyncAnthropic(api_key=rag.config.anthropic_api_key)

        async with client.messages.stream(
            model=rag.config.llm.claude_model,
            max_tokens=rag.config.llm.max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            async for text in stream.text_stream:
                yield text


async def _stream_gemini(
    rag, prompt: str, system_prompt: str
) -> AsyncGenerator[str, None]:
    """Stream tokens from Gemini."""
    try:
        from google.genai import types
        from src.core.gemini_client import get_gemini_client
    except ImportError:
        yield "[Error: google-genai package not installed for streaming]"
        return

    # Gemini uses combined prompt (system + user)
    combined_prompt = f"{system_prompt}\n\n---\n\n{prompt}"

    client = get_gemini_client()

    # Use streaming API
    response = client.models.generate_content_stream(
        model=rag.config.llm.gemini_model,
        contents=[types.Part.from_text(text=combined_prompt)],
        config=types.GenerateContentConfig(
            temperature=rag.config.llm.temperature,
            max_output_tokens=rag.config.llm.max_tokens,
        ),
    )

    # Gemini streaming yields chunks with text attribute
    for chunk in response:
        if chunk.text:
            yield chunk.text
