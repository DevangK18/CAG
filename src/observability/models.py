"""
SQLAlchemy ORM model for query logs.

Stored in the same Postgres DB as the entity graph (cag_entity_graph).
Uses SQLAlchemy 2.0 declarative mapping.
"""

import uuid
from datetime import datetime
from typing import Optional, List, Literal

from sqlalchemy import (
    BigInteger,
    Integer,
    String,
    Text,
    Float,
    Boolean,
    DateTime,
    Numeric,
    Index,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB, ARRAY
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Valid interaction modes for query logging
InteractionMode = Literal["chat", "agentic", "directory", "home", "home_search", "agentic_sub"]


class Base(DeclarativeBase):
    """Separate declarative base for observability tables."""
    pass


class QueryLog(Base):
    """
    Comprehensive query log capturing the full lifecycle of a RAG query.

    Fields are organized into logical groups:
    - Identity: query_id, parent_query_id, timestamp, environment
    - Query inputs: query_text, filters, style
    - Enhancement: query_enhancement, auto_filters, merged_filters
    - Retrieval: retrieved_chunks, search_type, rerank_scores
    - Agentic: complexity, sub_query_count, trace
    - Generation: LLM provider/model, prompts (dev only), final answer
    - Groundedness: verification results
    - Cost & latency: token usage, cost estimate, latency breakdown
    - Session: client_session_id, user_agent
    """

    __tablename__ = "query_logs"

    # Primary key
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    # Identity
    query_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, unique=True, default=uuid.uuid4
    )
    parent_query_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )
    environment: Mapped[str] = mapped_column(String(20), nullable=False)
    interaction_mode: Mapped[str] = mapped_column(String(40), nullable=False)

    # Query inputs
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    style: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    report_ids_filter: Mapped[Optional[List[str]]] = mapped_column(
        ARRAY(Text), nullable=True
    )
    series_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    explicit_filters: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    auto_filters: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    merged_filters: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    # Query enhancement
    query_enhancement: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    # Retrieval
    retrieved_chunks: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    retrieval_search_type: Mapped[Optional[str]] = mapped_column(
        String(40), nullable=True
    )
    retrieval_total_candidates: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    retrieval_total_after_rerank: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    rerank_scores: Mapped[Optional[List[float]]] = mapped_column(
        ARRAY(Float), nullable=True
    )
    context_sufficient: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    reranker_used: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)

    # Agentic-specific
    agentic_complexity: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    agentic_sub_query_count: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    agentic_total_iterations: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    agentic_reformulation_count: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    agentic_bail_reason: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    agentic_trace: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    # Generation
    llm_provider: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    llm_model: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    llm_system_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    llm_user_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    llm_raw_response: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    final_answer: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    answer_length_chars: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    citations_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Groundedness
    groundedness_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    groundedness_verified: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    groundedness_num_claims: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    groundedness_num_grounded: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    groundedness_report: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    # Cost & latency
    token_usage_prompt: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    token_usage_completion: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    token_usage_total: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    cost_estimate_usd: Mapped[Optional[float]] = mapped_column(
        Numeric(10, 6), nullable=True
    )
    latency_total_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    latency_breakdown_ms: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    # Errors
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Session
    client_session_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Table-level indexes
    __table_args__ = (
        Index("idx_query_logs_timestamp", "timestamp"),
        Index("idx_query_logs_environment_mode", "environment", "interaction_mode"),
        Index("idx_query_logs_parent", "parent_query_id"),
        Index("idx_query_logs_session", "client_session_id"),
        Index("idx_query_logs_groundedness", "groundedness_score"),
        Index("idx_query_logs_success", "success"),
        Index(
            "idx_query_logs_complexity",
            "agentic_complexity",
            postgresql_where="agentic_complexity IS NOT NULL",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<QueryLog(id={self.id}, query_id={self.query_id}, "
            f"mode={self.interaction_mode}, success={self.success})>"
        )
