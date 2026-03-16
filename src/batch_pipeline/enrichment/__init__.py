"""
P2-1 LLM-Augmented Enrichment Package.

This package provides intelligent LLM-powered enrichment for CAG audit reports,
building on Phase 1's algorithmic foundation.

Architecture:
- EnrichmentRouter: Decides which chunks need LLM processing
- OpenAIBatchService: High-volume extraction (GPT-4o-mini, 50% discount)
- EnrichmentService: Main orchestrator coordinating dual-provider batches

Cost Model:
- Finding extraction: ~$0.02-0.10/report (OpenAI)
- Complex analysis: ~$0.10-0.30/report (Anthropic)
- Total: ~$0.35-1.00/report
"""

from .enrichment_router import EnrichmentRouter, EnrichmentTask, RoutingDecision
from .openai_batch import OpenAIBatchService
from .enrichment_service import EnrichmentService

__all__ = [
    "EnrichmentRouter",
    "EnrichmentTask",
    "RoutingDecision",
    "OpenAIBatchService",
    "EnrichmentService",
]
