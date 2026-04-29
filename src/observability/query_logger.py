"""
Query logger with context manager pattern for the CAG RAG pipeline.

Usage:
    with query_logger.start_query(
        query_text=question,
        interaction_mode="directory",
        environment="dev",
    ) as ctx:
        ctx.record_query_enhancement(enhancement)
        ctx.record_auto_filters(auto_filters)
        ctx.record_retrieval(retrieval_result, reranker_used)
        ctx.record_generation(answer, system_prompt, user_prompt, ...)
        ctx.record_groundedness(groundedness_report)
        return result
    # On exit, log is written async to Postgres
"""

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .cost_calculator import calculate_cost
from .models import QueryLog, Base

try:
    from src.core.config import ObservabilityConfig
except ImportError:
    from core.config import ObservabilityConfig

logger = logging.getLogger(__name__)


class QueryLogContext:
    """
    Context manager for capturing query lifecycle data.

    Collects data via record_*() methods during query execution,
    then writes to Postgres on exit.
    """

    def __init__(
        self,
        logger_instance: "QueryLogger",
        query_text: str,
        interaction_mode: str,
        environment: str,
        report_ids_filter: Optional[List[str]] = None,
        series_id: Optional[str] = None,
        explicit_filters: Optional[Dict[str, Any]] = None,
        style: Optional[str] = None,
        parent_query_id: Optional[uuid.UUID] = None,
        client_session_id: Optional[str] = None,
        user_agent: Optional[str] = None,
    ):
        self._logger = logger_instance
        self._start_time = time.time()
        self._phase_timings: Dict[str, float] = {}
        self._current_phase: Optional[str] = None
        self._phase_start: Optional[float] = None

        # Initialize log data
        self.query_id = uuid.uuid4()
        self.parent_query_id = parent_query_id
        self.query_text = query_text
        self.interaction_mode = interaction_mode
        self.environment = environment
        self.report_ids_filter = report_ids_filter
        self.series_id = series_id
        self.explicit_filters = explicit_filters
        self.style = style
        self.client_session_id = client_session_id
        self.user_agent = user_agent[:200] if user_agent else None

        # Data populated via record_*() methods
        self.auto_filters: Optional[Dict[str, Any]] = None
        self.merged_filters: Optional[Dict[str, Any]] = None
        self.query_enhancement: Optional[Dict[str, Any]] = None

        # Retrieval data
        self.retrieved_chunks: Optional[Dict[str, Any]] = None
        self.retrieval_search_type: Optional[str] = None
        self.retrieval_total_candidates: Optional[int] = None
        self.retrieval_total_after_rerank: Optional[int] = None
        self.rerank_scores: Optional[List[float]] = None
        self.context_sufficient: Optional[bool] = None
        self.reranker_used: Optional[str] = None

        # Agentic data
        self.agentic_complexity: Optional[str] = None
        self.agentic_sub_query_count: Optional[int] = None
        self.agentic_total_iterations: Optional[int] = None
        self.agentic_reformulation_count: Optional[int] = None
        self.agentic_bail_reason: Optional[str] = None
        self.agentic_trace: Optional[Dict[str, Any]] = None

        # Generation data
        self.llm_provider: Optional[str] = None
        self.llm_model: Optional[str] = None
        self.llm_system_prompt: Optional[str] = None
        self.llm_user_prompt: Optional[str] = None
        self.llm_raw_response: Optional[str] = None
        self.final_answer: Optional[str] = None
        self.token_usage_prompt: Optional[int] = None
        self.token_usage_completion: Optional[int] = None

        # Groundedness data
        self.groundedness_score: Optional[float] = None
        self.groundedness_verified: Optional[bool] = None
        self.groundedness_num_claims: Optional[int] = None
        self.groundedness_num_grounded: Optional[int] = None
        self.groundedness_report: Optional[Dict[str, Any]] = None

        # Status
        self.success = True
        self.error_message: Optional[str] = None
        self._should_log = True  # set False by sampling/disabled to skip the write

    def __enter__(self):
        """Enter the context. Returns self for use in `with X as ctx:`."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit the context. Records errors and writes to DB."""
        if exc_type is not None:
            self.record_error(str(exc_val))
        if self._should_log:
            self._logger._write_log(self)
        return False  # do not swallow exceptions

    def start_phase(self, phase_name: str) -> None:
        """Start timing a phase (enhancement, retrieval, rerank, generation, groundedness)."""
        if self._current_phase:
            self.end_phase(self._current_phase)
        self._current_phase = phase_name
        self._phase_start = time.time()

    def end_phase(self, phase_name: str) -> None:
        """End timing a phase."""
        if self._phase_start and self._current_phase == phase_name:
            elapsed_ms = int((time.time() - self._phase_start) * 1000)
            self._phase_timings[phase_name] = elapsed_ms
            self._current_phase = None
            self._phase_start = None

    def record_query_enhancement(self, enhancement: Any) -> None:
        """Record query enhancement results."""
        if enhancement is None:
            return

        # Handle both dict and object
        if hasattr(enhancement, "to_dict"):
            self.query_enhancement = enhancement.to_dict()
        elif hasattr(enhancement, "__dict__"):
            self.query_enhancement = {
                "question_type": getattr(enhancement, "question_type", None),
                "expanded_queries": getattr(enhancement, "expanded_queries", []),
                "recommended_style": getattr(enhancement, "recommended_style", None),
                "suggested_filters": getattr(enhancement, "suggested_filters", {}),
                "top_k": getattr(enhancement, "top_k", None),
                "max_context_chars": getattr(enhancement, "max_context_chars", None),
            }
        elif isinstance(enhancement, dict):
            self.query_enhancement = enhancement

    def record_auto_filters(self, auto_filters: Optional[Dict[str, Any]]) -> None:
        """Record auto-extracted filters."""
        self.auto_filters = auto_filters

    def record_merged_filters(self, merged_filters: Optional[Dict[str, Any]]) -> None:
        """Record final merged filters."""
        self.merged_filters = merged_filters

    def record_retrieval(
        self,
        retrieval_result: Any,
        reranker_used: Optional[str] = None,
        include_full_content: bool = False,
    ) -> None:
        """
        Record retrieval results.

        Args:
            retrieval_result: RetrievalResult object
            reranker_used: Name of reranker used
            include_full_content: If True, stores full chunk content (dev_debug only)
        """
        if retrieval_result is None:
            return

        self.retrieval_search_type = getattr(retrieval_result, "search_type", None)
        self.retrieval_total_candidates = getattr(
            retrieval_result, "total_candidates", None
        )
        self.retrieval_total_after_rerank = getattr(
            retrieval_result, "total_after_rerank", None
        )
        self.reranker_used = reranker_used or getattr(
            retrieval_result, "reranker_used", None
        )

        # Extract top rerank scores
        scores = []
        parents = getattr(retrieval_result, "parents", [])
        for parent in parents:
            for child in getattr(parent, "children", []):
                scores.append(getattr(child, "score", 0.0))
        self.rerank_scores = sorted(scores, reverse=True)[:10] if scores else None

        # Build chunk summary (always) or full content (dev_debug only)
        chunks_summary = []
        for parent in parents:
            for child in getattr(parent, "children", []):
                chunk_info = {
                    "chunk_id": getattr(child, "chunk_id", None),
                    "report_id": getattr(child, "report_id", None),
                    "score": round(getattr(child, "score", 0.0), 4),
                    "page": getattr(child, "page_physical", None),
                    "preview": getattr(child, "content", "")[:200]
                    if hasattr(child, "content")
                    else None,
                }
                if include_full_content and hasattr(child, "content"):
                    chunk_info["full_content"] = child.content
                chunks_summary.append(chunk_info)

        self.retrieved_chunks = {"chunks": chunks_summary[:20]}  # Cap at 20

    def record_context_sufficient(self, sufficient: bool) -> None:
        """Record context sufficiency check result."""
        self.context_sufficient = sufficient

    def record_agentic_trace(self, trace: Any) -> None:
        """Record agentic query trace."""
        if trace is None:
            return

        if hasattr(trace, "to_dict"):
            trace_dict = trace.to_dict()
        elif isinstance(trace, dict):
            trace_dict = trace
        else:
            return

        self.agentic_trace = trace_dict
        self.agentic_complexity = trace_dict.get("complexity")
        self.agentic_sub_query_count = len(trace_dict.get("sub_queries", []))
        self.agentic_total_iterations = trace_dict.get("total_iterations")
        self.agentic_bail_reason = trace_dict.get("bail_reason")

        # Count reformulations
        reformulation_count = 0
        for sq_result in trace_dict.get("sub_query_results", []):
            reformulation_count += len(sq_result.get("reformulations", []))
        self.agentic_reformulation_count = reformulation_count

    def record_generation(
        self,
        answer: str,
        system_prompt: Optional[str] = None,
        user_prompt: Optional[str] = None,
        raw_response: Optional[str] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        prompt_tokens: Optional[int] = None,
        completion_tokens: Optional[int] = None,
    ) -> None:
        """Record LLM generation details."""
        self.final_answer = answer
        self.llm_system_prompt = system_prompt
        self.llm_user_prompt = user_prompt
        self.llm_raw_response = raw_response
        self.llm_provider = provider
        self.llm_model = model
        self.token_usage_prompt = prompt_tokens
        self.token_usage_completion = completion_tokens

    def record_groundedness(self, groundedness_report: Any) -> None:
        """Record groundedness verification results."""
        if groundedness_report is None:
            return

        if hasattr(groundedness_report, "to_dict"):
            report_dict = groundedness_report.to_dict()
        elif isinstance(groundedness_report, dict):
            report_dict = groundedness_report
        else:
            return

        self.groundedness_score = report_dict.get("score")
        self.groundedness_verified = report_dict.get("verified")
        self.groundedness_num_claims = report_dict.get("num_claims")
        self.groundedness_num_grounded = report_dict.get("num_grounded")
        self.groundedness_report = report_dict

    def record_error(self, error_message: str) -> None:
        """Record an error."""
        self.success = False
        self.error_message = error_message

    def _build_log_dict(self) -> Dict[str, Any]:
        """Build the complete log dictionary for database insertion."""
        # End any open phase
        if self._current_phase:
            self.end_phase(self._current_phase)

        # Calculate total latency
        total_ms = int((time.time() - self._start_time) * 1000)
        self._phase_timings["total"] = total_ms

        # Calculate cost
        cost = calculate_cost(
            self.llm_provider,
            self.llm_model,
            self.token_usage_prompt,
            self.token_usage_completion,
        )

        # Build the log dict
        log_dict = {
            "query_id": self.query_id,
            "parent_query_id": self.parent_query_id,
            "environment": self.environment,
            "interaction_mode": self.interaction_mode,
            "query_text": self.query_text
            if self._logger.config.log_query_text
            else "[REDACTED]",
            "style": self.style,
            "report_ids_filter": self.report_ids_filter,
            "series_id": self.series_id,
            "explicit_filters": self.explicit_filters,
            "auto_filters": self.auto_filters,
            "merged_filters": self.merged_filters,
            "query_enhancement": self.query_enhancement,
            "retrieved_chunks": self.retrieved_chunks,
            "retrieval_search_type": self.retrieval_search_type,
            "retrieval_total_candidates": self.retrieval_total_candidates,
            "retrieval_total_after_rerank": self.retrieval_total_after_rerank,
            "rerank_scores": self.rerank_scores,
            "context_sufficient": self.context_sufficient,
            "reranker_used": self.reranker_used,
            "agentic_complexity": self.agentic_complexity,
            "agentic_sub_query_count": self.agentic_sub_query_count,
            "agentic_total_iterations": self.agentic_total_iterations,
            "agentic_reformulation_count": self.agentic_reformulation_count,
            "agentic_bail_reason": self.agentic_bail_reason,
            "agentic_trace": self.agentic_trace,
            "llm_provider": self.llm_provider,
            "llm_model": self.llm_model,
            "final_answer": self.final_answer,
            "answer_length_chars": len(self.final_answer)
            if self.final_answer
            else None,
            "citations_count": None,  # Set by caller if available
            "groundedness_score": self.groundedness_score,
            "groundedness_verified": self.groundedness_verified,
            "groundedness_num_claims": self.groundedness_num_claims,
            "groundedness_num_grounded": self.groundedness_num_grounded,
            "groundedness_report": self.groundedness_report,
            "token_usage_prompt": self.token_usage_prompt,
            "token_usage_completion": self.token_usage_completion,
            "token_usage_total": (self.token_usage_prompt or 0)
            + (self.token_usage_completion or 0)
            if self.token_usage_prompt or self.token_usage_completion
            else None,
            "cost_estimate_usd": cost if cost > 0 else None,
            "latency_total_ms": total_ms,
            "latency_breakdown_ms": self._phase_timings,
            "success": self.success,
            "error_message": self.error_message,
            "client_session_id": self.client_session_id,
            "user_agent": self.user_agent,
        }

        # Strip dev-only fields in prod (unless dev_debug is on)
        if self.environment != "dev" and not self._logger.config.dev_debug:
            log_dict["llm_system_prompt"] = None
            log_dict["llm_user_prompt"] = None
            log_dict["llm_raw_response"] = None
            # Strip full chunk content from retrieved_chunks
            if log_dict.get("retrieved_chunks"):
                chunks = log_dict["retrieved_chunks"].get("chunks", [])
                for chunk in chunks:
                    chunk.pop("full_content", None)
        else:
            # In dev mode, include prompts
            log_dict["llm_system_prompt"] = self.llm_system_prompt
            log_dict["llm_user_prompt"] = self.llm_user_prompt
            log_dict["llm_raw_response"] = self.llm_raw_response

        return log_dict


class QueryLogger:
    """
    Main query logger class.

    Manages database connections and provides context manager for logging.
    """

    def __init__(self, config: Optional[ObservabilityConfig] = None):
        self.config = config or ObservabilityConfig()
        self._engine = None
        self._session_factory = None

    def _get_engine(self):
        """Lazy-initialize the database engine (reuses entity graph connection)."""
        if self._engine is None:
            try:
                from src.entity_graph.db import get_engine

                self._engine = get_engine()
            except ImportError:
                try:
                    from entity_graph.db import get_engine

                    self._engine = get_engine()
                except ImportError:
                    logger.error("Could not import entity_graph.db.get_engine")
                    return None
        return self._engine

    def _get_session_factory(self):
        """Get or create session factory."""
        if self._session_factory is None:
            engine = self._get_engine()
            if engine:
                from sqlalchemy.orm import sessionmaker

                self._session_factory = sessionmaker(
                    bind=engine, expire_on_commit=False
                )
        return self._session_factory

    def init_tables(self) -> None:
        """Create query_logs table if it doesn't exist."""
        engine = self._get_engine()
        if engine:
            Base.metadata.create_all(engine)
            logger.info("Query logs table initialized")

    def start_query(
        self,
        query_text: str,
        interaction_mode: str,
        environment: Optional[str] = None,
        report_ids_filter: Optional[List[str]] = None,
        series_id: Optional[str] = None,
        explicit_filters: Optional[Dict[str, Any]] = None,
        style: Optional[str] = None,
        parent_query_id: Optional[uuid.UUID] = None,
        client_session_id: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> QueryLogContext:
        """
        Start a query logging context.

        Returns a QueryLogContext that is itself a context manager.

        Usage:
            with logger.start_query(...) as ctx:
                ctx.record_*()
            # _write_log fires on __exit__

        Or manually (as streaming_wrapper does):
            log_ctx = logger.start_query(...)
            log_ctx.__enter__()
            log_ctx.record_*()
            log_ctx.__exit__(None, None, None)
        """
        ctx = QueryLogContext(
            logger_instance=self,
            query_text=query_text,
            interaction_mode=interaction_mode,
            environment=environment or self.config.environment,
            report_ids_filter=report_ids_filter,
            series_id=series_id,
            explicit_filters=explicit_filters,
            style=style,
            parent_query_id=parent_query_id,
            client_session_id=client_session_id,
            user_agent=user_agent,
        )

        # Apply sampling: disabled or below sample rate → skip the actual DB write
        if not self.config.enabled:
            ctx._should_log = False
        elif self.config.sampling_rate < 1.0:
            import random

            if random.random() > self.config.sampling_rate:
                ctx._should_log = False

        return ctx

    def _write_log(self, ctx: QueryLogContext) -> None:
        """Write the log entry to Postgres."""
        if not self.config.enabled:
            return

        log_dict = ctx._build_log_dict()

        if self.config.async_writes:
            try:
                asyncio.get_running_loop()
                asyncio.create_task(asyncio.to_thread(self._sync_write, log_dict))
            except RuntimeError:
                # No running event loop, fall back to sync write
                self._sync_write(log_dict)
        else:
            self._sync_write(log_dict)

    def _sync_write(self, log_dict: Dict[str, Any]) -> None:
        """Synchronous database write. Never raises."""
        try:
            session_factory = self._get_session_factory()
            if not session_factory:
                logger.warning("Query log write failed: no session factory")
                return

            session = session_factory()
            try:
                query_log = QueryLog(**log_dict)
                session.add(query_log)
                session.commit()
                logger.debug(f"Query log written: {log_dict.get('query_id')}")
            except Exception as e:
                session.rollback()
                logger.warning(f"Query log write failed: {e}")
            finally:
                session.close()
        except Exception as e:
            logger.warning(f"Query log write failed (outer): {e}")


# Module-level singleton (initialized by API startup)
_query_logger: Optional[QueryLogger] = None


def get_query_logger() -> Optional[QueryLogger]:
    """Get the global query logger instance."""
    return _query_logger


def init_query_logger(config: Optional[ObservabilityConfig] = None) -> QueryLogger:
    """Initialize the global query logger."""
    global _query_logger
    _query_logger = QueryLogger(config)
    _query_logger.init_tables()
    return _query_logger
