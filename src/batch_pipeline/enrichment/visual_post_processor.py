"""
VisualPostProcessor: Quality gate and enrichment for extracted table/chart data.

Phase 10c in the pipeline — runs after Gemini visual extraction (Phase 10b).

Responsibilities:
1. TOC Detection & Filtering: Removes table-of-contents pages misdetected as tables
2. Title Enrichment: Infers table/chart titles from surrounding text context
3. StructuredTable Hydration: Converts Gemini markdown output → full StructuredTable JSON
4. StructuredChart Hydration: Converts Gemini chart output → full StructuredChart JSON
5. Confidence Scoring: Assigns quality scores based on extraction notes
6. Markdown Regeneration: Rebuilds clean markdown from structured data for RAG indexing

Usage:
    processor = VisualPostProcessor()
    
    # Process a single chunk JSON file
    stats = processor.process_file(json_path)
    
    # Process all reports
    stats = processor.process_all(json_files)
"""

import re
import json
import logging
from pathlib import Path
from typing import List, Dict, Optional, Any, Tuple
from collections import Counter

from src.core.table_contracts import StructuredTable
from src.core.chart_contracts import (
    StructuredChart,
    ChartType,
    ChartAxisConfig,
    ChartSeries,
    DataPoint,
    AxisType,
)
from src.parsing_pipeline.modules.structured_table_extractor import StructuredTableExtractor

logger = logging.getLogger(__name__)


class VisualPostProcessor:
    """
    Post-processes Gemini visual extraction results for quality and consistency.
    """

    # TOC detection patterns — if a table's content matches these, it's likely a TOC
    TOC_PATTERNS = [
        r"table\s+of\s+contents",
        r"list\s+of\s+(tables|figures|charts|abbreviations|annexures)",
        r"contents\s*$",
        r"^sl\.?\s*no\.?\s*\|\s*(particulars|subject|chapter|description)",
        r"page\s*no\.?\s*$",  # Last column is "Page No."
        r"^(chapter|section)\s+\|\s+(title|heading|description)\s+\|\s+page",
    ]

    # Patterns that indicate low-value extraction
    LOW_VALUE_PATTERNS = [
        r"^[\s\|\-]+$",  # Only pipes and dashes (empty table)
        r"^```",  # Still wrapped in code fences
    ]

    def __init__(self, trace_emitter=None):
        """Initialize post-processor with StructuredTableExtractor.

        Args:
            trace_emitter: Optional TraceEmitter for Phase 10c instrumentation
        """
        self.structured_extractor = StructuredTableExtractor()
        self._trace_emitter = trace_emitter
        self.stats = {
            "tables_processed": 0,
            "tables_filtered_toc": 0,
            "tables_hydrated": 0,
            "charts_processed": 0,
            "charts_hydrated": 0,
            "titles_enriched": 0,
        }

    # ========== MAIN ENTRY POINTS ==========

    def process_all(
        self,
        json_files: List[Path],
        trace_emitter=None,
    ) -> Dict[str, int]:
        """
        Process all chunk JSON files.

        Args:
            json_files: List of *_chunks.json file paths
            trace_emitter: Optional TraceEmitter for Phase 10c instrumentation

        Returns:
            Aggregate statistics dict
        """
        emitter = trace_emitter or self._trace_emitter
        errors = []

        # Emit initial I/O
        if emitter:
            emitter.emit_io(
                "10c",
                {"json_files": len(json_files)},
                {"processing_started": True},
            )

        for json_path in json_files:
            try:
                self.process_file(json_path, trace_emitter=emitter)
            except Exception as e:
                logger.error(f"Failed to process {json_path.name}: {e}")
                errors.append((json_path.name, str(e)))

        # Emit final summary
        if emitter:
            emitter.emit_io(
                "10c",
                {"files_processed": len(json_files)},
                {
                    "tables_processed": self.stats["tables_processed"],
                    "tables_filtered_toc": self.stats["tables_filtered_toc"],
                    "tables_hydrated": self.stats["tables_hydrated"],
                    "charts_processed": self.stats["charts_processed"],
                    "charts_hydrated": self.stats["charts_hydrated"],
                    "titles_enriched": self.stats["titles_enriched"],
                    "errors": len(errors),
                },
            )

            # Red flags for filtered TOCs and errors
            if self.stats["tables_filtered_toc"] > 0:
                emitter.emit_decision(
                    "10c",
                    "toc_filtering",
                    f"filtered_{self.stats['tables_filtered_toc']}",
                    [],
                    f"Filtered {self.stats['tables_filtered_toc']} TOC tables masquerading as data tables",
                )

            if errors:
                emitter.emit_red_flag(
                    "10c",
                    f"Post-processing errors in {len(errors)} files",
                    {"files": [e[0] for e in errors[:5]]},  # First 5 errors
                )
                emitter.set_phase_status("10c", "partial")
            else:
                emitter.set_phase_status("10c", "success")

        return self.stats.copy()

    def process_file(self, json_path: Path, trace_emitter=None) -> Dict[str, int]:
        """
        Process a single chunk JSON file — applies all post-processing steps.

        Args:
            json_path: Path to *_chunks.json
            trace_emitter: Optional TraceEmitter for per-file instrumentation

        Returns:
            Per-file statistics
        """
        emitter = trace_emitter or self._trace_emitter

        with open(json_path) as f:
            data = json.load(f)

        report_id = data.get("report_metadata", {}).get("report_id", "unknown")
        chunks = data.get("child_chunks", [])

        # Per-file trace: processing started
        if emitter:
            emitter.emit_io(
                "10c",
                {"file": json_path.name, "report_id": report_id},
                {"chunks_to_process": len(chunks)},
            )

        modified = False
        file_stats = {"filtered": 0, "hydrated": 0, "titles": 0}

        for chunk in chunks:
            content_type = chunk.get("content_type", "")
            structured_data = chunk.get("structured_data")

            # === TABLE POST-PROCESSING ===
            if content_type == "table_markdown":
                self.stats["tables_processed"] += 1

                # Step 1: TOC filtering
                if self._is_toc_table(chunk):
                    # Mark as filtered but don't delete — downstream can decide
                    chunk["extraction_confidence"] = 0.05
                    if structured_data:
                        structured_data["_filtered_reason"] = "toc_detected"
                    self.stats["tables_filtered_toc"] += 1
                    file_stats["filtered"] += 1
                    modified = True
                    continue

                # Step 2: Title enrichment
                if self._needs_title(chunk):
                    title = self._infer_title(chunk, chunks)
                    if title:
                        if structured_data and isinstance(structured_data, dict):
                            structured_data["title"] = title
                        self.stats["titles_enriched"] += 1
                        file_stats["titles"] += 1
                        modified = True

                # Step 3: Hydrate Gemini markdown → StructuredTable
                if structured_data and isinstance(structured_data, dict):
                    gemini_markdown = structured_data.get("markdown")
                    if gemini_markdown and not structured_data.get("rows"):
                        hydrated = self._hydrate_table(
                            gemini_markdown, chunk, structured_data
                        )
                        if hydrated:
                            chunk["structured_data"] = hydrated
                            # Also update the content field with clean markdown
                            chunk["content"] = gemini_markdown
                            self.stats["tables_hydrated"] += 1
                            file_stats["hydrated"] += 1
                            modified = True

                # Step 4: Confidence scoring
                confidence = self._score_table_confidence(chunk)
                chunk["extraction_confidence"] = confidence

            # === CHART POST-PROCESSING ===
            elif content_type in ("chart_data_path", "image_caption"):
                if not structured_data or not isinstance(structured_data, dict):
                    continue

                self.stats["charts_processed"] += 1

                # Hydrate Gemini chart output → StructuredChart
                if structured_data.get("series") and not structured_data.get("chart_id"):
                    hydrated = self._hydrate_chart(chunk, structured_data)
                    if hydrated:
                        chunk["structured_data"] = hydrated
                        self.stats["charts_hydrated"] += 1
                        modified = True

        # Save if modified
        if modified:
            with open(json_path, "w") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            logger.info(
                f"✅ Post-processed {json_path.name}: "
                f"{file_stats['filtered']} filtered, "
                f"{file_stats['hydrated']} hydrated, "
                f"{file_stats['titles']} titles enriched"
            )

            # Per-file trace: processing complete with stats
            if emitter:
                emitter.emit_io(
                    "10c",
                    {"file": json_path.name, "report_id": report_id},
                    {
                        "filtered": file_stats["filtered"],
                        "hydrated": file_stats["hydrated"],
                        "titles": file_stats["titles"],
                        "modified": True,
                    },
                )

        return file_stats

    # ========== TOC DETECTION ==========

    def _is_toc_table(self, chunk: Dict) -> bool:
        """
        Detect if a table chunk is actually a table of contents.

        Checks:
        1. Content matches TOC patterns
        2. High ratio of page numbers in last column
        3. Section/chapter numbering in first column

        Args:
            chunk: ChildChunk dict

        Returns:
            True if this is likely a TOC, not a data table
        """
        content = chunk.get("content", "").lower()
        structured = chunk.get("structured_data", {})

        # Pattern matching on raw content
        for pattern in self.TOC_PATTERNS:
            if re.search(pattern, content, re.IGNORECASE | re.MULTILINE):
                return True

        # Check markdown for "Page No." column
        if isinstance(structured, dict):
            markdown = structured.get("markdown", content)
        else:
            markdown = content

        lines = markdown.split("\n")
        if not lines:
            return False

        # Heuristic: if header row contains "page" and rows have small numbers at end
        header = lines[0].lower() if lines else ""
        if "page" in header and ("no" in header or "#" in header):
            return True

        # Heuristic: Check if last column is predominantly small integers (page numbers)
        page_num_count = 0
        data_rows = [l for l in lines[2:] if l.strip() and "|" in l]  # Skip header + separator

        for row in data_rows:
            cells = [c.strip() for c in row.split("|") if c.strip()]
            if cells:
                last_cell = cells[-1].strip()
                # Page numbers are typically 1-500
                if re.match(r"^\d{1,3}$", last_cell):
                    page_num_count += 1

        if data_rows and page_num_count / len(data_rows) > 0.7:
            return True

        return False

    # ========== TITLE ENRICHMENT ==========

    def _needs_title(self, chunk: Dict) -> bool:
        """Check if a table chunk needs title enrichment."""
        structured = chunk.get("structured_data")
        if isinstance(structured, dict):
            title = structured.get("title")
            return title is None or title == "" or title == "null"
        return True

    def _infer_title(self, target_chunk: Dict, all_chunks: List[Dict]) -> Optional[str]:
        """
        Infer table/chart title from surrounding text context.

        Strategy:
        1. Look for "Table X.X:" pattern in adjacent chunks on same page
        2. Look at preceding header/text chunks
        3. Fall back to hierarchy section title

        Args:
            target_chunk: The table/chart chunk needing a title
            all_chunks: All chunks in the report

        Returns:
            Inferred title string, or None
        """
        target_page = target_chunk.get("source_page_physical", -1)
        target_y = target_chunk.get("source_bbox", [0, 0, 0, 0])[1]

        # Find chunks on the same page, sorted by vertical position
        same_page = [
            c for c in all_chunks
            if c.get("source_page_physical") == target_page
            and c.get("chunk_id") != target_chunk.get("chunk_id")
        ]
        same_page.sort(key=lambda c: c.get("source_bbox", [0, 0, 0, 0])[1])

        # Strategy 1: Look for "Table X.X" pattern in chunks ABOVE this table
        table_ref_pattern = re.compile(
            r"(Table|Chart|Figure|Graph|Statement)\s+[\d\.]+[\s:.\-]+(.+)",
            re.IGNORECASE,
        )

        for c in reversed(same_page):
            c_y = c.get("source_bbox", [0, 0, 0, 0])[1]
            if c_y >= target_y:
                continue  # Skip chunks below the table

            content = c.get("content", "").strip()
            match = table_ref_pattern.match(content)
            if match:
                return match.group(0).strip()

            # Also check if it's a short text chunk just above (likely a caption)
            if (
                c.get("content_type") in ("paragraph", "header")
                and len(content) < 200
                and target_y - c_y < 50  # Within ~50 PDF units above
            ):
                return content

        # Strategy 2: Use hierarchy section title
        hierarchy = target_chunk.get("hierarchy", {})
        if hierarchy:
            # Use the deepest level
            deepest = list(hierarchy.values())[-1] if hierarchy else None
            if deepest:
                return deepest

        return None

    # ========== TABLE HYDRATION ==========

    def _hydrate_table(
        self,
        markdown: str,
        chunk: Dict,
        gemini_data: Dict,
    ) -> Optional[Dict]:
        """
        Convert Gemini's markdown output into a full StructuredTable dict.

        Uses StructuredTableExtractor (same as pdfplumber pipeline)
        then overlays Gemini metadata (title, monetary_unit, notes).

        Args:
            markdown: Gemini-extracted markdown table
            chunk: Original ChildChunk dict
            gemini_data: Raw Gemini extraction result

        Returns:
            StructuredTable dict, or None on failure
        """
        try:
            page = chunk.get("source_page_physical", 0)
            bbox = chunk.get("source_bbox", [0, 0, 100, 100])
            table_id = f"table_{page}_{int(bbox[0])}_{int(bbox[1])}"

            structured = self.structured_extractor.extract(
                markdown_table=markdown,
                table_id=table_id,
                source_chunk_id=chunk.get("chunk_id", ""),
                source_page_physical=page,
                source_bbox=bbox,
            )

            if not structured:
                return None

            result = structured.model_dump()

            # Overlay Gemini metadata
            if gemini_data.get("title"):
                result["title"] = gemini_data["title"]
            if gemini_data.get("monetary_unit"):
                result["monetary_unit"] = f"₹ in {gemini_data['monetary_unit']}"
            if gemini_data.get("extraction_notes"):
                result["_extraction_notes"] = gemini_data["extraction_notes"]
            result["_extraction_method"] = "gemini-2.5-flash"

            return result

        except Exception as e:
            logger.warning(f"Table hydration failed: {e}")
            return None

    # ========== CHART HYDRATION ==========

    def _hydrate_chart(self, chunk: Dict, gemini_data: Dict) -> Optional[Dict]:
        """
        Convert Gemini's chart extraction into a full StructuredChart dict.

        Args:
            chunk: ChildChunk dict
            gemini_data: Gemini extraction result with series, axes, etc.

        Returns:
            StructuredChart dict, or None on failure
        """
        try:
            page = chunk.get("source_page_physical", 0)
            bbox = chunk.get("source_bbox", [0, 0, 100, 100])

            # Map chart type
            chart_type_str = (gemini_data.get("chart_type") or "unknown").lower()
            chart_type_map = {
                "bar": ChartType.BAR,
                "line": ChartType.LINE,
                "pie": ChartType.PIE,
                "scatter": ChartType.SCATTER,
                "area": ChartType.AREA,
                "combo": ChartType.COMBO,
            }
            chart_type = chart_type_map.get(chart_type_str, ChartType.UNKNOWN)

            # Build series
            series_list = []
            raw_series = gemini_data.get("series") or []
            for i, s in enumerate(raw_series):
                data_points = []
                for dp in s.get("data_points") or []:
                    # Safely parse value - handle None, percentages, and non-numeric strings
                    raw_value = dp.get("value")
                    parsed_value = self._safe_parse_float(raw_value)
                    if parsed_value is None:
                        continue  # Skip data points with unparseable values
                    data_points.append(DataPoint(
                        category=str(dp.get("category") or ""),
                        value=parsed_value,
                        series=s.get("name") or f"Series {i+1}",
                    ))

                series_list.append(ChartSeries(
                    series_id=f"series_{i}",
                    series_name=s.get("name") or f"Series {i+1}",
                    data_points=data_points,
                ))

            # Detect axis types
            x_type = AxisType.CATEGORICAL
            if series_list and series_list[0].data_points:
                first_cat = series_list[0].data_points[0].category
                if re.match(r"\d{4}-\d{2}", first_cat):
                    x_type = AxisType.TEMPORAL

            # Build chart
            chart = StructuredChart(
                chart_id=f"chart_{page}_{int(bbox[0])}_{int(bbox[1])}",
                source_chunk_id=chunk.get("chunk_id", ""),
                source_page_physical=page,
                source_bbox=bbox,
                image_path=chunk.get("content", ""),
                title=gemini_data.get("title") or "Untitled Chart",
                chart_type=chart_type,
                description=gemini_data.get("description"),
                x_axis=ChartAxisConfig(
                    axis_id="x_axis",
                    axis_label=gemini_data.get("x_axis_label") or "",  # Handle None
                    axis_type=x_type,
                ),
                y_axis=ChartAxisConfig(
                    axis_id="y_axis",
                    axis_label=gemini_data.get("y_axis_label") or "",  # Handle None
                    axis_type=AxisType.NUMERIC,
                    unit=gemini_data.get("monetary_unit"),
                ),
                series=series_list,
                monetary_unit=gemini_data.get("monetary_unit"),
                extraction_method="gemini-2.5-flash-vision",
                has_structured_data=len(series_list) > 0,
                confidence=self._score_chart_confidence(gemini_data),
                extraction_notes=gemini_data.get("extraction_notes") or [],
            )

            # Extract time periods and entities from data
            all_categories = chart.get_all_categories()
            chart.time_periods = [
                c for c in all_categories
                if re.match(r"\d{4}(-\d{2,4})?|FY\s*\d{4}", c)
            ]

            return chart.model_dump()

        except Exception as e:
            logger.warning(f"Chart hydration failed: {e}")
            import traceback
            traceback.print_exc()
            return None

    # ========== HELPER METHODS ==========

    def _safe_parse_float(self, value: Any) -> Optional[float]:
        """
        Safely parse a value to float, handling None, percentages, and invalid strings.

        Args:
            value: Raw value from Gemini response (could be None, str, int, float)

        Returns:
            Parsed float or None if unparseable
        """
        if value is None:
            return None

        if isinstance(value, (int, float)):
            return float(value)

        if isinstance(value, str):
            # Strip whitespace
            value = value.strip()
            if not value:
                return None

            # Handle percentages: "55%" -> 55.0
            if value.endswith('%'):
                try:
                    return float(value[:-1])
                except ValueError:
                    return None

            # Try direct float conversion
            try:
                return float(value)
            except ValueError:
                # Value is non-numeric text like "Total", "N/A", etc.
                return None

        return None

    # ========== CONFIDENCE SCORING ==========

    def _score_table_confidence(self, chunk: Dict) -> float:
        """
        Score table extraction confidence based on multiple signals.

        Args:
            chunk: ChildChunk dict with structured_data

        Returns:
            Confidence score 0.0 - 1.0
        """
        score = 0.8  # Base score for having structured data

        structured = chunk.get("structured_data")
        if not structured or not isinstance(structured, dict):
            return 0.3  # Low confidence without structured data

        # Penalize for extraction notes/issues
        notes = structured.get("extraction_notes", structured.get("_extraction_notes", []))
        if notes:
            score -= 0.05 * len(notes)

        # Bonus for having title
        if structured.get("title"):
            score += 0.05

        # Bonus for having monetary_unit (important for CAG)
        if structured.get("monetary_unit"):
            score += 0.05

        # Check row/col counts from Gemini metadata
        row_count = structured.get("row_count", structured.get("num_rows", 0))
        if row_count < 2:
            score -= 0.2  # Very small table, might be header-only

        # Model-based scoring
        model = chunk.get("model_used", "")
        if "pdfplumber" in model:
            score += 0.1  # Native extraction gets a boost
        elif "gemini" in model.lower():
            score += 0.0  # Neutral for Gemini

        return max(0.0, min(1.0, score))

    def _score_chart_confidence(self, gemini_data: Dict) -> float:
        """
        Score chart extraction confidence.

        Args:
            gemini_data: Gemini extraction result

        Returns:
            Confidence 0.0 - 1.0
        """
        score = 0.7

        series = gemini_data.get("series") or []
        if not series:
            return 0.2

        # More data points = more confident
        total_points = sum(len(s.get("data_points") or []) for s in series)
        if total_points > 5:
            score += 0.1
        if total_points > 15:
            score += 0.05

        # Has axis labels
        if gemini_data.get("x_axis_label"):
            score += 0.05
        if gemini_data.get("y_axis_label"):
            score += 0.05

        # Penalize for extraction notes
        notes = gemini_data.get("extraction_notes") or []
        score -= 0.05 * len(notes)

        return max(0.0, min(1.0, score))

    def get_stats(self) -> Dict[str, int]:
        """Return processing statistics."""
        return self.stats.copy()

    def reset_stats(self):
        """Reset statistics counters."""
        self.stats = {k: 0 for k in self.stats}
