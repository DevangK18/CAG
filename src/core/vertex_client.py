"""
Vertex AI Client Wrappers for Google Cloud Platform
====================================================

Provides drop-in replacements for direct API clients (Anthropic, OpenAI)
that route through Vertex AI Model Garden, enabling:
- Single billing through GCP
- Use of GCP credits ($300 trial)
- Same API patterns as direct SDKs

Usage:
    Set USE_VERTEX_AI=true to enable Vertex AI routing.

    # For Claude (Anthropic) models:
    from src.core.vertex_client import get_anthropic_client, get_async_anthropic_client

    # For embeddings:
    from src.core.vertex_client import get_vertex_embeddings

Environment Variables:
    USE_VERTEX_AI: Set to "true" to use Vertex AI instead of direct APIs
    USE_VERTEX_EMBEDDINGS: Set to "true" to use Vertex AI for embeddings
    GOOGLE_CLOUD_PROJECT: Your GCP project ID
    VERTEX_AI_REGION: Region for Vertex AI (default: us-central1)
"""

import os
import logging
from typing import Optional, List

logger = logging.getLogger(__name__)

# Feature flags
USE_VERTEX_AI = os.getenv("USE_VERTEX_AI", "false").lower() == "true"
USE_VERTEX_EMBEDDINGS = os.getenv("USE_VERTEX_EMBEDDINGS", "false").lower() == "true"

# GCP configuration
GOOGLE_CLOUD_PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT", "")
VERTEX_AI_REGION = os.getenv("VERTEX_AI_REGION", "us-central1")

# Model mapping: Direct API model names -> Vertex AI model names
# Vertex AI uses simpler naming without date suffixes
CLAUDE_MODEL_MAP = {
    # Sonnet models (API name -> Vertex AI name)
    "claude-sonnet-4-5-20250514": "claude-sonnet-4-5",
    "claude-3-5-sonnet-20241022": "claude-sonnet-4-5",
    "claude-3-5-sonnet-latest": "claude-sonnet-4-5",
    # Haiku models
    "claude-haiku-4-5-20251001": "claude-haiku-4-5",
    "claude-3-5-haiku-20241022": "claude-3-5-haiku",
    "claude-3-5-haiku-latest": "claude-3-5-haiku",
    # Opus models
    "claude-opus-4-5-20250514": "claude-opus-4-5",
    # These are already correct format for Vertex AI
    "claude-sonnet-5": "claude-sonnet-5",
    "claude-sonnet-4-5": "claude-sonnet-4-5",
    "claude-sonnet-4": "claude-sonnet-4",
    "claude-opus-5": "claude-opus-5",
    "claude-opus-4-5": "claude-opus-4-5",
    "claude-opus-4": "claude-opus-4",
    "claude-haiku-4-5": "claude-haiku-4-5",
}


def get_vertex_model_name(model: str) -> str:
    """Map direct API model name to Vertex AI model name."""
    return CLAUDE_MODEL_MAP.get(model, model)


def is_vertex_ai_enabled() -> bool:
    """Check if Vertex AI is enabled."""
    return USE_VERTEX_AI


def is_vertex_embeddings_enabled() -> bool:
    """Check if Vertex AI embeddings are enabled."""
    return USE_VERTEX_EMBEDDINGS


# =============================================================================
# ANTHROPIC CLAUDE ON VERTEX AI
# =============================================================================


def get_anthropic_client():
    """
    Get an Anthropic client - either direct or via Vertex AI.

    Returns:
        AnthropicVertex client if USE_VERTEX_AI=true, else Anthropic client
    """
    if USE_VERTEX_AI:
        try:
            from anthropic import AnthropicVertex

            if not GOOGLE_CLOUD_PROJECT:
                raise ValueError(
                    "GOOGLE_CLOUD_PROJECT must be set when USE_VERTEX_AI=true"
                )

            logger.info(
                f"Using Vertex AI Claude (project: {GOOGLE_CLOUD_PROJECT}, region: {VERTEX_AI_REGION})"
            )
            return AnthropicVertex(
                project_id=GOOGLE_CLOUD_PROJECT,
                region=VERTEX_AI_REGION,
            )
        except ImportError:
            raise ImportError(
                "anthropic[vertex] package required. Install with: pip install 'anthropic[vertex]'"
            )
    else:
        from anthropic import Anthropic

        return Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


def get_async_anthropic_client():
    """
    Get an async Anthropic client - either direct or via Vertex AI.

    Returns:
        AsyncAnthropicVertex client if USE_VERTEX_AI=true, else AsyncAnthropic client
    """
    if USE_VERTEX_AI:
        try:
            from anthropic import AsyncAnthropicVertex

            if not GOOGLE_CLOUD_PROJECT:
                raise ValueError(
                    "GOOGLE_CLOUD_PROJECT must be set when USE_VERTEX_AI=true"
                )

            logger.info(
                f"Using Async Vertex AI Claude (project: {GOOGLE_CLOUD_PROJECT}, region: {VERTEX_AI_REGION})"
            )
            return AsyncAnthropicVertex(
                project_id=GOOGLE_CLOUD_PROJECT,
                region=VERTEX_AI_REGION,
            )
        except ImportError:
            raise ImportError(
                "anthropic[vertex] package required. Install with: pip install 'anthropic[vertex]'"
            )
    else:
        from anthropic import AsyncAnthropic

        return AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


# =============================================================================
# VERTEX AI EMBEDDINGS
# =============================================================================


class VertexEmbeddingService:
    """
    Embedding service using Vertex AI text-embedding-005.

    Cost: $0.00625 per 1M tokens (vs OpenAI's $0.13/1M for text-embedding-3-large)
    Dimensions: 768 (configurable down to 256)

    Note: This is a drop-in replacement for OpenAI embeddings but uses
    Google's embedding model through Vertex AI.
    """

    def __init__(
        self,
        model: str = "text-embedding-005",
        dimensions: int = 768,
        project_id: Optional[str] = None,
        location: str = "us-central1",
    ):
        self.model = model
        self.dimensions = dimensions
        self.project_id = project_id or GOOGLE_CLOUD_PROJECT
        self.location = location
        self.total_tokens = 0
        self._initialized = False

        if not self.project_id:
            raise ValueError(
                "GOOGLE_CLOUD_PROJECT must be set for Vertex AI embeddings"
            )

    def _ensure_initialized(self):
        """Lazy initialization of Vertex AI."""
        if not self._initialized:
            try:
                import vertexai

                vertexai.init(project=self.project_id, location=self.location)
                self._initialized = True
                logger.info(f"Vertex AI initialized (project: {self.project_id})")
            except ImportError:
                raise ImportError(
                    "google-cloud-aiplatform required. Install with: pip install google-cloud-aiplatform"
                )

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """
        Generate embeddings for a list of texts.

        Args:
            texts: List of texts to embed

        Returns:
            List of embedding vectors
        """
        if not texts:
            return []

        self._ensure_initialized()

        from vertexai.language_models import TextEmbeddingModel

        model = TextEmbeddingModel.from_pretrained(self.model)

        # text-embedding-005 supports batching
        embeddings = model.get_embeddings(texts)

        # Track approximate token count (rough estimate: 1 token per 4 chars)
        for text in texts:
            self.total_tokens += len(text) // 4

        return [e.values for e in embeddings]

    def embed_single(self, text: str) -> List[float]:
        """Embed a single text."""
        return self.embed_texts([text])[0]

    def embed_batch(
        self,
        texts: List[str],
        batch_size: int = 250,
        show_progress: bool = True,
    ) -> List[List[float]]:
        """
        Embed texts in batches.

        Args:
            texts: List of texts to embed
            batch_size: Number of texts per batch (max 250 for Vertex AI)
            show_progress: Whether to show progress bar

        Returns:
            List of embedding vectors
        """
        if not texts:
            return []

        from tqdm import tqdm

        all_embeddings = []
        batches = [texts[i : i + batch_size] for i in range(0, len(texts), batch_size)]

        iterator = (
            tqdm(batches, desc="Embedding (Vertex AI)") if show_progress else batches
        )

        for batch in iterator:
            embeddings = self.embed_texts(batch)
            all_embeddings.extend(embeddings)

        return all_embeddings

    def get_cost_estimate(self) -> float:
        """
        Get estimated cost in USD.

        text-embedding-005: $0.00625 per 1M tokens
        """
        return (self.total_tokens / 1_000_000) * 0.00625


def get_embedding_service(config=None):
    """
    Get the appropriate embedding service based on configuration.

    Args:
        config: Optional EmbeddingConfig

    Returns:
        VertexEmbeddingService if USE_VERTEX_EMBEDDINGS=true, else None
        (caller should fall back to OpenAI DenseEmbeddingService)
    """
    if USE_VERTEX_EMBEDDINGS:
        dimensions = 768
        if config and hasattr(config, "dimensions"):
            # Vertex AI max is 768, adjust if needed
            dimensions = min(config.dimensions, 768)

        return VertexEmbeddingService(
            model="text-embedding-005",
            dimensions=dimensions,
        )

    return None


# =============================================================================
# GEMINI ON VERTEX AI (Native)
# =============================================================================


def get_vertex_gemini_client():
    """
    Get a Gemini client through Vertex AI.

    This is the native way to use Gemini on GCP (uses GCP credits).
    """
    try:
        import vertexai
        from vertexai.generative_models import GenerativeModel

        if not GOOGLE_CLOUD_PROJECT:
            raise ValueError("GOOGLE_CLOUD_PROJECT must be set for Vertex AI Gemini")

        vertexai.init(project=GOOGLE_CLOUD_PROJECT, location=VERTEX_AI_REGION)

        return GenerativeModel
    except ImportError:
        raise ImportError(
            "google-cloud-aiplatform required. Install with: pip install google-cloud-aiplatform"
        )


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================


def log_vertex_status():
    """Log current Vertex AI configuration status."""
    logger.info("=== Vertex AI Configuration ===")
    logger.info(f"USE_VERTEX_AI: {USE_VERTEX_AI}")
    logger.info(f"USE_VERTEX_EMBEDDINGS: {USE_VERTEX_EMBEDDINGS}")
    logger.info(f"GOOGLE_CLOUD_PROJECT: {GOOGLE_CLOUD_PROJECT or '(not set)'}")
    logger.info(f"VERTEX_AI_REGION: {VERTEX_AI_REGION}")
    logger.info("==============================")
