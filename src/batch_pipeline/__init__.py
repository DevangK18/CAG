"""
CAG Gateway - Phase 10: Overview & Summary Generation

Batch processing pipeline using Claude Batch API with Extended Thinking.

Usage:
    # Submit batch jobs for existing reports
    python -m services.batch_pipeline.submit_jobs
    
    # Check status (use --watch for continuous monitoring)
    python -m services.batch_pipeline.check_status
    
    # Process results when batches complete
    python -m services.batch_pipeline.process_results

For new reports processed through the full pipeline, Phase 10 is 
automatically triggered at the end of main.py.
"""

from .batch_service import BatchService
from .phase10_service import Phase10Service

__all__ = ["BatchService", "Phase10Service"]
