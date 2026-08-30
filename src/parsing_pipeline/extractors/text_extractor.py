"""
TextExtractor: Precision text extraction using PyMuPDF bounding box clipping.
Handles all textual content types: paragraphs, headers, lists, footnotes, etc.
"""

import logging

import fitz  # PyMuPDF
from typing import List, Optional
import re

from src.core.data_contracts import ExtractedContent
from src.parsing_pipeline.modules.ocr_normalizer import get_ocr_normalizer


logger = logging.getLogger(__name__)

class TextExtractor:
    """
    Extracts precise textual content from PDF bounding boxes using PyMuPDF's clip parameter.
    Handles text normalization and content type classification.
    """

    def __init__(self):
        """Initialize with text processing patterns."""
        logger.info("TextExtractor initialized with PyMuPDF text extraction.")

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
        P1-11 + M3: Extract text handling rotated pages.

        For 90°/270° rotated pages, use dict-based extraction to get
        proper reading order, then filter by clip region.

        M3 fix: Improved handling for all rotation cases including 180°.

        Args:
            page: PyMuPDF page object.
            clip_rect: Clipping rectangle for extraction.
            sort: Whether to sort text by position.

        Returns:
            Extracted text with proper reading order.
        """
        rotation = self._get_page_rotation(page)

        if rotation == 0:
            return page.get_text("text", clip=clip_rect, sort=sort)

        if rotation in (90, 270):
            # Use "dict" extraction which provides block/line/span structure
            blocks = page.get_text("dict", clip=clip_rect)["blocks"]

            # Extract text from blocks
            text_parts = []
            for block in blocks:
                if block["type"] == 0:  # Text block
                    for line in block["lines"]:
                        if rotation == 270:
                            # M3: Reverse each SPAN with word-boundary awareness
                            # First try simple character reversal
                            reversed_spans = []
                            for span in line["spans"]:
                                span_text = span["text"]
                                # If span contains multiple words, reverse each word individually
                                if ' ' in span_text:
                                    reversed_spans.append(' '.join(word[::-1] for word in span_text.split()))
                                else:
                                    reversed_spans.append(span_text[::-1])
                            line_text = " ".join(reversed_spans)
                        else:  # 90°
                            line_text = " ".join(span["text"] for span in line["spans"])
                        text_parts.append(line_text)

            return "\n".join(text_parts)

        if rotation == 180:
            # M3: For 180° rotation, text may appear upside down
            # PyMuPDF usually handles this, but if text is still reversed,
            # the _detect_reversed_content fallback will catch it
            text = page.get_text("text", clip=clip_rect, sort=sort)

            # Check if the text looks reversed (upside down text reads backwards)
            if self._detect_reversed_content(text):
                logger.debug(f"M3: Detected reversed content on 180° rotated page, applying correction")
                return self._reverse_text_content(text)

            return text

        # Fallback for unexpected rotation values
        return page.get_text("text", clip=clip_rect, sort=sort)

    # D9-FIX: Common reversed word patterns found in CAG reports
    # These are reversed versions of common English words that appear in audit reports
    # The reversed forms are RARE/NON-EXISTENT as valid English words
    # REMEDIATION §3.5: Expanded patterns for education/audit domain
    REVERSED_WORD_PATTERNS = {
        # Common functional words (high frequency in any English text)
        "eht",      # the
        "dna",      # and (also DNA but rare standalone)
        "rof",      # for
        "htiw",     # with
        "morf",     # from
        "evah",     # have
        "siht",     # this
        "taht",     # that
        "erew",     # were
        "neeb",     # been
        # CAG-specific vocabulary (high frequency in audit reports)
        "elbaliava",   # available
        "tegduB",      # Budget
        "tnemucoD",    # Document
        "troper",      # report
        "tidua",       # audit
        "hkal",        # lakh (Indian unit)
        "erorc",       # crore (Indian unit)
        "tnemnrevoG",  # Government
        "tnemtrapeD",  # Department
        "yrtsinim",    # ministry
        "detroper",    # reported
        "devresbo",    # observed
        "dehsilbuP",   # Published
        "toN",         # Not (with capital)
        # REMEDIATION §3.5: Education domain (OD_2025_05 p152 fix)
        "stneduts",    # students - key word from OD p152
        "loohcs",      # school
        "noitacude",   # education
        "srehcaet",    # teachers
        "gniniart",    # training
        "seiticapac",  # capacities
        "margorp",     # program
        "semmargorP",  # Programmes
        # REMEDIATION §3.5: Audit/finance domain
        "tcirtsid",    # district
        "gnidneps",    # spending
        "deviecer",    # received
        "detubirtsid", # distributed
        "noitatnemelp",# implementation (partial)
        "tnemeganam",  # management
        "erutidnepxe", # expenditure
        "secruoser",   # resources
        "seitivitca",  # activities
        "stifeneb",    # benefits
        "serudecorp",  # procedures
        "stnuocca",    # accounts
        "ecnanif",     # finance
        "sdnuf",       # funds
        "tneiciffe",   # efficient
        # Note: Don't add short common words that are valid both ways (saw/was, ton/not)
    }

    def _detect_reversed_content(self, text: str) -> bool:
        """
        D9-FIX: Detect content-reversed text (no rotation metadata but reversed characters).

        Two-pronged detection:
        1. Pattern matching: Look for known reversed word patterns common in CAG reports
        2. Structural heuristic: Unusual lowercase+uppercase transitions (reversed proper nouns)

        Returns True if either signal is strong enough.
        """
        if len(text) < 20:
            return False

        text_lower = text.lower()
        words = text.split()

        # D9-FIX: Check for known reversed patterns
        # If we find ANY of the characteristic reversed patterns, flag as reversed
        # REMEDIATION §3.5: More aggressive detection with expanded pattern set
        reversed_pattern_count = 0
        matched_patterns = []
        for pattern in self.REVERSED_WORD_PATTERNS:
            # Case-insensitive search for the pattern
            if pattern.lower() in text_lower:
                reversed_pattern_count += 1
                matched_patterns.append(pattern)
                # If we find 2+ different reversed patterns, high confidence
                if reversed_pattern_count >= 2:
                    logger.debug(f"D9: Detected multiple reversed patterns: {matched_patterns}")
                    return True

        # REMEDIATION §3.5: Lower threshold from 50 to 30 chars for single-pattern detection
        # Single pattern match with length check (avoid false positives on short text)
        if reversed_pattern_count >= 1 and len(text) >= 30:
            logger.debug(f"D9: Detected reversed pattern '{matched_patterns[0]}' in text (len={len(text)})")
            return True

        # Original heuristic: lowercase followed by uppercase (reversed proper nouns)
        # This catches Indian proper names like "gnarabaN" (Nabarang)
        reversed_caps_pattern = re.findall(r'[a-z][A-Z]', text)
        if len(words) > 3 and len(reversed_caps_pattern) / len(words) > 0.3:
            logger.debug(f"D9: Detected reversed proper nouns in text")
            return True

        return False

    def _reverse_text_content(self, text: str) -> str:
        """
        C2 fix: Reverse word-level content to recover readable text.

        When text is detected as reversed (e.g., "stneduts" instead of "students"),
        this method reverses each word while preserving whitespace and line structure.

        Args:
            text: Reversed text content

        Returns:
            Corrected text with words reversed back to normal
        """
        lines = text.split('\n')
        corrected_lines = []

        for line in lines:
            # Split line into words and non-word tokens (preserve spacing/punctuation)
            words = line.split()
            corrected_words = []

            for word in words:
                # Preserve leading/trailing punctuation
                leading_punct = ""
                trailing_punct = ""

                # Extract leading punctuation
                while word and not word[0].isalnum():
                    leading_punct += word[0]
                    word = word[1:]

                # Extract trailing punctuation
                while word and not word[-1].isalnum():
                    trailing_punct = word[-1] + trailing_punct
                    word = word[:-1]

                # Reverse the core word
                reversed_word = word[::-1] if word else ""

                # Reconstruct with punctuation
                corrected_words.append(leading_punct + reversed_word + trailing_punct)

            corrected_lines.append(' '.join(corrected_words))

        return '\n'.join(corrected_lines)

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
