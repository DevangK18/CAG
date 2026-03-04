"""
API Routes for Report Overview

Endpoints:
- GET /reports/{report_id}/overview - Complete overview
- GET /reports/{report_id}/toc - Table of Contents for PDF navigation
- GET /reports/{report_id}/findings - Filterable findings list
- GET /reports/{report_id}/topics - Topics covered
- GET /reports/{report_id}/glossary - Glossary terms
"""

from fastapi import APIRouter, HTTPException, Query
from pathlib import Path
import json
import re
from typing import Optional
import logging

logger = logging.getLogger(__name__)

router = APIRouter(tags=["overview"])

# Configure data directory - adjust if needed
DATA_DIR = Path("data/processed")
SUMMARIES_DIR = Path("data/batch_jobs/summaries")


def get_overview_path(report_id: str) -> Path:
    """Get path to overview JSON file."""
    return DATA_DIR / f"{report_id}_overview.json"


def load_overview(report_id: str) -> dict:
    """Load overview data for a report."""
    overview_path = get_overview_path(report_id)

    if not overview_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Overview not found for report: {report_id}. Run Phase 10 processing first."
        )

    with open(overview_path) as f:
        return json.load(f)


def extract_context_and_scope(content: str) -> Optional[str]:
    """
    Extract only the "Context & Scope" section content from the executive summary.
    Returns just the paragraph text without any headers.
    """
    if not content:
        return None

    # Pattern to find Context & Scope section start
    # Matches: "## Context & Scope", "## 1. Context & Scope", "1. Context & Scope", "**Context & Scope**"
    context_patterns = [
        r'##\s*(?:\d+\.\s*)?Context\s*(?:&|and)\s*Scope\s*\n+',
        r'\d+\.\s*Context\s*(?:&|and)\s*Scope\s*\n+',
        r'\*\*Context\s*(?:&|and)\s*Scope\*\*\s*\n+',
    ]

    # Pattern to find next section header (ends Context & Scope section)
    next_section_pattern = r'\n(?:##\s+|(?:\d+\.\s+)?(?:\*\*)?(?:Critical|Key|Major|Significant|Important|Recommendations|Findings|Conclusion))'

    context_start = -1
    for pattern in context_patterns:
        match = re.search(pattern, content, re.IGNORECASE)
        if match:
            context_start = match.end()
            break

    if context_start == -1:
        return None

    # Find where the next section starts
    next_section_match = re.search(next_section_pattern, content[context_start:], re.IGNORECASE)
    if next_section_match:
        context_end = context_start + next_section_match.start()
    else:
        context_end = len(content)

    # Extract the content
    context_content = content[context_start:context_end].strip()

    # Clean up any remaining markdown formatting
    # Remove bold markers
    context_content = re.sub(r'\*\*([^*]+)\*\*', r'\1', context_content)
    # Remove italic markers
    context_content = re.sub(r'\*([^*]+)\*', r'\1', context_content)
    # Clean up multiple newlines
    context_content = re.sub(r'\n{3,}', '\n\n', context_content)

    return context_content.strip() if context_content else None


@router.get("/reports/{report_id}/overview")
async def get_overview(report_id: str):
    """
    Get complete overview for a report.

    Returns all overview data including:
    - basic_info: Title, ministry, year, etc.
    - table_of_contents: TOC with page numbers
    - findings_summary: Totals and breakdowns
    - findings_list: All findings with details
    - recommendations: All recommendations
    - audit_scope: Period, coverage, entities (LLM extracted)
    - audit_objectives: List of objectives (LLM extracted)
    - topics_covered: Neutral topic names (LLM extracted)
    - glossary_terms: Abbreviations and definitions (LLM extracted)
    - executive_summary: AI-generated executive brief excerpt (NEW)
    """
    overview_data = load_overview(report_id)

    # Load AI executive summary
    ai_executive_summary = None
    summaries_path = SUMMARIES_DIR / f"{report_id}_summaries.json"

    if summaries_path.exists():
        try:
            with open(summaries_path) as f:
                summaries_data = json.load(f)

            # Get executive variant (best for overview tab)
            executive_variant = summaries_data.get("variants", {}).get("executive", {})
            full_content = executive_variant.get("content", "")

            if full_content:
                # Extract only the Context & Scope section content
                ai_executive_summary = extract_context_and_scope(full_content)
        except Exception as e:
            logger.warning(f"Failed to load AI summary for {report_id}: {e}")

    # Add AI summary to response
    overview_data["executive_summary"] = ai_executive_summary
    overview_data["executive_summary_fallback"] = overview_data.get("executive_summary_index")

    return overview_data


@router.get("/reports/{report_id}/toc")
async def get_toc(report_id: str):
    """
    Get Table of Contents with page numbers for PDF navigation.
    
    Each entry includes:
    - id: Chunk ID for linking
    - title: Section title
    - level: TOC depth level (1, 2, 3)
    - page_start: Physical page number (0-indexed)
    - page_end: Last page of section
    - hierarchy: Full hierarchy path
    """
    overview = load_overview(report_id)
    
    return {
        "report_id": report_id,
        "title": overview.get("basic_info", {}).get("title"),
        "entry_count": len(overview.get("table_of_contents", [])),
        "entries": overview.get("table_of_contents", [])
    }


@router.get("/reports/{report_id}/findings")
async def get_findings(
    report_id: str,
    severity: Optional[str] = Query(None, description="Filter by severity: critical, high, medium, low"),
    finding_type: Optional[str] = Query(None, description="Filter by finding type"),
    min_amount_crore: Optional[float] = Query(None, description="Minimum amount in crores"),
    max_amount_crore: Optional[float] = Query(None, description="Maximum amount in crores"),
    chapter: Optional[str] = Query(None, description="Filter by chapter (partial match)"),
    limit: int = Query(50, ge=1, le=200, description="Maximum findings to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination")
):
    """
    Get findings with optional filters.

    Supports filtering by:
    - severity: critical, high, medium, low
    - finding_type: Type of finding
    - min_amount_crore / max_amount_crore: Amount range
    - chapter: Chapter name (partial match)

    Supports pagination with limit/offset.
    """
    overview = load_overview(report_id)
    findings = overview.get("findings_list", [])

    # Apply filters
    if severity:
        findings = [f for f in findings if f.get("severity", "").lower() == severity.lower()]

    if finding_type:
        findings = [f for f in findings if f.get("type", "").lower() == finding_type.lower()]

    if min_amount_crore is not None:
        findings = [f for f in findings if (f.get("amount_crore") or 0) >= min_amount_crore]

    if max_amount_crore is not None:
        findings = [f for f in findings if (f.get("amount_crore") or 0) <= max_amount_crore]

    if chapter:
        findings = [f for f in findings if chapter.lower() in (f.get("chapter") or "").lower()]

    # Get total before pagination
    total = len(findings)

    # Apply pagination
    findings = findings[offset:offset + limit]

    return {
        "report_id": report_id,
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": (offset + limit) < total,
        "summary": overview.get("findings_summary", {}),
        "findings": findings
    }


@router.get("/reports/{report_id}/topics")
async def get_topics(report_id: str):
    """
    Get topics covered in the report.
    
    Topics are NEUTRAL names describing what was examined,
    with section references and page ranges for navigation.
    
    Example topics:
    - "Tax Assessment Procedures" (not "Assessment Errors")
    - "Revenue Collection Mechanisms" (not "Revenue Loss")
    """
    overview = load_overview(report_id)
    
    topics = overview.get("topics_covered")
    
    if not topics:
        return {
            "report_id": report_id,
            "note": "Topics not yet extracted. Run Phase 10 LLM extraction.",
            "topics": []
        }
    
    return {
        "report_id": report_id,
        "topic_count": len(topics),
        "topics": topics
    }


@router.get("/reports/{report_id}/glossary")
async def get_glossary(
    report_id: str,
    search: Optional[str] = Query(None, description="Search term or abbreviation")
):
    """
    Get glossary terms for the report.
    
    Includes abbreviations and technical terms extracted from the report.
    
    Optional search parameter filters by term or abbreviation.
    """
    overview = load_overview(report_id)
    
    terms = overview.get("glossary_terms") or []
    
    # Apply search filter if provided
    if search:
        search_lower = search.lower()
        terms = [
            t for t in terms
            if search_lower in (t.get("term") or "").lower()
            or search_lower in (t.get("abbreviation") or "").lower()
        ]
    
    return {
        "report_id": report_id,
        "term_count": len(terms),
        "terms": terms
    }


@router.get("/reports/{report_id}/audit-scope")
async def get_audit_scope(report_id: str):
    """
    Get audit scope details.
    
    Returns:
    - period: Start/end dates and description
    - geographic_coverage: Regions/states covered
    - sample_size: Number of cases examined
    - entities_covered: Organizations audited
    """
    overview = load_overview(report_id)
    
    scope = overview.get("audit_scope")
    
    if not scope:
        return {
            "report_id": report_id,
            "note": "Audit scope not yet extracted. Run Phase 10 LLM extraction.",
            "scope": None
        }
    
    return {
        "report_id": report_id,
        "scope": scope
    }


@router.get("/reports/{report_id}/objectives")
async def get_objectives(report_id: str):
    """
    Get audit objectives.
    
    Returns list of objectives as stated in the report.
    """
    overview = load_overview(report_id)
    
    objectives = overview.get("audit_objectives")
    
    if not objectives:
        return {
            "report_id": report_id,
            "note": "Objectives not yet extracted. Run Phase 10 LLM extraction.",
            "objectives": []
        }
    
    return {
        "report_id": report_id,
        "objective_count": len(objectives),
        "objectives": objectives
    }


@router.get("/reports/{report_id}/recommendations")
async def get_recommendations(
    report_id: str,
    chapter: Optional[str] = Query(None, description="Filter by chapter"),
    limit: int = Query(50, ge=1, le=200)
):
    """
    Get recommendations from the report.
    """
    overview = load_overview(report_id)

    recs = overview.get("recommendations", [])

    if chapter:
        recs = [r for r in recs if chapter.lower() in (r.get("chapter") or "").lower()]

    return {
        "report_id": report_id,
        "total": len(recs),
        "recommendations": recs[:limit]
    }
