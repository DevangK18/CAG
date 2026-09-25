"""
TextExtractor: Precision text extraction using PyMuPDF bounding box clipping.
Handles all textual content types: paragraphs, headers, lists, footnotes, etc.
"""

import logging

import fitz  # PyMuPDF
from typing import List, Optional
import re

from src.core.data_contracts import ExtractedContent
from src.parsing_pipeline.extractors.text_repair import (
    build_vocabulary,
    is_letter_spaced,
    is_reversed,
    repair_font_shift,
    respace_letter_spaced,
    reverse_words,
)
from src.parsing_pipeline.modules.ocr_normalizer import get_ocr_normalizer


logger = logging.getLogger(__name__)

class TextExtractor:
    """
    Extracts precise textual content from PDF bounding boxes using PyMuPDF's clip parameter.
    Handles text normalization and content type classification.
    """

    def __init__(self):
        """Initialize with text processing patterns."""
        self._vocab_cache = {}
        logger.info("TextExtractor initialized with PyMuPDF text extraction.")

    def _vocabulary(self, pdf_path: str):
        """Word frequencies of the report's normally spaced pages (for re-spacing)."""
        if pdf_path not in self._vocab_cache:
            with fitz.open(pdf_path) as doc:
                pages = [page.get_text("text") for page in doc]
            self._vocab_cache = {
                pdf_path: build_vocabulary(" ".join(t for t in pages if not is_letter_spaced(t)))
            }
        return self._vocab_cache[pdf_path]

    def _normalize_text(self, text: str) -> str:
        """
        Normalize extracted text: ligatures, hyphenation, whitespace, artifacts.

        Args:
            text: Raw text extracted from PDF.

        Returns:
            Cleaned and normalized text.
        """

        if not text:
            return ""

        # Step 1: Ligature replacement
        ligature_map = {
            "ﬀ": "ff",
            "ﬁ": "fi",
            "ﬂ": "fl",
            "ﬃ": "ffi",
            "ﬄ": "ffl",
            "Ɵ": "ti",  # Common OCR artifact
            "ﬆ": "st",
            "œ": "oe",
            "æ": "ae",
            "Œ": "OE",
            "Æ": "AE",
        }

        for ligature, replacement in ligature_map.items():
            text = text.replace(ligature, replacement)

        # Step 2: Unicode normalization for special characters
        special_chars = {
            "\u200b": "",  # Zero-width space
            "\u00ad": "",  # Soft hyphen
            "\ufeff": "",  # BOM
            "\u00a0": " ",  # Non-breaking space
            "–": "-",  # En dash
            "—": "-",  # Em dash
            '"': '"',  # Left double quote
            '"': '"',  # Right double quote
            """: "'",          # Left single quote
            """: "'",  # Right single quote
            "…": "...",  # Ellipsis
            "′": "'",  # Prime
            "″": '"',  # Double prime
        }

        for char, replacement in special_chars.items():
            text = text.replace(char, replacement)

        # Step 3: Rejoin hyphenated words at line breaks
        text = re.sub(r"-\s*\n\s*", "", text)  # Remove hyphen + newline

        # Step 4: Normalize whitespace
        text = re.sub(r"\s+", " ", text)

        # Step 5: Clean up common OCR artifacts
        text = re.sub(r"\s+([.,;:!?])", r"\1", text)  # Remove space before punctuation

        return text.strip()

    def _classify_content_type(self, layout_label: str, text: str) -> str:
        """
        Map DocLayNet layout labels to internal content type classifications.

        Args:
            layout_label: Original DocLayNet label from LayoutAnalysisService.
            text: The normalized text content.

        Returns:
            Internal content type: 'paragraph', 'header', or 'list'.
        """
        # Direct mappings based on label
        if "header" in layout_label.lower() or "title" in layout_label.lower():
            return "header"

        if "list" in layout_label.lower() or "list-item" in layout_label.lower():
            return "list"

        if "footnote" in layout_label.lower():
            return "paragraph"  # Footnotes treated as regular paragraphs

        # Default for all other text elements
        return "paragraph"

    def _get_page_rotation(self, page) -> int:
        """
        P1-11: Get effective page rotation (0, 90, 180, 270).

        Args:
            page: PyMuPDF page object.

        Returns:
            Rotation angle normalized to 0, 90, 180, or 270.
        """
        return page.rotation % 360

    def _extract_text_with_rotation_handling(
        self, page, clip_rect: fitz.Rect, sort: bool = True
    ) -> str:
        """
        Extract text from a clip region, handling rotated pages.

        Docling reports boxes in the displayed (rotated) page space, while PyMuPDF
        clips in unrotated space. Mapping the clip through the derotation matrix
        gives correct text and reading order for 90/180/270 pages; the previous
        span-reversal approach cut words at column edges ("ple Sig cur inte").

        Args:
            page: PyMuPDF page object.
            clip_rect: Clipping rectangle in displayed page coordinates.
            sort: Whether to sort text by position.

        Returns:
            Extracted text.
        """
        if self._get_page_rotation(page):
            clip_rect = fitz.Rect(clip_rect) * page.derotation_matrix
        return page.get_text("text", clip=clip_rect, sort=sort)

    def _detect_reversed_content(self, text: str) -> bool:
        """D9-FIX: Detect word-reversed text (see text_repair.is_reversed)."""
        return is_reversed(text)

    def _reverse_text_content(self, text: str) -> str:
        """C2 fix: Reverse each word back, preserving lines and punctuation."""
        return reverse_words(text)

    def _extract_text_from_bbox(
        self, pdf_path: str, page_num: int, bbox: List[float]
    ) -> tuple:
        """
        Extract text precisely from within a bounding box using PyMuPDF's clip parameter.

        Args:
            pdf_path: Path to the PDF document.
            page_num: Zero-indexed page number.
            bbox: [x0, y0, x1, y1] coordinates in PDF space.

        Returns:
            Tuple of (extracted_text, rotation_angle).

        Raises:
            ValueError: If PDF access fails or bounding box is invalid.
        """
        if len(bbox) != 4:
            raise ValueError(
                f"Bounding box must have 4 coordinates, got {len(bbox)}: {bbox}"
            )

        doc = fitz.open(pdf_path)

        try:
            page = doc.load_page(page_num)

            # Create clipping rectangle from bounding box
            clip_rect = fitz.Rect(bbox)

            # P1-11: Get page rotation
            rotation = self._get_page_rotation(page)

            # P1-11: Use rotation-aware text extraction
            text = self._extract_text_with_rotation_handling(page, clip_rect, sort=True)

            return text, rotation

        except Exception as e:
            doc.close()
            raise ValueError(f"Failed to extract text from PDF: {str(e)}") from e
        finally:
            doc.close()

    def extract(
        self, pdf_path: str, page_num: int, bbox: List[float], **kwargs
    ) -> Optional[ExtractedContent]:
        """Main extraction method for textual content."""
        try:
            # Extract raw text from bounding box (P1-11: returns tuple with rotation)
            raw_text, rotation = self._extract_text_from_bbox(pdf_path, page_num, bbox)

            # Normalize text (hyphenation, whitespace)
            normalized_text = self._normalize_text(raw_text)

            # Decode lines set in fonts whose glyphs are shifted 29 code points low
            normalized_text = repair_font_shift(normalized_text)


            # P2-17: Apply OCR header normalization (fixes Roman numeral corruptions)
            normalized_text = get_ocr_normalizer().normalize_headers(normalized_text)

            # C2 + M3 fix: Detect and recover reversed text content
            # This handles cases where:
            # 1. Page has reversed characters without rotation metadata (rotation == 0)
            # 2. Rotation handling didn't fully fix the text (rotated pages)
            # Apply detection as a final fallback for all pages
            content_was_reversed = False
            if self._detect_reversed_content(normalized_text):
                logger.debug(f"C2/M3: Detected reversed content on page {page_num} (rotation={rotation}), applying correction")
                normalized_text = self._reverse_text_content(normalized_text)
                content_was_reversed = True

            # Rejoin text whose PDF text layer has spaces between letters
            if is_letter_spaced(normalized_text):
                normalized_text = respace_letter_spaced(normalized_text, self._vocabulary(pdf_path))

            # Skip if no meaningful text was extracted
            if not normalized_text or normalized_text.isspace():
                return None

            # Classify content type based on layout label
            layout_label = kwargs.get("label", "Text")
            content_type = self._classify_content_type(layout_label, normalized_text)

            # P1-11: Log rotation for debugging if non-zero
            if rotation != 0:
                logger.debug(f"P1-11: Extracted text from rotated page {page_num} (rotation={rotation})")

            # Create ExtractedContent object
            # P1-11: Include rotation in structured_data if non-zero
            # C2: Include content_reversed flag if text was reversed
            structured_data = None
            if rotation != 0 or content_was_reversed:
                structured_data = {}
                if rotation != 0:
                    structured_data["page_rotation"] = rotation
                if content_was_reversed:
                    structured_data["content_reversed"] = True

            return ExtractedContent(
                content_type=content_type,
                content=normalized_text,
                source_page_physical=page_num,
                source_bbox=bbox,
                model_used="PyMuPDF-clip",
                layout_label=layout_label,
                layout_confidence=kwargs.get("confidence"),
                structured_data=structured_data,
                # C3 fix: Add extraction_method for provenance tracking
                extraction_method="pymupdf-text",
            )

        except Exception as e:
            logger.error(f"Text extraction failed on page {page_num}: {e}")
            import traceback

            traceback.print_exc()
            return None
