"""
TextExtractor: Precision text extraction using PyMuPDF bounding box clipping.
Handles all textual content types: paragraphs, headers, lists, footnotes, etc.
"""

import fitz  # PyMuPDF
from typing import List, Optional
import re

from src.core.data_contracts import ExtractedContent


class TextExtractor:
    """
    Extracts precise textual content from PDF bounding boxes using PyMuPDF's clip parameter.
    Handles text normalization and content type classification.
    """

    def __init__(self):
        """Initialize with text processing patterns."""
        print("TextExtractor initialized with PyMuPDF text extraction.")

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

    def _extract_text_from_bbox(
        self, pdf_path: str, page_num: int, bbox: List[float]
    ) -> str:
        """
        Extract text precisely from within a bounding box using PyMuPDF's clip parameter.

        Args:
            pdf_path: Path to the PDF document.
            page_num: Zero-indexed page number.
            bbox: [x0, y0, x1, y1] coordinates in PDF space.

        Returns:
            Extracted text from within the bounding box.

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

            # Extract text only within the clipping rectangle
            text = page.get_text("text", clip=clip_rect, sort=True)

            return text

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
            # Extract raw text from bounding box
            raw_text = self._extract_text_from_bbox(pdf_path, page_num, bbox)

            # Normalize text (hyphenation, whitespace)
            normalized_text = self._normalize_text(raw_text)

            # Skip if no meaningful text was extracted
            if not normalized_text or normalized_text.isspace():
                return None

            # Classify content type based on layout label
            layout_label = kwargs.get("label", "Text")
            content_type = self._classify_content_type(layout_label, normalized_text)

            # Create ExtractedContent object
            return ExtractedContent(
                content_type=content_type,
                content=normalized_text,
                source_page_physical=page_num,
                source_bbox=bbox,
                model_used="PyMuPDF-clip",
                layout_label=layout_label,
                layout_confidence=kwargs.get("confidence"),
            )

        except Exception as e:
            print(f"Text extraction failed on page {page_num}: {e}")
            import traceback

            traceback.print_exc()
            return None
