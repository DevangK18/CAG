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
        accelerator_device="cpu",
        table_min_non_empty_cells=4,
        conversion_timeout=60,
        conversion_timeout_per_page=2.0,
    )
    service = LayoutAnalysisService(config=config)

    assert service.accelerator_device == "cpu"
    assert service.table_min_non_empty_cells == 4
    assert service.conversion_timeout == 60
    assert service.conversion_timeout_per_page == 2.0
    mock_converter_cls.assert_called_once()


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
    # DocItemLabel values
    assert layout_service._map_docling_label("page_header") == "Page-header"
    assert layout_service._map_docling_label("section_header") == "Section-header"
    assert layout_service._map_docling_label("list_item") == "List-item"
    assert layout_service._map_docling_label("footnote") == "Footnote"
    assert layout_service._map_docling_label("caption") == "Caption"
    assert layout_service._map_docling_label("chart") == "Picture"
    assert layout_service._map_docling_label("document_index") == "Table"
    # Legacy class names still map
    assert layout_service._map_docling_label("PageFooter") == "Page-footer"
    assert layout_service._map_docling_label("ListItem") == "List-item"
    # Unknown item types fall back to Text
    assert layout_service._map_docling_label("UnknownLabel") == "Text"


@pytest.mark.parametrize(
    "markdown,expected",
    [
        ("| A |\n|---|\n| 1 |", 2),
        ("", 0),
        # Separator rows are never content
        ("| A | B |\n|---|---|\n| 1 | 2 |", 4),
        ("| A |  |\n| --- | :---: |\n|  |  |", 1),
    ],
)
def test_count_non_empty_cells(layout_service, markdown, expected):
    assert layout_service._count_non_empty_cells(markdown) == expected


def test_normalize_table_markdown_collapses_padding():
    from src.parsing_pipeline.modules.layout_analysis_service import normalize_table_markdown

    md = "| Audit observations" + " " * 300 + "| Reply |\n|" + "-" * 320 + "|-------|\n| x" + " " * 318 + "| y |"
    out = normalize_table_markdown(md)
    assert "  " not in out
    assert out.splitlines()[1] == "| --- | --- |"


# ── Docling document conversion ─────────────────────────────────────────────


class _BBox:
    """Bottom-left-origin box as Docling reports it."""

    def __init__(self, l, t, r, b):
        self.l, self.t, self.r, self.b = l, t, r, b

    def to_top_left_origin(self, page_height):
        return SimpleNamespace(l=self.l, t=page_height - self.t, r=self.r, b=page_height - self.b)


class _Ref:
    def __init__(self, target):
        self.target = target

    def resolve(self, doc):
        return self.target


_REFS = iter(range(10_000))


class Item:
    """Docling-like item: label value, self_ref, provenances."""

    def __init__(self, label, page_no, bbox, text="", provs=None):
        self.label = SimpleNamespace(value=label)
        self.self_ref = f"#/items/{next(_REFS)}"
        self.prov = provs or [SimpleNamespace(page_no=page_no, bbox=bbox)]
        self.text = text
        self.captions = []
        self.footnotes = []


class TableItem(Item):
    def __init__(self, page_no, bbox, markdown):
        super().__init__("table", page_no, bbox)
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
    doc = _docling_doc([Item("text", 2, _BBox(50, 700, 300, 650))])

    result = layout_service._convert_docling_doc_to_standard_format(doc)

    assert list(result) == [1]
    block = result[1][0]
    assert block["bbox"] == [50, 100, 300, 150]
    assert block["label"] == "Text"
    assert block["docling_label"] == "text"
    assert block["confidence"] is None  # Docling v2 items carry no layout score
    assert block["docling_table_available"] is False


@pytest.mark.parametrize(
    "label,expected",
    [("section_header", "Section-header"), ("footnote", "Footnote"),
     ("caption", "Caption"), ("list_item", "List-item"), ("page_footer", "Page-footer")],
)
def test_convert_uses_docling_label_not_class(layout_service, label, expected):
    doc = _docling_doc([Item(label, 1, _BBox(50, 780, 300, 760))])
    block = layout_service._convert_docling_doc_to_standard_format(doc)[0][0]
    assert block["label"] == expected


def test_convert_keeps_every_provenance(layout_service):
    provs = [SimpleNamespace(page_no=1, bbox=_BBox(50, 100, 300, 50)),
             SimpleNamespace(page_no=2, bbox=_BBox(50, 780, 300, 700))]
    item = Item("text", 1, None, provs=provs)
    result = layout_service._convert_docling_doc_to_standard_format(_docling_doc([item]))
    assert [b["prov_index"] for b in result[0] + result[1]] == [0, 1]
    assert result[0][0]["docling_ref"] == result[1][0]["docling_ref"]


def test_convert_binds_caption_and_footnote_to_table(layout_service):
    caption = Item("caption", 1, _BBox(50, 720, 500, 705), text="Table 2.1: Grants released")
    note = Item("footnote", 1, _BBox(50, 480, 500, 470), text="Source: Finance Accounts")
    table = TableItem(1, _BBox(50, 700, 500, 500), "| A | B |\n|---|---|\n| 1 | 2 |")
    table.captions = [_Ref(caption)]
    table.footnotes = [_Ref(note)]
    blocks = layout_service._convert_docling_doc_to_standard_format(_docling_doc([caption, table, note]))[0]

    by_label = {b["docling_label"]: b for b in blocks}
    assert by_label["table"]["docling_caption"] == "Table 2.1: Grants released"
    assert by_label["table"]["docling_footnotes"] == ["Source: Finance Accounts"]
    assert by_label["caption"]["bound_to"] == table.self_ref
    assert by_label["footnote"]["bound_to"] == table.self_ref


def test_convert_ignores_running_header_bound_as_caption(layout_service):
    header = Item("caption", 1, _BBox(50, 790, 500, 780), text="Report No. 8 of 2025")
    table = TableItem(1, _BBox(50, 700, 500, 500), "| A | B |\n|---|---|\n| 1 | 2 |")
    table.captions = [_Ref(header)]
    blocks = layout_service._convert_docling_doc_to_standard_format(_docling_doc([header, table]))[0]
    by_label = {b["docling_label"]: b for b in blocks}
    assert "docling_caption" not in by_label["table"]
    assert "bound_to" not in by_label["caption"]


def test_convert_ignores_caption_nearer_to_another_table(layout_service):
    # "Table 2" is printed just above the second table; Docling bound it to the first
    cap1 = Item("caption", 1, _BBox(50, 720, 500, 705), text="Table 1: Core grant")
    first = TableItem(1, _BBox(50, 700, 500, 560), "| A | B |\n|---|---|\n| 1 | 2 |")
    cap2 = Item("caption", 1, _BBox(50, 545, 500, 530), text="Table 2: Other grants")
    second = TableItem(1, _BBox(50, 525, 500, 380), "| A | B |\n|---|---|\n| 3 | 4 |")
    first.captions = [_Ref(cap2)]
    blocks = layout_service._convert_docling_doc_to_standard_format(
        _docling_doc([cap1, first, cap2, second])
    )[0]
    tables = [b for b in blocks if b["docling_label"] == "table"]
    assert "docling_caption" not in tables[0]
    assert all("bound_to" not in b for b in blocks if b["docling_label"] == "caption")


def test_convert_skips_items_without_provenance(layout_service):
    item = Item("text", 1, _BBox(0, 10, 10, 0))
    item.prov = []
    assert layout_service._convert_docling_doc_to_standard_format(_docling_doc([item])) == {}


def test_convert_keeps_docling_table_markdown(layout_service):
    layout_service.table_min_non_empty_cells = 3
    markdown = "| Year | Amount |\n| --- | --- |\n| 2022-23 | 120.5 |"
    doc = _docling_doc([TableItem(1, _BBox(50, 700, 500, 500), markdown)])

    block = layout_service._convert_docling_doc_to_standard_format(doc)[0][0]

    assert block["label"] == "Table"
    assert block["docling_table_available"] is True
    assert block["docling_table_markdown"] == markdown


def test_convert_rejects_sparse_docling_table(layout_service):
    layout_service.table_min_non_empty_cells = 3
    doc = _docling_doc([TableItem(1, _BBox(50, 700, 500, 500), "| A |  |\n|---|---|\n|  |  |")])

    block = layout_service._convert_docling_doc_to_standard_format(doc)[0][0]

    assert block["docling_table_available"] is False
    assert "docling_table_markdown" not in block
