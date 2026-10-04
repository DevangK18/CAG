"""Output quality checks run on every report (preflight checks against the source PDF)."""

from src.parsing_pipeline.quality.preflight import (
    THRESHOLDS,
    check_report,
    grade,
    summarize,
)

__all__ = ["THRESHOLDS", "check_report", "grade", "summarize"]
