"""
P2-17: Unit tests for OCR header normalization.

Tests for Roman numeral corruption fixes in chapter headers
from Tesseract OCR output.
"""

import pytest
from src.parsing_pipeline.modules.ocr_normalizer import OcrNormalizer, get_ocr_normalizer


@pytest.fixture
def normalizer():
    """Create an OcrNormalizer instance."""
    return OcrNormalizer()


class TestChapterRomanNumeralCorrectionsP217:
    """P2-17: Test chapter Roman numeral OCR corrections."""

    def test_chapter_iti_corrected(self, normalizer):
        """P2-17: 'CHAPTER ITI' should be corrected to 'CHAPTER III'."""
        result = normalizer.normalize_headers("CHAPTER ITI Overview of Findings")

        assert result == "CHAPTER III Overview of Findings"

    def test_chapter_it_corrected(self, normalizer):
        """P2-17: 'CHAPTER IT' should be corrected to 'CHAPTER II' (distinct from ITI)."""
        result = normalizer.normalize_headers("CHAPTER IT Compliance Audit")

        assert result == "CHAPTER II Compliance Audit"

    def test_chapter_il_corrected(self, normalizer):
        """P2-17: 'CHAPTER Il' (I + lowercase L) should be corrected to 'CHAPTER II'."""
        result = normalizer.normalize_headers("CHAPTER Il Revenue Receipts")

        assert result == "CHAPTER II Revenue Receipts"

    def test_chapter_vii_l_corrected(self, normalizer):
        """P2-17: 'CHAPTER VIl' should be corrected to 'CHAPTER VII'."""
        result = normalizer.normalize_headers("CHAPTER VIl Audit Observations")

        assert result == "CHAPTER VII Audit Observations"

    def test_chapter_viii_l_corrected(self, normalizer):
        """P2-17: 'CHAPTER VIIl' should be corrected to 'CHAPTER VIII'."""
        result = normalizer.normalize_headers("CHAPTER VIIl General")

        assert result == "CHAPTER VIII General"

    def test_correct_chapter_unchanged(self, normalizer):
        """P2-17: Correctly formatted chapters should remain unchanged."""
        result = normalizer.normalize_headers("CHAPTER III Compliance Audit")

        assert result == "CHAPTER III Compliance Audit"

    def test_non_chapter_text_unchanged(self, normalizer):
        """P2-17: Regular text without chapter patterns should not be modified."""
        text = "The audit covered IT systems and ITI training programs."
        result = normalizer.normalize_headers(text)

        # IT and ITI in regular context should NOT be changed
        assert result == text

    def test_mixed_case_chapter(self, normalizer):
        """P2-17: Mixed case 'Chapter ITI' should also be corrected."""
        result = normalizer.normalize_headers("Chapter ITI Overview")

        assert result == "Chapter III Overview"

    def test_chapter_with_title(self, normalizer):
        """P2-17: Chapter with additional title text should be corrected."""
        result = normalizer.normalize_headers("CHAPTER ITI: Financial Audit of Railways")

        assert result == "CHAPTER III: Financial Audit of Railways"

    def test_no_false_positives_on_similar_patterns(self, normalizer):
        """P2-17: Words like 'ITERATION' should not be modified."""
        text = "The ITERATION process was completed."
        result = normalizer.normalize_headers(text)

        assert "ITERATION" in result
        assert result == text

    def test_empty_and_null_input(self, normalizer):
        """P2-17: Empty and None inputs should be handled gracefully."""
        assert normalizer.normalize_headers("") == ""
        assert normalizer.normalize_headers(None) is None

    def test_chapter_xi_l_corrected(self, normalizer):
        """P2-17: 'CHAPTER Xl' (X + lowercase L) should be corrected to 'CHAPTER XI'."""
        result = normalizer.normalize_headers("CHAPTER Xl General Observations")

        assert result == "CHAPTER XI General Observations"


class TestOrdinalCorrectionsP217:
    """P2-17: Test ordinal number corrections (Finance Commission context)."""

    def test_144_cfc_corrected(self, normalizer):
        """P2-17: '144 CFC' should be corrected to '14th CFC'."""
        result = normalizer.normalize_headers("Recommendations of 144 CFC were implemented")

        assert "14th CFC" in result


class TestNormalizeTocEntryP217:
    """P2-17: Test normalize_toc_entry alias method."""

    def test_toc_entry_normalized(self, normalizer):
        """P2-17: normalize_toc_entry should apply same corrections."""
        result = normalizer.normalize_toc_entry("CHAPTER ITI")

        assert result == "CHAPTER III"


class TestSingletonPatternP217:
    """P2-17: Test the singleton get_ocr_normalizer function."""

    def test_get_ocr_normalizer_returns_instance(self):
        """P2-17: get_ocr_normalizer should return an OcrNormalizer."""
        normalizer = get_ocr_normalizer()

        assert isinstance(normalizer, OcrNormalizer)

    def test_get_ocr_normalizer_returns_same_instance(self):
        """P2-17: get_ocr_normalizer should return the same instance."""
        normalizer1 = get_ocr_normalizer()
        normalizer2 = get_ocr_normalizer()

        assert normalizer1 is normalizer2
