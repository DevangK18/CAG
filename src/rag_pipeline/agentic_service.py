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
from typing import List, Dict, Any, Optional, AsyncIterator, Iterator

try:
    from ..core.config import RAGConfig, AgenticConfig, LLMProvider
    from .models import RAGResponse, Citation, RetrievalResult
    from .rag_service import RAGService, ResponseStyle
    from .retrieval_service import RetrievalService
    from .query_enhancer import QueryEnhancer, QueryEnhancement
except ImportError:
    from src.core.config import RAGConfig, AgenticConfig, LLMProvider
    from models import RAGResponse, Citation, RetrievalResult
    from rag_service import RAGService, ResponseStyle
    from retrieval_service import RetrievalService
    from query_enhancer import QueryEnhancer, QueryEnhancement

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
# AGENTIC SERVICE
# =============================================================================


class AgenticRAGService:
    """
    Orchestrator for multi-hop and cross-report queries.

    Composes RAGService — does not replace it.
    """

    def __init__(self, rag_service: RAGService, config: Optional[AgenticConfig] = None):
        self.rag = rag_service
        self.config = config or rag_service.config.agentic

        # We reuse the parent's LLM clients
        self.openai = rag_service.openai
        self.anthropic = rag_service.anthropic
        self.gemini = rag_service.gemini

    # -------------------------------------------------------------------------
    # Main entry points (sync)
    # -------------------------------------------------------------------------

    def ask(
        self,
        question: str,
        filters: Optional[Dict[str, Any]] = None,
        top_k: int = 10,
        style: Optional[ResponseStyle] = None,
    ) -> RAGResponse:
        """
        Agentic ask. Plans, decomposes, and synthesizes multi-hop queries.

        For simple queries, delegates to rag.ask() unchanged.
        """
        t_start = time.time()

        # Step 1: Plan / decompose
        plan = self._decompose(question)
        trace = AgenticTrace(
            original_query=question,
            complexity=plan["complexity"],
            decomposition_reason=plan["reason"],
            sub_queries=plan.get("sub_queries") or [question],
        )

        # Short-circuit: simple queries go through normal RAGService
        # TODO(Phase 12): Use plan.get("report_filter_hint") to narrow filters for cross_report queries
        if plan["complexity"] == "simple":
            logger.info(
                "Agentic classified query as simple; delegating to RAGService.ask()"
            )
            response = self.rag.ask(question, filters=filters, top_k=top_k, style=style)
            # Note: we attach trace via the new `agentic_trace` field, not groundedness
            response.agentic_trace = (
                trace.to_dict()
            )  # requires the field on RAGResponse (see below)
            return response

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

        # Step 3: Synthesize
        if not all_retrievals:
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
        answer = self._synthesize_answer(
            question, sub_queries, merged, style or ResponseStyle.ADAPTIVE
        )

        # Build citations from merged result
        citations = self.rag.build_citations(merged)

        # Optional: groundedness check
        groundedness_dict = None
        if self.rag.groundedness_service:
            report = self.rag.groundedness_service.verify(answer, merged)
            groundedness_dict = report.to_dict()

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

    def _decompose(self, question: str) -> Dict[str, Any]:
        """Single LLM call to plan the query."""
        try:
            response = self.openai.chat.completions.create(
                model=self.config.planner_model,
                max_tokens=800,
                temperature=0.0,
                messages=[
                    {"role": "system", "content": DECOMPOSITION_SYSTEM_PROMPT},
                    {"role": "user", "content": f'Question: "{question}"'},
                ],
                response_format={"type": "json_object"},
            )
            return json.loads(response.choices[0].message.content.strip())
        except Exception as e:
            logger.warning(f"Decomposition failed: {e}; falling back to simple")
            return {
                "complexity": "simple",
                "reason": f"decomposition_failed: {e}",
                "sub_queries": None,
                "report_filter_hint": None,
            }

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

        for iteration in range(self.config.max_iterations_per_subquery):
            # Reuse existing multi-query retrieval infrastructure
            # We could reuse QueryEnhancer but for loop overhead reasons
            # we use a simpler single-query retrieve
            result = self.rag.retrieval.retrieve(
                current_query,
                top_k=self.config.top_k_per_subquery,
                filters=filters,
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
        return parsed.get("reformulation", original_sub_query)

    # -------------------------------------------------------------------------
    # Merge & synthesize
    # -------------------------------------------------------------------------

    def _merge_retrievals(self, retrievals: List[RetrievalResult]) -> RetrievalResult:
        """
        Merge multiple RetrievalResults into one.

        Deduplicates by chunk_id. Keeps highest score per chunk.
        """
        seen: Dict[str, Any] = {}  # chunk_id -> (chunk, parent_id)
        parent_map: Dict[str, Any] = {}  # parent_id -> ParentContext

        for result in retrievals:
            for parent in result.parents:
                if parent.chunk_id not in parent_map:
                    # Create a copy so we don't mutate the original
                    from copy import copy

                    parent_map[parent.chunk_id] = copy(parent)
                    parent_map[parent.chunk_id].children = []

                for child in parent.children:
                    if child.chunk_id not in seen:
                        seen[child.chunk_id] = (child, parent.chunk_id)
                        parent_map[parent.chunk_id].children.append(child)
                    else:
                        existing, _ = seen[child.chunk_id]
                        if child.score > existing.score:
                            existing.score = child.score

        parents_list = [p for p in parent_map.values() if p.children]
        parents_list.sort(key=lambda p: -max(c.score for c in p.children))

        from .models import RetrievalResult as RR

        return RR(
            query=retrievals[0].query if retrievals else "",
            total_candidates=sum(r.total_candidates for r in retrievals),
            total_after_rerank=len(seen),
            parents=parents_list,
            filters_applied=retrievals[0].filters_applied if retrievals else {},
            reranker_used=retrievals[0].reranker_used if retrievals else "none",
            search_type="agentic_merged",
        )

    def _synthesize_answer(
        self,
        original_question: str,
        sub_queries: List[str],
        merged: RetrievalResult,
        style: ResponseStyle,
    ) -> str:
        """Synthesize final answer from merged retrievals."""
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
