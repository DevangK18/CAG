"""
CAG RAG Pipeline
================

A production-ready RAG system for CAG (Comptroller and Auditor General) audit reports.

Features:
- Hybrid search (dense + sparse vectors)
- Cross-encoder reranking
- LLM-based table summaries
- Semantic filtering (finding type, severity, amount)
- O(1) neighbor chunk retrieval

Quick Start:
    from services.rag_pipeline import RAGService

    rag = RAGService()
    response = rag.ask("What are the audit findings on toll collection?")
    print(response.answer)

Indexing:
    python -m services.rag_pipeline.indexer --input-dir data/processed

Querying:
    python -m services.rag_pipeline.cli "What revenue losses were found?" --min-amount 10
    python -m services.rag_pipeline.cli --interactive
"""

# Load environment variables
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from ..core.config import (
    RAGConfig,
    EmbeddingConfig,
    QdrantConfig,
    RetrievalConfig,
    LLMConfig,
)
from ..core.config import RerankerType, LLMProvider

from .models import (
    RetrievedChunk,
    ParentContext,
    RetrievalResult,
    Citation,
    RAGResponse,
)

from .embedding_service import EmbeddingService
from .qdrant_service import QdrantService
from .retrieval_service import RetrievalService
from .rag_service import RAGService, quick_ask

__version__ = "2.0.0"

__all__ = [
    # Config
    "RAGConfig",
    "EmbeddingConfig",
    "QdrantConfig",
    "RetrievalConfig",
    "LLMConfig",
    "RerankerType",
    "LLMProvider",
    # Models
    "RetrievedChunk",
    "ParentContext",
    "RetrievalResult",
    "Citation",
    "RAGResponse",
    # Services
    "EmbeddingService",
    "QdrantService",
    "RetrievalService",
    "RAGService",
    # Convenience
    "quick_ask",
]
