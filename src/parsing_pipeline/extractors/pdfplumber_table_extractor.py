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
from typing import List, Optional, Dict, Any, Tuple

import pdfplumber
from pathlib import Path

from src.core.data_contracts import ExtractedContent
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
        # CAG tables are typically ruled (have visible lines/borders)
        self.TABLE_SETTINGS = {
            "vertical_strategy": "lines_strict",
            "horizontal_strategy": "lines_strict",
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

        Tries lines_strict first (best for ruled tables), then falls back
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

            # B3 fix: Get page rotation for text reversal handling
            rotation = page.rotation % 360
            if rotation != 0:
                logger.debug(f"B3: Table on rotated page {page_num} (rotation={rotation}°)")

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

            # Attempt 1: lines_strict (best for ruled CAG tables)
            tables = cropped.find_tables(table_settings=self.TABLE_SETTINGS)

            if tables:
                raw = tables[0].extract()
                if raw and self._has_meaningful_data(raw):
                    return self._clean_raw_table(raw, rotation), "lines_strict"

            # Attempt 2: text-based fallback (for borderless tables)
            tables_fb = cropped.find_tables(
                table_settings=self.TABLE_SETTINGS_FALLBACK
            )

            if tables_fb:
                raw = tables_fb[0].extract()
                if raw and self._has_meaningful_data(raw):
                    return self._clean_raw_table(raw, rotation), "text_fallback"

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

    # D9-FIX: Reversed word patterns for content-baked reversal detection
    # These are common English words reversed - their reversed forms are rare/invalid
    REVERSED_PATTERNS = {
        "eht", "dna", "rof", "htiw", "morf", "evah", "siht", "taht", "erew", "neeb",
        "elbaliava", "tegduB", "troper", "tidua", "hkal", "erorc",
        "tnemnrevoG", "tnemtrapeD", "yrtsinim", "detroper", "devresbo", "dehsilbuP", "toN",
    }

    def _detect_cell_reversal(self, text: str) -> bool:
        """
        D9-FIX: Detect if cell text is reversed (content-baked reversal).

        Checks for known reversed patterns in the text.

        Args:
            text: Cell text to check

        Returns:
            True if text appears to be reversed
        """
        if not text or len(text) < 3:
            return False

        text_lower = text.lower()
        # Check for any known reversed pattern
        for pattern in self.REVERSED_PATTERNS:
            if pattern.lower() in text_lower:
                return True
        return False

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
        # D9-FIX: First pass - detect if table has reversed content (check sample cells)
        # Sample a few non-empty cells to check for reversal
        sample_texts = []
        for row in raw[:min(5, len(raw))]:
            for cell in row:
                if cell and len(cell.strip()) > 5:
                    sample_texts.append(cell)
                    if len(sample_texts) >= 10:
                        break
            if len(sample_texts) >= 10:
                break

        # Check if any sample cells have reversed patterns
        needs_reversal = rotation == 270 or rotation == 180
        if not needs_reversal and sample_texts:
            for sample in sample_texts:
                if self._detect_cell_reversal(sample):
                    needs_reversal = True
                    logger.debug("D9-FIX: Detected content-baked reversal in table")
                    break

        cleaned = []
        for row in raw:
            cleaned_row = []
            for cell in row:
                if cell is None:
                    cleaned_row.append("")
                else:
                    # Normalize whitespace (pdfplumber preserves newlines within cells)
                    text = " ".join(cell.split())
                    # Strip common artifacts
                    text = text.strip("| \t")
                    # B3 fix: For rotated pages or D9 content-baked reversal
                    if needs_reversal and text:
                        text = self._reverse_cell_text(text)
                    cleaned_row.append(text)
            cleaned.append(cleaned_row)
        return cleaned

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
