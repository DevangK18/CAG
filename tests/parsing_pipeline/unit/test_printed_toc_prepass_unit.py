"""
Unit tests for the printed Table of Contents parser (Phase 4).

Builds small PDFs with a contents page and numbered body pages, the way CAG reports
print them: one visual row per entry ("Chapter I Introduction ... 1-9"), titles that
wrap, chapter lines without a page, and a blank separator that shifts the page offset.
"""

import fitz
import pytest

from src.core.data_contracts import DocumentTask
from src.parsing_pipeline.modules.printed_toc_parser import parse_printed_toc
from src.parsing_pipeline.modules.scaffolding_service import ScaffoldingService

CONTENTS_ROWS = [
    ("Table of Contents", None),
    ("Particulars", "Page No."),
    ("Preface", "i"),
    ("Chapter I Introduction", "1-2"),
    ("1.1 Background", "1"),
    ("1.2 Objectives of the audit and", "2"),
    ("scope of examination", None),  # wrapped title tail
    ("Chapter II Findings", None),  # chapter line without its own page
    ("2.1 Major Issues", "4"),
    ("Annexures", "6"),
]


def _make_report(path, blank_before_chapter_two=True):
    doc = fitz.open()
    cover = doc.new_page()
    cover.insert_text((72, 100), "Report of the Comptroller and Auditor General of India")

    contents = doc.new_page()
    y = 80
    for title, page in CONTENTS_ROWS:
        contents.insert_text((72, y), title, fontsize=11)
        if page:
            contents.insert_text((480, y), page, fontsize=11)
        y += 22

    preface = doc.new_page()
    preface.insert_text((72, 60), "i")
    preface.insert_text((72, 100), "Preface")

    printed = 1
    for heading in ("Chapter I Introduction 1.1 Background", "1.2 Objectives of the audit"):
        page = doc.new_page()
        page.insert_text((72, 60), str(printed))
        page.insert_text((72, 100), heading)
        printed += 1
    if blank_before_chapter_two:
        doc.new_page()  # unnumbered separator: printed offset changes after this
    for heading in ("Chapter II Findings", "2.1 Major Issues", "Continued", "Annexures"):
        page = doc.new_page()
        page.insert_text((72, 60), str(printed))
        page.insert_text((72, 100), heading)
        printed += 1
    doc.save(path)
    return path


@pytest.fixture
def report_pdf(tmp_path):
    return _make_report(str(tmp_path / "report.pdf"))


class TestParsePrintedToc:
    def test_entries_levels_and_pages(self, report_pdf):
        toc, confidence = parse_printed_toc(fitz.open(report_pdf), "test")
        by_title = {title: (level, page) for level, title, page in toc}

        assert by_title["Preface"] == (1, 2)
        assert by_title["Chapter I Introduction"] == (1, 3)
        assert by_title["1.1 Background"] == (2, 3)
        # Page after the blank separator: offset is not constant
        assert by_title["2.1 Major Issues"] == (2, 7)
        assert confidence >= 0.8

    def test_wrapped_title_joined_to_previous_entry(self, report_pdf):
        toc, _ = parse_printed_toc(fitz.open(report_pdf), "test")
        titles = [title for _, title, _ in toc]
        assert "1.2 Objectives of the audit and scope of examination" in titles
        assert not any(t.startswith("scope of") for t in titles)

    def test_chapter_without_page_takes_next_entry_page(self, report_pdf):
        toc, _ = parse_printed_toc(fitz.open(report_pdf), "test")
        chapter_two = next(e for e in toc if e[1] == "Chapter II Findings")
        assert chapter_two[0] == 1 and chapter_two[2] == 7

    def test_header_rows_skipped(self, report_pdf):
        toc, _ = parse_printed_toc(fitz.open(report_pdf), "test")
        assert not any("Particulars" in title for _, title, _ in toc)

    def test_no_contents_page(self, tmp_path):
        doc = fitz.open()
        doc.new_page().insert_text((72, 100), "Just body text without contents")
        assert parse_printed_toc(doc, "test") == ([], 0.0)


class TestBuildScaffoldUsesPrintedToc:
    def test_printed_toc_preferred_over_heuristics(self, report_pdf):
        task = DocumentTask(
            report_id="test", source_url="x", local_pdf_path=report_pdf,
            processed_pdf_path=report_pdf, initial_metadata={},
        )
        result = ScaffoldingService().build_scaffold(task)

        assert result.scaffold["toc_method"] == "printed_toc"
        assert result.scaffold["toc_quality"] >= 60
        titles = [e[1] for e in result.scaffold["toc"]]
        # Printed/bookmark TOCs skip the heuristic candidate filter
        assert "1.1 Background" in titles
