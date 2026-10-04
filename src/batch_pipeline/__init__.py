"""
CAG Gateway - Phase 10: Overview & Summary Generation

Gemini on Vertex AI, run at the end of src.parsing_pipeline.main.

Usage (for reports already processed):
    python -m src.batch_pipeline.submit_jobs
    python -m src.batch_pipeline.check_status
    python -m src.batch_pipeline.process_results
"""

from .batch_service import BatchService

__all__ = ["BatchService"]
