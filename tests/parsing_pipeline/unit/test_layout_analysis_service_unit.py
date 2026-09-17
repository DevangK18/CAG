import pytest
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
from ..src.modules.layout_analysis_service import LayoutAnalysisService
from ..src.modules.data_contracts import DocumentTask


@pytest.fixture
def layout_service(tmp_path):
    """LayoutAnalysisService fixture with temporary model directory."""
    return LayoutAnalysisService(model_cache_dir=str(tmp_path / "models"))


@pytest.fixture
def mock_document_task(tmp_path):
    """Create a mock DocumentTask with valid PDF path."""
    pdf_path = tmp_path / "test.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\ntest content")  # Minimal valid PDF
    return DocumentTask(
        report_id="report_001_test",
        source_url="https://example.com/test.pdf",
        local_pdf_path=str(pdf_path),
        initial_metadata={"Title": "Test Report"},
        scaffolding={"pages": [0, 1, 2]},  # Mock scaffolding data
    )


@pytest.fixture
def mock_ocred_task(tmp_path):
    """Create a mock DocumentTask with OCR'd PDF path."""
    ocred_path = tmp_path / "test_ocred.pdf"
    ocred_path.write_bytes(b"%PDF-1.4\ntest ocred content")
    return DocumentTask(
        report_id="report_002_ocred",
        source_url="https://example.com/test.pdf",
        local_pdf_path=str(tmp_path / "test.pdf"),
        ocred_pdf_path=str(ocred_path),
        initial_metadata={"Title": "OCR'd Report"},
        scaffolding={"pages": [0, 1]},
    )


def test_layout_analysis_service_init(tmp_path):
    """Test LayoutAnalysisService initialization with custom parameters."""
    model_dir = tmp_path / "custom_models"
    service = LayoutAnalysisService(
        model_cache_dir=str(model_dir),
        device="cpu",
        confidence_threshold=0.8,
        dpi=150,
    )

    assert model_dir.exists()
    assert service.model_cache_dir == model_dir
    assert service.device == "cpu"
    assert service.confidence_threshold == 0.8
    assert service.dpi == 150


def test_layout_analysis_service_default_init(tmp_path):
    """Test LayoutAnalysisService with default parameters."""
    service = LayoutAnalysisService()
    assert service.device == "auto"
    assert service.confidence_threshold == 0.7
    assert service.dpi == 300
    assert service.model_cache_dir.exists()


def test_get_pdf_path_local(layout_service, mock_document_task):
    """Test PDF path selection prefers local PDF."""
    pdf_path = layout_service._get_pdf_path(mock_document_task)
    assert pdf_path == mock_document_task.local_pdf_path


def test_get_pdf_path_ocred(layout_service, mock_ocred_task):
    """Test PDF path selection prefers OCR'd PDF when available."""
    pdf_path = layout_service._get_pdf_path(mock_ocred_task)
    assert pdf_path == mock_ocred_task.ocred_pdf_path


def test_get_pdf_path_neither_available(layout_service):
    """Test PDF path selection when neither path is available."""
    task = DocumentTask(
        report_id="report_empty",
        source_url="https://example.com/test.pdf",
        local_pdf_path="/nonexistent/path.pdf",
        initial_metadata={},
    )
    pdf_path = layout_service._get_pdf_path(task)
    assert pdf_path is None


def test_get_pdf_path_file_not_exists(layout_service, tmp_path):
    """Test PDF path selection when file doesn't exist."""
    task = DocumentTask(
        report_id="report_missing",
        source_url="https://example.com/test.pdf",
        local_pdf_path=str(tmp_path / "missing.pdf"),
        initial_metadata={},
    )
    pdf_path = layout_service._get_pdf_path(task)
    assert pdf_path is None


@patch(
    "services.parsing_pipeline.src.modules.layout_analysis_service.LayoutAnalysisService._initialize_docling_pipeline"
)
@patch("pathlib.Path.exists")
def test_analyze_layout_pdf_not_found(
    mock_path_exists, mock_init_pipeline, layout_service, mock_document_task
):
    """Test layout analysis with missing PDF file."""
    mock_path_exists.return_value = False

    result = layout_service.analyze_layout(mock_document_task)

    assert result.processing_status == "failed_layout"
    assert "PDF path not available" in result.error_log[0]
    mock_init_pipeline.assert_not_called()


@patch(
    "services.parsing_pipeline.src.modules.layout_analysis_service.LayoutAnalysisService._process_document_pages"
)
@patch(
    "services.parsing_pipeline.src.modules.layout_analysis_service.LayoutAnalysisService._initialize_docling_pipeline"
)
def test_analyze_layout_success(
    mock_init_pipeline, mock_process_pages, layout_service, mock_document_task
):
    """Test successful layout analysis workflow."""
    mock_pipeline = MagicMock()
    mock_init_pipeline.return_value = mock_pipeline

    # Mock successful processing
    mock_results = {
        0: [{"bbox": [10, 20, 100, 50], "label": "Text", "confidence": 0.85}],
        1: [{"bbox": [15, 25, 95, 45], "label": "Table", "confidence": 0.92}],
    }
    mock_process_pages.return_value = mock_results

    result = layout_service.analyze_layout(mock_document_task)

    assert result.processing_status == "layout_complete"
    assert result.layout == mock_results
    assert "Layout analysis completed: 2 blocks detected" in result.error_log[-1]
    mock_init_pipeline.assert_called_once()
    mock_process_pages.assert_called_once()


@patch(
    "services.parsing_pipeline.src.modules.layout_analysis_service.LayoutAnalysisService._process_document_pages"
)
@patch(
    "services.parsing_pipeline.src.modules.layout_analysis_service.LayoutAnalysisService._initialize_docling_pipeline"
)
def test_analyze_layout_processing_failure(
    mock_init_pipeline, mock_process_pages, layout_service, mock_document_task
):
    """Test layout analysis with processing failure."""
    mock_pipeline = MagicMock()
    mock_init_pipeline.return_value = mock_pipeline
    mock_process_pages.side_effect = Exception("PDF processing failed")

    result = layout_service.analyze_layout(mock_document_task)

    assert result.processing_status == "failed_layout"
    assert "Layout analysis failed: PDF processing failed" in result.error_log[-1]


def test_validate_and_merge_results_empty():
    """Test result validation with empty results."""
    service = LayoutAnalysisService()
    result = service._validate_and_merge_results({})
    assert result == {}


def test_validate_and_merge_results_single_page(layout_service):
    """Test result validation with single page results."""
    raw_results = {
        0: [
            {"bbox": [10, 20, 100, 50], "label": "Text", "confidence": 0.85},
            {"bbox": [60, 70, 120, 90], "label": "Table", "confidence": 0.75},
        ]
    }
    result = layout_service._validate_and_merge_results(raw_results)
    assert 0 in result
    assert len(result[0]) == 2


def test_validate_and_merge_results_overlap_filtering(layout_service):
    """Test result validation with minimal overlapping block filtering."""
    # Use blocks that have minimal overlap
    raw_results = {
        0: [
            {"bbox": [10, 20, 50, 40], "label": "Text", "confidence": 0.95},
            {
                "bbox": [60, 20, 100, 40],
                "label": "Text",
                "confidence": 0.85,
            },  # No significant overlap
            {
                "bbox": [10, 60, 50, 80],
                "label": "Table",
                "confidence": 0.75,
            },  # No overlap
        ]
    }
    result = layout_service._validate_and_merge_results(raw_results)
    assert 0 in result
    # Should keep all blocks (no significant overlap)
    assert len(result[0]) == 3


def test_map_doclaynet_label(layout_service):
    """Test DocLayNet label mapping."""
    # Test mapped labels
    assert layout_service._map_doclaynet_label("Page-header") == "Header"
    assert layout_service._map_doclaynet_label("Section-header") == "SectionHeader"
    assert layout_service._map_doclaynet_label("Figure") == "Picture"
    assert layout_service._map_doclaynet_label("Text") == "Text"
    assert layout_service._map_doclaynet_label("Table") == "Table"

    # Test unmapped label returns as-is
    assert layout_service._map_doclaynet_label("UnknownLabel") == "UnknownLabel"


@pytest.mark.parametrize(
    "block1,block2,expected_overlap",
    [
        # Significant overlap (>80% IoU) - boxes almost identical
        (
            {"bbox": [10, 10, 90, 90]},
            {"bbox": [11, 11, 89, 89]},
            True,
        ),
        # Moderate overlap (~56% IoU)
        (
            {"bbox": [10, 10, 90, 90]},
            {"bbox": [20, 20, 80, 80]},
            False,  # Actually ~56% IoU, so False for 80% threshold
        ),
        # Minimal overlap (<80% IoU)
        (
            {"bbox": [10, 10, 50, 50]},
            {"bbox": [60, 60, 100, 100]},
            False,
        ),
        # Exact overlap
        (
            {"bbox": [10, 10, 90, 90]},
            {"bbox": [10, 10, 90, 90]},
            True,
        ),
        # No overlap
        (
            {"bbox": [10, 10, 40, 40]},
            {"bbox": [50, 50, 80, 80]},
            False,
        ),
    ],
)
def test_blocks_overlap_significantly(layout_service, block1, block2, expected_overlap):
    """Test block overlap detection with different scenarios."""
    result = layout_service._blocks_overlap_significantly(block1, block2)
    assert result == expected_overlap


def test_initialize_docling_pipeline_placeholder_fallback(layout_service):
    """Test that pipeline initialization falls back to placeholder."""
    with patch("sys.modules", {"docling.pipeline.standard_pdf_pipeline": None}):
        pipeline = layout_service._initialize_docling_pipeline()

    # Should return the placeholder class since import fails
    from ..src.modules.layout_analysis_service import DocLingPipelinePlaceholder

    assert isinstance(pipeline, DocLingPipelinePlaceholder)


def test_docling_pipeline_placeholder_process_image():
    """Test the placeholder pipeline's process_image method."""
    from ..src.modules.layout_analysis_service import DocLingPipelinePlaceholder

    pipeline = DocLingPipelinePlaceholder()

    # Test with any image (PIL Image not needed since it's mocked)
    result = pipeline.process_image(None)  # Mock image

    assert hasattr(result, "predictions")
    assert len(result.predictions) == 1

    prediction = result.predictions[0]
    assert hasattr(prediction, "bbox")
    assert hasattr(prediction, "label")
    assert hasattr(prediction, "confidence")
    assert prediction.label == "Text"
    assert prediction.confidence == 0.85


@pytest.mark.parametrize(
    "docling_bbox,expected_standardized",
    [
        ([0.1, 0.2, 0.8, 0.9], [72.0, 144.0, 576.0, 648.0]),  # 72 DPI scaling
        ([0.0, 0.0, 1.0, 1.0], [0.0, 0.0, 720.0, 720.0]),  # Full page in inches
    ],
)
def test_convert_docling_to_standard_format(
    layout_service, docling_bbox, expected_standardized
):
    """Test DocLing result conversion to standard format."""
    # Mock pixmap for coordinate scaling
    mock_pixmap = MagicMock()
    mock_pixmap.width = 720  # 10 inches at 72 DPI
    mock_pixmap.xres = 72  # 72 pixels per inch
    mock_pixmap.yres = 72  # Same as xres for square pixels
    mock_pixmap.height = 720

    # Mock docling result
    mock_result = MagicMock()
    mock_result.predictions = [
        MagicMock(
            bbox=docling_bbox,
            label="Text",
            confidence=0.87,
        )
    ]

    # Add detections fallback
    mock_result.detections = mock_result.predictions

    result = layout_service._convert_docling_to_standard_format(
        mock_result, mock_pixmap
    )

    assert len(result) == 1
    block = result[0]
    assert block["bbox"] == expected_standardized
    assert block["label"] == "Text"
    assert block["confidence"] == 0.87
    assert block["content_type"] == "Text"


def test_convert_docling_to_standard_format_unrecognized(layout_service):
    """Test DocLing result conversion with unrecognized result format."""
    mock_result = MagicMock()
    # No predictions or detections attributes
    del mock_result.predictions
    del mock_result.detections

    mock_pixmap = MagicMock()
    result = layout_service._convert_docling_to_standard_format(
        mock_result, mock_pixmap
    )

    assert result == []


def test_convert_docling_to_standard_format_missing_bbox(layout_service):
    """Test DocLing result conversion when prediction lacks bbox."""
    mock_result = MagicMock()
    mock_prediction = MagicMock()
    # No bbox attribute
    del mock_prediction.bbox
    del mock_prediction.box
    mock_result.predictions = [mock_prediction]

    mock_pixmap = MagicMock()
    result = layout_service._convert_docling_to_standard_format(
        mock_result, mock_pixmap
    )

    assert result == []
