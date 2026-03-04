"""
Service for loading and managing report metadata.

Loads report information from processed JSON files and provides
lookup functions for the API routes.
"""

import json
import logging
import re
from pathlib import Path
from typing import List, Optional, Dict

from ..config import settings
from ..models import ReportSummary, ReportDetail

logger = logging.getLogger(__name__)

# In-memory cache of report metadata
_reports_cache: Dict[str, ReportDetail] = {}
_initialized: bool = False


def _extract_year(report_no: str) -> int:
    """Extract year from report number like 'Report 7 of 2023'."""
    match = re.search(r'20\d{2}', str(report_no))
    if match:
        return int(match.group())
    return 2024  # Default


def _determine_status(semantic: dict) -> str:
    """Determine report status based on semantic data."""
    findings = semantic.get("findings", [])
    if not findings:
        return "Compliant"
    
    high_severity = sum(1 for f in findings if f.get("severity") == "high")
    if high_severity > 5:
        return "Action Pending"
    elif high_severity > 0:
        return "Under Review"
    else:
        return "Partial Compliance"


def _build_executive_summary(metadata: dict, semantic: dict) -> str:
    """Build executive summary from available data."""
    summary = metadata.get("executive_summary", "")
    if summary:
        return summary[:1000]

    # Fallback: construct from findings
    findings = semantic.get("findings", [])
    if findings:
        top_findings = findings[:3]
        summary_parts = [
            f"The audit identified {len(findings)} key findings."
        ]
        for f in top_findings:
            desc = f.get("description", f.get("text", ""))[:200]
            if desc:
                summary_parts.append(desc)
        return " ".join(summary_parts)

    return "Executive summary not available."


def _load_reports():
    """Load all report metadata from processed JSON files."""
    global _reports_cache, _initialized
    
    if _initialized:
        return
    
    _reports_cache = {}
    
    if not settings.PROCESSED_DIR.exists():
        logger.warning(f"Processed directory not found: {settings.PROCESSED_DIR}")
        _initialized = True
        return
    
    # Load each report's detailed JSON
    json_files = list(settings.PROCESSED_DIR.glob("*_chunks.json"))
    
    if not json_files:
        logger.warning(f"No *_chunks.json files found in {settings.PROCESSED_DIR}")
        _initialized = True
        return
    
    for json_file in json_files:
        try:
            with open(json_file, encoding="utf-8") as f:
                data = json.load(f)
            
            metadata = data.get("report_metadata", {})
            semantic = data.get("semantic_enrichment", {})
            
            report_id = metadata.get("report_id", json_file.stem.replace("_chunks", ""))
            
            # Extract key findings (first 10)
            findings_raw = semantic.get("findings", [])
            key_findings = []
            for f in findings_raw[:10]:
                desc = f.get("description", f.get("text", ""))
                if desc:
                    key_findings.append(desc[:500])
            
            # Extract recommendations (first 10)
            recs_raw = semantic.get("recommendations", [])
            recommendations = []
            for r in recs_raw[:10]:
                text = r.get("text", r.get("description", ""))
                if text:
                    recommendations.append(text[:500])
            
            # Calculate monetary impact
            monetary_stats = semantic.get("monetary_statistics", {})
            total_amount = monetary_stats.get("total_amount_crore", 0)
            if isinstance(total_amount, (int, float)) and total_amount > 0:
                monetary_impact = f"₹{total_amount:,.2f} crore"
            else:
                monetary_impact = None
            
            # Build filename
            filename = metadata.get("source_filename", f"{report_id}.pdf")
            if not filename.endswith(".pdf"):
                filename = filename.rsplit(".", 1)[0] + ".pdf"
            
            # Get page count
            pages = metadata.get("page_count", 0)
            if pages == 0:
                processing_stats = data.get("processing_stats", {})
                pages = processing_stats.get("pages_processed", 0)
            
            report = ReportDetail(
                id=report_id,
                title=metadata.get("report_title", "Untitled Report"),
                report_no=metadata.get("report_no", "N/A"),
                ministry=metadata.get("ministry", "Unknown Ministry"),
                sector=metadata.get("sector", metadata.get("department", "General")),
                year=_extract_year(metadata.get("report_no", "")),
                pages=pages,
                filename=filename,
                status=_determine_status(semantic),
                executive_summary=_build_executive_summary(metadata, semantic),
                key_findings=key_findings,
                recommendations=recommendations,
                monetary_impact=monetary_impact,
                findings_count=len(findings_raw),
                report_type=metadata.get("report_type")
            )
            
            _reports_cache[report_id] = report
            logger.info(f"Loaded report: {report_id} - {report.title[:50]}...")
            
        except Exception as e:
            logger.error(f"Error loading {json_file}: {e}", exc_info=True)
    
    _initialized = True
    logger.info(f"Loaded {len(_reports_cache)} reports total")


def initialize():
    """Initialize the report service (load all reports)."""
    _load_reports()


def get_reports_count() -> int:
    """Get total number of loaded reports."""
    _load_reports()
    return len(_reports_cache)


def get_all_reports() -> List[ReportSummary]:
    """Get all reports as summary objects."""
    _load_reports()
    return [
        ReportSummary(
            id=r.id,
            title=r.title,
            report_no=r.report_no,
            ministry=r.ministry,
            sector=r.sector,
            year=r.year,
            findings_count=r.findings_count,
            monetary_impact=r.monetary_impact,
            status=r.status,
            filename=r.filename,
            report_type=r.report_type
        )
        for r in _reports_cache.values()
    ]


def get_report_by_id(report_id: str) -> Optional[ReportDetail]:
    """Get a specific report by ID."""
    _load_reports()
    return _reports_cache.get(report_id)


def get_reports_by_sector(sector: str) -> List[ReportSummary]:
    """Get reports filtered by sector."""
    _load_reports()
    return [
        ReportSummary(
            id=r.id, title=r.title, report_no=r.report_no,
            ministry=r.ministry, sector=r.sector, year=r.year,
            findings_count=r.findings_count, monetary_impact=r.monetary_impact,
            status=r.status, filename=r.filename, report_type=r.report_type
        )
        for r in _reports_cache.values()
        if r.sector.lower() == sector.lower()
    ]


def get_reports_by_year(year: int) -> List[ReportSummary]:
    """Get reports filtered by year."""
    _load_reports()
    return [
        ReportSummary(
            id=r.id, title=r.title, report_no=r.report_no,
            ministry=r.ministry, sector=r.sector, year=r.year,
            findings_count=r.findings_count, monetary_impact=r.monetary_impact,
            status=r.status, filename=r.filename, report_type=r.report_type
        )
        for r in _reports_cache.values()
        if r.year == year
    ]


def get_report_filename(report_id: str) -> Optional[str]:
    """Get PDF filename for a report."""
    _load_reports()
    report = _reports_cache.get(report_id)
    return report.filename if report else None
