"""
PdfplumberTableExtractor: High-accuracy table extraction for native-text PDFs.

Drop-in replacement for TableExtractor (TATR + Tesseract).
Uses pdfplumber's text-stream parsing for native PDFs — no OCR needed.

Tier 1 in the hybrid extraction strategy:
  Tier 1: pdfplumber (native PDFs) — this file
  Tier 2: Docling TableFormer ACCURATE (scanned PDFs) — layout_analysis_service.py
  Tier 3: Gemini 2.5 Flash Vision (fallback) — gemini_visual_extractor.py

Interface matches TableExtractor exactly:
  - __init__()
  - extract(pdf_path, page_num, bbox, **kwargs) -> Optional[ExtractedContent]
  - shutdown()
"""

import logging
import re
from collections import Counter
from typing import List, Optional, Dict, Any, Tuple

import pdfplumber
from pathlib import Path

from src.core.data_contracts import ExtractedContent
from src.parsing_pipeline.extractors.text_repair import (
    decode_cid_shift,
    has_cid_shift,
    is_reversed,
    repair_font_shift,
)
from src.parsing_pipeline.modules.structured_table_extractor import StructuredTableExtractor
from src.parsing_pipeline.config import get_config, ContentExtractionConfig

logger = logging.getLogger(__name__)


class PdfplumberTableExtractor:
    """
    Extracts tables from native-text PDFs using pdfplumber's text-stream parser.

    No ML models, no OCR — reads PDF text streams directly.
    Produces markdown + StructuredTable JSON, with confidence scoring.

    CAG-tuned settings loaded from configuration.
    """

    def __init__(self, config: Optional[ContentExtractionConfig] = None):
        """Initialize the pdfplumber table extractor with configuration."""
        # Load from config if not provided
        if config is None:
            config = get_config().content_extraction

        self.config = config

        # pdfplumber table_settings tuned for CAG audit reports
        # CAG tables are ruled, but the rules are drawn as thin filled rectangles, not
        # line objects: "lines_strict" ignores rect edges and found almost no tables,
        # leaving the whitespace fallback to split words across columns.
        self.TABLE_SETTINGS = {
            "vertical_strategy": "lines",
            "horizontal_strategy": "lines",
            "snap_tolerance": config.pdfplumber_snap_tolerance,
            "snap_x_tolerance": config.pdfplumber_snap_tolerance,
            "snap_y_tolerance": config.pdfplumber_snap_tolerance,
            "join_tolerance": config.pdfplumber_join_tolerance,
            "join_x_tolerance": config.pdfplumber_join_tolerance,
            "join_y_tolerance": config.pdfplumber_join_tolerance,
            "min_words_vertical": 1,
            "min_words_horizontal": 1,
        }

        # Fallback settings for tables without strong ruling lines
        self.TABLE_SETTINGS_FALLBACK = {
            "vertical_strategy": "text",
            "horizontal_strategy": "lines",
            "snap_tolerance": config.pdfplumber_snap_tolerance,
            "join_tolerance": config.pdfplumber_join_tolerance,
            "min_words_vertical": 2,
            "min_words_horizontal": 1,
        }

        self.structured_extractor = StructuredTableExtractor()
        logger.info("PdfplumberTableExtractor initialized (no GPU required)")

    def shutdown(self):
        """No-op: pdfplumber has no persistent resources to clean up."""
        pass

    def extract(
        self, pdf_path: str, page_num: int, bbox: List[float], **kwargs
    ) -> Optional[ExtractedContent]:
        """
        Extract table from PDF page within bounding box.

        Args:
            pdf_path: Path to source PDF.
            page_num: 0-indexed physical page number.
            bbox: [x0, y0, x1, y1] bounding box from Docling layout analysis.
            **kwargs: label, confidence, report_id from router.

        Returns:
            ExtractedContent with markdown table + structured_data, or None.
        """
        try:
            # Step 1: Extract raw 2D grid from PDF text stream
            raw_table, extraction_method = self._extract_table_data(
                pdf_path, page_num, bbox
            )

            if raw_table is None:
                logger.warning(
                    f"pdfplumber: No table found on page {page_num} at bbox {bbox}"
                )
                return None

            # Step 2: Validate extraction quality
            confidence = self._compute_confidence(raw_table)

            if confidence < self.config.table_min_confidence:
                logger.warning(
                    f"pdfplumber: Low confidence ({confidence:.2f}) on page {page_num}, "
                    f"skipping (will fall through to Tier 3)"
                )
                return None

            # Step 3: Convert to markdown
            markdown_table = self._to_markdown(raw_table)
            if not markdown_table:
                return None

            # Step 4: Generate StructuredTable JSON
            structured_data = self._build_structured_data(
                markdown_table, page_num, bbox
            )

            # Step 5: Build ExtractedContent
            model_tag = f"pdfplumber-{extraction_method}"

            return ExtractedContent(
                content_type="table_markdown",
                content=markdown_table,
                source_page_physical=page_num,
                source_bbox=bbox,
                model_used=model_tag,
                layout_label=kwargs.get("label", "Table"),
                layout_confidence=kwargs.get("confidence"),
                structured_data=structured_data,
                # P1-14b: Populate extraction_method for visual asset registry
                extraction_method=f"pdfplumber-{extraction_method}",
                extraction_confidence=confidence,
            )

        except Exception as e:
            logger.error(f"pdfplumber extraction failed on page {page_num}: {e}")
            import traceback
            traceback.print_exc()
            return None

    # ========== CORE EXTRACTION ==========

    def _extract_table_data(
        self, pdf_path: str, page_num: int, bbox: List[float]
    ) -> Tuple[Optional[List[List[str]]], str]:
        """
        Extract table cells from PDF using pdfplumber.

        Tries ruling lines and rect edges first (CAG tables are ruled), then falls back
        to text-based detection.

        Args:
            pdf_path: PDF file path
            page_num: 0-indexed page number
            bbox: [x0, y0, x1, y1] Docling bounding box

        Returns:
            Tuple of (2D list of cell strings, extraction_method) or (None, "")
        """
        with pdfplumber.open(pdf_path) as pdf:
            if page_num >= len(pdf.pages):
                logger.error(
                    f"Page {page_num} out of range (PDF has {len(pdf.pages)} pages)"
                )
                return None, ""

            page = pdf.pages[page_num]

            # pdfplumber returns rotated pages' text in reversed order and in unrotated
            # coordinates; leave those tables to Docling (Tier 2), which handles rotation
            rotation = page.rotation % 360
            if rotation != 0:
                logger.debug(f"Table on rotated page {page_num} (rotation={rotation}°): deferring to Docling")
                return None, ""

            # Crop to Docling's bounding box
            # pdfplumber uses (x0, top, x1, bottom) — same as our [x0, y0, x1, y1]
            cropped = page.crop(
                (
                    max(0, bbox[0] - 2),  # small margin for edge tables
                    max(0, bbox[1] - 2),
                    min(page.width, bbox[2] + 2),
                    min(page.height, bbox[3] + 2),
                )
            )

            # Attempt 1: ruling lines and rectangle edges (CAG tables are ruled). Some tables
            # rule only the title/header, so "lines" can return a fragment: keep it only if
            # it covers the region's text, else take whichever strategy covers more.
            region_tokens = self._tokens(cropped.extract_text() or "")
            candidates = []
            tables = cropped.find_tables(table_settings=self.TABLE_SETTINGS)
            if tables:
                # Double rules and merged cells leave empty columns/rows; drop them
                # before judging fill ratio, or valid tables get rejected
                raw = self._drop_empty_lines([row for t in tables for row in t.extract()])
                if raw and self._has_meaningful_data(raw):
                    candidates.append((self._coverage(raw, region_tokens), 1, raw, "lines"))

            # Attempt 2: text-based fallback (for borderless tables)
            if not candidates or candidates[0][0] < 0.9:
                tables_fb = cropped.find_tables(table_settings=self.TABLE_SETTINGS_FALLBACK)
                if tables_fb:
                    # Whitespace columns cut words ("Typ | e"); stitch them back
                    vocabulary = set(re.findall(r"[a-z]+", (page.extract_text() or "").lower()))
                    raw = self._stitch_split_cells(
                        self._drop_empty_lines(tables_fb[0].extract()), vocabulary
                    )
                    if raw and self._has_meaningful_data(raw):
                        candidates.append((self._coverage(raw, region_tokens), 0, raw, "text_fallback"))

            if candidates:
                # Prefer ruling lines unless the whitespace strategy captures clearly more
                best = max(candidates, key=lambda c: (round(c[0] + 0.05 * c[1], 2), c[1]))
                return self._clean_raw_table(best[2], rotation), best[3]

            # Attempt 3: Extract ALL text as single-column if table was detected
            # by Docling but pdfplumber can't parse structure
            text = cropped.extract_text()
            if text and len(text.strip()) > 20:
                # Return as single-column pseudo-table for downstream Tier 3
                logger.info(
                    f"pdfplumber: No table structure found, returning raw text for page {page_num}"
                )
                return None, ""

            return None, ""

    @staticmethod
    def _tokens(text: str) -> List[str]:
        """Data values of a table region (amounts, counts); words if it has none."""
        numbers = re.findall(r"\d[\d,]*\.\d+|\d{1,3}(?:,\d{2,3})+|\d{3,}", text)
        return numbers if len(numbers) >= 5 else re.findall(r"[A-Za-z]{3,}", text)

    def _coverage(self, raw: List[List[Optional[str]]], region_tokens: List[str]) -> float:
        """Share of the region's words/numbers that ended up in the table cells."""
        if not region_tokens:
            return 1.0
        cells_text = " ".join(cell or "" for row in raw for cell in row)
        found = Counter(re.findall(r"\d[\d,]*\.\d+|\d{1,3}(?:,\d{2,3})+|\d{3,}|[A-Za-z]{3,}", cells_text))
        expected = Counter(region_tokens)
        return sum(min(n, found[t]) for t, n in expected.items()) / sum(expected.values())

    @staticmethod
    def _stitch_split_cells(raw: List[List[Optional[str]]], vocabulary: set) -> List[List[Optional[str]]]:
        """
        Move word fragments back into the cell they were cut from.

        The whitespace strategy places column boundaries inside words ("Activity Typ" |
        "e of Non-") and fiscal years ("20" | "17-18 20"). A fragment moves left when the
        joined word appears on the page and neither piece does on its own.
        """
        stitched = []
        for row in raw:
            cells = [c or "" for c in row]
            for i in range(len(cells) - 1):
                left, right = cells[i], cells[i + 1]
                word = re.search(r"([A-Za-z]+)$", left)
                fragment = re.match(r"([a-z]{1,8})\b", right)
                if word and fragment:
                    joined = (word.group(1) + fragment.group(1)).lower()
                    if (
                        joined in vocabulary
                        and word.group(1).lower() not in vocabulary
                        and fragment.group(1) not in vocabulary
                    ):
                        cells[i] = left + fragment.group(1)
                        cells[i + 1] = right[fragment.end():].lstrip()
                        continue
                century = re.search(r"(?:^|\s)(19|20)$", left)
                if century and re.match(r"\d{2}-\d{2}", right):
                    cells[i] = left[:century.start(1)].rstrip()
                    cells[i + 1] = century.group(1) + right
            stitched.append([c if c else None for c in cells])
        return stitched

    @staticmethod
    def _drop_empty_lines(raw: Optional[List[List[Optional[str]]]]) -> List[List[Optional[str]]]:
        """Remove rows and columns whose cells are all empty."""
        if not raw:
            return []
        filled = lambda cell: cell is not None and cell.strip() != ""
        rows = [row for row in raw if any(filled(c) for c in row)]
        if not rows:
            return []
        width = max(len(row) for row in rows)
        keep = [i for i in range(width) if any(i < len(row) and filled(row[i]) for row in rows)]
        return [[row[i] if i < len(row) else None for i in keep] for row in rows]

    def _reverse_cell_text(self, text: str) -> str:
        """
        D9-FIX: Reverse each word in cell text to recover original.

        Preserves punctuation and spacing while reversing word characters.

        Args:
            text: Reversed cell text

        Returns:
            Corrected text with each word reversed back
        """
        words = text.split()
        corrected = []
        for word in words:
            # Preserve leading/trailing punctuation
            leading = ""
            trailing = ""
            while word and not word[0].isalnum():
                leading += word[0]
                word = word[1:]
            while word and not word[-1].isalnum():
                trailing = word[-1] + trailing
                word = word[:-1]
            # Reverse the core word
            corrected.append(leading + word[::-1] + trailing)
        return " ".join(corrected)

    def _clean_raw_table(
        self, raw: List[List[Optional[str]]], rotation: int = 0
    ) -> List[List[str]]:
        """
        Clean pdfplumber's raw extraction output.

        Handles None cells, normalizes whitespace, strips artifacts.
        B3 fix: Handles rotated pages by reversing cell text.
        D9-FIX: Detects and corrects content-baked reversal (no rotation metadata).

        Args:
            raw: pdfplumber's extract() output (may contain None)
            rotation: Page rotation angle (0, 90, 180, 270)

        Returns:
            Cleaned 2D list of strings
        """
        # D9-FIX: Decide reversal on the whole table's text. A single-cell substring
        # check reversed whole tables because "Profit" contains "rof".
        table_text = " ".join(cell for row in raw for cell in row if cell)
        needs_cid_decode = has_cid_shift(table_text)
        if needs_cid_decode:
            table_text = decode_cid_shift(table_text)
        needs_reversal = is_reversed(table_text)
        if needs_reversal:
            logger.debug("D9-FIX: Detected content-baked reversal in table")

        cleaned = []
        for row in raw:
            cleaned_row = []
            for cell in row:
                if cell is None:
                    cleaned_row.append("")
                else:
                    if needs_cid_decode:
                        cell = decode_cid_shift(cell)
                    # Normalize whitespace (pdfplumber preserves newlines within cells)
                    text = " ".join(cell.split())
                    # Strip common artifacts
                    text = text.strip("| \t")
                    text = repair_font_shift(text)
                    if needs_reversal and text:
                        text = self._reverse_cell_text(text)
                    cleaned_row.append(text)
            cleaned.append(cleaned_row)
        # Cells holding only decoded spaces leave empty rows/columns
        return self._drop_empty_lines(cleaned) or cleaned

    def _has_meaningful_data(self, raw: List[List[Optional[str]]]) -> bool:
        """
        Check if extraction produced meaningful content (not just empty cells).

        Args:
            raw: pdfplumber's raw output

        Returns:
            True if table has enough non-empty cells
        """
        if not raw or len(raw) < 2:
            return False

        total_cells = sum(len(row) for row in raw)
        non_empty = sum(
            1 for row in raw for cell in row
            if cell is not None and cell.strip()
        )

        if total_cells == 0:
            return False

        fill_ratio = non_empty / total_cells
        return (fill_ratio > self.config.table_fill_ratio_threshold and
                non_empty >= self.config.table_min_non_empty_cells)

    # ========== CONFIDENCE SCORING ==========

    def _compute_confidence(self, table: List[List[str]]) -> float:
        """
        Compute extraction confidence score.

        Factors:
        - Empty cell ratio (penalize >50% empty)
        - Column consistency (penalize irregular col counts)
        - Numeric data presence (CAG tables are heavily numeric)

        Args:
            table: Cleaned 2D list of cell strings

        Returns:
            Confidence score 0.0 - 1.0
        """
        if not table or len(table) < 2:
            return 0.0

        score = 1.0

        # Factor 1: Empty cell ratio
        total_cells = sum(len(row) for row in table)
        empty_cells = sum(1 for row in table for cell in row if not cell.strip())
        empty_ratio = empty_cells / total_cells if total_cells > 0 else 1.0

        if empty_ratio > self.config.table_empty_ratio_penalty_threshold:
            score -= 0.4

        # Factor 2: Column consistency
        col_counts = [len(row) for row in table]
        if col_counts:
            most_common = max(set(col_counts), key=col_counts.count)
            consistent = sum(1 for c in col_counts if c == most_common)
            consistency = consistent / len(col_counts)

            if consistency < self.config.table_column_consistency_threshold:
                score -= 0.3

        # Factor 3: Numeric data presence (data rows only, skip header)
        data_rows = table[1:] if len(table) > 1 else table
        all_data_cells = [
            cell for row in data_rows for cell in row if cell.strip()
        ]

        if all_data_cells:
            numeric_count = sum(
                1 for cell in all_data_cells
                if self._looks_numeric(cell)
            )
            numeric_ratio = numeric_count / len(all_data_cells)

            # CAG tables should have some numbers
            if numeric_ratio < self.config.table_numeric_ratio_threshold:
                score -= 0.2

        return max(0.0, min(1.0, score))

    def _looks_numeric(self, text: str) -> bool:
        """Check if cell text looks numeric (numbers, currency, percentages)."""
        import re
        cleaned = text.strip().replace(",", "").replace("₹", "").replace("`", "")
        # Match: plain numbers, negative in parens, percentages, fiscal years
        return bool(re.match(
            r'^[\-\(]?\d+[\.\d]*\)?%?$|^\d{4}-\d{2,4}$',
            cleaned
        ))

    # ========== MARKDOWN GENERATION ==========

    def _to_markdown(self, table: List[List[str]]) -> str:
        """
        Convert 2D list to GitHub-flavored markdown table.

        Args:
            table: Cleaned 2D list of cell strings

        Returns:
            Markdown table string, or empty string on failure
        """
        if not table or not any(len(row) > 0 for row in table):
            return ""

        # Normalize column count
        num_cols = max(len(row) for row in table)
        padded = []
        for row in table:
            padded_row = list(row)
            while len(padded_row) < num_cols:
                padded_row.append("")
            padded.append(padded_row)

        # Header row
        header = " | ".join(str(cell) for cell in padded[0])

        # Separator
        separator = " | ".join(["---"] * num_cols)

        # Data rows
        body_rows = []
        for row in padded[1:]:
            body_row = " | ".join(str(cell) for cell in row)
            body_rows.append(f"| {body_row} |")

        if body_rows:
            return f"| {header} |\n| {separator} |\n" + "\n".join(body_rows)
        else:
            return f"| {header} |\n| {separator} |"

    # ========== STRUCTURED DATA ==========

    def _build_structured_data(
        self, markdown_table: str, page_num: int, bbox: List[float]
    ) -> Optional[Dict[str, Any]]:
        """
        Generate StructuredTable JSON from markdown.

        Delegates to StructuredTableExtractor (same as old TableExtractor).

        Args:
            markdown_table: Markdown table string
            page_num: 0-indexed page number
            bbox: Bounding box

        Returns:
            StructuredTable dict or None
        """
        try:
            table_id = f"table_{page_num}_{int(bbox[0])}_{int(bbox[1])}"

            structured_table = self.structured_extractor.extract(
                markdown_table=markdown_table,
                table_id=table_id,
                source_chunk_id="temp",  # Set during chunking phase
                source_page_physical=page_num,
                source_bbox=bbox,
            )

            if structured_table:
                return structured_table.model_dump()

        except Exception as e:
            logger.warning(
                f"Structured extraction failed for table on page {page_num}: {e}"
            )

        return None
