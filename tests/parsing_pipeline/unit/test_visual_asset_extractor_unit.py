"""
Unit tests for VisualAssetExtractor: Florence-2 image analysis and HITL workflow.
Tests caption generation, chart handling, and PDF image extraction.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from PIL import Image
import fitz

from ..src.extractors.visual_asset_extractor import VisualAssetExtractor
from ..src.modules.data_contracts import ExtractedContent


class TestVisualAssetExtractor:
    """Test VisualAssetExtractor functionality with mocked Florence-2."""

    @pytest.fixture
    def visual_extractor(self):
        """Create VisualAssetExtractor with mocked dependencies."""
        with (
            patch("transformers.AutoModelForCausalLM.from_pretrained"),
            patch("transformers.AutoProcessor.from_pretrained"),
        ):
            extractor = VisualAssetExtractor()
            # Mock the required attributes to avoid initialization
            extractor.model = Mock()
            extractor.processor = Mock()
            extractor.device = "cpu"
            extractor.dtype = "float32"
            return extractor

    def test_initialization(self):
        """Test VisualAssetExtractor initializes correctly."""
        with (
            patch("transformers.AutoModelForCausalLM.from_pretrained"),
            patch("transformers.AutoProcessor.from_pretrained"),
        ):
            extractor = VisualAssetExtractor()
            assert extractor.device in ["cpu", "cuda"]

    @patch("fitz.open")
    def test_extract_image_from_pdf_valid_extraction(self, mock_fitz, visual_extractor):
        """Test image extraction from PDF with valid bounding box."""
        # Mock PDF document and page
        mock_doc = Mock()
        mock_page = Mock()
        mock_doc.load_page.return_value = mock_page
        mock_fitz.return_value = mock_doc

        # Mock image info and extraction
        mock_img_info = {"xref": 123, "width": 100, "height": 100}
        mock_page.get_images.return_value = [mock_img_info]
        mock_page.get_image_bbox.return_value = fitz.Rect(50, 50, 200, 200)

        # Mock image extraction
        mock_doc.extract_image.return_value = {
            "image": b"fake_image_data",
            "ext": "png",
        }

        # Create test bounding box that intersects with image
        bbox = [100, 100, 150, 150]

        with patch("PIL.Image.open") as mock_img_open:
            mock_image = Mock(spec=Image.Image)
            mock_img_open.return_value.convert.return_value = mock_image

            result = visual_extractor._extract_image_from_pdf("test.pdf", 0, bbox)

            assert result == mock_image

    @patch("fitz.open")
    def test_extract_image_from_pdf_no_intersection(self, mock_fitz, visual_extractor):
        """Test image extraction when no images intersect bounding box."""
        # Mock PDF with images outside bounding box
        mock_doc = Mock()
        mock_page = Mock()
        mock_doc.load_page.return_value = mock_page
        mock_fitz.return_value = mock_doc

        mock_page.get_images.return_value = [{"xref": 123}]
        # Image is far from bounding box
        mock_page.get_image_bbox.return_value = fitz.Rect(500, 500, 600, 600)

        result = visual_extractor._extract_image_from_pdf(
            "test.pdf", 0, [0, 0, 100, 100]
        )
        assert result is None

    def test_generate_detailed_caption(self, visual_extractor):
        """Test Florence-2 caption generation."""
        # Mock Florence-2 components
        mock_image = Mock()

        # Mock processor post-processing
        visual_extractor.processor.post_process_generation.return_value = {
            "<DETAILED_CAPTION>": "A detailed description of the image content."
        }

        result = visual_extractor._generate_detailed_caption(mock_image)

        assert result == "A detailed description of the image content."
        visual_extractor.processor.post_process_generation.assert_called_once()

    def test_handle_quantitative_chart_hitl_workflow(self, visual_extractor):
        """Test HITL chart handling workflow."""
        with (
            patch("pathlib.Path.mkdir"),
            patch("PIL.Image.Image.save"),
            patch("hashlib.md5") as mock_md5,
            patch.object(visual_extractor, "_extract_image_from_pdf") as mock_extract,
        ):
            # Mock image and MD5
            mock_image = Mock()
            mock_extract.return_value = mock_image
            mock_md5.return_value.hexdigest.return_value = "abcd1234"

            result = visual_extractor._handle_quantitative_chart(
                "test.pdf", 0, [100, 100, 200, 200], "report_001"
            )

            expected_path = "data/assets_for_hitl/report_001_p0_abcd12.png"
            assert result == expected_path
            mock_image.save.assert_called_once_with(
                expected_path[:44]
            )  # First part matches

    def test_extract_qualitative_picture_success(self, visual_extractor):
        """Test successful extraction of qualitative picture content."""
        with (
            patch.object(
                visual_extractor, "_extract_image_from_pdf"
            ) as mock_img_extract,
            patch.object(
                visual_extractor, "_generate_detailed_caption"
            ) as mock_caption,
        ):
            # Mock successful extraction
            mock_image = Mock()
            mock_img_extract.return_value = mock_image
            mock_caption.return_value = "Detailed image description"

            result = visual_extractor.extract(
                pdf_path="test.pdf",
                page_num=1,
                bbox=[100, 200, 300, 400],
                label="Picture",
                confidence=0.92,
                report_id="test_report",
            )

            assert isinstance(result, ExtractedContent)
            assert result.content_type == "image_caption"
            assert result.content == "Detailed image description"
            assert result.model_used == "Florence-2-large"
            assert result.layout_label == "Picture"

    def test_extract_qualitative_picture_failure(self, visual_extractor):
        """Test picture extraction when image extraction fails."""
        with patch.object(visual_extractor, "_extract_image_from_pdf") as mock_extract:
            mock_extract.return_value = None  # Image extraction fails

            result = visual_extractor.extract(
                pdf_path="test.pdf",
                page_num=0,
                bbox=[0, 0, 100, 100],
                label="Picture",
                confidence=0.8,
            )

            assert result is None

    def test_extract_quantitative_figure_success(self, visual_extractor):
        """Test successful extraction of quantitative figure content."""
        with patch.object(visual_extractor, "_handle_quantitative_chart") as mock_chart:
            mock_chart.return_value = "data/assets_for_hitl/test_chart.png"

            result = visual_extractor.extract(
                pdf_path="test.pdf",
                page_num=2,
                bbox=[50, 50, 250, 300],
                label="Figure",
                confidence=0.88,
                report_id="report_001",
            )

            assert isinstance(result, ExtractedContent)
            assert result.content_type == "chart_data_path"
            assert result.content == "data/assets_for_hitl/test_chart.png"
            assert result.model_used == "HITL-PlotDigitizer"
            assert result.layout_label == "Figure"

    def test_extract_unknown_asset_type(self, visual_extractor):
        """Test handling of unknown asset types."""
        result = visual_extractor.extract(
            pdf_path="test.pdf",
            page_num=0,
            bbox=[0, 0, 100, 100],
            label="UnknownAssetType",
            confidence=0.5,
        )

        assert result is None

    def test_extract_error_handling_caption_failure(self, visual_extractor):
        """Test error handling when caption generation fails."""
        with (
            patch.object(visual_extractor, "_extract_image_from_pdf") as mock_extract,
            patch.object(
                visual_extractor, "_generate_detailed_caption"
            ) as mock_caption,
        ):
            mock_extract.return_value = Mock()
            mock_caption.side_effect = Exception("Caption generation failed")

            result = visual_extractor.extract(
                pdf_path="test.pdf",
                page_num=0,
                bbox=[0, 0, 100, 100],
                label="Picture",
                confidence=0.8,
            )

            assert result is None

    def test_label_classification_logic(self, visual_extractor):
        """Test that different labels route to different extraction routes."""
        test_cases = [
            ("Picture", "image_caption"),
            ("Figure", "chart_data_path"),
            ("Chart", "chart_data_path"),
            ("Graph", "chart_data_path"),
            ("Unknown", None),
        ]

        for label, expected_type in test_cases:
            with (
                patch.object(
                    visual_extractor, "_extract_image_from_pdf"
                ) as mock_extract,
                patch.object(
                    visual_extractor, "_generate_detailed_caption"
                ) as mock_caption,
                patch.object(
                    visual_extractor, "_handle_quantitative_chart"
                ) as mock_chart,
            ):
                if expected_type == "image_caption":
                    mock_extract.return_value = Mock()
                    mock_caption.return_value = "Caption"
                    mock_chart.return_value = None
                elif expected_type == "chart_data_path":
                    mock_extract.return_value = Mock()
                    mock_caption.return_value = None
                    mock_chart.return_value = "chart_path.png"
                else:
                    mock_extract.return_value = None

                result = visual_extractor.extract(
                    pdf_path="test.pdf",
                    page_num=0,
                    bbox=[0, 0, 100, 100],
                    label=label,
                    confidence=0.8,
                    report_id="test_report",
                )

                if expected_type:
                    assert isinstance(result, ExtractedContent)
                    assert result.content_type == expected_type
                else:
                    assert result is None

    def test_shutdown_method(self, visual_extractor):
        """Test resource cleanup on shutdown."""
        visual_extractor.shutdown()
        # Visual extractor doesn't require special cleanup in current implementation
        # This test ensures method exists and doesn't raise exceptions
