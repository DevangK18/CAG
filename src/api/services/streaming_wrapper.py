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
    )


async def generate_stream(
    query: str,
    style: str = "adaptive",
    report_ids: Optional[List[str]] = None,
    top_k: int = 10,
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

    try:
        loop = asyncio.get_event_loop()
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

        # NEW: Run query enhancement first (in thread pool)
        enhancement = None
        if hasattr(rag, "query_enhancer") and rag.config.query_enhancement.enabled:
            enhancement = await loop.run_in_executor(
                _executor, lambda: rag.query_enhancer.enhance(query, style=style)
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

        if retrieval_result.total_after_rerank == 0:
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
        if not context_sufficient:
            yield {"type": "caveat", "data": "low_relevance"}

        # Step 2: Build and send citation map FIRST
        rag_citations = rag.build_citations(retrieval_result)
        api_citations = _convert_citations(rag_citations)
        citation_map = _build_citation_map(api_citations)

        yield {"type": "citation_map", "data": citation_map}

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

        # Step 4: Stream from LLM
        provider = rag.config.llm.provider.value

        if provider == "claude":
            async for token in _stream_anthropic(rag, user_prompt, system_prompt):
                yield {"type": "token", "data": token}
        elif provider == "gemini":
            async for token in _stream_gemini(rag, user_prompt, system_prompt):
                yield {"type": "token", "data": token}
        else:
            async for token in _stream_openai(rag, user_prompt, system_prompt):
                yield {"type": "token", "data": token}

        yield {"type": "done", "data": None}

    except Exception as e:
        logger.error(f"Stream generation error: {e}", exc_info=True)
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
    """Stream tokens from Anthropic."""
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
        from google import genai
        from google.genai import types
    except ImportError:
        yield "[Error: google-genai package not installed for streaming]"
        return

    # Gemini uses combined prompt (system + user)
    combined_prompt = f"{system_prompt}\n\n---\n\n{prompt}"

    client = genai.Client()

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
