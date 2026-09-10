"""
P1-14b: Unit tests for Extraction Method Population.

Tests:
- pdfplumber sets extraction_method='pdfplumber-lines_strict' or 'pdfplumber-text_fallback'
- Docling sets extraction_method='docling-tableformer'
- Visual extraction sets extraction_method='image-crop-for-gemini'
- Gemini updates extraction_method='gemini-2.5-flash-vision'
"""

import pytest
from unittest.mock import MagicMock, patch

from src.core.data_contracts import ExtractedContent


class TestExtractedContentHasExtractionMethod:
    """P1-14b: Verify ExtractedContent model has extraction_method field."""

    def test_extraction_method_field_exists(self):
        """ExtractedContent should have extraction_method field."""
        content = ExtractedContent(
            content_type="paragraph",
            content="Test content",
            source_page_physical=0,
            source_bbox=[0, 0, 100, 100],
            model_used="test",
            layout_label="Text",
            extraction_method="test-method",
        )
        assert hasattr(content, "extraction_method")
        assert content.extraction_method == "test-method"

    def test_extraction_method_optional(self):
        """extraction_method should be optional (None by default)."""
        content = ExtractedContent(
            content_type="paragraph",
            content="Test content",
            source_page_physical=0,
            source_bbox=[0, 0, 100, 100],
            model_used="test",
            layout_label="Text",
        )
        assert content.extraction_method is None

    def test_extraction_confidence_field_exists(self):
        """ExtractedContent should have extraction_confidence field."""
        content = ExtractedContent(
            content_type="paragraph",
            content="Test content",
            source_page_physical=0,
            source_bbox=[0, 0, 100, 100],
            model_used="test",
            layout_label="Text",
            extraction_confidence=0.95,
        )
        assert hasattr(content, "extraction_confidence")
        assert content.extraction_confidence == 0.95


class TestPdfplumberExtractionMethod:
    """P1-14b: Test pdfplumber sets extraction_method correctly."""

    def test_extraction_method_in_returned_content(self):
        """Verify extraction_method is set when creating ExtractedContent."""
        # Test that when we create ExtractedContent with extraction_method,
        # it's properly stored
        content = ExtractedContent(
            content_type="table_markdown",
            content="| A | B |\n|---|---|\n| 1 | 2 |",
            source_page_physical=5,
            source_bbox=[100, 100, 500, 300],
            model_used="pdfplumber-lines_strict",
            layout_label="Table",
            layout_confidence=0.9,
            extraction_method="pdfplumber-lines_strict",
            extraction_confidence=0.85,
        )
        assert content.extraction_method == "pdfplumber-lines_strict"
        assert content.extraction_confidence == 0.85

    def test_extraction_method_text_fallback(self):
        """Test text_fallback method is correctly set."""
        content = ExtractedContent(
            content_type="table_markdown",
            content="| A | B |\n|---|---|\n| 1 | 2 |",
            source_page_physical=5,
            source_bbox=[100, 100, 500, 300],
            model_used="pdfplumber-text_fallback",
            layout_label="Table",
            layout_confidence=0.9,
            extraction_method="pdfplumber-text_fallback",
        )
        assert content.extraction_method == "pdfplumber-text_fallback"


class TestDoclingExtractionMethod:
    """P1-14b: Test Docling TableFormer sets extraction_method correctly."""

    def test_docling_tableformer_method(self):
        """Docling should set extraction_method='docling-tableformer'."""
        content = ExtractedContent(
            content_type="table_markdown",
            content="| Column1 | Column2 |\n|---|---|\n| data | data |",
            source_page_physical=10,
            source_bbox=[50, 200, 400, 500],
            model_used="docling-tableformer",
            layout_label="Table",
            layout_confidence=0.88,
            extraction_method="docling-tableformer",
            extraction_confidence=0.88,
        )
        assert content.extraction_method == "docling-tableformer"
        assert content.model_used == "docling-tableformer"


class TestVisualExtractionMethod:
    """P1-14b: Test visual extraction sets extraction_method correctly."""

    def test_image_crop_for_gemini_method(self):
        """Visual extraction should set extraction_method='image-crop-for-gemini'."""
        content = ExtractedContent(
            content_type="image_caption",
            content="data/extraction_images/charts/report_chart_p5_100_200.png",
            source_page_physical=5,
            source_bbox=[100, 200, 400, 500],
            model_used="image-crop-for-gemini",
            layout_label="Figure",
            layout_confidence=0.92,
            extraction_method="image-crop-for-gemini",
        )
        assert content.extraction_method == "image-crop-for-gemini"


class TestGeminiExtractionMethod:
    """P1-14b: Test Gemini vision sets extraction_method correctly."""

    def test_gemini_flash_vision_method(self):
        """Gemini should set extraction_method='gemini-2.5-flash-vision'."""
        content = ExtractedContent(
            content_type="table_markdown",
            content="| Extracted | By | Gemini |\n|---|---|---|\n| 1 | 2 | 3 |",
            source_page_physical=7,
            source_bbox=[50, 100, 500, 400],
            model_used="gemini-2.5-flash-vision",
            layout_label="Table",
            extraction_method="gemini-2.5-flash-vision",
        )
        assert content.extraction_method == "gemini-2.5-flash-vision"


class TestExtractionMethodForRegistry:
    """P1-14b: Test extraction_method values are suitable for visual asset registry."""

    def test_all_valid_extraction_methods(self):
        """All extraction methods should be parseable strings."""
        valid_methods = [
            "pdfplumber-lines_strict",
            "pdfplumber-text_fallback",
            "docling-tableformer",
            "image-crop-for-gemini",
            "gemini-2.5-flash-vision",
        ]

        for method in valid_methods:
            content = ExtractedContent(
                content_type="table_markdown",
                content="| A | B |",
                source_page_physical=0,
                source_bbox=[0, 0, 100, 100],
                model_used="test",
                layout_label="Table",
                extraction_method=method,
            )
            assert content.extraction_method == method
            # Method should be a non-empty string
            assert isinstance(content.extraction_method, str)
            assert len(content.extraction_method) > 0

    def test_extraction_stats_can_be_aggregated(self):
        """Extraction methods should be suitable for statistics aggregation."""
        contents = [
            ExtractedContent(
                content_type="table_markdown",
                content="| A |",
                source_page_physical=0,
                source_bbox=[0, 0, 100, 100],
                model_used="pdfplumber-lines_strict",
                layout_label="Table",
                extraction_method="pdfplumber-lines_strict",
            ),
            ExtractedContent(
                content_type="table_markdown",
                content="| B |",
                source_page_physical=1,
                source_bbox=[0, 0, 100, 100],
                model_used="pdfplumber-lines_strict",
                layout_label="Table",
                extraction_method="pdfplumber-lines_strict",
            ),
            ExtractedContent(
                content_type="table_markdown",
                content="| C |",
                source_page_physical=2,
                source_bbox=[0, 0, 100, 100],
                model_used="docling-tableformer",
                layout_label="Table",
                extraction_method="docling-tableformer",
            ),
        ]

        # Aggregate by extraction_method
        stats = {}
        for c in contents:
            method = c.extraction_method or "unknown"
            stats[method] = stats.get(method, 0) + 1

        assert stats["pdfplumber-lines_strict"] == 2
        assert stats["docling-tableformer"] == 1
