"""
Unit tests for text a reader cannot see and for misread text directions:
- a paragraph painted over by a white box and retyped on top (2025_35, GJ), which read
  twice and was then reversed ("elb'noHelb'noH");
- digits set below 2 pt next to footnote markers (BR: "Corporations447");
- glued or doubled words taken for reversed text (2025_03 signature, 2025_35);
- OCR read from upside-down scans (RJ chapter dividers).
Real-PDF regressions run when the review corpus is present.
"""

import os
from collections import Counter
from pathlib import Path

import fitz
import pytest

from src.parsing_pipeline.extractors.text_extractor import (
    TextExtractor,
    covered_glyphs,
    sorted_text,
    visible_words,
)
from src.parsing_pipeline.extractors.text_repair import is_garbled, is_reversed

REPO_ROOT = Path(__file__).resolve().parents[3]
PDF_DIR = Path(
    os.getenv("CAG_REVIEW_PDF_DIR") or REPO_ROOT / "data" / "review_corpus" / "pdfs"
)
OLD = "Hon'ble Supreme Court of India ordered the review of all mining projects"
NEW = "Hon'ble Supreme Court of India ordered that all mining projects be revalidated"


def _overprinted(path):
    """A paragraph painted over by a white box, with the edited text typed on top."""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), OLD, fontsize=10)
    page.draw_rect(fitz.Rect(70, 88, 540, 104), color=None, fill=(1, 1, 1))
    page.insert_text((72.3, 100), NEW, fontsize=10)
    page.insert_text((72, 140), "Unchanged paragraph below the box.", fontsize=10)
    doc.save(path)
    return path


def _extract(path, page_num, rect, label="Text"):
    result = TextExtractor().extract(str(path), page_num, list(rect), label=label)
    return result.content if result else None


class TestCoveredText:
    def test_painted_over_paragraph_is_not_read(self, tmp_path):
        path = _overprinted(str(tmp_path / "r.pdf"))
        assert _extract(path, 0, (60, 80, 550, 110)) == NEW

    def test_text_outside_the_box_unchanged(self, tmp_path):
        path = _overprinted(str(tmp_path / "r.pdf"))
        assert (
            _extract(path, 0, (60, 125, 550, 150))
            == "Unchanged paragraph below the box."
        )

    def test_covered_glyphs_lists_only_the_old_text(self, tmp_path):
        doc = fitz.open(_overprinted(str(tmp_path / "r.pdf")))
        covered = covered_glyphs(doc[0])
        assert sum(len(v) for v in covered.values()) == len(OLD.replace(" ", ""))

    def test_box_drawn_before_the_text_hides_nothing(self, tmp_path):
        doc = fitz.open()
        page = doc.new_page()
        page.draw_rect(fitz.Rect(70, 88, 540, 104), color=None, fill=(1, 1, 1))
        page.insert_text((72, 100), NEW, fontsize=10)
        assert covered_glyphs(page) == {}

    def test_nothing_hidden_returns_none(self, tmp_path):
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 100), NEW, fontsize=10)
        textpage = page.get_textpage(flags=fitz.TEXTFLAGS_TEXT)
        assert visible_words(textpage, {}) is None


class TestTinyText:
    def test_digit_below_two_points_dropped(self, tmp_path):
        doc = fitz.open()
        page = doc.new_page()
        x = 72 + fitz.get_text_length("eight Councils", "helv", 12)
        page.insert_text((72, 100), "eight Councils", fontsize=12)
        page.insert_text((x, 100), "8", fontsize=1, color=(1, 1, 1))
        page.insert_text((x + 2, 100), " and nine Nagar Panchayats", fontsize=12)
        path = str(tmp_path / "r.pdf")
        doc.save(path)
        text = _extract(path, 0, (60, 85, 550, 110))
        assert "8" not in text
        assert text.startswith("eight Councils")


class TestSortedText:
    def test_same_as_pymupdf_sorted_text(self):
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((300, 100), "right column", fontsize=10)
        page.insert_text((72, 101), "left column", fontsize=10)
        page.insert_text((72, 140), "next line after a gap", fontsize=10)
        textpage = page.get_textpage(flags=fitz.TEXTFLAGS_TEXT)
        assert sorted_text(textpage.extractWORDS()) == page.get_text("text", sort=True)


class TestReversedFalsePositives:
    @pytest.mark.parametrize(
        "text",
        [
            # Doubled words from overprinted text
            "Hon'bleHon'ble SupremeSupreme CourtCourt ofof IndiaIndia orderedordered",
            # A signature stamp's two columns glued word to word
            "Purushott DigitallyPurushottamsignedTiwaryby am Tiwary Date:09:27:07",
        ],
    )
    def test_glued_or_doubled_words_are_not_reversed(self, text):
        assert not is_reversed(text)

    def test_reversed_proper_nouns_still_detected(self):
        assert is_reversed("gnarabaN tcirtsiD ,ruprayaN tcirtsiD ,kudnaR tcirtsiD")


class TestUpsideDownOcr:
    VOCAB = Counter({w: 3 for w in "user charges for solid waste management".split()})

    def test_garbled_ocr_detected(self):
        assert is_garbled("A1-.1aJdBq3 V Al!l!Qgl!gA JO 's~n.ia 'sau!~!Paw", self.VOCAB)

    def test_words_are_not_garbled(self):
        assert not is_garbled("User charges for solid waste management", self.VOCAB)

    def _flipped(self, path, text):
        doc = fitz.open()
        for _ in range(3):  # pages that give the report its vocabulary
            doc.new_page().insert_text(
                (72, 100), "User charges for solid waste management", fontsize=10
            )
        page = doc.new_page()
        page.insert_text((400, 400), text, fontsize=14, rotate=180)
        doc.save(path)
        return path

    def test_upside_down_ocr_noise_dropped(self, tmp_path):
        path = self._flipped(
            str(tmp_path / "r.pdf"), "A1-.1aJdBq3 Al!l!Qgl!gA 'sau!~!Paw"
        )
        assert _extract(path, 3, (0, 0, 595, 842)) is None

    def test_upside_down_words_kept(self, tmp_path):
        path = self._flipped(
            str(tmp_path / "r.pdf"), "User charges for solid waste management"
        )
        assert "solid waste" in _extract(path, 3, (0, 0, 595, 842))


def _pdf(prefix):
    matches = sorted(PDF_DIR.glob(f"{prefix}*.pdf")) if PDF_DIR.is_dir() else []
    if not matches:
        pytest.skip(f"{prefix} PDF not under {PDF_DIR} (set CAG_REVIEW_PDF_DIR)")
    return str(matches[0])


class TestRealReports:
    def test_2025_35_edited_paragraph_reads_once(self):
        text = _extract(_pdf("2025_35"), 30, (100, 165, 545, 300))
        assert text.startswith("Hon'ble Supreme Court of India ordered (August 2017)")
        assert "SupremeSupreme" not in text and not is_reversed(text)

    def test_bihar_hidden_reference_numbers_dropped(self):
        text = _extract(_pdf("BR_2024"), 74, (161.0, 214.4, 542.0, 255.3))
        assert "Corporations[^44], 11 Municipal Councils[^45]" in text
        assert "Panchayats[^46]," in text

    def test_2025_03_signature_not_reversed(self):
        text = _extract(_pdf("2025_03"), 0, (234.2, 562.5, 528.8, 645.9))
        assert "Digitally" in text


class TestShiftedFontByFont:
    """2023_07 p.85: a font mapped 29 code points low, split by Docling into words."""

    def test_single_word_block_decoded(self):
        # "QJLQHHUV" alone does not read as English; its font does
        assert _extract(_pdf("2023_07"), 85, (137, 74, 188, 86)) == "Engineers"

    def test_digits_and_punctuation_kept(self):
        text = _extract(_pdf("2023_07"), 85, (70.8, 37.7, 508.5, 127.8))
        assert text.startswith("Report No. 7 of 2023 Independent Engineers")
        assert "projects, rectifying" in text

    def test_preflight_expects_decoded_text(self):
        from src.parsing_pipeline.quality.preflight import _body_text

        with fitz.open(_pdf("2023_07")) as doc:
            body = " ".join(_body_text(doc[85]).split())
        assert "Highway Nest Mini to provide essential facilities" in body
        assert "14 Toll Plazas" in body
