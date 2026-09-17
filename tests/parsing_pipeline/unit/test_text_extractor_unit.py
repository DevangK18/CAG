"""
Unit tests for TextExtractor: PyMuPDF text extraction with bounding box clipping.
Tests precision text extraction and content type classification.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock

from ..src.extractors.text_extractor import TextExtractor
from ..src.modules.data_contracts import ExtractedContent


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
        # Mock PDF document and page
        mock_doc = Mock()
        mock_page = Mock()
        mock_doc.load_page.return_value = mock_page
        mock_fitz.return_value = mock_doc

        # Mock get_text with clip parameter
        mock_page.get_text.return_value = "Extracted text content"

        # Test extraction
        result = text_extractor._extract_text_from_bbox(
            "test.pdf", 0, [10, 20, 100, 50]
        )

        # Verify result and calls
        assert result == "Extracted text content"
        mock_page.get_text.assert_called_once_with("text", clip=Mock(), sort=True)

    @patch("fitz.open")
    def test_extract_text_from_bbox_invalid(self, mock_fitz, text_extractor):
        """Test text extraction with invalid bounding box."""
        with pytest.raises(ValueError, match="Bounding box must have 4 coordinates"):
            text_extractor._extract_text_from_bbox(
                "test.pdf", 0, [10, 20]
            )  # Too few coords

    @patch.object(TextExtractor, "_extract_text_from_bbox")
    def test_full_extract_pipeline(self, mock_extract, text_extractor):
        """Test complete extraction pipeline."""
        # Mock text extraction
        mock_extract.return_value = "This is a sample paragraph of text content."

        # Test extraction
        result = text_extractor.extract(
            pdf_path="test.pdf",
            page_num=1,
            bbox=[50, 100, 300, 150],
            label="Text",
            confidence=0.87,
        )

        # Verify result structure
        assert isinstance(result, ExtractedContent)
        assert result.content_type == "paragraph"
        assert result.content == "This is a sample paragraph of text content."
        assert result.source_page_physical == 1
        assert result.source_bbox == [50, 100, 300, 150]
        assert result.model_used == "PyMuPDF-clip"
        assert result.layout_label == "Text"
        assert result.layout_confidence == 0.87

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
            mock_extract.return_value = text_content

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
        # Test empty string
        mock_extract.return_value = ""

        result = text_extractor.extract(
            pdf_path="test.pdf",
            page_num=0,
            bbox=[0, 0, 100, 50],
            label="Text",
            confidence=0.8,
        )
        assert result is None

        # Test whitespace only
        mock_extract.return_value = "   \n\t  "

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
        # Text with hyphenation and extra whitespace
        mock_extract.return_value = (
            "This is a hy-\nphenated word  with\textra\t\twhitespace."
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
    def test_pdf_access_error_handling(self, mock_fitz, text_extractor):
        """Test error handling when PDF access fails."""
        # Mock PDF opening failure
        mock_fitz.side_effect = Exception("PDF access error")

        with pytest.raises(ValueError, match="Failed to extract text from PDF"):
            text_extractor._extract_text_from_bbox("test.pdf", 0, [0, 0, 100, 50])

    def test_extract_error_recovery(self, text_extractor):
        """Test that extraction failures are handled gracefully."""
        with patch.object(text_extractor, "_extract_text_from_bbox") as mock_extract:
            # Mock extraction failure
            mock_extract.side_effect = Exception("PyMuPDF error")

            result = text_extractor.extract(
                pdf_path="test.pdf",
                page_num=0,
                bbox=[0, 0, 100, 50],
                label="Text",
                confidence=0.8,
            )

            # Should return None on failure
            assert result is None
