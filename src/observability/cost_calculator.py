"""
LLM cost calculator for query observability.

Pricing table maps (provider, model) to per-million token rates.
Update quarterly as providers change pricing.

Note: Cohere rerank costs are tracked separately ($1 per 1k searches).
"""

from typing import Optional, Tuple
import logging

logger = logging.getLogger(__name__)

# Pricing per million tokens (as of Q3 2026)
# Format: (provider, model) -> {"prompt": rate, "completion": rate}
PRICING: dict[Tuple[str, str], dict[str, float]] = {
    # OpenAI
    ("openai", "gpt-4o"): {"prompt": 2.50, "completion": 10.00},
    ("openai", "gpt-4o-mini"): {"prompt": 0.15, "completion": 0.60},
    ("openai", "gpt-4-turbo"): {"prompt": 10.00, "completion": 30.00},
    ("openai", "gpt-4"): {"prompt": 30.00, "completion": 60.00},
    ("openai", "gpt-3.5-turbo"): {"prompt": 0.50, "completion": 1.50},
    # Anthropic Claude
    ("anthropic", "claude-opus-4-20250514"): {"prompt": 15.00, "completion": 75.00},
    ("anthropic", "claude-sonnet-4-20250514"): {"prompt": 3.00, "completion": 15.00},
    ("anthropic", "claude-3-5-sonnet-20241022"): {"prompt": 3.00, "completion": 15.00},
    ("anthropic", "claude-haiku-4-5-20251001"): {"prompt": 1.00, "completion": 5.00},
    ("anthropic", "claude-3-5-haiku-20241022"): {"prompt": 1.00, "completion": 5.00},
    # Google Gemini - Latest models (GCP credit billing)
    ("google", "gemini-3.6-flash"): {"prompt": 1.50, "completion": 7.50},
    ("google", "gemini-3.5-flash"): {"prompt": 0.50, "completion": 3.00},
    ("google", "gemini-3.5-flash-lite"): {"prompt": 0.30, "completion": 2.50},
    ("google", "gemini-3.1-pro-preview"): {"prompt": 2.00, "completion": 12.00},
    # Google Gemini - Legacy models
    ("google", "gemini-2.5-pro"): {"prompt": 1.25, "completion": 10.00},
    ("google", "gemini-2.5-flash"): {"prompt": 0.075, "completion": 0.30},
    ("google", "gemini-2.0-flash"): {"prompt": 0.10, "completion": 0.40},  # Deprecated June 2026
    ("google", "gemini-1.5-pro"): {"prompt": 1.25, "completion": 5.00},
    ("google", "gemini-1.5-flash"): {"prompt": 0.075, "completion": 0.30},
    # Cohere (for reranking cost tracking - per 1k searches, not tokens)
    # Note: Rerank costs are calculated differently; this is a placeholder
    ("cohere", "rerank-english-v3.0"): {"prompt": 0.00, "completion": 0.00},
}

# Embedding costs (per million tokens)
EMBEDDING_PRICING: dict[Tuple[str, str], float] = {
    # OpenAI embeddings
    ("openai", "text-embedding-3-large"): 0.13,
    ("openai", "text-embedding-3-small"): 0.02,
    ("openai", "text-embedding-ada-002"): 0.10,
    # Vertex AI embeddings (GCP credit billing - 20x cheaper)
    ("google", "text-embedding-005"): 0.00625,
    ("google", "text-embedding-004"): 0.00625,
}

# Cohere rerank cost: $1 per 1000 searches
COHERE_RERANK_COST_PER_SEARCH = 0.001  # $0.001 per search


def calculate_cost(
    provider: Optional[str],
    model: Optional[str],
    prompt_tokens: Optional[int],
    completion_tokens: Optional[int],
) -> float:
    """
    Calculate estimated cost in USD for an LLM call.

    Args:
        provider: LLM provider name (openai, anthropic, google)
        model: Model identifier
        prompt_tokens: Number of input tokens
        completion_tokens: Number of output tokens

    Returns:
        Estimated cost in USD. Returns 0.0 if pricing not found or inputs invalid.
    """
    if not provider or not model:
        return 0.0

    prompt_tokens = prompt_tokens or 0
    completion_tokens = completion_tokens or 0

    # Normalize provider name
    provider_lower = provider.lower()
    if "claude" in provider_lower or "anthropic" in provider_lower:
        provider_lower = "anthropic"
    elif "gemini" in provider_lower or "google" in provider_lower:
        provider_lower = "google"
    elif "gpt" in provider_lower or "openai" in provider_lower:
        provider_lower = "openai"

    # Look up rates
    rates = PRICING.get((provider_lower, model))

    if not rates:
        # Try partial model match (e.g., "gpt-4o-mini-2024-07-18" -> "gpt-4o-mini")
        for (p, m), r in PRICING.items():
            if p == provider_lower and model.startswith(m):
                rates = r
                break

    if not rates:
        logger.debug(f"No pricing found for ({provider_lower}, {model})")
        return 0.0

    cost = (
        prompt_tokens * rates["prompt"] / 1_000_000
        + completion_tokens * rates["completion"] / 1_000_000
    )

    return round(cost, 6)


def calculate_embedding_cost(
    provider: str,
    model: str,
    total_tokens: int,
) -> float:
    """
    Calculate estimated cost for embedding generation.

    Args:
        provider: Embedding provider (usually openai)
        model: Model identifier
        total_tokens: Total tokens embedded

    Returns:
        Estimated cost in USD.
    """
    rate = EMBEDDING_PRICING.get((provider.lower(), model))
    if not rate:
        return 0.0

    return round(total_tokens * rate / 1_000_000, 6)


def calculate_rerank_cost(num_searches: int) -> float:
    """
    Calculate Cohere rerank cost.

    Args:
        num_searches: Number of rerank searches performed

    Returns:
        Estimated cost in USD.
    """
    return round(num_searches * COHERE_RERANK_COST_PER_SEARCH, 6)
