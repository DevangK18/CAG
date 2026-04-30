"""
Service for loading and managing report metadata.

Loads report information from processed JSON files and provides
lookup functions for the API routes.
"""

import json
import logging
import re
import time
from pathlib import Path
from typing import List, Optional, Dict

from ..config import settings
from ..models import ReportSummary, ReportDetail

logger = logging.getLogger(__name__)

# In-memory cache of report metadata
_reports_cache: Dict[str, ReportDetail] = {}
_initialized: bool = False

# Ministry canonicalization bridge (Phase A.5)
# Maps ReportInfo.ministry string → entity_id from entity graph
_ministry_bridge: Dict[str, int] = {}
_ministry_bridge_loaded: bool = False

# Phase B: Pre-computed indexes for home page (§5.1)
_ministry_index: Dict[str, List[str]] = {}  # ministry → [report_ids]
_year_index: Dict[int, List[str]] = {}  # report_year → [report_ids]
_audit_year_index: Dict[str, List[str]] = {}  # audit_year → [report_ids]
_state_index: Dict[str, List[str]] = {}  # state_name → [report_ids]
_audit_category_index: Dict[str, List[str]] = {}  # audit_category → [report_ids]
_tier_index: Dict[str, List[str]] = {}  # government_body_type → [report_ids]
_recent_reports: List[ReportSummary] = []  # top 20 by year DESC

# Phase E: Pre-computed top entities for facets (§15)
# Prevents per-request DB query in get_home_facets()
_top_entities_facets: List[Dict[str, any]] = []  # top 50 non-ministry entities

# Phase B: Glossary index (§5.2)
_glossary_index: Dict[str, List[Dict[str, str]]] = {}  # term_lower → [entries]
_glossary_loaded: bool = False

# Phase D: Trending searches cache (§9.4)
_trending_searches_cache: List[Dict[str, any]] = []
_trending_searches_cache_time: float = 0.0
_trending_searches_cache_ttl: int = 3600  # 1 hour in seconds

# Phase E: Home stats cache (§15, §18.1)
# Prevents repeated expensive Qdrant count queries on every request
_home_stats_cache: Optional[any] = None
_home_stats_cache_time: float = 0.0
_home_stats_cache_ttl: int = 3600  # 1 hour in seconds


def normalize_report_no(report_no: Optional[str]) -> Optional[str]:
    """
    Normalize report_no to clean 'X of YYYY' format.

    Handles:
    - Already clean: "16 of 2020" → "16 of 2020"
    - Underscore num_year: "02_2024" → "2 of 2024"
    - Underscore year_num: "2017_10" → "10 of 2017"
    - "Unknown" or empty → None
    - None → None

    Returns:
        Normalized report number string, or None if not available
    """
    if report_no is None:
        return None

    val = str(report_no).strip()

    # Handle "Unknown" or empty
    if not val or val.lower() == "unknown" or val == "N/A":
        return None

    # Already in clean format "X of YYYY"
    if re.match(r"^\d+\s+of\s+\d{4}$", val, re.IGNORECASE):
        return val

    # Handle underscore formats
    if "_" in val:
        parts = val.split("_")
        if len(parts) == 2:
            first, second = parts
            # year_num format: "2017_10"
            if first.isdigit() and len(first) == 4:
                return f"{int(second)} of {first}"
            # num_year format: "02_2024"
            elif second.isdigit() and len(second) == 4:
                return f"{int(first)} of {second}"

    # Handle slash formats: "2025/15" or "15/2025"
    if "/" in val:
        parts = val.split("/")
        if len(parts) == 2:
            first, second = parts
            if first.isdigit() and len(first) == 4:
                return f"{int(second)} of {first}"
            elif second.isdigit() and len(second) == 4:
                return f"{int(first)} of {second}"

    # Return as-is if we can't parse it
    return val


def normalize_organization(value: Optional[str]) -> Optional[str]:
    """
    Normalize ministry/department values.

    Returns None for placeholder values like "Unknown", "Unknown Ministry", "N/A".

    Args:
        value: Raw ministry or department string

    Returns:
        Cleaned string, or None if placeholder/empty
    """
    if value is None:
        return None

    val = str(value).strip()

    # Handle placeholder values
    if not val:
        return None

    lower = val.lower()
    if lower in ('unknown', 'unknown ministry', 'n/a', '-', 'none'):
        return None

    return val


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
    
    # Load each report's detailed JSON (recursively search subdirectories)
    json_files = list(settings.PROCESSED_DIR.glob("**/*_chunks.json"))

    if not json_files:
        logger.warning(f"No *_chunks.json files found in {settings.PROCESSED_DIR} or subdirectories")
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

            # Build filename with subfolder prefix for nested directory structure
            # e.g., if file is in data/processed/union/, PDF will be in data/raw/union/
            base_filename = metadata.get("source_filename", f"{report_id}.pdf")
            if not base_filename.endswith(".pdf"):
                base_filename = base_filename.rsplit(".", 1)[0] + ".pdf"

            # Get relative path from PROCESSED_DIR to include subfolder
            relative_dir = json_file.parent.relative_to(settings.PROCESSED_DIR)
            if str(relative_dir) != ".":
                filename = f"{relative_dir}/{base_filename}"
            else:
                filename = base_filename
            
            # Get page count
            pages = metadata.get("page_count", 0)
            if pages == 0:
                processing_stats = data.get("processing_stats", {})
                pages = processing_stats.get("pages_processed", 0)
            
            # Normalize report_no to clean format
            raw_report_no = metadata.get("report_no")
            normalized_report_no = normalize_report_no(raw_report_no)

            # Normalize ministry and department (strip "Unknown" placeholders)
            normalized_ministry = normalize_organization(metadata.get("ministry"))
            normalized_department = normalize_organization(metadata.get("department"))

            report = ReportDetail(
                id=report_id,
                title=metadata.get("report_title", "Untitled Report"),
                report_no=normalized_report_no or "N/A",
                ministry=normalized_ministry or "Unknown Ministry",
                sector=metadata.get("sector", metadata.get("department", "General")),
                year=_extract_year(normalized_report_no or metadata.get("report_no", "")),
                pages=pages,
                filename=filename,
                status=_determine_status(semantic),
                executive_summary=_build_executive_summary(metadata, semantic),
                key_findings=key_findings,
                recommendations=recommendations,
                monetary_impact=monetary_impact,
                findings_count=len(findings_raw),
                report_type=metadata.get("report_type"),
                government_body_type=metadata.get("government_body_type", "union"),
                state_name=metadata.get("state_name"),
                department=normalized_department,
                audit_category=metadata.get("audit_category", "compliance")
            )
            
            _reports_cache[report_id] = report
            logger.info(f"Loaded report: {report_id} - {report.title[:50]}...")

        except Exception as e:
            logger.error(f"Error loading {json_file}: {e}", exc_info=True)

    # Build pre-computed indexes (Phase B)
    _build_indexes()

    _initialized = True
    logger.info(f"Loaded {len(_reports_cache)} reports total")


def initialize():
    """Initialize the report service (load all reports)."""
    _load_reports()
    load_ministry_bridge()  # Phase A.5: load ministry canonicalization bridge
    build_glossary_index()  # Phase B: build glossary index


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
            report_type=r.report_type,
            government_body_type=r.government_body_type,
            state_name=r.state_name,
            department=r.department,
            audit_category=r.audit_category
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
            status=r.status, filename=r.filename, report_type=r.report_type,
            government_body_type=r.government_body_type, state_name=r.state_name,
            department=r.department, audit_category=r.audit_category
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
            status=r.status, filename=r.filename, report_type=r.report_type,
            government_body_type=r.government_body_type, state_name=r.state_name,
            department=r.department, audit_category=r.audit_category
        )
        for r in _reports_cache.values()
        if r.year == year
    ]


def get_report_filename(report_id: str) -> Optional[str]:
    """Get PDF filename for a report."""
    _load_reports()
    report = _reports_cache.get(report_id)
    return report.filename if report else None


def _build_indexes():
    """
    Build pre-computed indexes from loaded reports (Phase B).

    Called once at the end of _load_reports().
    Phase E: Also pre-computes top entities for facets (§15).
    """
    global _ministry_index, _year_index, _audit_year_index, _state_index
    global _audit_category_index, _tier_index, _recent_reports, _top_entities_facets

    _ministry_index = {}
    _year_index = {}
    _audit_year_index = {}
    _state_index = {}
    _audit_category_index = {}
    _tier_index = {}

    for report_id, report in _reports_cache.items():
        # Ministry index (skip "Unknown Ministry")
        if report.ministry and report.ministry != "Unknown Ministry":
            _ministry_index.setdefault(report.ministry, []).append(report_id)

        # Year index
        _year_index.setdefault(report.year, []).append(report_id)

        # Audit year index (extract from report_no if available)
        audit_year = _extract_audit_year(report.report_no)
        if audit_year:
            _audit_year_index.setdefault(audit_year, []).append(report_id)

        # State index
        if report.state_name:
            _state_index.setdefault(report.state_name, []).append(report_id)

        # Audit category index
        _audit_category_index.setdefault(report.audit_category, []).append(report_id)

        # Tier index
        _tier_index.setdefault(report.government_body_type, []).append(report_id)

    # Build recent reports list (top 20 by year DESC, then by ingested_at if available)
    all_summaries = [
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
            report_type=r.report_type,
            government_body_type=r.government_body_type,
            state_name=r.state_name,
            department=r.department,
            audit_category=r.audit_category,
            ingested_at=r.ingested_at,
        )
        for r in _reports_cache.values()
    ]

    # Sort by year DESC (recent first), then by ingested_at if available
    _recent_reports = sorted(
        all_summaries,
        key=lambda r: (r.year, r.ingested_at or ""),
        reverse=True,
    )[:20]

    # Phase E: Pre-compute top entities for facets (avoids per-request DB query)
    _top_entities_facets = []
    try:
        from src.entity_graph.entity_service import get_entity_service
        from src.entity_graph.db import session_scope
        from src.entity_graph.models import Entity

        entity_service = get_entity_service()
        if entity_service:
            with session_scope() as session:
                top_entities = (
                    session.query(Entity)
                    .filter(Entity.entity_type != "ministry")
                    .order_by(Entity.mention_count.desc())
                    .limit(50)
                    .all()
                )

                for ent in top_entities:
                    _top_entities_facets.append({
                        'id': ent.id,
                        'canonical_name': ent.canonical_name,
                        'mention_count': ent.mention_count,
                    })
    except Exception as e:
        logger.warning(f"Could not pre-compute top entities facets: {e}")

    logger.info(
        f"Built indexes: {len(_ministry_index)} ministries, "
        f"{len(_year_index)} years, {len(_state_index)} states, "
        f"{len(_audit_category_index)} categories, "
        f"{len(_top_entities_facets)} top entities"
    )


def _extract_audit_year(report_no: str) -> Optional[str]:
    """
    Extract audit year from report_no like '16 of 2020' → '2020'.

    Returns:
        Year string or None
    """
    if not report_no:
        return None

    # Extract 4-digit year
    match = re.search(r"20\d{2}", report_no)
    if match:
        return match.group()

    return None


def load_ministry_bridge():
    """
    Load ministry canonicalization bridge from data/canonical/ministry_bridge.json.

    This bridge maps ReportInfo.ministry strings to entity_id values from the
    Phase 12 entity graph. Called once at startup.

    Returns gracefully (with warning) if bridge file doesn't exist yet.
    """
    global _ministry_bridge, _ministry_bridge_loaded

    if _ministry_bridge_loaded:
        return

    bridge_path = Path("data/canonical/ministry_bridge.json")

    if not bridge_path.exists():
        logger.warning(
            f"Ministry bridge not found at {bridge_path}. "
            "Run scripts/generate_ministry_bridge.py to create it. "
            "Ministry-related features will work with degraded functionality."
        )
        _ministry_bridge_loaded = True
        return

    try:
        with open(bridge_path, encoding="utf-8") as f:
            data = json.load(f)

        # Extract mappings from the JSON structure
        mappings = data.get("mappings", {})

        # Convert to simple ministry_string -> entity_id dict
        _ministry_bridge = {
            ministry: mapping["entity_id"]
            for ministry, mapping in mappings.items()
            if isinstance(mapping, dict) and "entity_id" in mapping
        }

        logger.info(f"Loaded ministry bridge with {len(_ministry_bridge)} mappings")
        _ministry_bridge_loaded = True

    except Exception as e:
        logger.error(f"Error loading ministry bridge: {e}", exc_info=True)
        _ministry_bridge_loaded = True  # Mark as loaded to avoid repeated failures


def get_ministry_entity_id(ministry: str) -> Optional[int]:
    """
    Get entity_id for a ministry string.

    Args:
        ministry: Ministry name from ReportInfo.ministry

    Returns:
        entity_id from entity graph, or None if no mapping exists

    Example:
        >>> get_ministry_entity_id("Ministry of Railways")
        123
        >>> get_ministry_entity_id("Unknown Ministry")
        None
    """
    # Ensure bridge is loaded
    if not _ministry_bridge_loaded:
        load_ministry_bridge()

    if not ministry:
        return None

    # Direct lookup (case-sensitive for now - the bridge should have exact strings)
    return _ministry_bridge.get(ministry)


# ============================================================================
# Phase B: Index Getters (§5.1)
# ============================================================================


def get_ministry_index() -> Dict[str, List[str]]:
    """Get ministry → [report_ids] index."""
    _load_reports()
    return _ministry_index


def get_year_index() -> Dict[int, List[str]]:
    """Get report_year → [report_ids] index."""
    _load_reports()
    return _year_index


def get_audit_year_index() -> Dict[str, List[str]]:
    """Get audit_year → [report_ids] index."""
    _load_reports()
    return _audit_year_index


def get_state_index() -> Dict[str, List[str]]:
    """Get state_name → [report_ids] index."""
    _load_reports()
    return _state_index


def get_audit_category_index() -> Dict[str, List[str]]:
    """Get audit_category → [report_ids] index."""
    _load_reports()
    return _audit_category_index


def get_tier_index() -> Dict[str, List[str]]:
    """Get government_body_type → [report_ids] index."""
    _load_reports()
    return _tier_index


def get_recent_reports() -> List[ReportSummary]:
    """Get top 20 recent reports (by year DESC)."""
    _load_reports()
    return _recent_reports


# ============================================================================
# Phase B: Glossary Index (§5.2)
# ============================================================================


def build_glossary_index():
    """
    Build glossary index from *_overview_llm.json files.

    Extracts term/abbreviation/definition tuples and builds a searchable index.
    Called once at startup.
    """
    global _glossary_index, _glossary_loaded

    if _glossary_loaded:
        return

    _glossary_index = {}

    if not settings.PROCESSED_DIR.exists():
        logger.warning("Processed directory not found for glossary indexing")
        _glossary_loaded = True
        return

    # Find all overview files
    overview_files = list(settings.PROCESSED_DIR.glob("**/*_overview_llm.json"))

    for overview_file in overview_files:
        try:
            with open(overview_file, encoding="utf-8") as f:
                data = json.load(f)

            # Extract report_id from filename
            report_id = overview_file.stem.replace("_overview_llm", "")

            # Get glossary entries
            glossary_entries = data.get("glossary", [])
            if not glossary_entries:
                continue

            for entry in glossary_entries:
                # Handle both dict and list-of-list formats
                if isinstance(entry, dict):
                    term = entry.get("term", "")
                    abbrev = entry.get("abbreviation") or entry.get("abbr")
                    definition = entry.get("definition", "")
                elif isinstance(entry, (list, tuple)) and len(entry) >= 2:
                    term = entry[0] if len(entry) > 0 else ""
                    abbrev = entry[1] if len(entry) > 1 else None
                    definition = entry[2] if len(entry) > 2 else ""
                else:
                    continue

                if not term:
                    continue

                glossary_entry = {
                    "term": term,
                    "abbreviation": abbrev,
                    "definition": definition,
                    "report_id": report_id,
                }

                # Index by term (lowercase)
                term_lower = term.lower().strip()
                _glossary_index.setdefault(term_lower, []).append(glossary_entry)

                # Also index by abbreviation if present
                if abbrev:
                    abbrev_lower = abbrev.lower().strip()
                    _glossary_index.setdefault(abbrev_lower, []).append(glossary_entry)

        except Exception as e:
            logger.warning(f"Error loading glossary from {overview_file}: {e}")

    _glossary_loaded = True
    logger.info(f"Built glossary index with {len(_glossary_index)} terms")


def get_glossary_index() -> Dict[str, List[Dict[str, str]]]:
    """Get glossary index (term_lower → entries)."""
    if not _glossary_loaded:
        build_glossary_index()
    return _glossary_index


# ============================================================================
# Phase B: Home Page Functions (§5.3, §15)
# ============================================================================


def get_home_stats():
    """
    Get aggregate statistics for home page hero (§5.3).

    Returns:
        HomeStats model with counts from registry, entity_service, and qdrant

    Phase E: Cached to avoid expensive Qdrant count queries on every request (§15, §18.1).
    Cache TTL: 1 hour. Call invalidate_aggregates() after ingestion to clear.
    """
    from ..models import HomeStats
    global _home_stats_cache, _home_stats_cache_time

    # Check cache (1 hour TTL)
    now = time.time()
    if _home_stats_cache and (now - _home_stats_cache_time) < _home_stats_cache_ttl:
        return _home_stats_cache

    _load_reports()

    # Registry aggregates
    total_reports = len(_reports_cache)
    years = [r.year for r in _reports_cache.values() if r.year > 0]
    year_range = (min(years), max(years)) if years else (0, 0)

    # Latest ingest (from ingested_at field)
    latest_ingest = None
    ingested_dates = [
        r.ingested_at for r in _reports_cache.values() if r.ingested_at
    ]
    if ingested_dates:
        latest_ingest = max(ingested_dates)

    # Entity service aggregates (with graceful fallback)
    from src.entity_graph.entity_service import get_entity_service

    entity_service = get_entity_service()
    if entity_service:
        total_entities = entity_service.count_all()
        total_ministries = entity_service.count_by_type("ministry")
        total_mentions = entity_service.count_mentions()
    else:
        total_entities = 0
        total_ministries = 0
        total_mentions = 0

    # Qdrant aggregates (with graceful fallback)
    total_findings = 0
    total_charts = 0
    total_tables = 0

    try:
        from src.rag_pipeline.qdrant_service import QdrantService

        qdrant = QdrantService()

        total_findings = qdrant.count_filtered({"finding_type": {"$ne": None}})
        total_charts = qdrant.count_filtered({"content_type": "chart"})
        total_tables = qdrant.count_filtered({"content_type": "table_markdown"})
    except Exception as e:
        logger.warning(f"Qdrant stats unavailable: {e}")

    stats = HomeStats(
        total_reports=total_reports,
        total_entities=total_entities,
        total_ministries=total_ministries,
        total_mentions=total_mentions,
        total_findings=total_findings,
        total_charts=total_charts,
        total_tables=total_tables,
        latest_ingest=latest_ingest,
        year_range=year_range,
    )

    # Update cache
    _home_stats_cache = stats
    _home_stats_cache_time = now

    return stats


def get_home_facets():
    """
    Get all facet values for home page filtering.

    Returns:
        HomeFacets model with counts for each facet
    """
    from ..models import HomeFacets, FacetValue

    _load_reports()

    # Tiers
    tier_facets = [
        FacetValue(value=tier, label=tier.title(), count=len(report_ids))
        for tier, report_ids in _tier_index.items()
    ]
    tier_facets.sort(key=lambda f: -f.count)

    # States
    state_facets = [
        FacetValue(value=state, label=state, count=len(report_ids))
        for state, report_ids in _state_index.items()
    ]
    state_facets.sort(key=lambda f: f.label)

    # Years
    year_facets = [
        FacetValue(value=str(year), label=str(year), count=len(report_ids))
        for year, report_ids in _year_index.items()
    ]
    year_facets.sort(key=lambda f: -int(f.value))

    # Ministries (with entity bridge)
    ministry_facets = []
    for ministry, report_ids in _ministry_index.items():
        # Skip Unknown
        if ministry == "Unknown Ministry":
            continue

        entity_id = get_ministry_entity_id(ministry)
        if entity_id:
            ministry_facets.append(
                FacetValue(
                    value=str(entity_id), label=ministry, count=len(report_ids)
                )
            )
        else:
            # Fallback: use ministry string as value
            ministry_facets.append(
                FacetValue(value=ministry, label=ministry, count=len(report_ids))
            )

    ministry_facets.sort(key=lambda f: -f.count)

    # Entities (top 50 by mention_count, non-ministry)
    # Phase E: Use pre-computed list to avoid per-request DB query (§15)
    entity_facets = [
        FacetValue(
            value=str(ent['id']),
            label=ent['canonical_name'],
            count=ent['mention_count'],
        )
        for ent in _top_entities_facets
    ]

    # Audit categories
    category_facets = [
        FacetValue(value=cat, label=cat.title(), count=len(report_ids))
        for cat, report_ids in _audit_category_index.items()
    ]
    category_facets.sort(key=lambda f: -f.count)

    return HomeFacets(
        tiers=tier_facets,
        states=state_facets,
        years=year_facets,
        ministries=ministry_facets,
        entities=entity_facets,
        audit_categories=category_facets,
    )


def get_home_featured():
    """
    Get featured content for home page rails.

    Returns:
        HomeFeatured model with top ministries, entities, recent reports, etc.
    """
    from ..models import (
        HomeFeatured,
        FeaturedMinistry,
        FeaturedEntity,
        TimeSeriesInfo,
    )
    from src.entity_graph.entity_service import get_entity_service
    import random
    from datetime import datetime

    _load_reports()

    entity_service = get_entity_service()

    # Top ministries (top 8 by report_count, using entity bridge)
    top_ministries = []
    if entity_service:
        # Build ministry entity_id → report_count map
        ministry_counts: Dict[int, Dict[str, any]] = {}

        for ministry, report_ids in _ministry_index.items():
            if ministry == "Unknown Ministry":
                continue

            entity_id = get_ministry_entity_id(ministry)
            if entity_id:
                if entity_id not in ministry_counts:
                    ministry_counts[entity_id] = {
                        "report_count": 0,
                        "canonical_name": ministry,
                    }
                ministry_counts[entity_id]["report_count"] += len(report_ids)

        # Get full entity details for top ministries
        top_ministry_ids = sorted(
            ministry_counts.keys(),
            key=lambda eid: ministry_counts[eid]["report_count"],
            reverse=True,
        )[:8]

        for entity_id in top_ministry_ids:
            entity = entity_service.get_entity(entity_id)
            if entity:
                top_ministries.append(
                    FeaturedMinistry(
                        entity_id=entity["id"],
                        canonical_name=entity["canonical_name"],
                        report_count=ministry_counts[entity_id]["report_count"],
                        finding_count=entity["finding_count"],
                        mention_count=entity["mention_count"],
                        primary_tier=entity["primary_tier"],
                    )
                )

    # Top entities (top 8 by mention_count, non-ministry)
    top_entities = []
    if entity_service:
        from src.entity_graph.db import session_scope
        from src.entity_graph.models import Entity

        with session_scope() as session:
            entities = (
                session.query(Entity)
                .filter(Entity.entity_type != "ministry")
                .order_by(Entity.mention_count.desc())
                .limit(8)
                .all()
            )

            for ent in entities:
                top_entities.append(
                    FeaturedEntity(
                        entity_id=ent.id,
                        canonical_name=ent.canonical_name,
                        entity_type=ent.entity_type,
                        mention_count=ent.mention_count,
                        finding_count=ent.finding_count,
                        primary_tier=ent.primary_tier,
                    )
                )

    # Recent reports (top 20 from pre-computed list)
    recent_reports = _recent_reports[:20]

    # Deep dives (from series registry)
    deep_dives = []
    try:
        from ..routes.series import _get_all_series_data

        series_data = _get_all_series_data()
        for s in series_data[:5]:  # Top 5 series
            from ..models import SeriesReportSummary

            deep_dives.append(
                TimeSeriesInfo(
                    series_id=s["series_id"],
                    name=s["name"],
                    description=s["description"],
                    reports=[SeriesReportSummary(**r) for r in s["reports"]],
                    years_covered=[
                        r["audit_year"] for r in s["reports"] if r.get("audit_year")
                    ],
                )
            )
    except Exception as e:
        logger.warning(f"Could not load deep dives: {e}")

    # Popular starts (deterministic 10 items, seeded by today's UTC date)
    # Mix of ministries and entities
    today_seed = datetime.utcnow().date().toordinal()
    random.seed(today_seed)

    popular_pool = top_ministries[:5] + top_entities[:5]
    popular_starts = random.sample(popular_pool, min(10, len(popular_pool)))

    return HomeFeatured(
        top_ministries=top_ministries,
        top_entities=top_entities,
        recent_reports=recent_reports,
        deep_dives=deep_dives,
        popular_starts=popular_starts,
    )


# ============================================================================
# Phase D: Trending Searches (§9)
# ============================================================================


def _sanitize_query_text(query_text: str) -> Optional[str]:
    """
    Sanitize query text to remove potentially sensitive data (§9.3).

    Filters out:
    - Email addresses (x@y.z pattern)
    - Phone numbers (10+ digits)
    - Document IDs (UUID patterns, long alphanumeric strings)

    Args:
        query_text: Raw query text

    Returns:
        Sanitized query text, or None if it should be filtered out
    """
    if not query_text:
        return None

    # Email pattern: word@word.word
    if re.search(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', query_text):
        logger.debug(f"Filtered trending query containing email: {query_text[:20]}...")
        return None

    # Phone number pattern: 10+ consecutive digits
    if re.search(r'\b\d{10,}\b', query_text):
        logger.debug(f"Filtered trending query containing phone number: {query_text[:20]}...")
        return None

    # UUID pattern: 8-4-4-4-12 hex format
    if re.search(r'\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b', query_text):
        logger.debug(f"Filtered trending query containing UUID: {query_text[:20]}...")
        return None

    # Long alphanumeric strings that look like document IDs (20+ chars, no spaces)
    if re.search(r'\b[A-Za-z0-9_-]{20,}\b', query_text):
        logger.debug(f"Filtered trending query containing document ID: {query_text[:20]}...")
        return None

    return query_text


def get_trending_searches() -> List[Dict[str, any]]:
    """
    Get trending searches from the last 7 days (§9).

    Queries the query_logs table with privacy guards:
    - Only surfaces queries asked 3+ times (HAVING COUNT(*) >= 3)
    - Filters out emails, phone numbers, document IDs
    - Results cached for 1 hour

    Returns:
        List of dicts with keys: query_text, hit_count, last_seen
        Empty list if query_logs table doesn't exist or query fails
    """
    global _trending_searches_cache, _trending_searches_cache_time

    # Check cache (1 hour TTL)
    now = time.time()
    if _trending_searches_cache and (now - _trending_searches_cache_time) < _trending_searches_cache_ttl:
        return _trending_searches_cache

    # Query the database
    try:
        from src.entity_graph.db import get_engine
        from sqlalchemy import text

        engine = get_engine()
        if not engine:
            logger.warning("No database engine available for trending searches")
            return []

        # SQL from §9.2 (adapted to include home_search mode)
        # Note: Removed environment='prod' filter to work in all environments
        # In production, consider adding: AND environment = 'prod'
        sql = text("""
            SELECT
                query_text,
                COUNT(*) AS hit_count,
                MAX(timestamp) AS last_seen
            FROM query_logs
            WHERE
                timestamp > NOW() - INTERVAL '7 days'
                AND interaction_mode IN ('home', 'directory', 'agentic_sub', 'home_search')
                AND success = TRUE
                AND length(query_text) BETWEEN 5 AND 100
            GROUP BY query_text
            HAVING COUNT(*) >= 3
            ORDER BY hit_count DESC
            LIMIT 10
        """)

        with engine.connect() as conn:
            result = conn.execute(sql)
            rows = result.fetchall()

        # Sanitize and build response
        trending = []
        for row in rows:
            query_text = row[0]
            hit_count = row[1]
            last_seen = row[2]

            # Sanitize (§9.3)
            sanitized_query = _sanitize_query_text(query_text)
            if not sanitized_query:
                continue

            trending.append({
                "query_text": sanitized_query,
                "hit_count": hit_count,
                "last_seen": last_seen.isoformat() if last_seen else None,
            })

        # Update cache
        _trending_searches_cache = trending
        _trending_searches_cache_time = now

        logger.info(f"Loaded {len(trending)} trending searches")
        return trending

    except Exception as e:
        # Graceful degradation: return empty list if query_logs table doesn't exist
        # or any other error occurs
        logger.warning(f"Could not load trending searches: {e}")
        return []


# ============================================================================
# Phase E: Cache Management (§18.1)
# ============================================================================


def invalidate_aggregates():
    """
    Clear all home page caches (stats, trending, etc.).

    Call this after new reports are ingested to ensure fresh data.
    Per §18.1: entity_service.canonicalize and entity_service.index operations
    should call this post-completion.

    For now, restarting the API process also clears caches (they're in-memory).

    Example usage in ingestion runbook:
        ```python
        from src.api.services.report_service import invalidate_aggregates
        invalidate_aggregates()
        ```
    """
    global _home_stats_cache, _home_stats_cache_time
    global _trending_searches_cache, _trending_searches_cache_time
    global _reports_cache, _initialized

    logger.info("Invalidating home page aggregates cache")

    # Clear stats cache
    _home_stats_cache = None
    _home_stats_cache_time = 0.0

    # Clear trending cache
    _trending_searches_cache = []
    _trending_searches_cache_time = 0.0

    # Optionally reload reports (forces rebuild of indexes)
    # Only do this if reports were actually re-ingested
    # For now, we just clear the caches; report reload happens on next API restart
    # _initialized = False
    # _load_reports()

    logger.info("Home page cache invalidated successfully")
