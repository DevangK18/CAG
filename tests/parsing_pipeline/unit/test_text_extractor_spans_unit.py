"""
Unit tests for TextExtractor's span-level repairs: footnote markers from superscript
digits (B-6-19), the rupee sign from Rupee fonts (B-6-06) and sideways text (B-6-05).
"""

from pathlib import Path

import fitz
import pytest

from src.parsing_pipeline.extractors.text_extractor import TextExtractor, word_fixes
from src.parsing_pipeline.extractors.text_repair import (
    respace_letter_spaced,
    reverse_words,
)

PDFS = Path("/Users/dev/Projects/CAG/data/review_corpus/pdfs")
BR_PDF = (
    PDFS
    / "BR_2024_03_Report_on_Local_Government_in_Bihar_for_the_year_ended_31st_March_2022.pdf"
)


def _put(page, x, y, text, size):
    page.insert_text((x, y), text, fontsize=size, fontname="helv")
    return x + fitz.get_text_length(text, "helv", size)


@pytest.fixture
def page():
    doc = fitz.open()
    yield doc.new_page()
    doc.close()


def _read(page, rect):
    return TextExtractor()._extract_text_with_rotation_handling(page, fitz.Rect(rect))


class TestFootnoteMarkers:
    def test_superscript_after_amount_becomes_marker(self, page):
        x = _put(page, 72, 100, "Loss of Rs. 1.14 crore", 12)
        x = _put(page, x, 95, "36", 7)
        _put(page, x, 100, " was not recovered.", 12)
        assert (
            _read(page, (60, 85, 560, 110))
            == "Loss of Rs. 1.14 crore[^36] was not recovered."
        )

    def test_superscript_before_punctuation(self, page):
        x = _put(page, 72, 100, "the Vision document", 12)
        x = _put(page, x, 95, "1", 7)
        _put(page, x, 100, ". This requires", 12)
        assert (
            _read(page, (60, 85, 560, 110)) == "the Vision document[^1]. This requires"
        )

    def test_footnote_text_keeps_its_number(self, page):
        x = _put(page, 72, 200, "36", 7)
        _put(page, x, 205, "The Government notified the rules.", 9)
        assert (
            _read(page, (60, 190, 560, 210)) == "36 The Government notified the rules."
        )

    def test_exponent_and_subscript_left_alone(self, page):
        x = _put(page, 72, 300, "Area of 10,000 m", 12)
        x = _put(page, x, 295, "2", 7)
        _put(page, x, 300, " was", 12)
        x = _put(page, 72, 400, "emission of pCO", 12)
        x = _put(page, x, 403, "2", 7)
        _put(page, x, 400, " sensors", 12)
        assert _read(page, (60, 285, 560, 310)) == "Area of 10,000 m2 was"
        assert _read(page, (60, 390, 560, 410)) == "emission of pCO2 sensors"

    def test_text_without_superscripts_unchanged(self, page):
        _put(page, 72, 100, "Plain text with 2018-19 figures and 36 items.", 12)
        rect = fitz.Rect(60, 85, 560, 110)
        assert _read(page, rect) == page.get_text("text", clip=rect, sort=True)

    def test_power_of_ten_is_not_a_footnote(self, page):
        x = _put(page, 72, 100, "one million million (10", 12)
        x = _put(page, x, 95, "12", 7)
        x = _put(page, x, 100, ") operations in 2008", 12)
        x = _put(page, x, 95, "57", 7)
        assert (
            _read(page, (60, 85, 560, 110))
            == "one million million (10^12) operations in 2008[^57]"
        )

    def test_markers_recorded_on_item(self, tmp_path):
        doc = fitz.open()
        p = doc.new_page()
        x = _put(p, 72, 100, "there were 8,629 PRIs", 12)
        x = _put(p, x, 95, "4", 7)
        x = _put(p, x, 100, " and 2,47,426 posts", 12)
        x = _put(p, x, 95, "5", 7)
        path = tmp_path / "markers.pdf"
        doc.save(path)
        item = TextExtractor().extract(str(path), 0, [60, 85, 560, 110], label="Text")
        assert item.content == "there were 8,629 PRIs[^4] and 2,47,426 posts[^5]"
        assert item.structured_data == {"footnote_markers": ["4", "5"]}

    def test_marker_survives_reversal_and_respacing(self):
        assert reverse_words("ahbaS[^2], eht erorc[^36]") == "Sabha[^2], the crore[^36]"
        vocab = {"gram": 5, "sabha": 5, "the": 9}
        assert "Sabha[^2]" in respace_letter_spaced(
            "G r a m S a b h a [^2] o f t h e", vocab
        )

    @pytest.mark.skipif(not BR_PDF.exists(), reason="review corpus PDF not available")
    def test_real_report_markers(self):
        doc = fitz.open(BR_PDF)
        text = TextExtractor()._extract_text_with_rotation_handling(
            doc[21], doc[21].rect
        )
        assert "PRIs[^4]" in text and "representatives[^5]" in text
        assert "PRIs4" not in text


def _char(c, x, origin_y=100.0):
    return {
        "c": c,
        "origin": (x, origin_y),
        "bbox": (x, origin_y - 10, x + 5, origin_y),
    }


def _rawdict(spans):
    return {"blocks": [{"number": 0, "type": 0, "lines": [{"spans": spans}]}]}


class TestRupeeFont:
    def test_backtick_in_rupee_font_becomes_rupee(self):
        spans = [
            {
                "size": 10,
                "flags": 0,
                "font": "Rupee Foradian",
                "chars": [_char("`", 0)],
            },
            {"size": 10, "flags": 0, "font": "TimesNewRoman", "chars": [_char(" ", 5)]},
            {
                "size": 10,
                "flags": 0,
                "font": "TimesNewRoman",
                "chars": [_char(c, 10 + i) for i, c in enumerate("in")],
            },
        ]
        words = [(0, 0, 5, 10, "`", 0, 0, 0), (10, 0, 20, 10, "in", 0, 0, 1)]
        assert word_fixes(_rawdict(spans), words) == {"`": "₹"}

    def test_backtick_in_other_font_kept(self):
        spans = [
            {
                "size": 10,
                "flags": 0,
                "font": "Calibri",
                "chars": [_char(c, i) for i, c in enumerate("`NULL`")],
            }
        ]
        words = [(0, 0, 30, 10, "`NULL`", 0, 0, 0)]
        assert word_fixes(_rawdict(spans), words) == {}


KA_PDF = (
    PDFS
    / "KA_2022_06_Performance_Audit_of_Mukhyamanthrigala_Nagarothana_Yojane_PhaseIII_for_City_Corp.pdf"
)


class TestSidewaysText:
    def test_bottom_to_top_lines_read_in_order(self, page):
        page.insert_text(
            (100, 700), "Audit Report on Local Government", fontsize=12, rotate=90
        )
        page.insert_text(
            (116, 700), "for the year ended March 2022", fontsize=12, rotate=90
        )
        assert (
            _read(page, page.rect)
            == "Audit Report on Local Government\nfor the year ended March 2022"
        )

    def test_top_to_bottom_lines_read_in_order(self, page):
        page.insert_text(
            (116, 100), "Audit Report on Local Government", fontsize=12, rotate=270
        )
        page.insert_text(
            (100, 100), "for the year ended March 2022", fontsize=12, rotate=270
        )
        assert (
            _read(page, page.rect)
            == "Audit Report on Local Government\nfor the year ended March 2022"
        )

    def test_mostly_horizontal_clip_unchanged(self, page):
        _put(
            page,
            72,
            100,
            "A horizontal paragraph that is long enough to dominate the clip.",
            11,
        )
        page.insert_text((60, 300), "side", fontsize=8, rotate=90)
        assert _read(page, page.rect) == page.get_text("text", sort=True)

    @pytest.mark.skipif(not KA_PDF.exists(), reason="review corpus PDF not available")
    def test_real_sideways_annexure(self):
        doc = fitz.open(KA_PDF)
        text = " ".join(
            TextExtractor()
            ._extract_text_with_rotation_handling(doc[79], doc[79].rect)
            .split()
        )
        assert text.startswith(
            "Appendices Appendix 2.9 (Reference: Paragraph 2.9.6/Page 17)"
        )
        assert "(₹ in lakh)" in text
