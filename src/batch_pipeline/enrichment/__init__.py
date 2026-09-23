"""
P2-1 LLM-Augmented Enrichment Package.

This package provides intelligent LLM-powered enrichment for CAG audit reports,
building on Phase 1's algorithmic foundation.

Architecture:
- EnrichmentRouter: Decides which chunks need LLM processing
- GeminiVisualExtractor: Visual extraction via Gemini/Vertex AI
- EnrichmentService: Main orchestrator coordinating enrichment

Default: Uses Gemini via Vertex AI for GCP credit billing.
Billing: GCP project (Agent Platform) via src.core.gemini_client.
"""

from .enrichment_router import EnrichmentRouter, EnrichmentTask, RoutingDecision
from .enrichment_service import EnrichmentService
from .gemini_visual_extractor import GeminiVisualExtractor

# Optional: OpenAI batch service (only if openai package installed)
try:
    from .openai_batch import OpenAIBatchService
except ImportError:
    OpenAIBatchService = None  # type: ignore

__all__ = [
    "EnrichmentRouter",
    "EnrichmentTask",
    "RoutingDecision",
    "EnrichmentService",
    "GeminiVisualExtractor",
    "OpenAIBatchService",
]
