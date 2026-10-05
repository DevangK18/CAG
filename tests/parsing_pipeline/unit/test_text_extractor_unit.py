"""
Unit tests for TextExtractor: PyMuPDF text extraction with bounding box clipping.
Tests precision text extraction and content type classification.
"""

import pytest
from unittest.mock import ANY, Mock, patch

from src.parsing_pipeline.extractors.text_extractor import TextExtractor
from src.core.data_contracts import ExtractedContent


class TestTextExtractor:
    """Test TextExtractor functionality with mocked PyMuPDF."""

    @pytest.fixture
    def text_extractor(self):
        """Create TextExtractor instance."""
        return TextExtractor()

    def test_initialization(self, text_extractor):
        """Test TextExtractor initializes correctly."""
        assert isinstance(text_extractor, TextExtractor)

    def test_text_normalization_complete(self, text_extractor):
        """Test comprehensive text normalization."""
        # Test hyphenation removal
        assert text_extractor._normalize_text("word-\nbreak") == "wordbreak"

        # Test whitespace normalization
        assert (
            text_extractor._normalize_text("multiple  \t\n  spaces")
            == "multiple spaces"
        )

        # Test leading/trailing whitespace removal
        assert text_extractor._normalize_text("  trimmed  ") == "trimmed"

        # Test empty content
        assert text_extractor._normalize_text("") == ""

        # Test only whitespace
        assert text_extractor._normalize_text("   \n\t  ") == ""

    def test_ligatures_and_space_before_punctuation(self, text_extractor):
        """Ligatures are expanded and stray spaces before punctuation dropped."""
        assert (
            text_extractor._normalize_text("eﬀective ﬁnancial") == "effective financial"
        )
        assert text_extractor._normalize_text("audit , period .") == "audit, period."

    def test_content_type_classification(self, text_extractor):
        """Test layout label to content type mapping."""
        # Header variants
        assert (
            text_extractor._classify_content_type("Section-header", "text") == "header"
        )
        assert text_extractor._classify_content_type("Title", "text") == "header"

        # List variants
        assert text_extractor._classify_content_type("List-item", "text") == "list"
        assert text_extractor._classify_content_type("List", "text") == "list"

        # Footnote handling
        assert text_extractor._classify_content_type("Footnote", "text") == "paragraph"

        # Default paragraph
        assert text_extractor._classify_content_type("Text", "text") == "paragraph"
        assert text_extractor._classify_content_type("Unknown", "text") == "paragraph"

    @patch("fitz.open")
    def test_extract_text_from_bbox_valid(self, mock_fitz, text_extractor):
        """Test text extraction with valid bounding box."""
        mock_doc = Mock()
        mock_page = Mock()
        mock_page.rotation = 0
        mock_doc.load_page.return_value = mock_page
        mock_fitz.return_value = mock_doc
        mock_page.get_text.return_value = "Extracted text content"

        text, rotation = text_extractor._extract_text_from_bbox(
            "test.pdf", 0, [10, 20, 100, 50]
        )

        assert text == "Extracted text content"
        assert rotation == 0
        mock_page.get_text.assert_called_once_with("text", clip=ANY, sort=True)
        mock_doc.close.assert_called()

    @patch("fitz.open")
    def test_extract_text_from_bbox_invalid(self, mock_fitz, text_extractor):
        """Test text extraction with invalid bounding box."""
        with pytest.raises(ValueError, match="Bounding box must have 4 coordinates"):
            text_extractor._extract_text_from_bbox(
                "test.pdf", 0, [10, 20]
            )  # Too few coords
        mock_fitz.assert_not_called()

    @patch.object(TextExtractor, "_extract_text_from_bbox")
    def test_full_extract_pipeline(self, mock_extract, text_extractor):
        """Test complete extraction pipeline."""
        mock_extract.return_value = ("This is a sample paragraph of text content.", 0)

        result = text_extractor.extract(
            pdf_path="test.pdf",
            page_num=1,
            bbox=[50, 100, 300, 150],
            label="Text",
            confidence=0.87,
        )

        assert isinstance(result, ExtractedContent)
        assert result.content_type == "paragraph"
        assert result.content == "This is a sample paragraph of text content."
        assert result.source_page_physical == 1
        assert result.source_bbox == [50, 100, 300, 150]
        assert result.model_used == "PyMuPDF-clip"
        assert result.extraction_method == "pymupdf-text"
        assert result.layout_label == "Text"
        assert result.layout_confidence == 0.87
        assert result.structured_data is None

    @patch.object(TextExtractor, "_extract_text_from_bbox")
    def test_rotated_page_recorded_in_structured_data(
        self, mock_extract, text_extractor
    ):
        """A non-zero page rotation is kept for the Phase 6 red flag."""
        mock_extract.return_value = ("Text read from a landscape annexure page.", 90)

        result = text_extractor.extract(
            pdf_path="test.pdf", page_num=3, bbox=[0, 0, 100, 50], label="Text"
        )

        assert result.structured_data == {"page_rotation": 90}

    @patch.object(TextExtractor, "_extract_text_from_bbox")
    def test_extract_with_different_content_types(self, mock_extract, text_extractor):
        """Test extraction with various content type mappings."""
        test_cases = [
            ("Section-header", "EXECUTIVE SUMMARY", "header"),
            ("List-item", "• First item\n• Second item", "list"),
            ("Title", "Chapter 1", "header"),
            ("Text", "Regular paragraph content", "paragraph"),
            ("Footnote", "Page reference", "paragraph"),
        ]

        for label, text_content, expected_type in test_cases:
            mock_extract.return_value = (text_content, 0)

            result = text_extractor.extract(
                pdf_path="test.pdf",
                page_num=0,
                bbox=[0, 0, 100, 50],
                label=label,
                confidence=0.8,
            )

            assert isinstance(result, ExtractedContent)
            assert result.content_type == expected_type
            assert result.layout_label == label

    @patch.object(TextExtractor, "_extract_text_from_bbox")
    def test_extract_empty_text_filtering(self, mock_extract, text_extractor):
        """Test that empty or whitespace-only text is filtered out."""
        for raw in ("", "   \n\t  "):
            mock_extract.return_value = (raw, 0)

            result = text_extractor.extract(
                pdf_path="test.pdf",
                page_num=0,
                bbox=[0, 0, 100, 50],
                label="Text",
                confidence=0.8,
            )
            assert result is None

    @patch.object(TextExtractor, "_extract_text_from_bbox")
    def test_extract_text_normalization(self, mock_extract, text_extractor):
        """Test that text normalization is applied correctly."""
        mock_extract.return_value = (
            "This is a hy-\nphenated word  with\textra\t\twhitespace.",
            0,
        )

        result = text_extractor.extract(
            pdf_path="test.pdf",
            page_num=0,
            bbox=[0, 0, 100, 50],
            label="Text",
            confidence=0.8,
        )

        assert result is not None
        assert "hyphenated" in result.content  # Hyphenation removed
        assert "  " not in result.content  # Multiple spaces normalized
        assert result.content.startswith("This")  # Leading space removed

    @patch("fitz.open")
    def test_page_access_error_wrapped(self, mock_fitz, text_extractor):
        """Errors reading the page are raised as ValueError."""
        mock_doc = Mock()
        mock_doc.load_page.side_effect = Exception("page out of range")
        mock_fitz.return_value = mock_doc

        with pytest.raises(ValueError, match="Failed to extract text from PDF"):
            text_extractor._extract_text_from_bbox("test.pdf", 0, [0, 0, 100, 50])
        mock_doc.close.assert_called()

    @patch("fitz.open")
    def test_unopenable_pdf_returns_none(self, mock_fitz, text_extractor):
        """A PDF that cannot be opened yields no content rather than an exception."""
        mock_fitz.side_effect = Exception("PDF access error")

        assert (
            text_extractor.extract("test.pdf", 0, [0, 0, 100, 50], label="Text") is None
        )

    def test_extract_error_recovery(self, text_extractor):
        """Test that extraction failures are handled gracefully."""
        with patch.object(text_extractor, "_extract_text_from_bbox") as mock_extract:
            mock_extract.side_effect = Exception("PyMuPDF error")

            result = text_extractor.extract(
                pdf_path="test.pdf",
                page_num=0,
                bbox=[0, 0, 100, 50],
                label="Text",
                confidence=0.8,
            )

            assert result is None


class TestNormalisationRepairs:
    """Rupee backtick, line-end hyphens and curly quotes (B-6-06/07/08)."""

    @pytest.fixture
    def text_extractor(self):
        return TextExtractor()

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("during 2018-\n19 the", "during 2018-19 the"),
            ("from 2014-15 to 2018-\n 19", "from 2014-15 to 2018-19"),
            ("COVID-\n19 cases", "COVID-19 cases"),
            ("Inter-\nState transfers", "Inter-State transfers"),
            ("imple-\nmentation of", "implementation of"),
            ("Chapter -\nIV", "Chapter - IV"),
        ],
    )
    def test_line_end_hyphen(self, text_extractor, raw, expected):
        assert text_extractor._normalize_text(raw) == expected

    def test_curly_quotes(self, text_extractor):
        raw = "“Audit” of the Government’s ‘scheme’"
        assert (
            text_extractor._normalize_text(raw)
            == "\"Audit\" of the Government's 'scheme'"
        )

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("cost being `  23.89 crore", "cost being ₹ 23.89 crore"),
            ("of `20 lakh in each case", "of ₹20 lakh in each case"),
            ("(` in crore)", "(₹ in crore)"),
            ("[Amount in ` Crore]", "[Amount in ₹ Crore]"),
            ("Tax Effect (`)", "Tax Effect (₹)"),
            ("difference of ` one crore", "difference of ₹ one crore"),
            ("as `NULL` in TMS database", "as `NULL` in TMS database"),
            ("head `income from other sources'", "head `income from other sources'"),
        ],
    )
    def test_rupee_backtick(self, text_extractor, raw, expected):
        assert text_extractor._normalize_text(raw) == expected


def test_abbreviation_dna_is_not_reversed_text():
    from src.parsing_pipeline.extractors.text_repair import is_reversed

    assert not is_reversed("| 5. | Muzaffarpur | 52,290 | 81,550 | DNA | DNA | DNA | DNA |")
    assert is_reversed("tnemtrapeD eht fo eunever dna erutidnepxe")
