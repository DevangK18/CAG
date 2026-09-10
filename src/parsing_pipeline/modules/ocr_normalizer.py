"""
P2-17: OCR Normalizer for post-OCR text correction.

Fixes common OCR errors, particularly Roman numeral corruptions
in chapter headers from Tesseract OCR.
"""

import re
from typing import List, Tuple


class OcrNormalizer:
    """
    Post-OCR text normalization for common OCR errors.

    Handles Roman numeral corruptions commonly introduced by Tesseract:
    - I/l confusion: "Il" → "II", "VIl" → "VII"
    - I/T confusion: "IT" → "II", "ITI" → "III"
    """

    # Chapter Roman numeral corrections
    # IMPORTANT: Longer patterns first to avoid partial matches
    # Order matters: ITI before IT to prevent ITI being partially matched as IT+I
    CHAPTER_ROMAN_CORRECTIONS: List[Tuple[str, str]] = [
        # Three-I patterns (ITI → III, must come before IT → II)
        (r"\bCHAPTER\s+ITI\b", "CHAPTER III"),
        (r"\bChapter\s+ITI\b", "Chapter III"),
        # Two-I patterns with T (IT → II)
        (r"\bCHAPTER\s+IT\b", "CHAPTER II"),
        (r"\bChapter\s+IT\b", "Chapter II"),
        # I + lowercase L patterns
        (r"\bCHAPTER\s+Il\b", "CHAPTER II"),
        (r"\bChapter\s+Il\b", "Chapter II"),
        # VIl, VIIl patterns (trailing lowercase L)
        (r"\bCHAPTER\s+VIIl\b", "CHAPTER VIII"),
        (r"\bChapter\s+VIIl\b", "Chapter VIII"),
        (r"\bCHAPTER\s+VIl\b", "CHAPTER VII"),
        (r"\bChapter\s+VIl\b", "Chapter VII"),
        (r"\bCHAPTER\s+IVl\b", "CHAPTER IV"),
        (r"\bChapter\s+IVl\b", "Chapter IV"),
        # X patterns with lowercase L
        (r"\bCHAPTER\s+XIl\b", "CHAPTER XII"),
        (r"\bChapter\s+XIl\b", "Chapter XII"),
        (r"\bCHAPTER\s+Xl\b", "CHAPTER XI"),
        (r"\bChapter\s+Xl\b", "Chapter XI"),
        # XIIl pattern
        (r"\bCHAPTER\s+XIIl\b", "CHAPTER XIII"),
        (r"\bChapter\s+XIIl\b", "Chapter XIII"),
    ]

    # Ordinal corrections (Finance Commission context)
    ORDINAL_CORRECTIONS: List[Tuple[str, str]] = [
        # "144 CFC" → "14th CFC" (4 misread as 44)
        (r"\b(\d)44\s+CFC\b", r"\g<1>4th CFC"),
        # "155 CFC" → "15th CFC"
        (r"\b(\d)55\s+CFC\b", r"\g<1>5th CFC"),
    ]

    def __init__(self):
        """Compile regex patterns for efficiency."""
        self._chapter_patterns = [
            (re.compile(pattern), replacement)
            for pattern, replacement in self.CHAPTER_ROMAN_CORRECTIONS
        ]
        self._ordinal_patterns = [
            (re.compile(pattern), replacement)
            for pattern, replacement in self.ORDINAL_CORRECTIONS
        ]

    def normalize_headers(self, text: str) -> str:
        """
        Apply OCR corrections to text.

        Args:
            text: Input text potentially containing OCR errors

        Returns:
            Corrected text
        """
        if not text:
            return text

        result = text

        # Apply chapter Roman numeral corrections
        for pattern, replacement in self._chapter_patterns:
            result = pattern.sub(replacement, result)

        # Apply ordinal corrections
        for pattern, replacement in self._ordinal_patterns:
            result = pattern.sub(replacement, result)

        return result

    def normalize_toc_entry(self, toc_entry: str) -> str:
        """
        Normalize a TOC entry (parent chunk title).

        This is the same as normalize_headers but provides
        semantic clarity for the use case.

        Args:
            toc_entry: TOC entry text

        Returns:
            Corrected TOC entry
        """
        return self.normalize_headers(toc_entry)


# Module-level singleton for convenience
_normalizer = None


def get_ocr_normalizer() -> OcrNormalizer:
    """Get singleton OcrNormalizer instance."""
    global _normalizer
    if _normalizer is None:
        _normalizer = OcrNormalizer()
    return _normalizer
