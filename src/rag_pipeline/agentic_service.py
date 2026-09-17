"""
Agentic Retrieval Service (Phase 11).

Wraps RAGService with an iterative retrieval loop for complex queries.
Uses a planner LLM call to decompose questions, then retrieves + reflects
for each sub-query.

Falls back to RAGService.ask() for simple queries.
"""

import json
import time
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, AsyncIterator, Iterator, TYPE_CHECKING

try:
    from ..core.config import RAGConfig, AgenticConfig, LLMProvider
    from .models import RAGResponse, Citation, RetrievalResult
    from .rag_service import RAGService, ResponseStyle
    from .retrieval_service import RetrievalService
    from .query_enhancer import QueryEnhancer, QueryEnhancement
    from .retrieval_utils import merge_filters, has_explicit_report_filter
    from .report_registry import SeriesContext
except ImportError:
    from src.core.config import RAGConfig, AgenticConfig, LLMProvider
    from models import RAGResponse, Citation, RetrievalResult
    from rag_service import RAGService, ResponseStyle
    from retrieval_service import RetrievalService
    from query_enhancer import QueryEnhancer, QueryEnhancement
    from retrieval_utils import merge_filters, has_explicit_report_filter
    from report_registry import SeriesContext

logger = logging.getLogger(__name__)


# =============================================================================
# TRACE & RESULT SHAPES
# =============================================================================


@dataclass
class SubQueryResult:
    """Result of running one sub-query through the loop."""

    sub_query: str
    iterations: int
    final_retrieval: Optional[RetrievalResult]
    sufficient: bool
    reformulations: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sub_query": self.sub_query,
            "iterations": self.iterations,
            "sufficient": self.sufficient,
            "reformulations": self.reformulations,
            "num_chunks": self.final_retrieval.total_after_rerank
            if self.final_retrieval
            else 0,
        }


@dataclass
class AgenticTrace:
    """Full trace of an agentic query."""

    original_query: str
    complexity: str  # "simple", "multi_hop", "cross_report"
    decomposition_reason: str
    sub_queries: List[str]
    sub_query_results: List[SubQueryResult] = field(default_factory=list)
    total_iterations: int = 0
    total_tokens_est: int = 0
    total_wall_ms: int = 0
    bail_reason: Optional[str] = None  # e.g. "budget_exceeded", "timeout"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "original_query": self.original_query,
            "complexity": self.complexity,
            "decomposition_reason": self.decomposition_reason,
            "sub_queries": self.sub_queries,
            "sub_query_results": [r.to_dict() for r in self.sub_query_results],
            "total_iterations": self.total_iterations,
            "total_wall_ms": self.total_wall_ms,
            "bail_reason": self.bail_reason,
        }


# =============================================================================
# PROMPTS
# =============================================================================

DECOMPOSITION_SYSTEM_PROMPT = """You are a query planner for a RAG system over Indian CAG audit reports.

Analyze whether a question needs multi-step retrieval or can be answered in one pass.

Decision criteria:
- "simple" — single fact/finding/definition. One retrieval pass suffices.
  Examples: "What is PRIASoft?", "What was the revenue loss at Nathavalasa toll plaza?", "When was NH Fee Amendment Rules introduced?"

- "multi_hop" — requires information from multiple distinct facets or depends on intermediate facts.
  Examples: "What caused the toll collection delays and how much did users lose as a result?",
           "Which recommendations from 2022 were addressed in 2024?",
           "Compare the findings in two specific audits"

- "cross_report" — explicitly needs synthesis across multiple reports.
  Examples: "What are the common irregularities across all NHAI toll audits?",
           "How have FRBM compliance findings evolved 2022-2024?"

Return ONLY valid JSON with this schema:
{
  "complexity": "simple" | "multi_hop" | "cross_report",
  "reason": "brief explanation of why this classification",
  "sub_queries": ["<sub-query 1>", "<sub-query 2>", ...] or null if simple,
  "report_filter_hint": "brief hint if cross_report" or null
}

Rules:
- For "simple", sub_queries must be null
- For "multi_hop" and "cross_report", generate 2-4 sub-queries that collectively answer the original
- Each sub-query must be STANDALONE (no pronouns referring to the original or other sub-queries)
- Use CAG/audit domain vocabulary in sub-queries"""


REFORMULATION_SYSTEM_PROMPT = """You rewrite a failing retrieval query to improve results.

You will be given:
1. The ORIGINAL SUB-QUERY that retrieved poor results
2. The TOP RESULTS it did retrieve (summaries only)
3. The REASON it failed (low relevance score, wrong entity, etc.)

Return ONLY valid JSON:
{
  "reformulation": "<new query text>",
  "reformulation_strategy": "add_entity | broaden | narrow | change_vocabulary"
}

Rules:
- Keep the reformulation specific to the user's intent
- If the top results mention a wrong entity, be explicit about the correct one
- If no results were found, broaden vocabulary and remove acronyms
- If too many unrelated results, narrow by adding domain terms"""


SYNTHESIS_SYSTEM_PROMPT_ADDITION = """
This answer synthesizes findings from multiple sub-queries. The user asked a compound question.

Structure your answer to address each aspect of the original question, using the sub-query results as evidence.
Preserve ALL citations exactly as they appear in the provided contexts — do not invent section numbers.

If a sub-query returned no sufficient evidence, explicitly state: "The available reports do not contain sufficient information on [aspect]."
"""


# =============================================================================
# SERIES-AWARE PROMPTS (Phase B - Temporal awareness)
# =============================================================================

SERIES_DECOMPOSITION_CONTEXT = """
---
IMPORTANT: This query is scoped to a TIME SERIES of related CAG audit reports.

{series_context}

TEMPORAL DECOMPOSITION GUIDELINES:
1. For trend/evolution questions ("how has X changed", "what improvements", "year-over-year"):
   - Classify as "cross_report"
   - Generate sub-queries targeting SPECIFIC YEARS from the series
   - Example: "FRBM compliance issues in 2021-22", "FRBM compliance issues in 2022-23"

2. For comparative questions ("compare", "difference between years"):
   - Classify as "cross_report"
   - Generate sub-queries for each year being compared
   - Make each sub-query mention the specific audit year explicitly

3. For aggregation questions ("common findings", "recurring issues"):
   - Classify as "cross_report"
   - Generate sub-queries that search across all years
   - Include year-specific variants if the series spans 3+ years

4. Sub-queries MUST include the audit year (e.g., "2022-23") when targeting a specific report.

5. The retrieval is already scoped to these reports — do NOT filter further by report name.
---
"""

SERIES_SYNTHESIS_ADDITION = """
---
TEMPORAL SYNTHESIS GUIDELINES:
This answer synthesizes findings across a TIME SERIES of audit reports.

1. STRUCTURE chronologically: Present findings in year order (oldest to newest).

2. LABEL by year: When citing findings, always indicate which audit year they come from.
   Example: "In 2021-22, the audit found... By 2023-24, this had improved to..."

3. HIGHLIGHT trends: Explicitly note:
   - Improvements or deteriorations over time
   - Recurring/persistent issues across years
   - New issues that appeared in later years
   - Issues that were resolved

4. QUANTIFY changes: If monetary amounts are mentioned, compare across years.
   Example: "Revenue loss decreased from ₹142 crore (2021-22) to ₹98 crore (2023-24)."

5. If certain years lack data on a topic, explicitly note: "No findings on [X] in [year]."
---
"""


# =============================================================================
# AGENTIC SERVICE
# =============================================================================


class AgenticRAGService:
    """
    Orchestrator for multi-hop and cross-report queries.

    Composes RAGService — does not replace it.

    Bridge C additions:
    - Query observability logging via QueryLogger
    - Sub-queries logged with parent_query_id linkage

    Default: Gemini 3.5 Flash for GCP credit billing.
    """

    def __init__(self, rag_service: RAGService, config: Optional[AgenticConfig] = None):
        self.rag = rag_service
        self.config = config or rag_service.config.agentic

        # We reuse the parent's LLM clients
        self.openai = rag_service.openai
        self.anthropic = rag_service.anthropic
        self.gemini = rag_service.gemini
        self._gemini_client = None  # Lazy-initialized for standalone Gemini calls

        # Check if planner uses Gemini
        self._use_gemini_planner = self.config.planner_model.startswith("gemini-")

        # Query logger (shared with RAG service)
        self.query_logger = getattr(rag_service, "query_logger", None)

    # -------------------------------------------------------------------------
    # Main entry points (sync)
    # -------------------------------------------------------------------------

    def ask(
        self,
        question: str,
        filters: Optional[Dict[str, Any]] = None,
        top_k: int = 10,
        style: Optional[ResponseStyle] = None,
        client_session_id: Optional[str] = None,
        user_agent: Optional[str] = None,
        series_context: Optional[SeriesContext] = None,
    ) -> RAGResponse:
        """
        Agentic ask. Plans, decomposes, and synthesizes multi-hop queries.

        For simple queries, delegates to rag.ask() unchanged.

        Args:
            question: The user's question
            filters: Qdrant filters (e.g., {"report_id": [...]})
            top_k: Number of chunks to retrieve
            style: Response style preference
            client_session_id: Session ID for logging
            user_agent: User agent for logging
            series_context: Optional SeriesContext for temporal-aware decomposition
                           and synthesis (Phase B - Series × Agentic integration)
        """
        # Extract report_ids for logging
        report_ids_filter = None
        if filters and "report_id" in filters:
            rid = filters["report_id"]
            report_ids_filter = rid if isinstance(rid, list) else [rid]

        # Start query logging context
        log_ctx = None
        if self.query_logger:
            log_ctx = self.query_logger.start_query(
                query_text=question,
                interaction_mode="home",  # Will be updated to agentic_* based on complexity
                report_ids_filter=report_ids_filter,
                explicit_filters=filters,
                style=style.value if style else None,
                client_session_id=client_session_id,
                user_agent=user_agent,
            )
            log_ctx = log_ctx.__enter__()
            log_ctx.start_phase("enhancement")

        try:
            return self._ask_impl(
                question=question,
                filters=filters,
                top_k=top_k,
                style=style,
                log_ctx=log_ctx,
                series_context=series_context,
            )
        except Exception as e:
            if log_ctx:
                log_ctx.record_error(str(e))
            raise
        finally:
            if log_ctx:
                log_ctx.__exit__(None, None, None)

    def _ask_impl(
        self,
        question: str,
        filters: Optional[Dict[str, Any]],
        top_k: int,
        style: Optional[ResponseStyle],
        log_ctx=None,
        series_context: Optional[SeriesContext] = None,
    ) -> RAGResponse:
        """Internal implementation of agentic ask() with logging support."""
        t_start = time.time()

        # Step 1: Plan / decompose (with series context if available)
        plan = self._decompose(question, series_context=series_context)
        trace = AgenticTrace(
            original_query=question,
            complexity=plan["complexity"],
            decomposition_reason=plan["reason"],
            sub_queries=plan.get("sub_queries") or [question],
        )

        # Log enhancement phase completion
        if log_ctx:
            log_ctx.end_phase("enhancement")

        # Short-circuit: simple queries go through normal RAGService
        # TODO(Phase 12): Use plan.get("report_filter_hint") to narrow filters for cross_report queries
        if plan["complexity"] == "simple":
            logger.info(
                "Agentic classified query as simple; delegating to RAGService.ask()"
            )
            # Log the agentic trace even for simple queries
            if log_ctx:
                log_ctx.record_agentic_trace(trace)
            response = self.rag.ask(question, filters=filters, top_k=top_k, style=style)
            # Note: we attach trace via the new `agentic_trace` field, not groundedness
            response.agentic_trace = (
                trace.to_dict()
            )  # requires the field on RAGResponse (see below)
            return response

        # Log that we're doing multi-hop/cross-report
        if log_ctx:
            log_ctx.agentic_complexity = plan["complexity"]
            log_ctx.start_phase("retrieval")

        # Step 2: Run loop per sub-query
        sub_queries = plan["sub_queries"]

        # Enforce max sub-queries
        if len(sub_queries) > self.config.max_sub_queries:
            sub_queries = sub_queries[: self.config.max_sub_queries]
            trace.sub_queries = sub_queries

        all_retrievals: List[RetrievalResult] = []
        aggregated_chunks_seen: set = set()

        for sub_q in sub_queries:
            # Check budget
            elapsed_ms = int((time.time() - t_start) * 1000)
            if elapsed_ms > self.config.max_wall_ms:
                trace.bail_reason = "timeout"
                break
            if trace.total_iterations >= self.config.max_total_iterations:
                trace.bail_reason = "iteration_budget_exceeded"
                break

            sub_result = self._run_subquery_loop(sub_q, filters, trace)
            trace.sub_query_results.append(sub_result)
            trace.total_iterations += sub_result.iterations

            if sub_result.final_retrieval:
                all_retrievals.append(sub_result.final_retrieval)

        trace.total_wall_ms = int((time.time() - t_start) * 1000)

        # Log retrieval phase completion
        if log_ctx:
            log_ctx.end_phase("retrieval")

        # Step 3: Synthesize
        if not all_retrievals:
            if log_ctx:
                log_ctx.record_agentic_trace(trace)
            return RAGResponse(
                query=question,
                answer="I couldn't find sufficient information in the CAG reports to answer this multi-part question. "
                "Try breaking it into simpler questions or checking if the topic is covered.",
                citations=[],
                sources_used=0,
                context_length=0,
                reranker_used="none",
                search_type="agentic",
                model_used=self.rag._get_model_name(),
                groundedness=None,
                agentic_trace=trace.to_dict(),
            )

        # Merge retrievals and synthesize
        merged = self._merge_retrievals(all_retrievals)

        # Log retrieval results
        if log_ctx:
            include_full = (
                self.rag.config.observability.dev_debug
                if hasattr(self.rag.config, "observability")
                else False
            )
            log_ctx.record_retrieval(
                merged,
                reranker_used=merged.reranker_used,
                include_full_content=include_full,
            )
            log_ctx.start_phase("generation")

        answer = self._synthesize_answer(
            question, sub_queries, merged, style or ResponseStyle.ADAPTIVE,
            series_context=series_context,
        )

        # Log generation
        if log_ctx:
            log_ctx.end_phase("generation")
            log_ctx.record_generation(
                answer=answer,
                provider=self.rag.config.llm.provider.value,
                model=self.rag._get_model_name(),
            )

        # Build citations from merged result
        citations = self.rag.build_citations(merged)

        # Optional: groundedness check
        groundedness_dict = None
        if self.rag.groundedness_service:
            if log_ctx:
                log_ctx.start_phase("groundedness")
            report = self.rag.groundedness_service.verify(answer, merged)
            groundedness_dict = report.to_dict()
            if log_ctx:
                log_ctx.end_phase("groundedness")
                log_ctx.record_groundedness(groundedness_dict)

        # Log agentic trace
        if log_ctx:
            log_ctx.record_agentic_trace(trace)

        return RAGResponse(
            query=question,
            answer=answer,
            citations=citations,
            sources_used=merged.total_after_rerank,
            context_length=sum(len(r.to_context_string()) for r in all_retrievals),
            reranker_used=merged.reranker_used,
            search_type="agentic",
            model_used=self.rag._get_model_name(),
            groundedness=groundedness_dict,
            agentic_trace=trace.to_dict(),
        )

    # -------------------------------------------------------------------------
    # Decomposition
    # -------------------------------------------------------------------------

    @property
    def gemini_client(self):
        """Lazy-initialize standalone Gemini client."""
        if self._gemini_client is None:
            try:
                from google import genai
                self._gemini_client = genai.Client()
            except ImportError:
                raise ImportError("Install google-genai: pip install google-genai")
        return self._gemini_client

    def _decompose(
        self,
        question: str,
        series_context: Optional[SeriesContext] = None,
    ) -> Dict[str, Any]:
        """
        Single LLM call to plan the query.

        Args:
            question: The user's question
            series_context: Optional SeriesContext for temporal-aware decomposition
        """
        try:
            # Build system prompt - add series context if available
            system_prompt = DECOMPOSITION_SYSTEM_PROMPT
            if series_context:
                # Inject series context into prompt for temporal awareness
                series_block = SERIES_DECOMPOSITION_CONTEXT.format(
                    series_context=series_context.to_prompt_block()
                )
                system_prompt = system_prompt + "\n" + series_block
                logger.info(
                    f"Decomposing with series context: {series_context.series_id} "
                    f"({len(series_context.years_covered)} years)"
                )

            if self._use_gemini_planner:
                return self._decompose_with_gemini(question, system_prompt)
            else:
                return self._decompose_with_openai(question, system_prompt)
        except Exception as e:
            logger.warning(f"Decomposition failed: {e}; falling back to simple")
            return {
                "complexity": "simple",
                "reason": f"decomposition_failed: {e}",
                "sub_queries": None,
                "report_filter_hint": None,
            }

    def _decompose_with_gemini(self, question: str, system_prompt: str) -> Dict[str, Any]:
        """Use Gemini for query decomposition (GCP credit billing)."""
        from google.genai import types

        combined_prompt = f"{system_prompt}\n\n---\n\nQuestion: \"{question}\"\n\nRespond with ONLY valid JSON."

        response = self.gemini_client.models.generate_content(
            model=self.config.planner_model,
            contents=[types.Part.from_text(text=combined_prompt)],
            config=types.GenerateContentConfig(
                temperature=0.0,
                max_output_tokens=800,
                response_mime_type="application/json",
            ),
        )
        return json.loads(response.text.strip())

    def _decompose_with_openai(self, question: str, system_prompt: str) -> Dict[str, Any]:
        """Use OpenAI for query decomposition (fallback)."""
        response = self.openai.chat.completions.create(
            model=self.config.planner_model,
            max_tokens=800,
            temperature=0.0,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f'Question: "{question}"'},
            ],
            response_format={"type": "json_object"},
        )
        return json.loads(response.choices[0].message.content.strip())

    # -------------------------------------------------------------------------
    # Sub-query loop
    # -------------------------------------------------------------------------

    def _run_subquery_loop(
        self,
        sub_query: str,
        filters: Optional[Dict[str, Any]],
        trace: AgenticTrace,
    ) -> SubQueryResult:
        """Run retrieve → assess → reformulate loop for one sub-query."""
        current_query = sub_query
        reformulations: List[str] = []
        last_retrieval: Optional[RetrievalResult] = None
        sufficient = False

        # Auto-filter extraction for sub-query (only if parent didn't specify report_id)
        merged_filters = filters
        if (
            self.rag.auto_filter_extractor
            and not has_explicit_report_filter(filters)
        ):
            auto_filters = self.rag.auto_filter_extractor.extract(sub_query, None)
            merged_filters = merge_filters(filters, auto_filters)

        for iteration in range(self.config.max_iterations_per_subquery):
            # Reuse existing multi-query retrieval infrastructure
            # We could reuse QueryEnhancer but for loop overhead reasons
            # we use a simpler single-query retrieve
            result = self.rag.retrieval.retrieve(
                current_query,
                top_k=self.config.top_k_per_subquery,
                filters=merged_filters,
                enhancement=None,  # Don't double-enhance
            )
            last_retrieval = result

            # Check sufficiency
            sufficient = self.rag._check_context_sufficiency(result)

            if sufficient:
                logger.info(
                    f"Sub-query sufficient at iteration {iteration+1}: '{current_query[:80]}...'"
                )
                break

            # Not sufficient — try reformulating
            if iteration < self.config.max_iterations_per_subquery - 1:
                try:
                    current_query = self._reformulate(sub_query, current_query, result)
                    reformulations.append(current_query)
                    logger.info(f"Reformulated sub-query to: '{current_query[:80]}...'")
                except Exception as e:
                    logger.warning(f"Reformulation failed: {e}")
                    break

        return SubQueryResult(
            sub_query=sub_query,
            iterations=iteration + 1,
            final_retrieval=last_retrieval,
            sufficient=sufficient,
            reformulations=reformulations,
        )

    def _reformulate(
        self,
        original_sub_query: str,
        last_attempt: str,
        last_result: RetrievalResult,
    ) -> str:
        """Generate a reformulation based on failed retrieval."""
        # Summarize top results for the reformulator
        top_snippets = []
        for parent in last_result.parents[:3]:
            for child in parent.children[:2]:
                top_snippets.append(f"- {child.content[:150]}")
        snippets_str = "\n".join(top_snippets) if top_snippets else "(no results)"

        user_prompt = f"""ORIGINAL SUB-QUERY: {original_sub_query}
LAST ATTEMPT: {last_attempt}

TOP RESULTS (summaries):
{snippets_str}

Reason for failure: sufficiency score below threshold.

Generate a reformulation."""

        if self._use_gemini_planner:
            return self._reformulate_with_gemini(user_prompt)
        else:
            return self._reformulate_with_openai(user_prompt)

    def _reformulate_with_gemini(self, user_prompt: str) -> str:
        """Use Gemini for reformulation (GCP credit billing)."""
        from google.genai import types

        combined_prompt = f"{REFORMULATION_SYSTEM_PROMPT}\n\n---\n\n{user_prompt}\n\nRespond with ONLY valid JSON."

        response = self.gemini_client.models.generate_content(
            model=self.config.planner_model,
            contents=[types.Part.from_text(text=combined_prompt)],
            config=types.GenerateContentConfig(
                temperature=0.0,
                max_output_tokens=200,
                response_mime_type="application/json",
            ),
        )
        parsed = json.loads(response.text.strip())
        return parsed.get("reformulation", "")

    def _reformulate_with_openai(self, user_prompt: str) -> str:
        """Use OpenAI for reformulation (fallback)."""
        response = self.openai.chat.completions.create(
            model=self.config.planner_model,
            max_tokens=200,
            temperature=0.0,
            messages=[
                {"role": "system", "content": REFORMULATION_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
        )
        parsed = json.loads(response.choices[0].message.content.strip())
        return parsed.get("reformulation", "")

    # -------------------------------------------------------------------------
    # Merge & synthesize
    # -------------------------------------------------------------------------

    def _merge_retrievals(self, retrievals: List[RetrievalResult]) -> RetrievalResult:
        """Merge multiple RetrievalResults. Phase 12: uses shared helper."""
        try:
            from .retrieval_utils import merge_retrieval_results
        except ImportError:
            from retrieval_utils import merge_retrieval_results
        return merge_retrieval_results(retrievals)

    def _synthesize_answer(
        self,
        original_question: str,
        sub_queries: List[str],
        merged: RetrievalResult,
        style: ResponseStyle,
        series_context: Optional[SeriesContext] = None,
    ) -> str:
        """
        Synthesize final answer from merged retrievals.

        Args:
            original_question: The user's original question
            sub_queries: List of sub-queries that were executed
            merged: Merged retrieval results
            style: Response style preference
            series_context: Optional SeriesContext for temporal-aware synthesis
        """
        # Build prompt using existing rag_service machinery
        inputs = self.rag.prepare_generation_inputs(
            question=original_question,
            retrieval_result=merged,
            style=style,
        )

        # Append the synthesis instruction + sub-query breadcrumbs
        sub_q_summary = "\n".join([f"- {sq}" for sq in sub_queries])
        enhanced_user_prompt = (
            inputs["user_prompt"]
            + f"\n\n---\n\nThis question was decomposed into these sub-queries:\n{sub_q_summary}\n\n"
            + SYNTHESIS_SYSTEM_PROMPT_ADDITION
        )

        # Add series-specific synthesis instructions if context is available
        if series_context:
            enhanced_user_prompt += "\n" + SERIES_SYNTHESIS_ADDITION
            logger.info(
                f"Synthesizing with series context: {series_context.series_id} "
                f"(years: {', '.join(series_context.years_covered)})"
            )

        # Dispatch to configured LLM
        if self.rag.config.llm.provider == LLMProvider.CLAUDE:
            return self.rag._generate_claude(
                enhanced_user_prompt, inputs["system_prompt"]
            )
        elif self.rag.config.llm.provider == LLMProvider.GEMINI:
            return self.rag._generate_gemini(
                enhanced_user_prompt, inputs["system_prompt"]
            )
        else:
            return self.rag._generate_openai(
                enhanced_user_prompt, inputs["system_prompt"]
            )
