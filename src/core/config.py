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

    # OPT-1: Context augmentation (pseudo-contextual embeddings)
    enable_context_augmentation: bool = True
    include_report_title_in_prefix: bool = True
    include_parent_context: bool = True

    # OPT-5: Content type signal in embedding
    enable_content_type_signal: bool = True


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

    # OPT-2: BM25 weight tuning (sparse gets more candidates for higher influence in RRF)
    # dense_candidates + sparse_candidates should roughly equal initial_candidates * 2
    dense_candidates: int = 40  # 40% weight
    sparse_candidates: int = 60  # 60% weight (favors exact term matching for audit docs)

    # OPT-4: Query instruction prefix for better retrieval
    # Note: Evaluation showed this causes regression (-6% MRR) when document embeddings
    # don't use matching prefixes. Disabled by default.
    enable_query_prefix: bool = False
    query_prefix: str = "Retrieve audit finding: "

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
        # Default to Gemini for GCP credit billing
        if self.provider is None:
            provider_str = os.getenv("LLM_PROVIDER", "gemini").lower()
            try:
                self.provider = LLMProvider(provider_str)
            except ValueError:
                self.provider = LLMProvider.GEMINI

        # Load models from environment or use defaults
        if self.claude_model is None:
            self.claude_model = os.getenv(
                "LLM_CLAUDE_MODEL", "claude-sonnet-5"
            )
        if self.openai_model is None:
            self.openai_model = os.getenv("LLM_OPENAI_MODEL", "gpt-4o")
        if self.gemini_model is None:
            self.gemini_model = os.getenv("LLM_GEMINI_MODEL", "gemini-3.8-flash")


@dataclass
class QueryEnhancementConfig:
    """Configuration for query-time intelligence (Phase 1)."""

    # Feature flags
    enabled: bool = True
    enable_query_expansion: bool = True
    enable_passage_reordering: bool = True
    enable_sufficiency_check: bool = True

    # Provider and model (shared single call)
    # Default to Gemini for GCP credit billing
    provider: LLMProvider = LLMProvider.GEMINI
    model: str = "gemini-3.8-flash-lite"  # Gemini model (cost-effective)
    gemini_model: str = "gemini-3.8-flash-lite"  # Gemini model
    max_tokens: int = 300
    temperature: float = 0.0

    # Query expansion
    num_expansions: int = 3  # Total queries including original

    # Sufficiency check
    min_rerank_score: float = 0.25  # Minimum top-1 Cohere score to consider sufficient

    # Passage reordering
    reorder_strategy: str = "best_first_last"  # "best_first_last" or "none"


@dataclass
class GroundednessConfig:
    """Configuration for groundedness verification (Phase 13)."""

    # Feature flags
    enabled: bool = True  # OFF by default; enable per-deployment
    block_on_failure: bool = False  # If True, caveat the answer when verification fails
    regenerate_on_failure: bool = (
        False  # If True, retry generation with stricter prompt when score low
    )

    # Provider selection (independent of main LLM)
    # Default to Gemini for speed + cost + GCP credit billing
    provider: LLMProvider = LLMProvider.GEMINI
    openai_model: str = "gpt-4o-mini"
    claude_model: str = "claude-haiku-4-5-20251001"
    gemini_model: str = "gemini-3.8-flash-lite"  # Updated from deprecated 2.0-flash

    max_tokens: int = 1500
    min_groundedness_score: float = 0.75  # Fraction of claims that must be grounded


@dataclass
class AgenticConfig:
    """Configuration for agentic retrieval (Phase 11)."""

    enabled: bool = True  # OFF by default; exposed via /chat/agentic endpoint

    # Planner (query decomposer) - Gemini for GCP credit billing
    planner_model: str = "gemini-3.8-flash"  # Gemini for GCP billing

    # Loop bounds
    max_sub_queries: int = 4
    max_iterations_per_subquery: int = 3
    max_total_iterations: int = 10
    max_wall_ms: int = 20_000  # 20 seconds
    max_total_tokens: int = 30_000  # Soft budget (not strictly enforced yet)

    # Retrieval per sub-query
    top_k_per_subquery: int = 8


@dataclass
class AutoFilterConfig:
    """Configuration for auto-filter extraction from queries."""

    # Master switch
    enabled: bool = True

    # State detection: require ≥N occurrences OR context cue
    # 1 = match always; 2 = require ≥2 occurrences or context cue
    state_confidence_min_occurrences: int = 1

    # Year inference: detect years and convert to audit_year/report_year filters
    allow_year_inference: bool = True

    # Tier inference: detect union/state/local_body keywords
    allow_tier_inference: bool = True


@dataclass
class EntityGraphConfig:
    """Configuration for the entity graph (Phase 12)."""

    enabled: bool = True  # OFF by default; turn on after canonicalization runs

    # Postgres DSN — required when enabled
    # Example: postgresql+psycopg://cag_user:pass@localhost:5432/cag_entity_graph
    dsn: Optional[str] = os.getenv("ENTITY_GRAPH_DSN")
    if not dsn:
        raise RuntimeError(
            "ENTITY_GRAPH_DSN not set. Required for entity graph operations."
        )

    # Canonicalization model (cross-corpus dedup) - Gemini for GCP billing
    canonicalization_model: str = "gemini-3.8-flash-lite"
    canonicalization_batch_size: int = 80  # entities per LLM call

    # Auto-index on chunk indexing? If True, indexer.py also writes to entity graph
    auto_index_on_ingest: bool = True

    # Comparative integration: use entity graph to narrow report selection?
    enable_comparative_filtering: bool = True

    # Max reports to retrieve from in ask_comparative() after narrowing
    comparative_max_reports: int = 20

    # Two-pass canonicalization (Phase 12+)
    # Only triggers pass 2 if raw record count exceeds this threshold
    two_pass_threshold: int = 1000
    pass2_batch_size: int = 250
    pass2_model: str = "gemini-3.8-flash-lite"  # Gemini for GCP billing

    def __post_init__(self):
        self.dsn = os.getenv("ENTITY_GRAPH_DSN", self.dsn)
        # Allow env override for two_pass_threshold
        env_threshold = os.getenv("ENTITY_GRAPH_TWO_PASS_THRESHOLD")
        if env_threshold:
            self.two_pass_threshold = int(env_threshold)


@dataclass
class ObservabilityConfig:
    """Configuration for query observability (Bridge C).

    Captures every query with full context for debugging, regression detection,
    and cost tracking. Stored in Postgres alongside entity graph.
    """

    # Master switch
    enabled: bool = True

    # Environment: 'dev' or 'prod' — affects what gets logged
    # Read from APP_ENV env var if set
    environment: str = "dev"

    # Dev debug mode: captures full LLM prompts and chunk content
    # Only effective when environment='dev'
    dev_debug: bool = True

    # Sampling rate: 1.0 = log everything, 0.1 = log 10%
    # Errors and low-groundedness queries are always logged regardless
    sampling_rate: float = 1.0

    # Privacy: disable to redact query_text in logs
    log_query_text: bool = True

    # Async writes: fire-and-forget to avoid adding latency
    async_writes: bool = True

    def __post_init__(self):
        # Read environment from APP_ENV if set
        env_value = os.getenv("APP_ENV")
        if env_value:
            self.environment = env_value.lower()
        # In prod, dev_debug should default to False unless explicitly set
        if self.environment == "prod" and os.getenv("OBSERVABILITY_DEV_DEBUG") is None:
            self.dev_debug = False


@dataclass
class HomeConfig:
    """Configuration for home page functionality."""

    enabled: bool = True
    cache_ttl_seconds: int = 3600  # how long stats/featured are cached
    surprise_min_mentions: int = 10
    trending_min_count: int = 3
    trending_window_days: int = 7


# =============================================================================
# SOTA RAG FEATURES CONFIGURATION
# =============================================================================


@dataclass
class HierarchicalConfig:
    """Configuration for RAPTOR/Hierarchical Retrieval (SOTA Feature 1).

    RAPTOR creates a hierarchical tree of summaries:
    - Level 3: Report-level summary (existing in Phase 10a)
    - Level 2: Chapter-level summaries (NEW)
    - Level 1: Section-level summaries (NEW)
    - Level 0: Original chunks
    """

    enabled: bool = True

    # Models for summary generation - Gemini for GCP credit billing
    chapter_model: str = "gemini-3.8-flash-lite"
    section_model: str = "gemini-3.8-flash-lite"

    # Max tokens for summaries
    chapter_max_tokens: int = 500  # 3-5 sentences
    section_max_tokens: int = 200  # 1-2 sentences

    # Retrieval settings
    drill_down_threshold: float = 0.85  # If top result below this, drill down
    default_level: int = 2  # Default to chapter level

    # Collection settings (uses same collection as child chunks)
    index_collection: str = "cag_child_chunks"


@dataclass
class QueryRoutingConfig:
    """Configuration for Query Routing (SOTA Feature 2).

    Routes queries to optimal retrieval strategy:
    - standard_rag: Default hybrid search
    - temporal: Cross-year comparisons
    - entity_graph: Entity-based comparisons
    - filtered: Strong filter signal
    - summary: High-level overview → RAPTOR summaries
    """

    enabled: bool = True

    # Classification model - Gemini for GCP credit billing
    model: str = "gemini-3.8-flash-lite"
    max_tokens: int = 200
    temperature: float = 0.0

    # Routing behavior
    min_confidence: float = 0.7
    fallback_on_low_confidence: bool = True
    fallback_on_error: bool = True


@dataclass
class SelfRAGConfig:
    """Configuration for Self-RAG / Adaptive Retrieval (SOTA Feature 3).

    Decides whether retrieval is needed:
    - SKIP: Answer from parametric knowledge (definitional queries)
    - RETRIEVE: Standard retrieval
    - MULTI_RETRIEVE: Multiple retrieval rounds (agentic)
    """

    enabled: bool = True

    # Use LLM for classification (False = rule-based only)
    use_llm_classifier: bool = False

    # Regex patterns for queries that DON'T need retrieval
    skip_patterns: List[str] = field(default_factory=lambda: [
        r"^what (?:is|are) (?:CAG|FRBM|PMAY|NHAI|FCI|GST|ITC)\??$",
        r"^how (?:does|do) (?:the\s)?(?:CAG|audit) work\??$",
        r"^what does .+ stand for\??$",
        r"^define (?:CAG|FRBM|compliance|audit)\??$",
    ])


@dataclass
class CorrectiveRAGConfig:
    """Configuration for Corrective RAG (SOTA Feature 4).

    Detects and fixes retrieval/generation failures:
    1. Check relevance of retrieved docs
    2. If low relevance: reformulate query and re-retrieve
    3. Validate citations in generated answer
    """

    enabled: bool = True

    # Relevance checking
    min_relevance_score: float = 0.25
    min_relevant_chunks: int = 3

    # Query reformulation - Gemini for GCP credit billing
    max_reformulations: int = 2
    reformulation_model: str = "gemini-3.8-flash-lite"

    # Citation validation
    validate_citations: bool = True
    strip_invalid_citations: bool = True


@dataclass
class SearchConfig:
    """Configuration for search functionality."""

    enabled: bool = True
    limit_per_channel: int = 5
    findings_min_query_length: int = 3
    findings_debounce_ms: int = 300  # advisory; frontend enforces
    fuzzy_match_threshold: int = 60  # rapidfuzz cutoff (0-100)


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
    groundedness: GroundednessConfig = field(default_factory=GroundednessConfig)
    agentic: AgenticConfig = field(default_factory=AgenticConfig)
    entity_graph: EntityGraphConfig = field(default_factory=EntityGraphConfig)
    auto_filter: AutoFilterConfig = field(default_factory=AutoFilterConfig)
    observability: ObservabilityConfig = field(default_factory=ObservabilityConfig)
    home: HomeConfig = field(default_factory=HomeConfig)
    search: SearchConfig = field(default_factory=SearchConfig)

    # SOTA RAG Features
    hierarchical: HierarchicalConfig = field(default_factory=HierarchicalConfig)
    query_routing: QueryRoutingConfig = field(default_factory=QueryRoutingConfig)
    self_rag: SelfRAGConfig = field(default_factory=SelfRAGConfig)
    corrective_rag: CorrectiveRAGConfig = field(default_factory=CorrectiveRAGConfig)

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

        # Check embedding requirements based on Vertex AI settings
        use_vertex_embeddings = os.getenv("USE_VERTEX_EMBEDDINGS", "false").lower() == "true"
        if not use_vertex_embeddings and not self.openai_api_key:
            errors.append("OPENAI_API_KEY not set (required for OpenAI embeddings). Set USE_VERTEX_EMBEDDINGS=true to use Vertex AI instead.")

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

        if self.entity_graph.enabled and not self.entity_graph.dsn:
            errors.append(
                "ENTITY_GRAPH_DSN not set (required when entity_graph.enabled)"
            )

        return errors


# Default configuration instance
default_config = RAGConfig()
