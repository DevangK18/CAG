"""
Unit tests for PdfplumberTableExtractor (PR 7):
- B-6-05: landscape tables typeset sideways on /Rotate 0 pages are read upright
- B-6-12: several tables in one bbox, pipes in cells, one open per document
"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import fitz
import pytest

from src.parsing_pipeline.extractors import pdfplumber_table_extractor as module
from src.parsing_pipeline.extractors.pdfplumber_table_extractor import (
    PdfplumberTableExtractor,
)
from src.parsing_pipeline.modules.structured_table_extractor import (
    StructuredTableExtractor,
)

CELLS = [
    ["Sl. No.", "District", "Remarks", "Amount"],
    ["1", "Gaya", "Pending", "12.50"],
    ["2", "Patna", "Completed", "300.75"],
    ["3", "Nalanda", "Delayed", "48.20"],
]


def _landscape_table_page(doc):
    """A ruled 4x4 table on a landscape page; returns the page."""
    page = doc.new_page(width=842, height=595)
    x0, y0, col_w, row_h = 80, 100, 160, 30
    for r in range(len(CELLS) + 1):
        page.draw_line((x0, y0 + r * row_h), (x0 + 4 * col_w, y0 + r * row_h))
    for c in range(5):
        page.draw_line((x0 + c * col_w, y0), (x0 + c * col_w, y0 + len(CELLS) * row_h))
    for r, row in enumerate(CELLS):
        for c, text in enumerate(row):
            page.insert_text(
                (x0 + c * col_w + 5, y0 + r * row_h + 20), text, fontsize=10
            )
    return page


def _sideways_pdf(path: Path, rotate: int) -> Path:
    """A portrait /Rotate 0 page with the landscape table drawn turned by `rotate`."""
    src = fitz.open()
    _landscape_table_page(src)
    out = fitz.open()
    page = out.new_page(width=595, height=842)
    page.show_pdf_page(page.rect, src, 0, rotate=rotate)
    out.save(path)
    return path


@pytest.fixture
def extractor():
    ex = PdfplumberTableExtractor()
    yield ex
    ex.close()


class TestSidewaysTables:
    @pytest.mark.parametrize("rotate,direction", [(90, -1), (-90, 1)])
    def test_sideways_table_reads_left_to_right(
        self, extractor, tmp_path, rotate, direction
    ):
        pdf = _sideways_pdf(tmp_path / f"side{rotate}.pdf", rotate)
        assert extractor._vertical_direction(str(pdf), 0) == direction
        result = extractor.extract(str(pdf), 0, [20, 20, 575, 822])
        assert result is not None
        table = StructuredTableExtractor()._parse_markdown_table(result.content)
        assert table[0] == CELLS[0]
        assert ["2", "Patna", "Completed", "300.75"] in table

    def test_upright_page_untouched(self, extractor, tmp_path):
        doc = fitz.open()
        _landscape_table_page(doc)
        doc.save(tmp_path / "flat.pdf")
        assert extractor._vertical_direction(str(tmp_path / "flat.pdf"), 0) == 0
        result = extractor.extract(str(tmp_path / "flat.pdf"), 0, [60, 80, 760, 240])
        assert (
            StructuredTableExtractor()._parse_markdown_table(result.content)[1][2]
            == "Pending"
        )

    def test_rotated_page_still_deferred_to_docling(self, extractor, tmp_path):
        doc = fitz.open()
        page = _landscape_table_page(doc)
        page.set_rotation(90)
        doc.save(tmp_path / "rot.pdf")
        assert extractor.extract(str(tmp_path / "rot.pdf"), 0, [0, 0, 595, 842]) is None

    @pytest.mark.parametrize("direction", [-1, 1])
    def test_bbox_transform_round_trip(self, direction):
        # The corners of the page map onto the corners of the upright copy
        w, h = 600.0, 800.0
        box = PdfplumberTableExtractor._upright_bbox([0, 0, w, h], direction, w, h)
        assert box == [0, 0, h, w]

    def test_dominant_direction_needs_a_majority(self):
        def line(d, text):
            return {"dir": d, "spans": [{"text": text}]}

        blocks = [{"lines": [line((0.0, -1.0), "x" * 60), line((1.0, 0.0), "y" * 40)]}]
        assert PdfplumberTableExtractor._dominant_vertical_direction(blocks) == -1
        blocks = [{"lines": [line((0.0, 1.0), "x" * 40), line((1.0, 0.0), "y" * 60)]}]
        assert PdfplumberTableExtractor._dominant_vertical_direction(blocks) == 0


BR_PDF = Path(
    "/Users/dev/Projects/CAG/data/review_corpus/pdfs/"
    "BR_2024_03_Report_on_Local_Government_in_Bihar_for_the_year_ended_31st_March_2022.pdf"
)


@pytest.mark.skipif(not BR_PDF.exists(), reason="review corpus PDF not available")
def test_bihar_sideways_appendix_not_reversed(extractor):
    # BR p.199 (0-based): Appendix-5.8, text runs bottom to top on a /Rotate 0 page
    result = extractor.extract(str(BR_PDF), 199, [60, 60, 570, 820])
    assert result is not None
    assert "Sl. No." in result.content
    assert "lS. oN." not in result.content


class TestCellsAndRegions:
    def test_pipe_in_cell_escaped_and_round_trips(self, extractor):
        markdown = extractor._to_markdown([["Item", "Value"], ["A | B", "1"]])
        assert "A \\| B" in markdown
        rows = StructuredTableExtractor()._parse_markdown_table(markdown)
        assert rows[1] == ["A | B", "1"]

    def _table(self, top, rows, x0=0, x1=100, bottom=None):
        bbox = (x0, top, x1, bottom if bottom is not None else top + 10)
        return SimpleNamespace(bbox=bbox, extract=lambda: rows)

    def test_different_tables_not_concatenated(self, extractor):
        small = self._table(0, [["Note", "x"], ["a", "b"]], x0=200, x1=300)
        big = self._table(
            50,
            [
                ["Sl", "Name", "Amount"],
                ["1", "Gaya", "12.50"],
                ["2", "Patna", "300.75"],
            ],
        )
        best = extractor._best_table([small, big], ["Gaya", "Patna", "12.50", "300.75"])
        assert best == [
            ["Sl", "Name", "Amount"],
            ["1", "Gaya", "12.50"],
            ["2", "Patna", "300.75"],
        ]

    def test_same_width_pieces_joined(self, extractor):
        top = self._table(0, [["Sl", "Name"], ["1", "Gaya"]])
        bottom = self._table(50, [["2", "Patna"]])
        assert extractor._best_table([bottom, top], []) == [
            ["Sl", "Name"],
            ["1", "Gaya"],
            ["2", "Patna"],
        ]

    def test_same_edges_joined_and_padded(self, extractor):
        # A rule gap splits one table; double rules make the pieces differ in width
        top = self._table(0, [["Sl", "Name", "Amount"], ["1", "Gaya", "12.50"]])
        bottom = self._table(50, [["2", "Patna"]])
        assert extractor._best_table([top, bottom], []) == [
            ["Sl", "Name", "Amount"],
            ["1", "Gaya", "12.50"],
            ["2", "Patna", None],
        ]

    def test_nested_header_cell_tables_dropped(self, extractor):
        # Header cells drawn as filled rectangles come back as tables inside the table
        main = self._table(0, [["Sl. No.", "Name"], ["1", "Gaya"]], bottom=100)
        cell = self._table(2, [["Sl."], ["No."]], x0=5, x1=40)
        assert extractor._best_table([main, cell], []) == [
            ["Sl. No.", "Name"],
            ["1", "Gaya"],
        ]

    def test_document_opened_once(self, tmp_path):
        doc = fitz.open()
        _landscape_table_page(doc)
        _landscape_table_page(doc)
        doc.save(tmp_path / "two.pdf")
        ex = PdfplumberTableExtractor()
        real_open = module.pdfplumber.open
        with patch.object(module.pdfplumber, "open", side_effect=real_open) as opened:
            for page in (0, 0, 1, 1):
                assert (
                    ex.extract(str(tmp_path / "two.pdf"), page, [60, 80, 760, 240])
                    is not None
                )
        ex.close()
        assert opened.call_count == 1

    def test_source_chunk_id_passed_through(self, extractor, tmp_path):
        doc = fitz.open()
        _landscape_table_page(doc)
        doc.save(tmp_path / "t.pdf")
        result = extractor.extract(
            str(tmp_path / "t.pdf"), 0, [60, 80, 760, 240], source_chunk_id="b_0_3"
        )
        assert result.structured_data["source_chunk_id"] == "b_0_3"


def test_raised_digits_after_a_word_become_markers():
    from types import SimpleNamespace

    def ch(text, size=10.0, bottom=100.0, font="Arial"):
        return {"text": text, "size": size, "bottom": bottom, "fontname": font}

    chars = [ch("T"), ch("a"), ch("x"), ch("1", 6.0, 96.0), ch("2", 6.0, 96.0),
             ch(" "), ch("5"), ch("m"), ch("2", 6.0, 96.0), ch("`", font="RupeeForadian")]
    page = SimpleNamespace(chars=chars)
    PdfplumberTableExtractor._mark_chars(page)
    assert "".join(c["text"] for c in chars) == "Tax[^12] 5m2₹"


def test_backwards_cells_on_upright_copy_are_flipped():
    ext = PdfplumberTableExtractor.__new__(PdfplumberTableExtractor)
    raw = [["Sl. No.", "LPB ni dlohesuoh aera fo eht .oN"], ["1.", "DNA"]]
    cleaned = ext._clean_raw_table(raw, rotation=0, check_reversal=False)
    assert cleaned == [["Sl. No.", "No. the of area household in BPL"], ["1.", "DNA"]]
