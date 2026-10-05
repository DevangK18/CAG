"""
VisualPostProcessor: Quality gate and enrichment for extracted table/chart data.

Phase 10c in the pipeline — runs after Gemini visual extraction (Phase 10b).

Responsibilities:
1. Contents tables: flags contents lists in the front matter parsed as tables
2. Table captions: a printed "Table/Statement N.N" caption above a table becomes its
   caption and title and is put in front of its text
3. StructuredTable Hydration: Tier-3 crops' Gemini markdown → StructuredTable rows
4. StructuredChart Hydration: Converts Gemini chart output → full StructuredChart JSON
5. Confidence Scoring: postprocess_confidence (Phase 8's extraction_confidence is kept)

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
from typing import List, Dict, Optional, Any

from src.core.chart_contracts import (
    StructuredChart,
    ChartType,
    ChartAxisConfig,
    ChartSeries,
    DataPoint,
    AxisType,
)
from src.parsing_pipeline.modules.structured_table_extractor import (
    StructuredTableExtractor,
)
from src.batch_pipeline.enrichment.gemini_visual_extractor import (
    GeminiVisualExtractor,
    PHASE6_IMAGE_KEYS,
    build_chart_text,
    chunk_image_path,
    has_chart_values,
)

logger = logging.getLogger(__name__)


class VisualPostProcessor:
    """
    Post-processes Gemini visual extraction results for quality and consistency.
    """

    # Opening of the first chapter: "CHAPTER 1", "Chapter-I", "Chapter I: ..."
    CHAPTER_ONE_RE = re.compile(r"^\s*chapter\s*[-–:.]?\s*(?:1|i|one)\b(?![.\d])", re.I)
    # Without a chapter heading, front matter is taken as this share of the pages
    FRONT_MATTER_SHARE = 0.12
    FRONT_MATTER_MAX_SHARE = 0.25
    FRONT_MATTER_MIN_PAGES = 8

    # Printed page reference in a contents row: "137", "vii", "vii-x", "12-15"
    PAGE_REF_RE = re.compile(
        r"^(\d{1,4}|[ivxlc]{1,7})(?:\s*[-–]\s*(?:\d{1,4}|[ivxlc]{1,7}))?$", re.I
    )
    SECTION_NUMBER_RE = re.compile(
        r"^\(?(?:\d+(?:\.\d+)*|[ivxlc]{1,6}|[a-z])\)?\.?$", re.I
    )
    TOC_MAX_DROP_SHARE = 0.1
    SEPARATOR_ROW_RE = re.compile(r"^\|?[\s:|-]*-{3,}[\s:|-]*$")

    # A printed table caption: "Table 3.2: Details of grants", "Statement 1.1 ..."
    TABLE_CAPTION_RE = re.compile(
        r"^\s*(?:table|statement)\s*(?:no\.?\s*)?[\dIVX]+(?:[.\-]\d+)*[A-Za-z]?\b",
        re.I,
    )
    # A caption more than this far (pt) above a table belongs to something else
    CAPTION_MAX_GAP = 80

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
        report_ctx = self._report_context(data)
        by_page: Dict[Any, List[Dict]] = {}
        for chunk in chunks:
            by_page.setdefault(chunk.get("source_page_physical"), []).append(chunk)

        for chunk in chunks:
            content_type = chunk.get("content_type", "")
            structured_data = chunk.get("structured_data")

            # === TABLE POST-PROCESSING ===
            if content_type == "table_markdown":
                self.stats["tables_processed"] += 1

                # Step 1: contents tables are flagged, not deleted; Phase 8's
                # extraction_confidence is left alone
                is_toc = self._is_toc_table(chunk, report_ctx)
                if isinstance(structured_data, dict):
                    if is_toc:
                        structured_data["_filtered_reason"] = "toc_detected"
                    elif structured_data.pop("_filtered_reason", None):
                        modified = True
                if is_toc:
                    chunk["postprocess_confidence"] = 0.05
                    self.stats["tables_filtered_toc"] += 1
                    file_stats["filtered"] += 1
                    modified = True
                    continue

                # Step 2: Tier-3 crops carry Gemini markdown; parse it into rows
                if isinstance(structured_data, dict):
                    gemini_markdown = structured_data.get("markdown")
                    if gemini_markdown and not structured_data.get("rows"):
                        hydrated = self._hydrate_table(
                            gemini_markdown, chunk, structured_data
                        )
                        if hydrated:
                            chunk["structured_data"] = structured_data = hydrated
                            if gemini_markdown not in (chunk.get("content") or ""):
                                chunk["content"] = gemini_markdown
                            self.stats["tables_hydrated"] += 1
                            file_stats["hydrated"] += 1
                            modified = True

                # Step 3: a printed "Table N.N" caption reaches caption, title and text
                if self._needs_title(chunk):
                    caption = self._infer_title(chunk, by_page)
                    if caption:
                        self._apply_caption(chunk, caption)
                        self.stats["titles_enriched"] += 1
                        file_stats["titles"] += 1
                        modified = True

                # Step 4: 10c's own score, kept apart from Phase 8's
                confidence = self._score_table_confidence(chunk)
                if chunk.get("postprocess_confidence") != confidence:
                    chunk["postprocess_confidence"] = confidence
                    modified = True

            # === CHART POST-PROCESSING ===
            elif content_type in ("chart_data_path", "image_caption"):
                if not structured_data or not isinstance(structured_data, dict):
                    continue

                self.stats["charts_processed"] += 1

                # Hydrate Gemini chart output → StructuredChart
                if structured_data.get("series") and not structured_data.get(
                    "chart_id"
                ):
                    hydrated = self._hydrate_chart(chunk, structured_data)
                    if hydrated:
                        chunk["structured_data"] = hydrated
                        structured_data = hydrated
                        self.stats["charts_hydrated"] += 1
                        modified = True

                # Output hydrated before PR 7 has the values only in structured_data
                if structured_data.get("series") and not has_chart_values(
                    chunk.get("content")
                ):
                    content = build_chart_text(
                        chunk.get("content") or "",
                        None,
                        structured_data["series"],
                        structured_data.get("monetary_unit"),
                    )
                    if content != chunk.get("content"):
                        chunk["content"] = content
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

    def _report_context(self, data: Dict) -> Dict[str, int]:
        """Page count and the first page after the front matter."""
        chunks = data.get("child_chunks", [])
        pages = [
            c.get("source_page_physical")
            for c in chunks
            if isinstance(c.get("source_page_physical"), int)
        ]
        page_count = max(pages) + 1 if pages else 0
        cap = max(
            self.FRONT_MATTER_MIN_PAGES, int(page_count * self.FRONT_MATTER_MAX_SHARE)
        )

        # First chapter opening: a short heading. Parent titles are not used: parents
        # built from contents lists or bookmarks start on the contents page itself.
        starts = [
            c.get("source_page_physical")
            for c in chunks
            if c.get("content_type") in ("header", "paragraph")
            and len((c.get("content") or "").strip()) <= 80
            and self.CHAPTER_ONE_RE.match(c.get("content") or "")
        ]
        # Pages 0-1 are covers; a match there is a title, not the chapter itself
        starts = [p for p in starts if isinstance(p, int) and p >= 2]
        if starts:
            end = min(starts)
        else:
            end = max(
                self.FRONT_MATTER_MIN_PAGES, int(page_count * self.FRONT_MATTER_SHARE)
            )
        return {"front_matter_end": min(end, cap), "page_count": page_count}

    @classmethod
    def _table_rows(cls, markdown: str) -> List[List[str]]:
        """Non-empty cells of each markdown row, separator rows dropped."""
        rows = []
        for line in (markdown or "").split("\n"):
            line = line.strip()
            if "|" not in line or cls.SEPARATOR_ROW_RE.match(line):
                continue
            cells = [c.strip() for c in line.strip("|").split("|")]
            cells = [c for c in cells if c]
            if cells:
                rows.append(cells)
        return rows

    @classmethod
    def _page_number(cls, cell: str) -> Optional[int]:
        """First arabic page of a page reference; 0 for roman (front-matter) pages."""
        match = cls.PAGE_REF_RE.match(cell.strip())
        if not match:
            return None
        start = match.group(1)
        return int(start) if start.isdigit() else 0

    def _is_toc_table(self, chunk: Dict, report_ctx: Optional[Dict] = None) -> bool:
        """
        A table of contents (or list of tables/appendices) parsed as a table.

        All three must hold:
        1. the table is in the front matter (before the first chapter page);
        2. the last column holds page references, arabic ones within the page count
           and non-decreasing (one stray row, or 10%, tolerated);
        3. the first column holds titles or section numbers, not years or amounts.
        Counts, percentages and small integers in data tables fail 1 or 2.
        """
        ctx = report_ctx or {}
        page = chunk.get("source_page_physical")
        if not isinstance(page, int) or page >= ctx.get("front_matter_end", 0):
            return False

        structured = chunk.get("structured_data")
        markdown = chunk.get("content") or ""
        if isinstance(structured, dict) and structured.get("markdown"):
            markdown = structured["markdown"]
        rows = [r for r in self._table_rows(markdown) if len(r) >= 2]
        body = rows[1:]  # first row is the header
        refs = [(r, self._page_number(r[-1])) for r in body]
        refs = [(r, n) for r, n in refs if n is not None]
        if len(refs) < 3 or len(refs) < 0.6 * len(body):
            return False

        arabic = [n for _, n in refs if n]
        page_count = ctx.get("page_count") or 0
        if page_count and any(n > page_count for n in arabic):
            return False
        # Docling sometimes splices a stray row (e.g. an appendix entry) into a
        # contents list; a data column of counts goes down far more often
        drops = sum(1 for a, b in zip(arabic, arabic[1:]) if b < a)
        if drops > max(1, self.TOC_MAX_DROP_SHARE * (len(arabic) - 1)):
            return False

        def title_like(cell: str) -> bool:
            return bool(re.search(r"[A-Za-z]{3}", cell)) or bool(
                self.SECTION_NUMBER_RE.match(cell)
            )

        titled = sum(1 for r, _ in refs if title_like(r[0]))
        return titled >= 0.6 * len(refs)

    # ========== TITLE ENRICHMENT ==========

    def _needs_title(self, chunk: Dict) -> bool:
        """Check if a table chunk has neither a caption nor a title."""
        structured = chunk.get("structured_data")
        if isinstance(structured, dict):
            if structured.get("caption"):
                return False
            title = structured.get("title")
            return title is None or title == "" or title == "null"
        return True

    def _infer_title(
        self, target_chunk: Dict, by_page: Dict[Any, List[Dict]]
    ) -> Optional[str]:
        """
        The printed "Table/Statement N.N" caption just above a table, or None.

        Walks up from the table, nearest first, within CAPTION_MAX_GAP; stops at
        another table or figure, whose caption that would be. Unit lines such as
        "(₹ in crore)" between caption and table are passed over.
        """
        target_bbox = GeminiVisualExtractor._chunk_bbox(target_chunk)
        if not target_bbox:
            return None
        above = []
        for c in by_page.get(target_chunk.get("source_page_physical"), []):
            if c is target_chunk:
                continue
            bbox = GeminiVisualExtractor._chunk_bbox(c)
            if not bbox or bbox[3] > target_bbox[1] + 5:
                continue
            gap = target_bbox[1] - bbox[3]
            if gap <= self.CAPTION_MAX_GAP:
                above.append((gap, c))
        above.sort(key=lambda item: item[0])

        for _, c in above:
            if c.get("content_type") in (
                "table_markdown",
                "image_caption",
                "chart_data_path",
            ):
                break
            content = (c.get("content") or "").strip()
            if len(content) <= 300 and self.TABLE_CAPTION_RE.match(content):
                return content
        return None

    @staticmethod
    def _apply_caption(chunk: Dict, caption: str) -> None:
        """Store the caption on the table and put it in front of the searchable text."""
        structured = chunk.get("structured_data")
        if isinstance(structured, dict):
            if not structured.get("caption"):
                structured["caption"] = caption
            if structured.get("title") in (None, "", "null"):
                structured["title"] = caption
        content = chunk.get("content") or ""
        if caption not in content:
            chunk["content"] = f"{caption}\n\n{content}" if content else caption

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
            bbox = GeminiVisualExtractor._chunk_bbox(chunk) or [0, 0, 100, 100]
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
            if gemini_data.get("title") or gemini_data.get("caption"):
                result["title"] = gemini_data.get("title") or gemini_data["caption"]
            unit = str(gemini_data.get("monetary_unit") or "").strip()
            if unit and unit.lower() not in ("null", "none"):
                result["monetary_unit"] = unit if "₹" in unit else f"₹ in {unit}"
            # Phase 6 and 10b fields of the crop stay with the table
            for key in (*PHASE6_IMAGE_KEYS, "table_number", "gemini_extracted"):
                if key in gemini_data and result.get(key) is None:
                    result[key] = gemini_data[key]
            if gemini_data.get("extraction_notes"):
                result["_extraction_notes"] = gemini_data["extraction_notes"]
            result["_extraction_method"] = chunk.get("extraction_method") or "gemini"

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
                    data_points.append(
                        DataPoint(
                            category=str(dp.get("category") or ""),
                            value=parsed_value,
                            series=s.get("name") or f"Series {i+1}",
                        )
                    )

                series_list.append(
                    ChartSeries(
                        series_id=f"series_{i}",
                        series_name=s.get("name") or f"Series {i+1}",
                        data_points=data_points,
                    )
                )

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
                image_path=gemini_data.get("image_path")
                or chunk_image_path(chunk)
                or "",
                title=gemini_data.get("title")
                or gemini_data.get("caption")
                or "Untitled Chart",
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
                extraction_method=chunk.get("extraction_method") or "gemini",
                has_structured_data=len(series_list) > 0,
                confidence=self._score_chart_confidence(gemini_data),
                extraction_notes=gemini_data.get("extraction_notes") or [],
            )

            # Extract time periods and entities from data
            all_categories = chart.get_all_categories()
            chart.time_periods = [
                c for c in all_categories if re.match(r"\d{4}(-\d{2,4})?|FY\s*\d{4}", c)
            ]

            result = chart.model_dump()
            # Keep the Phase 6 fields (subtype, caption, text layer) next to the chart
            for key in PHASE6_IMAGE_KEYS:
                if key in gemini_data and result.get(key) is None:
                    result[key] = gemini_data[key]
            return result

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
            if value.endswith("%"):
                try:
                    return float(value[:-1])
                except ValueError:
                    return None

            # Try direct float conversion; Indian grouping commas and ₹ are not part of it
            try:
                return float(value.replace(",", "").replace("₹", "").strip())
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
        notes = structured.get(
            "extraction_notes", structured.get("_extraction_notes", [])
        )
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
