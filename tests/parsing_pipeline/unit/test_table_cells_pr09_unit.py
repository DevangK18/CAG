"""
Table cells (PR 9):
- a column edge never cuts a word or number between two cells
- cells set vertically read along their own lines (BR p.194)
- a table holding little of its region's text is left to Docling
"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import fitz
import pdfplumber
import pytest

from src.parsing_pipeline.extractors.pdfplumber_table_extractor import (
    PdfplumberTableExtractor,
)
from src.parsing_pipeline.modules.structured_table_extractor import (
    StructuredTableExtractor,
)

CORPUS = Path("/Users/dev/Projects/CAG/data/review_corpus/pdfs")
BR_PDF = (
    CORPUS
    / "BR_2024_03_Report_on_Local_Government_in_Bihar_for_the_year_ended_31st_March_2022.pdf"
)
DT_PDF = CORPUS / (
    "2022_29_Compliance_Audit_on_Direct_taxes_for_period_202021_for_the_Union_Government_Depa.pdf"
)


@pytest.fixture
def extractor():
    ex = PdfplumberTableExtractor()
    yield ex
    ex.close()


def _rows_pdf(path: Path) -> Path:
    doc = fitz.open()
    page = doc.new_page(width=400, height=200)
    y = 50
    for left, right in (
        ("Particulars", "Amount"),
        ("Revenue", "12,345"),
        ("Indirect Taxes Receipts", "3,40,592"),
    ):
        page.insert_text((50, y), left, fontsize=10)
        page.insert_text((200, y), right, fontsize=10)
        y += 20
    doc.save(path)
    return path


class TestWholeWords:
    def test_column_edge_through_words(self, tmp_path):
        # Edges at x=110 and x=215 run through "Taxes" and the amounts
        with pdfplumber.open(_rows_pdf(tmp_path / "cut.pdf")) as pdf:
            table = pdf.pages[0].find_tables(
                {
                    "vertical_strategy": "explicit",
                    "horizontal_strategy": "explicit",
                    "explicit_vertical_lines": [40, 110, 190, 215, 260],
                    "explicit_horizontal_lines": [38, 55, 75, 95],
                }
            )[0]
            assert table.extract()[2][:2] == ["Indirect Taxe", "s Receipts"]
            cells = PdfplumberTableExtractor._extract_cells(table)
        assert cells[0] == ["Particulars", "", "", "Amount"]
        assert cells[1] == ["Revenue", "", "", "12,345"]
        assert cells[2] == ["Indirect Taxes", "Receipts", "", "3,40,592"]

    def test_same_cells_when_no_word_is_cut(self, tmp_path):
        with pdfplumber.open(_rows_pdf(tmp_path / "ok.pdf")) as pdf:
            table = pdf.pages[0].find_tables(
                {
                    "vertical_strategy": "explicit",
                    "horizontal_strategy": "explicit",
                    "explicit_vertical_lines": [40, 180, 260],
                    "explicit_horizontal_lines": [38, 55, 75, 95],
                }
            )[0]
            assert PdfplumberTableExtractor._extract_cells(table) == table.extract()

    @pytest.mark.skipif(not DT_PDF.exists(), reason="review corpus PDF not available")
    def test_direct_taxes_resources_table(self, extractor):
        # 2022_29 p.16 Table 1.1, read with whitespace columns: run D had
        # "Indirect Tax | es Receipts i | ncluding" and "D. Publi | c Debt Receipts"
        bbox = [143.62, 71.58, 523.56, 220.74]
        result = extractor.extract(str(DT_PDF), 16, bbox)
        assert result is not None
        assert "Tax | es" not in result.content
        assert "Publi | c" not in result.content
        assert "Indirect Taxes" in result.content


class TestVerticalCells:
    @pytest.mark.parametrize("rotate,origin", [(90, (60, 200)), (270, (60, 60))])
    def test_vertical_cell_reads_in_line_order(self, tmp_path, rotate, origin):
        doc = fitz.open()
        page = doc.new_page(width=300, height=300)
        page.insert_text(origin, "Number of\nhouseholds", fontsize=10, rotate=rotate)
        page.insert_text((150, 150), "Total", fontsize=10)
        doc.save(tmp_path / "v.pdf")
        with pdfplumber.open(tmp_path / "v.pdf") as pdf:
            chars = pdf.pages[0].chars
            vertical = [c for c in chars if c["x0"] < 140]
            upright = [c for c in chars if c["x0"] > 140]
            assert (
                PdfplumberTableExtractor._cell_text(vertical) == "Number of\nhouseholds"
            )
            assert PdfplumberTableExtractor._cell_text(upright) == "Total"
        assert PdfplumberTableExtractor._cell_text([]) == ""

    @pytest.mark.skipif(not BR_PDF.exists(), reason="review corpus PDF not available")
    def test_bihar_p194_header_cells_in_order(self, extractor):
        # Header cells set vertically inside a table printed sideways
        bbox = [150.04, 87.26, 525.44, 784.55]
        result = extractor.extract(str(BR_PDF), 194, bbox)
        rows = StructuredTableExtractor()._parse_markdown_table(result.content)
        header = rows[1]
        assert "Number of households" in header
        assert "No. of BPL household in the area" in header
        assert "Minimum User charge collectible 2020-21" in header
        assert "User charges Collected in 2020- 21&2021-22" in rows[0]


class TestCoverageFloor:
    def _state(self, cropped):
        page = SimpleNamespace(width=600, height=800, crop=lambda box: cropped)
        return {"rotation": 0, "upright_page": None, "page": page, "vocabulary": set()}

    def _cropped(self, text, ruled, whitespace=()):
        def find_tables(table_settings):
            ruled_strategy = table_settings["vertical_strategy"] == "lines"
            return ruled if ruled_strategy else list(whitespace)

        return SimpleNamespace(extract_text=lambda: text, find_tables=find_tables)

    def _fake(self, rows):
        return SimpleNamespace(bbox=(0, 0, 100, 100), extract=lambda: rows)

    def test_title_box_alone_left_to_docling(self, extractor):
        # A ruled box around the title; the rest of the region (a flow chart) unruled
        title = self._fake(
            [["Annexure 3.1", "Flow chart"], ["Reference", "paragraph 3.1.5"]]
        )
        text = "Annexure 3.1 Flow chart Reference paragraph " + " ".join(
            f"step{i} forwarding proposals railway board" for i in range(10)
        )
        with patch.object(
            PdfplumberTableExtractor,
            "_extract_cells",
            staticmethod(lambda t: t.extract()),
        ):
            raw, method = extractor._extract_from_page(
                self._state(self._cropped(text, [title])), 5, [0, 0, 100, 100]
            )
        assert raw is None and method == ""

    def test_table_covering_its_region_kept(self, extractor):
        table = self._fake([["Name", "Amount"], ["Gaya", "12.50"], ["Patna", "300.75"]])
        text = "Name Amount Gaya 12.50 Patna 300.75"
        with patch.object(
            PdfplumberTableExtractor,
            "_extract_cells",
            staticmethod(lambda t: t.extract()),
        ):
            raw, method = extractor._extract_from_page(
                self._state(self._cropped(text, [table])), 5, [0, 0, 100, 100]
            )
        assert method == "lines"
        assert raw[1] == ["Gaya", "12.50"]


def _put(page, x, y, text, size=10):
    """Place each character on its own, so both readers agree on every origin."""
    for ch in text:
        page.insert_text((x, y), ch, fontsize=size)
        x += fitz.get_text_length(ch, fontsize=size)


def _hidden_text_pdf(path: Path) -> Path:
    # Left half of a two-column source page placed with a clip (InDesign "PlacedPDF")
    src = fitz.open()
    source = src.new_page(width=600, height=300)
    for i, (name, amount) in enumerate(
        [("Name", "Amount"), ("Gaya", "12.50"), ("Patna", "300.75")]
    ):
        _put(source, 50, 50 + 20 * i, name)
        _put(source, 150, 50 + 20 * i, amount)
        _put(source, 350, 50 + 20 * i, "Hidden" + name)
        _put(source, 450, 50 + 20 * i, "9" + amount)
    doc = fitz.open()
    page = doc.new_page(width=300, height=300)
    page.show_pdf_page(page.rect, src, 0, clip=fitz.Rect(0, 0, 300, 300))
    # An old figure painted over with a white box and the new one printed on top
    _put(page, 50, 200, "Old 2750")
    page.draw_rect(fitz.Rect(40, 185, 200, 210), color=None, fill=(1, 1, 1))
    _put(page, 52, 230, "New 2,750")
    doc.save(path)
    return path


DT26_PDF = CORPUS / (
    "2025_26_Compliance_Audit_on_on_Development_of_MultiFunctional_Complexes_and_Commercial_s.pdf"
)
NLC_PDF = CORPUS / (
    "2025_35_Performance_Audit_on_Operational_Performance_of_NLC_India_Limited_Ministry_of_Co.pdf"
)


class TestHiddenText:
    def test_clipped_and_painted_over_text_dropped(self, extractor, tmp_path):
        pdf = _hidden_text_pdf(tmp_path / "placed.pdf")
        with pdfplumber.open(pdf) as raw:
            assert "Hidden" in raw.pages[0].extract_text()
        state = extractor._get_page_state(str(pdf), 0)
        text = state["page"].extract_text()
        assert "Hidden" not in text and "912.50" not in text
        assert "Old" not in text
        assert "Gaya" in text and "300.75" in text and "N e w" in text

    def test_page_without_hidden_text_untouched(self, extractor, tmp_path):
        doc = fitz.open()
        page = doc.new_page(width=300, height=300)
        _put(page, 50, 50, "Gaya 12.50")
        doc.save(tmp_path / "plain.pdf")
        state = extractor._get_page_state(str(tmp_path / "plain.pdf"), 0)
        assert state["page"] is state["page"].pdf.pages[0]

    @pytest.mark.skipif(not DT26_PDF.exists(), reason="review corpus PDF not available")
    def test_placed_pdf_page_2025_26(self, extractor):
        # p.51: run D had "Propo sals", "Areea pending", "N oo."
        result = extractor.extract(str(DT26_PDF), 51, [101.05, 109.22, 542.38, 433.45])
        assert "Proposals approved" in result.content
        assert "Area pending" in result.content and "Areea" not in result.content

    @pytest.mark.skipif(not NLC_PDF.exists(), reason="review corpus PDF not available")
    def test_white_box_over_old_table_2025_35(self, extractor):
        # p.57 Table 3.6: run D had "22,775500" (old and new figures interleaved)
        bbox = [65.96, 302.66, 501.16, 438.62]
        result = extractor.extract(str(NLC_PDF), 57, bbox)
        assert (
            "| 2,750 | 2,730 | 2,559.94 | 2,642.61 | 2,900 | 2,908 |" in result.content
        )
