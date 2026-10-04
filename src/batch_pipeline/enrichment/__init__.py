"""
Phase 10b/10c visual enrichment.

- GeminiVisualExtractor: chart and table extraction via Gemini on Vertex AI
- visual_post_processor: hydrates extracted visuals back into the chunks

Billing: GCP project (Agent Platform) via src.core.gemini_client.
"""

from .gemini_visual_extractor import GeminiVisualExtractor

__all__ = ["GeminiVisualExtractor"]
