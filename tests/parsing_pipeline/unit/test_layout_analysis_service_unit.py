"""
Unit tests for LayoutAnalysisService (Phase 5): Docling conversion is mocked,
so no layout models are loaded.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import fitz
import pytest

from src.core.data_contracts import DocumentTask
from src.parsing_pipeline.config import LayoutAnalysisConfig
from src.parsing_pipeline.modules.layout_analysis_service import LayoutAnalysisService

MODULE = "src.parsing_pipeline.modules.layout_analysis_service"


@pytest.fixture
def mock_converter_cls():
    with patch(f"{MODULE}.DocumentConverter") as converter_cls:
        yield converter_cls


@pytest.fixture
def layout_service(mock_converter_cls):
    """Service on CPU with the Docling converter mocked out."""
    return LayoutAnalysisService(config=LayoutAnalysisConfig(accelerator_device="cpu"))


def _write_pdf(path, pages=1):
    doc = fitz.open()
    for i in range(pages):
        doc.new_page().insert_text((50, 50), f"Page {i + 1}")
    doc.save(str(path))
    doc.close()
    return path


@pytest.fixture
def mock_document_task(tmp_path):
    """DocumentTask whose local PDF exists."""
    pdf_path = _write_pdf(tmp_path / "test.pdf", pages=2)
    return DocumentTask(
        report_id="report_001_test",
        source_url="https://example.com/test.pdf",
        local_pdf_path=str(pdf_path),
        initial_metadata={"Title": "Test Report"},
    )


@pytest.fixture
def mock_ocred_task(tmp_path):
    """DocumentTask with both an original and an OCR'd PDF."""
    local = _write_pdf(tmp_path / "test.pdf")
    ocred = _write_pdf(tmp_path / "test_ocred.pdf")
    return DocumentTask(
        report_id="report_002_ocred",
        source_url="https://example.com/test.pdf",
        local_pdf_path=str(local),
        ocred_pdf_path=str(ocred),
        initial_metadata={"Title": "OCR'd Report"},
    )


# ── Initialisation ──────────────────────────────────────────────────────────


def test_init_reads_layout_config(mock_converter_cls):
    config = LayoutAnalysisConfig(
        confidence_threshold=0.5,
        accelerator_device="cpu",
        table_min_non_empty_cells=4,
        conversion_timeout=60,
        conversion_timeout_per_page=2.0,
    )
    service = LayoutAnalysisService(config=config)

    assert service.confidence_threshold == 0.5
    assert service.accelerator_device == "cpu"
    assert service.table_min_non_empty_cells == 4
    assert service.conversion_timeout == 60
    assert service.conversion_timeout_per_page == 2.0
    mock_converter_cls.assert_called_once()


def test_confidence_threshold_argument_overrides_config(mock_converter_cls):
    service = LayoutAnalysisService(
        confidence_threshold=0.8,
        config=LayoutAnalysisConfig(confidence_threshold=0.5, accelerator_device="cpu"),
    )
    assert service.confidence_threshold == 0.8


def test_converter_failure_raises_runtime_error(mock_converter_cls):
    mock_converter_cls.side_effect = Exception("no models")
    with pytest.raises(RuntimeError, match="Could not initialize Docling"):
        LayoutAnalysisService(config=LayoutAnalysisConfig(accelerator_device="cpu"))


def test_explicit_accelerator_device_kept(layout_service):
    assert layout_service._resolve_accelerator_device("mps") == "mps"
    assert layout_service._resolve_accelerator_device("cpu") == "cpu"


# ── PDF selection ───────────────────────────────────────────────────────────


def test_get_pdf_path_local(layout_service, mock_document_task):
    assert layout_service._get_pdf_path(mock_document_task) == mock_document_task.local_pdf_path


def test_get_pdf_path_ocred(layout_service, mock_ocred_task):
    assert layout_service._get_pdf_path(mock_ocred_task) == mock_ocred_task.ocred_pdf_path


def test_get_pdf_path_neither_available(layout_service):
    task = DocumentTask(
        report_id="report_empty",
        source_url="https://example.com/test.pdf",
        local_pdf_path="/nonexistent/path.pdf",
        initial_metadata={},
    )
    assert layout_service._get_pdf_path(task) is None


def test_get_pdf_path_file_not_exists(layout_service, tmp_path):
    task = DocumentTask(
        report_id="report_missing",
        source_url="https://example.com/test.pdf",
        local_pdf_path=str(tmp_path / "missing.pdf"),
        initial_metadata={},
    )
    assert layout_service._get_pdf_path(task) is None


# ── analyze_layout ──────────────────────────────────────────────────────────


def test_analyze_layout_pdf_not_found(layout_service, tmp_path):
    task = DocumentTask(
        report_id="report_missing",
        source_url="https://example.com/test.pdf",
        local_pdf_path=str(tmp_path / "missing.pdf"),
        initial_metadata={},
    )

    result = layout_service.analyze_layout(task)

    assert result.processing_status == "failed_layout"
    assert "PDF path not available" in result.error_log[0]
    layout_service.converter.convert.assert_not_called()


def test_analyze_layout_success(layout_service, mock_document_task):
    blocks = {
        1: [
            {"bbox": [15, 60, 95, 80], "label": "Table", "confidence": 0.92},
            {"bbox": [10, 20, 100, 50], "label": "Text", "confidence": 0.85},
        ],
        0: [{"bbox": [10, 20, 100, 50], "label": "Text", "confidence": 0.85}],
    }
    with patch.object(
        layout_service, "_convert_docling_doc_to_standard_format", return_value=blocks
    ):
        result = layout_service.analyze_layout(mock_document_task)

    assert result.processing_status == "layout_complete"
    assert set(result.layout) == {0, 1}
    # Blocks are sorted top-down within each page
    assert [b["label"] for b in result.layout[1]] == ["Text", "Table"]
    assert "Layout analysis completed: 3 blocks detected." in result.error_log[-1]
    layout_service.converter.convert.assert_called_once_with(
        source=mock_document_task.local_pdf_path
    )


def test_analyze_layout_processing_failure(layout_service, mock_document_task):
    layout_service.converter.convert.side_effect = Exception("PDF processing failed")

    result = layout_service.analyze_layout(mock_document_task)

    assert result.processing_status == "failed_layout"
    assert "Layout analysis failed: PDF processing failed" in result.error_log[-1]


def test_analyze_layout_empty_result_still_completes(layout_service, mock_document_task):
    with patch.object(layout_service, "_convert_docling_doc_to_standard_format", return_value={}):
        result = layout_service.analyze_layout(mock_document_task)

    assert result.processing_status == "layout_complete"
    assert result.layout == {}


# ── Sorting and label mapping ───────────────────────────────────────────────


def test_validate_and_sort_results_empty(layout_service):
    assert layout_service._validate_and_sort_results({}) == {}


def test_validate_and_sort_results_reading_order(layout_service):
    raw = {
        0: [
            {"bbox": [300, 100, 500, 120], "label": "Text"},
            {"bbox": [10, 100, 200, 120], "label": "Text"},
            {"bbox": [10, 20, 500, 40], "label": "Section-header"},
        ]
    }
    result = layout_service._validate_and_sort_results(raw)
    assert [b["bbox"][:2] for b in result[0]] == [[10, 20], [10, 100], [300, 100]]


def test_map_docling_label(layout_service):
    assert layout_service._map_docling_label("PageHeader") == "Page-header"
    assert layout_service._map_docling_label("PageFooter") == "Page-footer"
    assert layout_service._map_docling_label("SectionHeader") == "Section-header"
    assert layout_service._map_docling_label("ListItem") == "List-item"
    assert layout_service._map_docling_label("Picture") == "Picture"
    assert layout_service._map_docling_label("Table") == "Table"
    assert layout_service._map_docling_label("Caption") == "Text"
    # Unknown item types fall back to Text
    assert layout_service._map_docling_label("UnknownLabel") == "Text"


# The separator regex has no inner "|", so a multi-column separator row ("|---|---|")
# is counted as content and sparse Docling tables pass the quality gate.
SEPARATOR_BUG = pytest.mark.xfail(
    strict=True,
    reason="_count_non_empty_cells counts the cells of a multi-column |---|---| "
    "separator row as content (fidelity PR)",
)


@pytest.mark.parametrize(
    "markdown,expected",
    [
        ("| A |\n|---|\n| 1 |", 2),
        ("", 0),
        pytest.param("| A | B |\n|---|---|\n| 1 | 2 |", 4, marks=SEPARATOR_BUG),
        pytest.param("| A |  |\n|---|---|\n|  |  |", 1, marks=SEPARATOR_BUG),
    ],
)
def test_count_non_empty_cells(layout_service, markdown, expected):
    assert layout_service._count_non_empty_cells(markdown) == expected


# ── Docling document conversion ─────────────────────────────────────────────


class _BBox:
    """Bottom-left-origin box as Docling reports it."""

    def __init__(self, l, t, r, b):
        self.l, self.t, self.r, self.b = l, t, r, b

    def to_top_left_origin(self, page_height):
        return SimpleNamespace(l=self.l, t=page_height - self.t, r=self.r, b=page_height - self.b)


class TextItem:
    def __init__(self, page_no, bbox, score=None):
        self.prov = [SimpleNamespace(page_no=page_no, bbox=bbox)]
        self.score = score


class SectionHeaderItem(TextItem):
    pass


class TableItem(TextItem):
    def __init__(self, page_no, bbox, markdown):
        super().__init__(page_no, bbox)
        self._markdown = markdown

    def export_to_markdown(self, doc):
        return self._markdown


def _docling_doc(items, page_height=800.0):
    doc = MagicMock()
    doc.iterate_items.return_value = [(item, 0) for item in items]
    doc.pages = {1: SimpleNamespace(size=SimpleNamespace(height=page_height)),
                 2: SimpleNamespace(size=SimpleNamespace(height=page_height))}
    return doc


def test_convert_flips_bbox_and_uses_zero_based_pages(layout_service):
    doc = _docling_doc([TextItem(2, _BBox(50, 700, 300, 650))])

    result = layout_service._convert_docling_doc_to_standard_format(doc)

    assert list(result) == [1]
    block = result[1][0]
    assert block["bbox"] == [50, 100, 300, 150]
    assert block["label"] == "Text"
    assert block["content_type"] == "Text"
    assert block["confidence"] == 1.0  # Missing score treated as confident
    assert block["docling_table_available"] is False


def test_convert_maps_item_type_to_label(layout_service):
    doc = _docling_doc([SectionHeaderItem(1, _BBox(50, 780, 300, 760))])
    block = layout_service._convert_docling_doc_to_standard_format(doc)[0][0]
    assert block["label"] == "Section-header"
    assert block["content_type"] == "SectionHeader"


def test_convert_filters_low_confidence(layout_service):
    layout_service.confidence_threshold = 0.65
    doc = _docling_doc([
        TextItem(1, _BBox(50, 700, 300, 650), score=0.4),
        TextItem(1, _BBox(50, 600, 300, 550), score=0.9),
    ])

    result = layout_service._convert_docling_doc_to_standard_format(doc)

    assert len(result[0]) == 1
    assert result[0][0]["confidence"] == 0.9


def test_convert_skips_items_without_provenance(layout_service):
    item = TextItem(1, _BBox(0, 10, 10, 0))
    item.prov = []
    assert layout_service._convert_docling_doc_to_standard_format(_docling_doc([item])) == {}


def test_convert_keeps_docling_table_markdown(layout_service):
    layout_service.table_min_non_empty_cells = 3
    markdown = "| Year | Amount |\n|---|---|\n| 2022-23 | 120.5 |"
    doc = _docling_doc([TableItem(1, _BBox(50, 700, 500, 500), markdown)])

    block = layout_service._convert_docling_doc_to_standard_format(doc)[0][0]

    assert block["label"] == "Table"
    assert block["docling_table_available"] is True
    assert block["docling_table_markdown"] == markdown


@SEPARATOR_BUG
def test_convert_rejects_sparse_docling_table(layout_service):
    layout_service.table_min_non_empty_cells = 3
    doc = _docling_doc([TableItem(1, _BBox(50, 700, 500, 500), "| A |  |\n|---|---|\n|  |  |")])

    block = layout_service._convert_docling_doc_to_standard_format(doc)[0][0]

    assert block["docling_table_available"] is False
    assert "docling_table_markdown" not in block
