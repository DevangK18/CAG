"""
Integration tests for ContentExtractionService: Full router-dispatcher testing.
Tests end-to-end content extraction with real extracts and synthetic documents.
"""

import pytest
from unittest.mock import Mock, patch
from PIL import Image, ImageDraw
import fitz

from ..src.modules.data_contracts import DocumentTask, ExtractedContent
from ..src.modules.content_extraction_service import ContentExtractionService


class TestContentExtractionService:
    """Integration tests for full ContentExtractionService pipeline."""

    @pytest.fixture
    def synthetic_layout_task(self):
        """Create a DocumentTask with synthetic layout data."""
        task = DocumentTask(
            report_id="test_report_001",
            source_url="https://example.com/test.pdf",
            local_pdf_path="data/raw/synthetic_test.pdf",
            initial_metadata={"title": "Test Report"},
            processing_status="layout_complete",
        )

        # Add synthetic layout blocks (mix of different content types)
        task.layout = {
            0: [  # Page 0
                {"label": "Table", "bbox": [100, 200, 500, 400], "confidence": 0.85},
                {"label": "Picture", "bbox": [600, 100, 700, 200], "confidence": 0.92},
                {
                    "label": "Section-header",
                    "bbox": [50, 50, 400, 80],
                    "confidence": 0.89,
                },
            ],
            1: [  # Page 1
                {"label": "Text", "bbox": [100, 300, 500, 350], "confidence": 0.78},
                {"label": "Figure", "bbox": [200, 400, 400, 500], "confidence": 0.88},
                {
                    "label": "List-item",
                    "bbox": [150, 600, 450, 650],
                    "confidence": 0.76,
                },
            ],
        }

        return task

    @pytest.fixture
    def content_service(self):
        """Create ContentExtractionService with mocked extractors."""
        with (
            patch(
                "services.parsing_pipeline.src.extractors.table_extractor.TableExtractor"
            ),
            patch(
                "services.parsing_pipeline.src.extractors.visual_asset_extractor.VisualAssetExtractor"
            ),
            patch(
                "services.parsing_pipeline.src.extractors.text_extractor.TextExtractor"
            ),
        ):
            service = ContentExtractionService()
            yield service

    def create_mock_table_extractor(self, service):
        """Create mock table extractor that returns table content."""
        mock_table = Mock()
        mock_table.extract.return_value = ExtractedContent(
            content_type="table_markdown",
            content="| Header1 | Header2 |\n| --- | --- |\n| Cell1 | Cell2 |",
            source_page_physical=0,
            source_bbox=[100, 200, 500, 400],
            model_used="Table-Transformer-SR+Tesseract",
            layout_label="Table",
            layout_confidence=0.85,
        )
        return mock_table

    def create_mock_visual_extractor(self, service):
        """Create mock visual extractor for pictures and figures."""
        mock_visual = Mock()
        mock_visual.extract.side_effect = [
            # Picture response
            ExtractedContent(
                content_type="image_caption",
                content="A detailed image showing organizational structure",
                source_page_physical=0,
                source_bbox=[600, 100, 700, 200],
                model_used="Florence-2-large",
                layout_label="Picture",
                layout_confidence=0.92,
            ),
            # Figure response for Page 1
            ExtractedContent(
                content_type="chart_data_path",
                content="data/assets_for_hitl/test_report_001_p1_unique.png",
                source_page_physical=1,
                source_bbox=[200, 400, 400, 500],
                model_used="HITL-PlotDigitizer",
                layout_label="Figure",
                layout_confidence=0.88,
            ),
        ]
        return mock_visual

    def create_mock_text_extractor(self, service):
        """Create mock text extractor for various text elements."""
        mock_text = Mock()
        mock_text.extract.side_effect = [
            # Section-header response
            ExtractedContent(
                content_type="header",
                content="Executive Summary",
                source_page_physical=0,
                source_bbox=[50, 50, 400, 80],
                model_used="PyMuPDF-clip",
                layout_label="Section-header",
                layout_confidence=0.89,
            ),
            # Text response
            ExtractedContent(
                content_type="paragraph",
                content="This report contains important findings...",
                source_page_physical=1,
                source_bbox=[100, 300, 500, 350],
                model_used="PyMuPDF-clip",
                layout_label="Text",
                layout_confidence=0.78,
            ),
            # List-item response
            ExtractedContent(
                content_type="list",
                content="• First bullet point\n• Second bullet point",
                source_page_physical=1,
                source_bbox=[150, 600, 450, 650],
                model_used="PyMuPDF-clip",
                layout_label="List-item",
                layout_confidence=0.76,
            ),
        ]
        return mock_text

    def test_router_initialization(self, content_service):
        """Test that ContentExtractionService initializes with proper router."""
        assert hasattr(content_service, "router")
        assert len([r for r in content_service.router.values() if r is not None]) == 6

        # Verify correct mappings
        assert "Table" in content_service.router
        assert "Picture" in content_service.router
        assert content_service.router["Table"] is not None

        # Verify noise filtering
        assert content_service.router.get("Page-header") is None
        assert content_service.router.get("Page-footer") is None

    def test_pdf_source_selection(self, content_service):
        """Test that PDF source selection works correctly."""
        # Test native document (no OCR needed)
        task_native = DocumentTask(
            report_id="test",
            source_url="",
            local_pdf_path="native.pdf",
            classification="native_text",
        )
        assert content_service._select_pdf_source(task_native) == "native.pdf"

        # Test scanned document with OCR'd path
        task_scanned = DocumentTask(
            report_id="test",
            source_url="",
            local_pdf_path="raw.pdf",
            ocred_pdf_path="ocred.pdf",
            classification="scanned",
        )
        assert content_service._select_pdf_source(task_scanned) == "ocred.pdf"

        # Test scanned document without OCR'd path (fallback)
        task_scanned_no_ocr = DocumentTask(
            report_id="test",
            source_url="",
            local_pdf_path="raw.pdf",
            classification="scanned",
        )
        assert content_service._select_pdf_source(task_scanned_no_ocr) == "raw.pdf"

    @patch("services.parsing_pipeline.src.extractors.table_extractor.TableExtractor")
    @patch(
        "services.parsing_pipeline.src.extractors.visual_asset_extractor.VisualAssetExtractor"
    )
    @patch("services.parsing_pipeline.src.extractors.text_extractor.TextExtractor")
    def test_full_extraction_pipeline(
        self, mock_text_cls, mock_visual_cls, mock_table_cls, synthetic_layout_task
    ):
        """Test complete content extraction pipeline with all extractors."""
        # Create mock extractors
        mock_table_extractor = Mock()
        mock_table_extractor.extract.return_value = ExtractedContent(
            content_type="table_markdown",
            content="| Header | Value |\n|---|---|\n| Test | Data |",
            source_page_physical=0,
            source_bbox=[100, 200, 500, 400],
            model_used="Table-Transformer-SR+Tesseract",
            layout_label="Table",
            layout_confidence=0.85,
        )
        mock_table_cls.return_value = mock_table_extractor

        mock_visual_extractor = Mock()
        mock_visual_extractor.extract.side_effect = [
            ExtractedContent(
                content_type="image_caption",
                content="Test image caption",
                source_page_physical=0,
                source_bbox=[600, 100, 700, 200],
                model_used="Florence-2-large",
                layout_label="Picture",
                layout_confidence=0.92,
            ),
            ExtractedContent(
                content_type="chart_data_path",
                content="data/assets_for_hitl/test.png",
                source_page_physical=1,
                source_bbox=[200, 400, 400, 500],
                model_used="HITL-PlotDigitizer",
                layout_label="Figure",
                layout_confidence=0.88,
            ),
        ]
        mock_visual_cls.return_value = mock_visual_extractor

        mock_text_extractor = Mock()
        mock_text_extractor.extract.side_effect = [
            ExtractedContent(
                content_type="header",
                content="Test Header",
                source_page_physical=0,
                source_bbox=[50, 50, 400, 80],
                model_used="PyMuPDF-clip",
                layout_label="Section-header",
                layout_confidence=0.89,
            ),
            ExtractedContent(
                content_type="paragraph",
                content="Test paragraph content",
                source_page_physical=1,
                source_bbox=[100, 300, 500, 350],
                model_used="PyMuPDF-clip",
                layout_label="Text",
                layout_confidence=0.78,
            ),
            ExtractedContent(
                content_type="list",
                content="• Test list item",
                source_page_physical=1,
                source_bbox=[150, 600, 450, 650],
                model_used="PyMuPDF-clip",
                layout_label="List-item",
                layout_confidence=0.76,
            ),
        ]
        mock_text_cls.return_value = mock_text_extractor

        # Create service and run extraction
        service = ContentExtractionService()
        result_task = service.extract_content(synthetic_layout_task)

        # Verify successful completion
        assert result_task.processing_status == "completed_content_extraction"
        assert result_task.extracted_content is not None
        assert len(result_task.extracted_content) == 5  # All 5 blocks processed

        # Verify content types extracted
        content_types = [elem.content_type for elem in result_task.extracted_content]
        assert "table_markdown" in content_types
        assert "image_caption" in content_types
        assert "chart_data_path" in content_types
        assert "header" in content_types
        assert "paragraph" in content_types
        assert "list" in content_types

        # Verify all extractors were called
        assert mock_table_extractor.extract.call_count == 1
        assert mock_visual_extractor.extract.call_count == 2
        assert mock_text_extractor.extract.call_count == 3

    @patch("services.parsing_pipeline.src.extractors.table_extractor.TableExtractor")
    @patch(
        "services.parsing_pipeline.src.extractors.visual_asset_extractor.VisualAssetExtractor"
    )
    @patch("services.parsing_pipeline.src.extractors.text_extractor.TextExtractor")
    def test_partial_extraction_with_errors(
        self, mock_text_cls, mock_visual_cls, mock_table_cls, synthetic_layout_task
    ):
        """Test that pipeline continues with partial failures."""
        # Setup mocks with some failures
        mock_table_extractor = Mock()
        mock_table_extractor.extract.return_value = None  # Table extraction fails
        mock_table_cls.return_value = mock_table_extractor

        mock_visual_extractor = Mock()
        mock_visual_extractor.extract.side_effect = [
            None,  # Picture extraction fails
            ExtractedContent(
                content_type="chart_data_path",
                content="path.png",
                source_page_physical=1,
                source_bbox=[200, 400, 400, 500],
                model_used="HITL",
                layout_label="Figure",
                layout_confidence=0.88,
            ),
        ]
        mock_visual_cls.return_value = mock_visual_extractor

        mock_text_extractor = Mock()
        mock_text_extractor.extract.side_effect = [
            ExtractedContent(
                content_type="header",
                content="Header text",
                source_page_physical=0,
                source_bbox=[50, 50, 400, 80],
                model_used="PyMuPDF",
                layout_label="Section-header",
                layout_confidence=0.89,
            ),
            None,  # Text extraction fails
            ExtractedContent(
                content_type="list",
                content="List content",
                source_page_physical=1,
                source_bbox=[150, 600, 450, 650],
                model_used="PyMuPDF",
                layout_label="List-item",
                layout_confidence=0.76,
            ),
        ]
        mock_text_cls.return_value = mock_text_extractor

        # Run extraction
        service = ContentExtractionService()
        result_task = service.extract_content(synthetic_layout_task)

        # Verify partial success
        assert result_task.processing_status == "partial_content_extraction"
        assert result_task.extracted_content is not None
        assert len(result_task.extracted_content) == 3  # Only successful extractions

        # Verify error log contains summary
        assert len(result_task.error_log) > 0
        assert "Content extraction completed: 3/5" in result_task.error_log[-1]

    def test_no_layout_data_rejection(self, content_service):
        """Test that tasks without layout data are rejected."""
        task_no_layout = DocumentTask(
            report_id="test", source_url="", local_pdf_path="test.pdf"
        )
        # No layout attribute set

        result = content_service.extract_content(task_no_layout)
        assert result.processing_status == "failed_content_extraction"
        assert "Layout analysis data missing" in result.error_log[0]

    def test_shutdown_method(self, content_service):
        """Test that shutdown method calls all extractor shutdowns."""
        mock_table = Mock()
        mock_visual = Mock()

        content_service.table_extractor = mock_table
        content_service.visual_asset_extractor = mock_visual

        content_service.shutdown()

        # Verify shutdown calls (text extractor doesn't have shutdown)
        mock_table.shutdown.assert_called_once()
        mock_visual.shutdown.assert_called_once()

    def test_progress_reporting(self):
        """Test progress reporting during extraction."""
        task = DocumentTask(
            report_id="test",
            source_url="",
            local_pdf_path="test.pdf",
            layout={
                0: [{"label": "Table", "bbox": [0, 0, 100, 100], "confidence": 0.8}],
                1: [{"label": "Text", "bbox": [0, 0, 100, 100], "confidence": 0.8}],
            },
        )

        service = ContentExtractionService()

        # Mock extractor to avoid actual processing
        with patch.object(service, "_route_block") as mock_route:
            mock_route.return_value = ExtractedContent(
                content_type="paragraph",
                content="Test",
                source_page_physical=0,
                source_bbox=[0, 0, 100, 100],
                model_used="Test",
                layout_label="Table",
                layout_confidence=0.8,
            )

            # Capture stdout to verify progress messages
            import io
            from contextlib import redirect_stdout

            stdout_capture = io.StringIO()
            with redirect_stdout(stdout_capture):
                service.extract_content(task)

            output = stdout_capture.getvalue()
            assert "blocks from" in output
            assert "Processed" in output
