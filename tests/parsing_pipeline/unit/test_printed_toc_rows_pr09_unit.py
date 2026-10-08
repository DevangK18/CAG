"""
Contents parser regressions: a chapter row the chapter's own title page prints again
is not a running header (synthetic repro); the "Sl. No. | Description | Paragraph |
Page" layout (UK); chapter rows lost from an OCR'd contents page (RJ); en-dash chapter
labels and parts whose chapter numbers restart (KL).
"""

import fitz

from src.parsing_pipeline.modules.printed_toc_parser import (
    _add_missing_chapters,
    _found,
    _normalize,
    _parse_rows,
    is_chapter_title,
    parse_printed_toc,
)
from src.parsing_pipeline.modules.toc_quality import score_toc


def rows(*items):
    """(y, text) rows 12pt apart unless a y is given."""
    out, y = [], 0.0
    for item in items:
        if isinstance(item, tuple):
            y, text = item
        else:
            y, text = y + 12, item
        out.append((float(y), text))
    return out


CONTENTS = [
    "Executive Summary 1",
    "CHAPTER I: INTRODUCTION",
    "1.1 Background 2",
    "1.2 Audit objectives 3",
    "CHAPTER II: FINDINGS",
    "2.1 Revenue 4",
    "2.2 Expenditure 5",
    "CHAPTER III: CONCLUSION",
    "3.1 Summary 6",
]
BODY = {
    1: ["Executive Summary", "The audit covered the period 2018-23."],
    2: ["CHAPTER I: INTRODUCTION", "1.1 Background", "The scheme started in 2018."],
    3: ["1.2 Audit objectives", "Audit examined the scheme."],
    4: ["CHAPTER II: FINDINGS", "2.1 Revenue", "Revenue was short."],
    5: ["2.2 Expenditure", "Expenditure was high."],
    6: ["CHAPTER III: CONCLUSION", "3.1 Summary", "The scheme fell short."],
}


def _report(path):
    """Cover, one contents page, then body pages printed 1-6 in the footer."""
    doc = fitz.open()
    doc.new_page().insert_text((72, 100), "Report of the Comptroller")
    page = doc.new_page()
    page.insert_text((72, 60), "Contents")
    for k, row in enumerate(CONTENTS):
        page.insert_text((72, 90 + 18 * k), row)
    for n in range(1, 7):
        page = doc.new_page()
        for k, line in enumerate(BODY[n]):
            page.insert_text((72, 60 + 18 * k), line)
        page.insert_text((290, 810), str(n))
    doc.save(path)
    return fitz.open(path)


class TestChapterRowRepeatedOnTitlePage:
    def test_first_chapter_row_is_kept(self, tmp_path):
        toc, _ = parse_printed_toc(_report(str(tmp_path / "r.pdf")))
        titles = [(level, title) for level, title, _ in toc]
        assert (1, "CHAPTER I: INTRODUCTION") in titles
        assert (1, "CHAPTER II: FINDINGS") in titles
        # The sections sit under chapter I, not under the Executive Summary
        i = titles.index((1, "CHAPTER I: INTRODUCTION"))
        assert titles[i + 1] == (2, "1.1 Background")

    def test_chapter_row_maps_to_its_title_page(self, tmp_path):
        toc, _ = parse_printed_toc(_report(str(tmp_path / "r.pdf")))
        pages = {title: page for _, title, page in toc}
        assert pages["CHAPTER I: INTRODUCTION"] == 3

    def test_running_header_on_continuation_pages_still_dropped(self):
        state = {"repeated": {"Audit Report (Local Government) 2022"}}
        entries = _parse_rows(
            ["Audit Report (Local Government) 2022", "1.1 Background 2"], state
        )
        assert entries == [("1.1 Background", "2")]


class TestSerialNumberLayout:
    def test_serial_is_not_the_section_number(self):
        # UK: "Sl. No. | Description | Paragraph | Page No."
        entries = _parse_rows(
            [
                "Sl. No. Description Paragraph Page No.",
                "1. Preface v",
                "Chapter - 1: Introduction",
                "3. Introduction 1.1 1",
                "4. Impact of the scheme 1.2 2",
            ]
        )
        assert entries == [
            ("Preface", "v"),
            ("Chapter - 1: Introduction", None),
            ("1.1 Introduction", "1"),
            ("1.2 Impact of the scheme", "2"),
        ]

    def test_wrapped_title_around_serial_and_para(self):
        entries = _parse_rows(
            rows(
                "Sl. No. Description Paragraph Page No.",
                (20, "Irregular planning at GPs/ Blocks/"),
                (27, "14. 2.1.2 10"),
                (34, "State levels"),
                (48, "15. Gap in persondays 2.1.2.1 11"),
            )
        )
        assert entries[0] == (
            "2.1.2 Irregular planning at GPs/ Blocks/ State levels",
            "10",
        )
        assert entries[1] == ("2.1.2.1 Gap in persondays", "11")

    def test_without_serial_header_numbers_stay(self):
        assert _parse_rows(["3. Introduction 1"]) == [("3. Introduction", "1")]


class TestChapterRows:
    def test_en_dash_chapter_is_a_chapter(self):
        # KL: "CHAPTER–II : GOODS AND SERVICES TAX"
        assert is_chapter_title("CHAPTER–II : GOODS AND SERVICES TAX")

    def test_chapter_row_ending_in_a_lower_number_is_not_a_page(self):
        # RJ: "Chapter IX - Sustainable Development Goal - 3" after page 106
        entries = _parse_rows(
            [
                "8.6 Regulation of Biomedical Waste Management 106",
                "Chapter IX - Sustainable Development Goal - 3",
                "9.1 Introduction 109",
            ]
        )
        assert entries[1] == ("Chapter IX - Sustainable Development Goal - 3", None)

    def test_bracketed_own_page_number_dropped(self):
        # KL prints "(ii)" at the foot of its second contents page
        entries = _parse_rows(["1.1 Background 2", "1.2 Audit objectives 3", "(ii)"])
        assert entries == [("1.1 Background", "2"), ("1.2 Audit objectives", "3")]


def _sections_only(path):
    """Contents whose chapter rows II-III were lost; chapter III's pages print its title."""
    doc = fitz.open()
    for n in range(8):
        page = doc.new_page()
        if n == 4:
            page.insert_text((72, 60), "Chapter-III: Healthcare Services")
        page.insert_text((72, 100), f"Body page {n}")
    doc.save(path)
    return fitz.open(path)


class TestMissingChapters:
    def test_lost_chapter_rows_added_from_section_numbers(self, tmp_path):
        doc = _sections_only(str(tmp_path / "r.pdf"))
        toc = [
            [1, "Chapter I - Introduction", 1],
            [2, "1.1 Background", 1],
            [2, "2.1 Planning", 3],
            [2, "3.1 Delivery of services", 4],
            [1, "Chapter IV - Equipment", 6],
            [2, "4.1 Introduction", 6],
        ]
        out = _add_missing_chapters(doc, toc)
        assert [e for e in out if e[0] == 1] == [
            [1, "Chapter I - Introduction", 1],
            [1, "Chapter II", 3],
            [1, "Chapter III - Healthcare Services", 4],
            [1, "Chapter IV - Equipment", 6],
        ]

    def test_list_without_chapter_rows_unchanged(self, tmp_path):
        doc = _sections_only(str(tmp_path / "r.pdf"))
        toc = [[2, "1.1 Background", 1], [2, "2.1 Planning", 3]]
        assert _add_missing_chapters(doc, toc) == toc


class TestVerification:
    def test_title_with_dropped_letters_found(self):
        page = _normalize("1.2 Healthcare facilities in Rajasthan were reviewed")
        assert _found(_normalize("Healthcare facilities in Ra·asthan"), page)

    def test_different_title_not_found(self):
        page = _normalize("Availability of drugs and medicines in hospitals")
        assert not _found(_normalize("Healthcare facilities in Rajasthan"), page)


class TestScoreParts:
    def test_chapter_numbers_restart_in_each_part(self):
        toc = [
            [1, "PART I – REVENUE SECTOR", 20],
            [1, "CHAPTER–I : GENERAL", 20],
            [2, "1.1 Trend of Revenue Receipts", 20],
            [1, "CHAPTER–II : GOODS AND SERVICES TAX", 38],
            [2, "2.1 Tax Administration", 38],
            [1, "PART II – ECONOMIC SERVICES", 134],
            [1, "CHAPTER-I : GENERAL", 134],
            [2, "1.1 Profile of Departments", 134],
            [1, "CHAPTER-II: COMPLIANCE AUDIT PARAGRAPHS", 140],
            [2, "2.1 Short transfer to Road Safety Fund", 140],
        ]
        result = score_toc(toc, 230)
        assert "duplicate_chapters" not in result["deductions"]
        assert "l1_same_page" not in result["deductions"]

    def test_repeated_chapter_numbers_without_parts_still_deducted(self):
        toc = [
            [1, "Chapter 1 Introduction", 2],
            [2, "1.1 Background", 2],
            [1, "Chapter 2 Findings", 5],
            [1, "Chapter 2 Findings (contd.)", 8],
            [2, "2.1 Revenue", 8],
        ]
        assert score_toc(toc, 20)["deductions"].get("duplicate_chapters") == 10
