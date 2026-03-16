"""
Unit tests for TableExtractor: TATR model and OCR pipeline testing.
Tests core table extraction logic with mock data and real processing.
"""

import pytest
import torch
from PIL import Image
import pytesseract
from unittest.mock import Mock, patch, MagicMock

from ..src.extractors.table_extractor import TableExtractor
from ..src.modules.data_contracts import ExtractedContent


class TestTableExtractor:
    """Test TableExtractor functionality with mocked TATR model."""

    @pytest.fixture
    def mock_tatr_processor(self):
        """Create mock TATR processor for testing."""
        with (
            patch("transformers.TableTransformerForObjectDetection.from_pretrained"),
            patch("transformers.DetrImageProcessor.from_pretrained") as mock_processor,
        ):
            # Configure mock processor
            mock_instance = Mock()
            mock_instance.id2label = {0: "table row", 1: "table column", 2: "noise"}
            mock_processor.return_value = mock_instance

            yield mock_instance

    @pytest.fixture
    def table_extractor(self, mock_tatr_processor):
        """Create TableExtractor instance with mocked dependencies."""
        return TableExtractor()

    def test_initialization(self, table_extractor):
        """Test TableExtractor initializes with correct defaults."""
        assert table_extractor.conf_threshold == 0.75
        assert table_extractor.ocr_psm == 6
        assert table_extractor.device == "cuda" if torch.cuda.is_available() else "cpu"

    def test_custom_parameters(self):
        """Test TableExtractor with custom parameters."""
        with (
            patch("transformers.TableTransformerForObjectDetection.from_pretrained"),
            patch("transformers.DetrImageProcessor.from_pretrained"),
        ):
            extractor = TableExtractor(conf_threshold=0.8, ocr_psm=8)
            assert extractor.conf_threshold == 0.8
            assert extractor.ocr_psm == 8

    def test_parameter_clamping(self):
        """Test parameter validation and clamping."""
        with (
            patch("transformers.TableTransformerForObjectDetection.from_pretrained"),
            patch("transformers.DetrImageProcessor.from_pretrained"),
        ):
            # Test upper bound clamping
            extractor = TableExtractor(conf_threshold=2.0)
            assert extractor.conf_threshold == 1.0

            # Test lower bound clamping
            extractor = TableExtractor(conf_threshold=-0.5)
            assert extractor.conf_threshold == 0.1

    def test_prepare_table_image_valid_bbox(self, table_extractor):
        """Test image cropping with valid bounding box."""
        with patch("fitz.open") as mock_fitz:
            # Mock PDF document and page
            mock_doc = Mock()
            mock_page = Mock()
            mock_doc.load_page.return_value = mock_page
            mock_fitz.return_value = mock_doc

            # Mock pixmap for rendering
            mock_pix = Mock()
            mock_pix.width = 1000
            mock_pix.height = 2000
            mock_pix.samples = b"fake_image_data" * 6000  # Fake RGB image data
            mock_page.get_pixmap.return_value = mock_pix

            # Test with valid bounding box
            bbox = [100, 200, 300, 400]  # [x0, y0, x1, y1]
            result = table_extractor._prepare_table_image("fake.pdf", 0, bbox)

            # Verify result is PIL Image
            assert isinstance(result, Image.Image)
            assert result.size == (250, 250)  # Cropped dimensions

    def test_prepare_table_image_invalid_bbox(self, table_extractor):
        """Test image preparation with invalid bounding box."""
        with patch("fitz.open"):
            with pytest.raises(
                ValueError, match="Bounding box must have 4 coordinates"
            ):
                table_extractor._prepare_table_image(
                    "fake.pdf", 0, [100, 200]
                )  # Too few coords

    @patch("pytesseract.image_to_string")
    def test_apply_ocr_to_cells(self, mock_ocr, table_extractor):
        """Test OCR application to table cells."""
        # Create mock table image and cell grid
        mock_image = Image.new("RGB", (100, 100), color="white")

        # Mock cell grid: 2 rows, 3 columns
        cell_grid = [
            [
                {"bbox": [10, 10, 30, 20]},  # Cell 1,1
                {"bbox": [30, 10, 50, 20]},  # Cell 1,2
                {"bbox": [50, 10, 70, 20]},  # Cell 1,3
            ],
            [
                {"bbox": [10, 20, 30, 30]},  # Cell 2,1
                {"bbox": [30, 20, 50, 30]},  # Cell 2,2
                {"bbox": [50, 20, 70, 30]},  # Cell 2,3
            ],
        ]

        # Mock OCR responses
        mock_ocr.side_effect = [
            "Header1",
            "Header2",
            "Header3",
            "Cell1",
            "Cell2",
            "Cell3",
        ]

        result = table_extractor._apply_ocr_to_cells(cell_grid, mock_image)

        # Verify structure and content
        assert len(result) == 2  # 2 rows
        assert len(result[0]) == 3  # 3 columns per row
        assert result[0][0] == "Header1"
        assert result[1][2] == "Cell3"

    def test_ocr_error_handling(self, table_extractor):
        """Test OCR error handling and empty string insertion."""
        mock_image = Image.new("RGB", (100, 100), color="white")

        # Mock failing OCR
        with patch(
            "pytesseract.image_to_string", side_effect=pytesseract.TesseractError()
        ):
            cell_grid = [[{"bbox": [10, 10, 30, 20]}]]
            result = table_extractor._apply_ocr_to_cells(cell_grid, mock_image)

            assert result[0][0] == ""  # Empty string on OCR failure

    def test_serialize_markdown_simple(self, table_extractor):
        """Test markdown serialization with simple table."""
        test_data = [["Header1", "Header2"], ["Cell1", "Cell2"]]

        markdown = table_extractor._serialize_to_markdown(test_data)

        # Verify markdown format
        assert "| Header1 | Header2 |" in markdown
        assert "| Cell1 | Cell2 |" in markdown
        assert "| --- | --- |" in markdown

    def test_serialize_markdown_empty(self, table_extractor):
        """Test markdown serialization with empty data."""
        empty_data = []
        markdown = table_extractor._serialize_to_markdown(empty_data)
        assert markdown == ""

        single_empty_row = [[""]]
        markdown = table_extractor._serialize_to_markdown(single_empty_row)
        assert markdown == "|  |\n| --- |"

    def test_shutdown(self, table_extractor):
        """Test resource cleanup on shutdown."""
        with patch("torch.cuda.empty_cache") as mock_cache:
            table_extractor.shutdown()

            if torch.cuda.is_available():
                mock_cache.assert_called_once()

    @patch("pytesseract.image_to_string")
    def test_full_extract_pipeline(self, mock_ocr, table_extractor):
        """Test complete extraction pipeline with mocked dependencies."""
        with (
            patch.object(table_extractor, "_prepare_table_image") as mock_img_prep,
            patch.object(table_extractor, "_get_table_structure") as mock_structure,
            patch.object(table_extractor, "_reconstruct_cell_grid") as mock_reconstruct,
        ):
            # Setup mocks
            mock_img_prep.return_value = Image.new("RGB", (100, 100), color="white")
            mock_structure.return_value = {"boxes": [], "labels": []}
            mock_reconstruct.return_value = [
                [{"bbox": [10, 10, 30, 30]}],
                [{"bbox": [10, 30, 30, 50]}],
            ]
            mock_ocr.return_value = "Test Content"

            # Test extraction
            result = table_extractor.extract(
                pdf_path="test.pdf",
                page_num=0,
                bbox=[100, 200, 300, 400],
                label="Table",
                confidence=0.85,
            )

            # Verify result structure
            assert isinstance(result, ExtractedContent)
            assert result.content_type == "table_markdown"
            assert result.model_used == "Table-Transformer-SR+Tesseract"
            assert result.layout_label == "Table"
            assert result.layout_confidence == 0.85
            assert result.source_page_physical == 0
            assert result.source_bbox == [100, 200, 300, 400]

            # Verify content is markdown
            assert "|" in result.content

    def test_extract_failure_cases(self, table_extractor):
        """Test extraction failure scenarios."""
        # Test invalid bounding box
        result = table_extractor.extract("fake.pdf", 0, [])
        assert result is None

        # Test table structure failure
        with (
            patch.object(table_extractor, "_prepare_table_image") as mock_img,
            patch.object(table_extractor, "_get_table_structure") as mock_struct,
            patch.object(table_extractor, "_reconstruct_cell_grid") as mock_recon,
        ):
            mock_img.return_value = Image.new("RGB", (100, 100), color="white")
            mock_struct.return_value = {"boxes": [], "labels": []}  # Empty results
            mock_recon.return_value = None  # No table structure found

            result = table_extractor.extract("test.pdf", 0, [0, 0, 100, 100])
            assert result is None  # Should return None when no structure found
