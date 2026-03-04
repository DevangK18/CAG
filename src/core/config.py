"""
CAG RAG Pipeline - Configuration
=================================

Central configuration for all RAG pipeline components.
"""

import os
from dataclasses import dataclass, field
from typing import Optional, List
from enum import Enum

# Load environment variables
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


class RerankerType(Enum):
    """Available reranker options."""

    NONE = "none"
    COHERE = "cohere"
    BGE = "bge"


class LLMProvider(Enum):
    """Available LLM providers."""

    CLAUDE = "claude"
    OPENAI = "openai"
    GEMINI = "gemini"


@dataclass
class EmbeddingConfig:
    """Configuration for embedding generation."""

    # OpenAI embedding settings
    model: str = "text-embedding-3-large"
    dimensions: int = 1536  # Reduced from 3072 for cost savings
    batch_size: int = 100
    max_chunk_tokens: int = 8000

    # Sparse embedding settings
    sparse_model: str = "Qdrant/bm25"

    # Table summary settings
    table_summary_model: str = "gpt-4o"
    table_summary_max_tokens: int = 100

    # Feature flags
    enable_sparse_vectors: bool = True
    enable_table_summaries: bool = True
    enable_hierarchy_prefix: bool = True
    enable_semantic_enrichment: bool = True


@dataclass
class QdrantConfig:
    """Configuration for Qdrant vector store."""

    # Connection
    host: str = "localhost"
    port: int = 6333
    url: Optional[str] = None  # For Qdrant Cloud
    api_key: Optional[str] = None

    # Collection names
    child_collection: str = "cag_child_chunks"
    parent_collection: str = "cag_parent_chunks"

    def __post_init__(self):
        # Load from environment if available
        self.url = os.getenv("QDRANT_URL", self.url)
        self.api_key = os.getenv("QDRANT_API_KEY", self.api_key)


@dataclass
class RetrievalConfig:
    """Configuration for retrieval."""

    # Search settings
    initial_candidates: int = 50  # Before reranking
    final_top_k: int = 10  # After reranking

    # Feature flags
    enable_hybrid_search: bool = True
    enable_reranking: bool = True
    enable_neighbor_chunks: bool = True
    neighbor_window: int = 1  # ±1 chunks

    # Reranker settings
    reranker_type: RerankerType = RerankerType.COHERE
    cohere_model: str = "rerank-english-v3.0"
    bge_model: str = "BAAI/bge-reranker-v2-m3"


@dataclass
class LLMConfig:
    """Configuration for LLM generation."""

    # Provider selection (can be overridden via LLM_PROVIDER env var)
    provider: LLMProvider = None  # Set in __post_init__

    # Claude settings
    claude_model: str = None  # Set in __post_init__

    # OpenAI settings
    openai_model: str = None  # Set in __post_init__

    # Gemini settings
    gemini_model: str = None  # Set in __post_init__

    # Generation settings
    max_tokens: int = 2000
    temperature: float = 0.1  # Low for factual responses

    # Context settings
    max_context_chars: int = 15000
    include_neighbor_context: bool = True
    include_semantic_tags: bool = True

    def __post_init__(self):
        # Load provider from environment or use default
        if self.provider is None:
            provider_str = os.getenv("LLM_PROVIDER", "openai").lower()
            try:
                self.provider = LLMProvider(provider_str)
            except ValueError:
                self.provider = LLMProvider.OPENAI

        # Load models from environment or use defaults
        if self.claude_model is None:
            self.claude_model = os.getenv("LLM_CLAUDE_MODEL", "claude-sonnet-4-20250514")
        if self.openai_model is None:
            self.openai_model = os.getenv("LLM_OPENAI_MODEL", "gpt-4o-mini")
        if self.gemini_model is None:
            self.gemini_model = os.getenv("LLM_GEMINI_MODEL", "gemini-2.5-flash")


@dataclass
class QueryEnhancementConfig:
    """Configuration for query-time intelligence (Phase 1)."""

    # Feature flags
    enabled: bool = True
    enable_query_expansion: bool = True
    enable_passage_reordering: bool = True
    enable_sufficiency_check: bool = True

    # Provider and model (shared single call)
    provider: LLMProvider = LLMProvider.OPENAI  # OpenAI or Gemini supported
    model: str = "gpt-4o-mini"  # OpenAI model
    gemini_model: str = "gemini-2.5-flash"  # Gemini model
    max_tokens: int = 300
    temperature: float = 0.0

    # Query expansion
    num_expansions: int = 3  # Total queries including original

    # Sufficiency check
    min_rerank_score: float = 0.25  # Minimum top-1 Cohere score to consider sufficient

    # Passage reordering
    reorder_strategy: str = "best_first_last"  # "best_first_last" or "none"


@dataclass
class RAGConfig:
    """Complete RAG pipeline configuration."""

    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    qdrant: QdrantConfig = field(default_factory=QdrantConfig)
    retrieval: RetrievalConfig = field(default_factory=RetrievalConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    query_enhancement: QueryEnhancementConfig = field(
        default_factory=QueryEnhancementConfig
    )

    # API Keys (loaded from environment)
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    cohere_api_key: Optional[str] = None
    google_api_key: Optional[str] = None

    def __post_init__(self):
        self.openai_api_key = os.getenv("OPENAI_API_KEY")
        self.anthropic_api_key = os.getenv("ANTHROPIC_API_KEY")
        self.cohere_api_key = os.getenv("COHERE_API_KEY")
        self.google_api_key = os.getenv("GOOGLE_API_KEY")

    def validate(self) -> List[str]:
        """Validate configuration and return list of errors."""
        errors = []

        if not self.openai_api_key:
            errors.append("OPENAI_API_KEY not set (required for embeddings)")

        if self.llm.provider == LLMProvider.CLAUDE and not self.anthropic_api_key:
            errors.append("ANTHROPIC_API_KEY not set (required for Claude)")

        if self.llm.provider == LLMProvider.OPENAI and not self.openai_api_key:
            errors.append("OPENAI_API_KEY not set (required for GPT)")

        if self.llm.provider == LLMProvider.GEMINI and not self.google_api_key:
            errors.append("GOOGLE_API_KEY not set (required for Gemini)")

        if (
            self.retrieval.enable_reranking
            and self.retrieval.reranker_type == RerankerType.COHERE
            and not self.cohere_api_key
        ):
            errors.append("COHERE_API_KEY not set (required for Cohere reranking)")

        return errors


# Default configuration instance
default_config = RAGConfig()
