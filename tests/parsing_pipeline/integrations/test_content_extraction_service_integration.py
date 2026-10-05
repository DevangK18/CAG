"""
Integration tests for ContentExtractionService: full router-dispatcher run over a
synthetic layout, with the pdfplumber, PyMuPDF and image-crop extractors mocked.
"""

from unittest.mock import Mock, patch

import pytest

from src.core.data_contracts import DocumentTask, ExtractedContent
from src.parsing_pipeline.modules.content_extraction_service import ContentExtractionService

MODULE = "src.parsing_pipeline.modules.content_extraction_service"


def _content(content_type, content, page, bbox, label, confidence, model="PyMuPDF-clip", sd=None):
    return ExtractedContent(
        content_type=content_type,
        content=content,
        source_page_physical=page,
        source_bbox=bbox,
        model_used=model,
        layout_label=label,
        layout_confidence=confidence,
        structured_data=sd,
    )


TABLE = _content(
    "table_markdown",
    "| Header | Value |\n|---|---|\n| Test | Data |",
    0, [100, 200, 500, 400], "Table", 0.85, model="pdfplumber",
)
# Phase 6 picture items: the path lives in structured_data, never in content
PICTURE = _content(
    "image_caption", "", 0, [600, 100, 700, 200], "Picture", 0.92, model="image-crop-for-gemini",
    sd={"image_path": "data/extraction_images/charts/test_report_001_p0_picture.png",
        "visual_subtype": None, "caption": "Picture 1.1: Site of the new building"},
)
FIGURE = _content(
    "image_caption", "", 1, [200, 400, 400, 500], "Figure", 0.88, model="image-crop-for-gemini",
    sd={"image_path": "data/extraction_images/charts/test_report_001_p1_chart.png",
        "visual_subtype": None, "caption": "Chart 2.1: Budget and expenditure"},
)
HEADER = _content("header", "Executive Summary", 0, [50, 50, 400, 80], "Section-header", 0.89)
PARAGRAPH = _content(
    "paragraph", "This report contains important findings on scheme implementation.",
    1, [100, 300, 500, 350], "Text", 0.78,
)
LIST_ITEM = _content(
    "list", "• First bullet point\n• Second bullet point",
    1, [150, 600, 450, 650], "List-item", 0.76,
)


@pytest.fixture
def synthetic_layout_task():
    """DocumentTask with a mixed synthetic layout over two pages."""
    return DocumentTask(
        report_id="test_report_001",
        source_url="https://example.com/test.pdf",
        local_pdf_path="data/raw/synthetic_test.pdf",
        initial_metadata={"title": "Test Report"},
        processing_status="layout_complete",
        layout={
            0: [
                {"label": "Table", "bbox": [100, 200, 500, 400], "confidence": 0.85},
                {"label": "Picture", "bbox": [600, 100, 700, 200], "confidence": 0.92},
                {"label": "Section-header", "bbox": [50, 50, 400, 80], "confidence": 0.89},
            ],
            1: [
                {"label": "Text", "bbox": [100, 300, 500, 350], "confidence": 0.78},
                {"label": "Figure", "bbox": [200, 400, 400, 500], "confidence": 0.88},
                {"label": "List-item", "bbox": [150, 600, 450, 650], "confidence": 0.76},
            ],
        },
    )


@pytest.fixture
def extractors():
    """Patch the extractor classes and the image-crop route before the router is built."""
    with (
        patch(f"{MODULE}.PdfplumberTableExtractor") as table_cls,
        patch(f"{MODULE}.TextExtractor") as text_cls,
        patch.object(ContentExtractionService, "_extract_and_save_visual") as visual,
    ):
        yield table_cls.return_value, text_cls.return_value, visual


@pytest.fixture
def content_service(extractors):
    return ContentExtractionService()


def test_router_initialization(content_service):
    """Router covers tables, visuals and text labels and skips page furniture."""
    active = {label for label, fn in content_service.router.items() if fn is not None}
    assert active == {
        "Table", "Picture", "Figure", "Text", "Section-header", "Title", "List-item", "Footnote",
        "Caption",
    }
    assert content_service.router["Page-header"] is None
    assert content_service.router["Page-footer"] is None


def test_pdf_source_selection(content_service):
    """Scanned documents use the OCR'd PDF when there is one."""
    native = DocumentTask(
        report_id="test", source_url="", local_pdf_path="native.pdf",
        initial_metadata={}, classification="native_text",
    )
    assert content_service._select_pdf_source(native) == "native.pdf"

    scanned = DocumentTask(
        report_id="test", source_url="", local_pdf_path="raw.pdf",
        initial_metadata={}, ocred_pdf_path="ocred.pdf", classification="scanned",
    )
    assert content_service._select_pdf_source(scanned) == "ocred.pdf"

    scanned_no_ocr = DocumentTask(
        report_id="test", source_url="", local_pdf_path="raw.pdf",
        initial_metadata={}, classification="scanned",
    )
    assert content_service._select_pdf_source(scanned_no_ocr) == "raw.pdf"


def test_full_extraction_pipeline(extractors, content_service, synthetic_layout_task):
    """Every block reaches its extractor and all results are kept."""
    table, text, visual = extractors
    table.extract.return_value = TABLE
    visual.side_effect = [PICTURE, FIGURE]
    text.extract.side_effect = [HEADER, PARAGRAPH, LIST_ITEM]

    result = content_service.extract_content(synthetic_layout_task)

    assert result.processing_status == "completed_content_extraction"
    assert len(result.extracted_content) == 6
    assert {c.content_type for c in result.extracted_content} == {
        "table_markdown", "image_caption", "header", "paragraph", "list",
    }
    assert table.extract.call_count == 1
    assert visual.call_count == 2
    assert text.extract.call_count == 3
    assert "Content extraction completed: 6/6" in result.error_log[-1]


def test_partial_extraction_with_errors(extractors, content_service, synthetic_layout_task):
    """Failed blocks are dropped and the task is marked partial."""
    table, text, visual = extractors
    table.extract.return_value = None  # pdfplumber fails, no Docling markdown
    visual.side_effect = [None, None, FIGURE]  # Gemini fallback for the table, then Picture, Figure
    text.extract.side_effect = [HEADER, None, LIST_ITEM]

    result = content_service.extract_content(synthetic_layout_task)

    assert result.processing_status == "partial_content_extraction"
    assert len(result.extracted_content) == 3
    assert "Content extraction completed: 3/6" in result.error_log[-1]


def test_native_table_falls_back_to_docling_markdown(extractors, content_service, synthetic_layout_task):
    """When pdfplumber finds no table, Docling's TableFormer markdown is used."""
    table, text, visual = extractors
    table.extract.return_value = None
    markdown = "| Year | Amount |\n|---|---|\n| 2022-23 | 120.50 |"
    synthetic_layout_task.layout = {
        0: [{"label": "Table", "bbox": [100, 200, 500, 400], "confidence": 0.85,
             "docling_table_markdown": markdown}],
    }

    result = content_service.extract_content(synthetic_layout_task)

    assert len(result.extracted_content) == 1
    block = result.extracted_content[0]
    assert block.content == markdown
    assert block.extraction_method == "docling-tableformer"
    visual.assert_not_called()


def test_scanned_table_skips_pdfplumber(extractors, content_service, synthetic_layout_task):
    """Scanned PDFs go straight to the Gemini image route when Docling has no table."""
    table, text, visual = extractors
    visual.return_value = PICTURE
    synthetic_layout_task.classification = "scanned"
    synthetic_layout_task.layout = {
        0: [{"label": "Table", "bbox": [100, 200, 500, 400], "confidence": 0.85}],
    }

    content_service.extract_content(synthetic_layout_task)

    table.extract.assert_not_called()
    assert visual.call_args.kwargs["label"] == "Table"


def test_footnote_tagged_with_number(extractors, content_service, synthetic_layout_task):
    table, text, visual = extractors
    text.extract.return_value = _content(
        "paragraph", "7 FSSAI standards notified under the Food Safety Act",
        0, [50, 700, 500, 720], "Footnote", 0.8,
    )
    synthetic_layout_task.layout = {
        0: [{"label": "Footnote", "bbox": [50, 700, 500, 720], "confidence": 0.8}],
    }

    result = content_service.extract_content(synthetic_layout_task)

    footnote = result.extracted_content[0]
    assert footnote.content_type == "footnote"
    assert footnote.content.startswith("[Footnote 7] ")


def test_no_layout_data_rejection(content_service):
    """Tasks without layout data are rejected."""
    task = DocumentTask(
        report_id="test", source_url="", local_pdf_path="test.pdf", initial_metadata={}
    )

    result = content_service.extract_content(task)

    assert result.processing_status == "failed_content_extraction"
    assert "Layout analysis data missing" in result.error_log[0]


def test_shutdown_method(content_service):
    """Shutdown releases the table extractor."""
    content_service.table_extractor = Mock()

    content_service.shutdown()

    content_service.table_extractor.shutdown.assert_called_once()


def test_progress_reporting(content_service):
    """The progress callback receives (processed, total) at the last block."""
    task = DocumentTask(
        report_id="test",
        source_url="",
        local_pdf_path="test.pdf",
        initial_metadata={},
        layout={
            0: [{"label": "Text", "bbox": [0, 0, 100, 100], "confidence": 0.8}],
            1: [{"label": "Text", "bbox": [0, 0, 100, 100], "confidence": 0.8}],
        },
    )
    progress = Mock()

    with patch.object(content_service, "_route_block", return_value=PARAGRAPH):
        content_service.extract_content(task, progress_callback=progress)

    progress.assert_called_once_with(2, 2)


def test_skipped_page_furniture_is_not_a_failure(extractors, content_service):
    """Page headers/footers skipped on purpose leave the status complete, not partial."""
    _, text, _ = extractors
    text.extract.return_value = PARAGRAPH
    task = DocumentTask(
        report_id="test_report_001",
        source_url="https://example.com/test.pdf",
        local_pdf_path="data/raw/synthetic_test.pdf",
        initial_metadata={},
        processing_status="layout_complete",
        layout={
            1: [
                {"label": "Page-header", "bbox": [50, 10, 400, 30], "confidence": 0.9},
                {"label": "Text", "bbox": [100, 300, 500, 350], "confidence": 0.78},
                {"label": "Page-footer", "bbox": [50, 800, 400, 820], "confidence": 0.9},
            ]
        },
    )
    result = content_service.extract_content(task)
    assert result.processing_status == "completed_content_extraction"
    assert any("2 skipped, 0 failed" in line for line in result.error_log)
