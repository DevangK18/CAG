"""
ValidationService: per-report output quality checks.

Runs the preflight checks (src/parsing_pipeline/quality) against the source PDF.
They replace the old "RAG readiness" score, which graded every report >= 84 and
stale, broken output "WORLD-CLASS" (C-8-10).
"""

import logging
import time
from pathlib import Path
from typing import Any, Dict, Optional, Union

from src.parsing_pipeline.quality import check_report

logger = logging.getLogger(__name__)


def run_quality_checks(report_data: Dict[str, Any], pdf_path: Optional[Union[str, Path]]) -> Dict[str, Any]:
    """Run the preflight checks on one report. Never raises: failures return {"error": ...}."""
    start = time.monotonic()
    try:
        if not pdf_path or not Path(pdf_path).is_file():
            return {"error": f"source PDF not found: {pdf_path}"}
        result = check_report(report_data, pdf_path)
    except Exception as e:
        # A quality check must never fail the report it is checking
        logger.warning("Quality checks failed for %s: %s", pdf_path, e)
        return {"error": f"{type(e).__name__}: {e}"}
    result["elapsed_s"] = round(time.monotonic() - start, 2)
    return result


class ValidationService:
    """Thin wrapper kept for main.py's existing import."""

    def validate_report(
        self,
        report_data: Dict[str, Any],
        enrichment_data: Optional[Dict] = None,  # unused; kept for the existing call
        pdf_path: Optional[Union[str, Path]] = None,
    ) -> Dict[str, Any]:
        return run_quality_checks(report_data, pdf_path)
