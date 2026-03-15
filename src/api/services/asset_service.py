"""
Service for extracting charts and tables from processed report JSON files.

VERSION 4 - Comprehensive extraction with fallback:

Primary: Extract from formal title patterns (Figure/Chart/Graph/Box X.X:)
Fallback: Extract from image_captions that describe charts/graphs (when no formal titles found)

Supported patterns:
- Figure X.X:, Chart X.X:, Graph X.X:, Box X.X:, Diagram X.X:, Exhibit X.X:, Map X.X:
- image_caption chunks that mention "bar chart", "pie chart", "graph", etc.
"""

import json
import re
import logging
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Any

from ..config import settings
from ..models import ChartItem, TableItem, ChartType

logger = logging.getLogger(__name__)

# Cache for extracted assets
_charts_cache: Dict[str, List[ChartItem]] = {}
_tables_cache: Dict[str, List[TableItem]] = {}


# ============================================================================
# VISUAL ELEMENT PATTERNS
# ============================================================================

VISUAL_ELEMENT_PATTERNS = [
    (re.compile(r"^(Figure\s+\d+[.\d]*)\s*[:\-–]\s*(.+)$", re.IGNORECASE), "figure"),
    (re.compile(r"^(Chart\s+\d+[.\d]*)\s*[:\-–]\s*(.+)$", re.IGNORECASE), "chart"),
    (re.compile(r"^(Graph\s+\d+[.\d]*)\s*[:\-–]\s*(.+)$", re.IGNORECASE), "graph"),
    (re.compile(r"^(Box\s+\d+[.\d]*)\s*[:\-–]\s*(.+)$", re.IGNORECASE), "box"),
    (re.compile(r"^(Diagram\s+\d+[.\d]*)\s*[:\-–]\s*(.+)$", re.IGNORECASE), "diagram"),
    (re.compile(r"^(Exhibit\s+\d+[.\d]*)\s*[:\-–]\s*(.+)$", re.IGNORECASE), "exhibit"),
    (re.compile(r"^(Map\s+\d+[.\d]*)\s*[:\-–]\s*(.+)$", re.IGNORECASE), "map"),
    (
        re.compile(r"^(Infographic\s+\d+[.\d]*)\s*[:\-–]\s*(.+)$", re.IGNORECASE),
        "infographic",
    ),
]

# Keywords that indicate an image_caption describes a chart (for fallback)
CHART_KEYWORDS_IN_CAPTION = [
    "bar chart",
    "pie chart",
    "line chart",
    "area chart",
    "graph depicting",
    "graph showing",
    "chart depicting",
    "chart showing",
    "histogram",
    "scatter plot",
    "trend line",
    "depicts the",
    "illustrates the",
    "shows the trend",
    "comparison chart",
    "flow chart",
    "flowchart",
]

# Keywords that indicate an image_caption should be SKIPPED (not a chart)
SKIP_CAPTION_KEYWORDS = [
    "logo",
    "emblem",
    "seal",
    "badge",
    "crest",
    "coat of arms",
    "cover",
    "title page",
    "black background",
    "blue background",
    "photo of",
    "photograph",
    "picture of a",
    "picture of the",
    "group of trucks",
    "building",
    "sandbags",
    "grain silo",
    "standing on",
    "man standing",
    "people",
    "person",
]


# ============================================================================
# CHART TYPE CLASSIFICATION
# ============================================================================


def _classify_chart_type(title: str, element_type: str) -> ChartType:
    """Classify chart type based on title keywords and element type."""
    title_lower = title.lower()

    if element_type == "box":
        return ChartType.TABLE_CHART

    # Explicit chart type mentions
    if "pie chart" in title_lower or "pie graph" in title_lower:
        return ChartType.PIE
    if "bar chart" in title_lower or "bar graph" in title_lower:
        return ChartType.BAR
    if "line chart" in title_lower or "line graph" in title_lower:
        return ChartType.LINE
    if "area chart" in title_lower:
        return ChartType.AREA

    # Keyword-based classification
    if any(
        kw in title_lower
        for kw in ["trend", "growth", "over time", "year-wise", "annual"]
    ):
        return ChartType.LINE
    if any(
        kw in title_lower
        for kw in ["composition", "share", "distribution", "breakdown", "proportion"]
    ):
        return ChartType.PIE
    if any(
        kw in title_lower
        for kw in ["comparison", "compare", "vs", "versus", "vis-a-vis", "vis-à-vis"]
    ):
        return ChartType.BAR
    if any(kw in title_lower for kw in ["analysis", "actuals", "estimates", "budget"]):
        return ChartType.BAR

    if element_type == "map":
        return ChartType.AREA

    return ChartType.BAR


def _extract_chart_title_from_caption(caption: str, page: int) -> str:
    """
    Extract a meaningful title from an image caption.

    Examples:
    - "a bar chart depicting the average statutory charges" → "Average Statutory Charges"
    - "shows a pie chart on a white background" → "Chart on Page X"
    """
    caption_lower = caption.lower()

    # Try to extract the subject after "depicting", "showing", etc.
    patterns = [
        r"(?:depicts?|depicting|shows?|showing|illustrat(?:es?|ing))\s+(?:the\s+)?(.{10,60}?)(?:\.|,|$)",
        r"(?:bar|pie|line)\s+chart\s+(?:of|for|depicting|showing)?\s*(?:the\s+)?(.{10,60}?)(?:\.|,|$)",
    ]

    for pattern in patterns:
        match = re.search(pattern, caption_lower)
        if match:
            subject = match.group(1).strip()
            # Clean up and title-case
            subject = re.sub(r"\s+", " ", subject)
            subject = subject.rstrip(".,;:")
            if len(subject) > 10:
                return subject.title()

    return f"Visual Element on Page {page}"


def _get_chart_analysis(title: str, section: str, element_type: str) -> str:
    """Generate analysis description for a visual element."""
    title_lower = title.lower()

    type_desc = {
        "figure": "figure",
        "chart": "chart",
        "graph": "graph",
        "box": "information box",
        "diagram": "diagram",
        "exhibit": "exhibit",
        "map": "map",
        "infographic": "infographic",
        "caption": "visual element",
    }.get(element_type, "visual element")

    if "trend" in title_lower:
        action = "illustrates the trend of"
    elif "comparison" in title_lower or "vis-a-vis" in title_lower:
        action = "compares"
    elif "composition" in title_lower or "component" in title_lower:
        action = "shows the composition of"
    elif "depicting" in title_lower or "showing" in title_lower:
        action = "depicts"
    else:
        action = "presents"

    if ":" in title:
        topic = title.split(":", 1)[1].strip()
    else:
        topic = title

    section_short = section.split(" > ")[-1] if " > " in section else section

    return f"This {type_desc} {action} {topic}, as discussed in {section_short}."


# ============================================================================
# TABLE PARSING
# ============================================================================


def _parse_table_dimensions(markdown_content: str) -> Tuple[int, int, List[str]]:
    """Parse markdown table to extract dimensions and headers."""
    lines = markdown_content.strip().split("\n")

    data_lines = []
    headers = []

    for i, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue
        if re.match(r"^[\|\s\-:]+$", line):
            continue

        cells = [cell.strip() for cell in line.split("|") if cell.strip()]

        if cells:
            if not headers:
                headers = cells
            data_lines.append(cells)

    rows = len(data_lines)
    columns = (
        len(headers)
        if headers
        else (max(len(row) for row in data_lines) if data_lines else 0)
    )

    return rows, columns, headers


def _generate_table_title(hierarchy: Dict[str, str], page: int) -> str:
    """Generate title for a table based on section hierarchy."""
    if hierarchy:
        levels = sorted(hierarchy.keys())
        deepest_section = hierarchy[levels[-1]]
        return f"Data Table: {deepest_section}"
    return f"Data Table on Page {page}"


def _generate_table_analysis(
    content: str, hierarchy: Dict[str, str], rows: int, cols: int
) -> str:
    """Generate analysis for a table."""
    content_lower = content.lower()

    themes = []
    if any(kw in content_lower for kw in ["crore", "₹", "rupee", "lakh"]):
        themes.append("financial figures")
    if any(
        kw in content_lower for kw in ["fy ", "2020", "2021", "2022", "2023", "2024"]
    ):
        themes.append("multi-year data")
    if any(kw in content_lower for kw in ["budget", "estimate", "actual"]):
        themes.append("budget comparisons")

    theme_str = ", ".join(themes) if themes else "tabular data"
    section_name = list(hierarchy.values())[-1] if hierarchy else "this section"

    return f"Contains {theme_str} related to {section_name}. Dimensions: {rows} rows × {cols} columns."


# ============================================================================
# JSON LOADING
# ============================================================================


def _load_report_json(report_id: str) -> Optional[Dict]:
    """Load the chunks JSON file for a report."""
    if not settings.PROCESSED_DIR.exists():
        logger.warning(f"Processed directory not found: {settings.PROCESSED_DIR}")
        return None

    # Try direct path first (both top-level and in subdirectories)
    for suffix in ["_chunks.json", "_enriched.json"]:
        # Check top-level
        json_path = settings.PROCESSED_DIR / f"{report_id}{suffix}"
        if json_path.exists():
            with open(json_path, encoding="utf-8") as f:
                return json.load(f)

        # Check subdirectories
        for json_file in settings.PROCESSED_DIR.glob(f"**/{report_id}{suffix}"):
            with open(json_file, encoding="utf-8") as f:
                return json.load(f)

    # Fallback: search recursively for files containing the report_id
    for json_file in settings.PROCESSED_DIR.glob("**/*_chunks.json"):
        if report_id in json_file.stem:
            with open(json_file, encoding="utf-8") as f:
                return json.load(f)

    logger.warning(f"No JSON file found for report: {report_id}")
    return None


# ============================================================================
# CHART EXTRACTION (v4 - WITH FALLBACK)
# ============================================================================


def extract_charts(report_id: str, use_cache: bool = True) -> List[ChartItem]:
    """
    Extract visual elements from a report.

    Strategy:
    1. PRIMARY: Look for formal title patterns (Figure/Chart/Graph X.X:)
    2. FALLBACK: If few formal titles found, extract from image_captions
       that describe charts/graphs (filtering out photos, logos, etc.)

    Args:
        report_id: The report identifier
        use_cache: Whether to use cached results

    Returns:
        List of ChartItem objects
    """
    if use_cache and report_id in _charts_cache:
        return _charts_cache[report_id]

    data = _load_report_json(report_id)
    if not data:
        return []

    child_chunks = data.get("child_chunks", [])
    charts = []
    chart_idx = 1
    found_elements = set()

    # Collect image captions for enrichment and potential fallback
    image_caption_chunks = []
    # P2-2: Collect chart_data_path chunks with structured data
    chart_data_chunks = []
    for chunk in child_chunks:
        if chunk.get("content_type") == "image_caption":
            image_caption_chunks.append(chunk)
        elif chunk.get("content_type") == "chart_data_path":
            chart_data_chunks.append(chunk)

    # Build page -> caption map for enrichment
    page_captions: Dict[int, str] = {}
    for chunk in image_caption_chunks:
        page = chunk.get("source_page_physical", 0)
        content = chunk.get("content", "")
        if page not in page_captions:
            page_captions[page] = content

    # ========== PRIMARY: Extract from formal title patterns ==========
    for chunk in child_chunks:
        content_type = chunk.get("content_type", "")
        if content_type not in ("paragraph", "header"):
            continue

        content = chunk.get("content", "").strip()
        if len(content) > 250:
            continue

        for pattern, element_type in VISUAL_ELEMENT_PATTERNS:
            match = pattern.match(content)
            if match:
                element_number = match.group(1)
                element_title = match.group(2).strip()
                full_title = f"{element_number}: {element_title}"

                element_key = f"{element_number}_{chunk.get('source_page_physical', 0)}"
                if element_key in found_elements:
                    break
                found_elements.add(element_key)

                page = chunk.get("source_page_physical", 0)
                hierarchy = chunk.get("hierarchy", {})
                section = (
                    " > ".join(hierarchy.values()) if hierarchy else "Unknown Section"
                )

                chart_type = _classify_chart_type(element_title, element_type)

                # Try to get analysis from image caption
                analysis = page_captions.get(page, "")
                if not analysis or len(analysis) < 50:
                    analysis = _get_chart_analysis(full_title, section, element_type)

                charts.append(
                    ChartItem(
                        id=f"chart-{chart_idx}",
                        title=full_title,
                        type=chart_type,
                        section=section,
                        page=page + 1,
                        analysis=analysis,
                        source_chunk_id=chunk.get("chunk_id"),
                    )
                )
                chart_idx += 1
                break

    # ========== P2-2: Extract from chart_data_path chunks (Claude Vision) ==========
    for chunk in chart_data_chunks:
        page = chunk.get("source_page_physical", 0)
        structured_data = chunk.get("structured_data")

        # Check if this page already has a chart from formal titles
        page_display = page + 1
        if any(c.page == page_display for c in charts):
            continue  # Skip duplicate

        # Build title from structured_data or fallback
        if structured_data and structured_data.get("title"):
            title = structured_data["title"]
        else:
            title = f"Chart (Page {page_display})"

        hierarchy = chunk.get("hierarchy", {})
        section = " > ".join(hierarchy.values()) if hierarchy else "Unknown Section"

        # Get chart type from structured_data
        if structured_data and structured_data.get("chart_type"):
            chart_type = structured_data["chart_type"]
        else:
            chart_type = "unknown"

        # Get analysis from structured_data description or page caption
        analysis = ""
        if structured_data and structured_data.get("description"):
            analysis = structured_data["description"]
        elif page in page_captions:
            analysis = page_captions[page]
        else:
            analysis = f"Chart on page {page_display}"

        # Create chart item with P2-2 structured data fields
        chart_item = ChartItem(
            id=f"chart-{chart_idx}",
            title=title,
            type=chart_type,
            section=section,
            page=page_display,
            analysis=analysis,
            source_chunk_id=chunk.get("chunk_id"),
            bbox=chunk.get("source_bbox"),
            # P2-2 fields
            has_structured_data=bool(structured_data and structured_data.get("has_structured_data")),
            extracted_series_count=len(structured_data.get("series", [])) if structured_data else None,
            time_periods=structured_data.get("time_periods") if structured_data else None,
            entities=structured_data.get("entities_referenced") if structured_data else None,
            monetary_unit=structured_data.get("monetary_unit") if structured_data else None,
            extraction_confidence=structured_data.get("confidence") if structured_data else None,
        )

        charts.append(chart_item)
        chart_idx += 1

    # ========== FALLBACK: Extract from image_captions if few formal titles ==========
    # Only use fallback if we found very few formal charts
    if len(charts) < 3:
        logger.info(
            f"Few formal charts ({len(charts)}) in {report_id}, using image_caption fallback"
        )

        caption_charts = []
        seen_pages = {c.page for c in charts}  # Don't duplicate pages

        for chunk in image_caption_chunks:
            content = chunk.get("content", "")
            content_lower = content.lower()
            page = chunk.get("source_page_physical", 0)

            # Skip if we already have a chart on this page
            if (page + 1) in seen_pages:
                continue

            # Skip non-chart images (photos, logos, etc.)
            if any(skip in content_lower for skip in SKIP_CAPTION_KEYWORDS):
                continue

            # Check if caption describes a chart
            is_chart = any(kw in content_lower for kw in CHART_KEYWORDS_IN_CAPTION)

            if is_chart:
                hierarchy = chunk.get("hierarchy", {})
                section = (
                    " > ".join(hierarchy.values()) if hierarchy else "Unknown Section"
                )

                # Extract title from caption
                title = _extract_chart_title_from_caption(content, page + 1)

                # Classify type from caption
                chart_type = _classify_chart_type(content, "caption")

                caption_charts.append(
                    ChartItem(
                        id=f"chart-{chart_idx}",
                        title=title,
                        type=chart_type,
                        section=section,
                        page=page + 1,
                        analysis=content[:300] + "..."
                        if len(content) > 300
                        else content,
                        source_chunk_id=chunk.get("chunk_id"),
                    )
                )
                chart_idx += 1
                seen_pages.add(page + 1)

        # Add caption-based charts
        charts.extend(caption_charts)
        if caption_charts:
            logger.info(f"Added {len(caption_charts)} charts from image_captions")

    # Sort by page number
    charts.sort(key=lambda x: (x.page, x.title))

    _charts_cache[report_id] = charts
    logger.info(f"Extracted {len(charts)} visual elements from {report_id}")

    return charts


# ============================================================================
# TABLE EXTRACTION
# ============================================================================


def extract_tables(report_id: str, use_cache: bool = True) -> List[TableItem]:
    """Extract tables from a report."""
    if use_cache and report_id in _tables_cache:
        return _tables_cache[report_id]

    data = _load_report_json(report_id)
    if not data:
        return []

    child_chunks = data.get("child_chunks", [])
    tables = []
    table_idx = 1

    for chunk in child_chunks:
        if chunk.get("content_type") != "table_markdown":
            continue

        content = chunk.get("content", "")
        page = chunk.get("source_page_physical", 0)
        hierarchy = chunk.get("hierarchy", {})
        bbox = chunk.get("metadata", {}).get("location", {}).get("bbox")
        chunk_id = chunk.get("chunk_id", "")

        if len(content) < 30:
            continue

        rows, columns, headers = _parse_table_dimensions(content)

        if rows < 2 or columns < 1:
            continue

        title = _generate_table_title(hierarchy, page + 1)
        section = " > ".join(hierarchy.values()) if hierarchy else "Unknown Section"
        analysis = _generate_table_analysis(content, hierarchy, rows, columns)
        clean_headers = [h[:50] for h in headers if h and h.strip()][:10]

        tables.append(
            TableItem(
                id=f"table-{table_idx}",
                title=title,
                section=section,
                page=page + 1,
                rows=rows,
                columns=columns,
                analysis=analysis,
                headers=clean_headers if clean_headers else None,
                bbox=bbox,
                source_chunk_id=chunk_id,
                structured_data=chunk.get("structured_data"),
            )
        )
        table_idx += 1

    _tables_cache[report_id] = tables
    logger.info(f"Extracted {len(tables)} tables from {report_id}")

    return tables


# ============================================================================
# CACHE MANAGEMENT
# ============================================================================


def clear_cache(report_id: Optional[str] = None):
    """Clear the asset cache."""
    global _charts_cache, _tables_cache

    if report_id:
        _charts_cache.pop(report_id, None)
        _tables_cache.pop(report_id, None)
    else:
        _charts_cache = {}
        _tables_cache = {}


def get_cache_stats() -> Dict[str, Any]:
    """Get cache statistics."""
    return {
        "charts_cached_reports": len(_charts_cache),
        "tables_cached_reports": len(_tables_cache),
        "total_charts_cached": sum(len(v) for v in _charts_cache.values()),
        "total_tables_cached": sum(len(v) for v in _tables_cache.values()),
    }
