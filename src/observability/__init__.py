"""
Query observability module for the CAG RAG pipeline.

Provides comprehensive logging of all queries with:
- Query inputs and filters
- Retrieval results and rerank scores
- LLM generation details (prompts, tokens, costs)
- Groundedness verification results
- Latency breakdown by phase
- Agentic trace for multi-hop queries

All logs are stored in Postgres (same DB as entity graph).
"""

from .query_logger import QueryLogger, QueryLogContext
from .models import QueryLog
from .cost_calculator import calculate_cost, PRICING

__all__ = [
    "QueryLogger",
    "QueryLogContext",
    "QueryLog",
    "calculate_cost",
    "PRICING",
]
