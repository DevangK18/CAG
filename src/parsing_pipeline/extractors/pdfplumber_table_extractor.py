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

import io
import logging
import os
import re
import threading
from collections import Counter
from typing import List, Optional, Dict, Any, Tuple

import fitz  # PyMuPDF
import pdfplumber

from src.core.data_contracts import ExtractedContent
from src.parsing_pipeline.extractors.text_repair import (
    FORWARD_WORDS,
    REVERSED_WORDS,
    decode_cid_shift,
    has_cid_shift,
    is_reversed,
    is_rupee_font,
    repair_font_shift,
    repair_rupee_backtick,
)
from src.parsing_pipeline.extractors.text_repair import _WORD_RE as WORD_RE
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

        # B-6-12: the document is opened once, and the current page's words, vocabulary
        # and orientation are computed once, not per table
        self._lock = threading.Lock()
        self._doc_key: Optional[Tuple[str, float]] = None
        self._pdf = None
        self._fitz_doc = None
        self._page_num: Optional[int] = None
        self._page_state: Optional[Dict[str, Any]] = None
        logger.info("PdfplumberTableExtractor initialized (no GPU required)")

    def shutdown(self):
        """Close the cached document."""
        self.close()

    def close(self):
        """Release the cached document and page (call after each report)."""
        with self._lock:
            self._release_page()
            for doc in (self._pdf, self._fitz_doc):
                if doc is not None:
                    try:
                        doc.close()
                    except Exception:
                        pass
            self._pdf = self._fitz_doc = None
            self._doc_key = None

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
                    f"skipping (falls through to Docling, Tier 2)"
                )
                return None

            # Step 3: Convert to markdown
            markdown_table = self._to_markdown(raw_table)
            if not markdown_table:
                return None

            # Step 4: Generate StructuredTable JSON
            structured_data = self._build_structured_data(
                markdown_table, page_num, bbox,
                source_chunk_id=kwargs.get("source_chunk_id") or "temp",
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
        with self._lock:
            state = self._get_page_state(pdf_path, page_num)
            if state is None:
                return None, ""
            return self._extract_from_page(state, page_num, bbox)

    def _extract_from_page(
        self, state: Dict[str, Any], page_num: int, bbox: List[float]
    ) -> Tuple[Optional[List[List[str]]], str]:
        # pdfplumber returns rotated pages' text in reversed order and in unrotated
        # coordinates; leave those tables to Docling (Tier 2), which handles rotation
        rotation = state["rotation"]
        if rotation != 0:
            logger.debug(f"Table on rotated page {page_num} (rotation={rotation}°): deferring to Docling")
            return None, ""

        # B-6-05: a landscape table typeset sideways on a /Rotate 0 page is read from
        # an upright copy of the page, with the bbox moved into its coordinates
        page = state["page"]
        if state["upright_page"] is not None:
            page = state["upright_page"]
            bbox = self._upright_bbox(bbox, state["direction"], state["width"], state["height"])

        # Crop to Docling's bounding box
        # pdfplumber uses (x0, top, x1, bottom) — same as our [x0, y0, x1, y1]
        crop_box = (
            max(0, bbox[0] - 2),  # small margin for edge tables
            max(0, bbox[1] - 2),
            min(page.width, bbox[2] + 2),
            min(page.height, bbox[3] + 2),
        )
        if crop_box[2] <= crop_box[0] or crop_box[3] <= crop_box[1]:
            return None, ""
        cropped = page.crop(crop_box)

        # Attempt 1: ruling lines and rectangle edges (CAG tables are ruled). Some tables
        # rule only the title/header, so "lines" can return a fragment: keep it only if
        # it covers the region's text, else take whichever strategy covers more.
        region_tokens = self._tokens(cropped.extract_text() or "")
        candidates = []
        tables = cropped.find_tables(table_settings=self.TABLE_SETTINGS)
        if tables:
            # B-6-12: several tables in one bbox are not concatenated into one
            raw = self._best_table(tables, region_tokens)
            if raw and self._has_meaningful_data(raw):
                candidates.append((self._coverage(raw, region_tokens), 1, raw, "lines"))

        # Attempt 2: text-based fallback (for borderless tables)
        if not candidates or candidates[0][0] < 0.9:
            tables_fb = cropped.find_tables(table_settings=self.TABLE_SETTINGS_FALLBACK)
            if tables_fb:
                # Whitespace columns cut words ("Typ | e"); stitch them back
                raw = self._stitch_split_cells(
                    self._best_table(tables_fb, region_tokens), state["vocabulary"]
                )
                if raw and self._has_meaningful_data(raw):
                    candidates.append((self._coverage(raw, region_tokens), 0, raw, "text_fallback"))

        if candidates:
            # Prefer ruling lines unless the whitespace strategy captures clearly more
            best = max(candidates, key=lambda c: (round(c[0] + 0.05 * c[1], 2), c[1]))
            # Text on the upright copy is known to read forwards
            check_reversal = state["upright_page"] is None
            return self._clean_raw_table(best[2], rotation, check_reversal), best[3]

        return None, ""

    def _best_table(self, tables, region_tokens: List[str]) -> List[List[Optional[str]]]:
        """
        The table in the region, from pdfplumber's tables found there.

        Tables that follow each other with the same width or the same left and right
        edges are one table cut by a gap in the ruling and are joined; otherwise the
        one covering most of the region's text is kept (B-6-12: different tables are
        no longer concatenated). Tables nested in another are dropped first.
        """
        # Header cells drawn as filled rectangles come back as small tables inside
        # the real one; their text is already in it
        def inside(a, b) -> bool:
            return a is not b and a.bbox[0] >= b.bbox[0] - 1 and a.bbox[1] >= b.bbox[1] - 1 \
                and a.bbox[2] <= b.bbox[2] + 1 and a.bbox[3] <= b.bbox[3] + 1
        tables = [t for t in tables if not any(inside(t, other) for other in tables)]

        groups: List[List[List[Optional[str]]]] = []
        width = None
        extent = None
        for table in sorted(tables, key=lambda t: t.bbox[1]):
            raw = self._drop_empty_lines(table.extract())
            if not raw:
                continue
            raw_width = max(len(row) for row in raw)
            same_extent = extent is not None and abs(table.bbox[0] - extent[0]) <= 3 \
                and abs(table.bbox[2] - extent[1]) <= 3
            if groups and (raw_width == width or same_extent):
                groups[-1].extend(raw)
            else:
                groups.append(list(raw))
            width, extent = raw_width, (table.bbox[0], table.bbox[2])
        if not groups:
            return []
        if len(groups) > 1:
            logger.debug(f"pdfplumber: {len(groups)} tables in one region; keeping the best")
        best = max(groups, key=lambda raw: (self._coverage(raw, region_tokens), len(raw)))
        # Joined pieces can differ in width: pad to a rectangle
        width = max(len(row) for row in best)
        return [list(row) + [None] * (width - len(row)) for row in best]

    # ========== DOCUMENT AND PAGE CACHE ==========

    def _get_page_state(self, pdf_path: str, page_num: int) -> Optional[Dict[str, Any]]:
        """Open the document once per report and analyse each page once."""
        try:
            key = (str(pdf_path), os.path.getmtime(pdf_path))
        except OSError:
            key = (str(pdf_path), 0.0)
        if key != self._doc_key:
            self._release_page()
            for doc in (self._pdf, self._fitz_doc):
                if doc is not None:
                    doc.close()
            self._pdf = pdfplumber.open(pdf_path)
            self._fitz_doc = None
            self._doc_key = key

        if page_num >= len(self._pdf.pages):
            logger.error(f"Page {page_num} out of range (PDF has {len(self._pdf.pages)} pages)")
            return None
        if self._page_num == page_num and self._page_state is not None:
            return self._page_state

        self._release_page()
        page = self._pdf.pages[page_num]
        rotation = page.rotation % 360
        state: Dict[str, Any] = {
            "page": page,
            "rotation": rotation,
            "direction": 0,
            "upright_page": None,
            "upright_pdf": None,
            "width": float(page.width),
            "height": float(page.height),
            "vocabulary": None,
        }
        if rotation == 0:
            direction = self._vertical_direction(pdf_path, page_num)
            if direction:
                upright_pdf = self._upright_copy(page_num, direction)
                if upright_pdf is not None:
                    state.update(
                        direction=direction,
                        upright_pdf=upright_pdf,
                        upright_page=upright_pdf.pages[0],
                    )
        text_page = state["upright_page"] or page
        self._mark_chars(text_page)
        state["vocabulary"] = set(re.findall(r"[a-z]+", (text_page.extract_text() or "").lower()))
        self._page_num, self._page_state = page_num, state
        return state

    @staticmethod
    def _mark_chars(page) -> None:
        """
        Character fixes before cells are read (B-6-19, B-6-06): a raised small digit
        right after a letter is a footnote marker and becomes "[^N]", so "Taxes2"
        reads "Taxes[^2]"; a backtick in a Rupee font is the rupee sign.
        """
        chars = page.chars
        i = 0
        while i < len(chars):
            c = chars[i]
            if c.get("text") == "`" and is_rupee_font(c.get("fontname")):
                c["text"] = "₹"
            prev = chars[i - 1] if i else None
            if (
                prev is not None
                and c.get("text", "").isdigit()
                and prev.get("text", "").isalpha()
                and c.get("size", 0) < 0.8 * prev.get("size", 0)
                and c.get("bottom", 0) < prev.get("bottom", 0) - 0.15 * prev.get("size", 0)
                and not (prev["text"] == "m" and i > 1 and not chars[i - 2].get("text", "").isalpha())
            ):
                j = i
                while (
                    j + 1 < len(chars)
                    and chars[j + 1].get("text", "").isdigit()
                    and abs(chars[j + 1].get("size", 0) - c.get("size", 0)) < 0.5
                ):
                    j += 1
                digits = "".join(chars[k]["text"] for k in range(i, j + 1))
                c["text"] = f"[^{digits}]"
                for k in range(i + 1, j + 1):
                    chars[k]["text"] = ""
                i = j + 1
                continue
            i += 1

    def _release_page(self):
        """Free the cached page's parsed objects and its upright copy."""
        state, self._page_state, self._page_num = self._page_state, None, None
        if not state:
            return
        if state.get("upright_pdf") is not None:
            try:
                state["upright_pdf"].close()
            except Exception:
                pass
        try:
            state["page"].close()
        except Exception:
            pass

    def _vertical_direction(self, pdf_path: str, page_num: int) -> int:
        """
        B-6-05: -1 if most of the page's text runs bottom-to-top (dir ≈ (0,-1)), +1 if
        top-to-bottom (dir ≈ (0,1)), 0 if the text is horizontal.
        """
        try:
            if self._fitz_doc is None:
                self._fitz_doc = fitz.open(pdf_path)
            blocks = self._fitz_doc[page_num].get_text("dict")["blocks"]
        except Exception as e:
            logger.debug(f"Orientation check failed on page {page_num}: {e}")
            return 0
        return self._dominant_vertical_direction(blocks)

    @staticmethod
    def _dominant_vertical_direction(blocks: List[Dict[str, Any]]) -> int:
        """Direction of the vertical text if over half of the characters are vertical."""
        total = 0
        by_direction = {-1: 0, 1: 0}
        for block in blocks:
            for line in block.get("lines", []):
                chars = sum(len(span.get("text", "").strip()) for span in line.get("spans", []))
                total += chars
                dx, dy = line.get("dir", (1.0, 0.0))
                if abs(dx) < 0.1 and abs(abs(dy) - 1) < 0.1:
                    by_direction[1 if dy > 0 else -1] += chars
        if not total:
            return 0
        direction = max(by_direction, key=by_direction.get)
        return direction if by_direction[direction] > total * 0.5 else 0

    def _upright_copy(self, page_num: int, direction: int):
        """A one-page pdfplumber document with the page turned so its text reads left to right."""
        try:
            src = self._fitz_doc
            rect = src[page_num].rect
            out = fitz.open()
            new_page = out.new_page(width=rect.height, height=rect.width)
            # Text running upwards is turned clockwise; downwards, anticlockwise
            new_page.show_pdf_page(new_page.rect, src, page_num, rotate=-90 if direction < 0 else 90)
            data = out.tobytes()
            out.close()
            return pdfplumber.open(io.BytesIO(data))
        except Exception as e:
            logger.warning(f"Could not derotate page {page_num}: {e}")
            return None

    @staticmethod
    def _upright_bbox(bbox: List[float], direction: int, width: float, height: float) -> List[float]:
        """Move a top-left-origin bbox from the sideways page into the upright copy."""
        x0, y0, x1, y1 = bbox
        if direction < 0:
            # (x, y) -> (H - y, x)
            return [height - y1, x0, height - y0, x1]
        # (x, y) -> (y, W - x)
        return [y0, width - x1, y1, width - x0]

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
        self, raw: List[List[Optional[str]]], rotation: int = 0, check_reversal: bool = True
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
        needs_reversal = check_reversal and is_reversed(table_text)
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
                    text = repair_rupee_backtick(repair_font_shift(text))
                    if needs_reversal and text:
                        text = self._reverse_cell_text(text)
                    elif not check_reversal and self._cell_reads_backwards(text):
                        # Header cells set vertically inside an already sideways table
                        # still read backwards on the upright copy (BR p.194)
                        text = text[::-1]
                    cleaned_row.append(text)
            cleaned.append(cleaned_row)
        # Cells holding only decoded spaces leave empty rows/columns
        return self._drop_empty_lines(cleaned) or cleaned

    @staticmethod
    def _cell_reads_backwards(text: str) -> bool:
        """A cell of two or more words with more reversed stop words than forward ones."""
        tokens = [t.lower() for t in WORD_RE.findall(text or "")]
        if len(tokens) < 2:
            return False
        backwards = sum(t in REVERSED_WORDS for t in tokens)
        return backwards >= 1 and backwards > sum(t in FORWARD_WORDS for t in tokens)

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

        # B-6-12: a pipe inside a cell would shift every later column when re-parsed
        def line(row: List[str]) -> str:
            return " | ".join(str(cell).replace("|", "\\|") for cell in row)

        # Header row
        header = line(padded[0])

        # Separator
        separator = " | ".join(["---"] * num_cols)

        # Data rows
        body_rows = []
        for row in padded[1:]:
            body_rows.append(f"| {line(row)} |")

        if body_rows:
            return f"| {header} |\n| {separator} |\n" + "\n".join(body_rows)
        else:
            return f"| {header} |\n| {separator} |"

    # ========== STRUCTURED DATA ==========

    def _build_structured_data(
        self, markdown_table: str, page_num: int, bbox: List[float], source_chunk_id: str = "temp"
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
                source_chunk_id=source_chunk_id,
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
