"""
Unit tests for the printed page map and the contents row parser (Phase 4, A-4-01/03/06).

Synthetic rows reproduce the layouts found in the review corpus: three-column
Title | Para | Page contents (OD, JH, HP), roman and PART chapter headings (BR, HP),
vertically centred cells (JH appendices, 2023_07), running and column headers glued
into entries (BR, JH) and BR's appendix table. Real-PDF regressions run when the
review corpus is present (CAG_REVIEW_PDF_DIR, or data/review_corpus/pdfs).
"""

import os
from pathlib import Path

import fitz
import pytest

from src.parsing_pipeline.modules.printed_toc_parser import (
    _level,
    _parse_rows,
    build_printed_page_map,
    interpolate_page_labels,
    logical_page_labels,
    parse_printed_toc,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
PDF_DIR = Path(
    os.getenv("CAG_REVIEW_PDF_DIR") or REPO_ROOT / "data" / "review_corpus" / "pdfs"
)


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


# --- contents rows -----------------------------------------------------------


class TestThreeColumnRows:
    def test_para_column_becomes_section_number_and_chapter_is_flushed(self):
        # OD: "Chapter-1 / Introduction" above "Introduction 1.1 1-3"
        entries = _parse_rows(
            rows(
                "Chapter-1",
                "Introduction",
                "Introduction 1.1 1-3",
                "Audit objectives 1.2 3",
            )
        )
        assert entries == [
            ("Chapter-1 Introduction", None),
            ("1.1 Introduction", "1"),
            ("1.2 Audit objectives", "3"),
        ]

    def test_roman_chapter_heading_spanning_lines(self):
        # BR: "I AN OVERVIEW OF ..." set over several capitalised lines
        entries = _parse_rows(
            rows(
                "I AN OVERVIEW OF THE FUNCTIONING,",
                "ACCOUNTABILITY MECHANISM",
                "Introduction 1.1 1",
                "II COMPLIANCE AUDIT",
                "Panchayati Raj Department",
                "Fraudulent payment 2.1 17",
            )
        )
        assert entries == [
            ("I AN OVERVIEW OF THE FUNCTIONING, ACCOUNTABILITY MECHANISM", None),
            ("1.1 Introduction", "1"),
            ("II COMPLIANCE AUDIT Panchayati Raj Department", None),
            ("2.1 Fraudulent payment", "17"),
        ]

    def test_part_and_chapter_headings_are_separate(self):
        # HP ATIR: PART-A above CHAPTER-1, both in capitals
        entries = _parse_rows(
            rows(
                "PART-A",
                "PANCHAYATI RAJ INSTITUTIONS (PRIs)",
                "CHAPTER-1",
                "PROFILE OF PRIs",
                "Background 1.1 1",
            )
        )
        assert [t for t, _ in entries] == [
            "PART-A PANCHAYATI RAJ INSTITUTIONS (PRIs)",
            "CHAPTER-1 PROFILE OF PRIs",
            "1.1 Background",
        ]

    def test_chapter_label_alone_is_not_a_page_number(self):
        # CG: "CHAPTER I" on its own row; "I" is the chapter, not page i
        entries = _parse_rows(
            rows("CHAPTER I", "An Overview of the Functioning", "Introduction 1.1 1")
        )
        assert entries[0] == ("CHAPTER I An Overview of the Functioning", None)

    def test_chapter_title_wrapped_onto_page_row(self):
        # 2020_16: the second line of the chapter title carries its page
        entries = _parse_rows(
            rows(
                "Chapter 2: Tax Base of Co-operative Societies and",
                "Co-operative Banks 9",
            )
        )
        assert entries == [
            (
                "Chapter 2: Tax Base of Co-operative Societies and Co-operative Banks",
                "9",
            )
        ]

    def test_two_column_numbered_rows_unchanged(self):
        entries = _parse_rows(
            rows("1.1 Introduction 1", "1.2 Organisational structure 2")
        )
        assert entries == [
            ("1.1 Introduction", "1"),
            ("1.2 Organisational structure", "2"),
        ]


class TestWrappedAndCentredCells:
    def test_lowercase_tail_joins_the_title_above(self):
        entries = _parse_rows(
            rows(
                (100, "Comparative view of the indicators related to 3.1 15-29"),
                (110, "education"),
                (125, "Availability of schools 3.2 29-32"),
            )
        )
        assert entries[0] == (
            "3.1 Comparative view of the indicators related to education",
            "15",
        )

    def test_label_only_row_takes_lines_above_and_below(self):
        # HP: title printed half a line above and below the "1.6 7" row
        entries = _parse_rows(
            rows(
                (85, "Accounting system in PRIs 1.5 6"),
                (100, "Financial reporting framework of"),
                (107, "1.6 7"),
                (114, "PRIs (Internal Control System)"),
                (130, "Primary audit 1.7 7"),
            )
        )
        assert entries == [
            ("1.5 Accounting system in PRIs", "6"),
            (
                "1.6 Financial reporting framework of PRIs (Internal Control System)",
                "7",
            ),
            ("1.7 Primary audit", "7"),
        ]

    def test_number_stays_first_when_title_starts_above_its_row(self):
        # 2023_07: number column centred on a three-line title
        entries = _parse_rows(
            rows(
                (80, "3.1 Incorrect application of rules 5"),
                (100, "Delay/non-reduction of toll fee on NHs being"),
                (107, "3.1.1 upgraded and collection of toll fee 5-7"),
                (114, "completion date in cases of delay"),
                (135, "3.2 Loss of revenue 12"),
            )
        )
        assert entries[1] == (
            "3.1.1 Delay/non-reduction of toll fee on NHs being upgraded and collection of toll fee "
            "completion date in cases of delay",
            "5",
        )

    def test_evenly_spaced_uppercase_wrap_stays_with_its_row(self):
        # HP_2019 appendices: rows and wrap lines evenly spaced
        state = {"appendix": True}
        entries = _parse_rows(
            rows(
                (100, "Non-maintenance of records by the Panchayati Raj 6 43"),
                (112, "Institutions"),
                (124, "Non-reconciliation of cash books 7 45"),
            ),
            state,
        )
        assert entries[0] == (
            "Appendix 6 Non-maintenance of records by the Panchayati Raj Institutions",
            "43",
        )

    def test_hyphen_at_line_break_joins_word(self):
        state = {"appendix": True}
        entries = _parse_rows(
            rows(
                (100, "5.19 Status of persons-in- 5.10.3 187"),
                (110, "position for SWM"),
            ),
            state,
        )
        assert entries == [
            ("Appendix 5.19 Status of persons-in-position for SWM", "187")
        ]

    def test_wrapped_line_ending_in_a_number_is_not_a_page(self):
        # KA: "(SJH Road) ... in Package 3" continues the previous appendix title
        state = {"appendix": True}
        entries = _parse_rows(
            rows(
                (100, "3.10 Details of payments made for same stretches 79"),
                (110, "(SJH Road) in Package 3"),
                (120, "at Mysuru"),
                (135, "3.11 Details of unjustified expenditure 80"),
            ),
            state,
        )
        assert entries[0] == (
            "Appendix 3.10 Details of payments made for same stretches (SJH Road) in Package 3 at Mysuru",
            "79",
        )


class TestHeadersAndAppendices:
    def test_running_and_column_headers_dropped(self):
        entries = _parse_rows(
            rows(
                "Audit Report (Local Government) for the year ended March 2022",
                "Reference to",
                "CHAPTER DESCRIPTION",
                "Paragraphs Page",
                "Accounting procedure and financial 5.3 56",
                "management",
                "ii",
            )
        )
        assert entries == [("5.3 Accounting procedure and financial management", "56")]

    def test_repeated_rows_dropped(self):
        state = {"repeated": {"State Finances Audit Report"}}
        assert _parse_rows(
            rows("State Finances Audit Report", "Conclusion 3.7 81"), state
        ) == [("3.7 Conclusion", "81")]

    def test_appendix_number_first_and_para_reference_dropped(self):
        # BR: "4.1 Avoidable expenditure ... 4.1 137" in the Appendices block
        state = {}
        entries = _parse_rows(
            rows(
                "Appendices",
                "APPENDIX DESCRIPTION",
                "4.1 Avoidable expenditure of interest and penalty 4.1 137",
                "5.2 (A) Service level benchmarks for SWM 5.2.1 143",
            ),
            state,
        )
        assert entries == [
            ("Appendices", None),
            ("Appendix 4.1 Avoidable expenditure of interest and penalty", "137"),
            ("Appendix 5.2 (A) Service level benchmarks for SWM", "143"),
        ]
        assert state["appendix"] is True

    def test_atir_appendix_number_column(self):
        # HP: "Particulars | Appendix No. | Page No."
        entries = _parse_rows(
            rows("APPENDICES", "Detail of 15-line departments assigned to PRIs 2 62")
        )
        assert entries[1] == (
            "Appendix 2 Detail of 15-line departments assigned to PRIs",
            "62",
        )

    def test_centred_appendix_label(self):
        # JH: title half a line above and below "Appendix 2.3 108"
        state = {"appendix": True}
        entries = _parse_rows(
            rows(
                (80, "Appendix 2.2 Time series data 106"),
                (100, "Summarised financial position of Government"),
                (107, "Appendix 2.3 108"),
                (114, "as on 31.03.2024"),
                (130, "Appendix 3.2 Unnecessary re-appropriation 111"),
            ),
            state,
        )
        assert entries[1] == (
            "Appendix 2.3 Summarised financial position of Government as on 31.03.2024",
            "108",
        )


class TestLevels:
    @pytest.mark.parametrize(
        "title, in_annexures, in_chapter, level",
        [
            ("I AN OVERVIEW OF THE FUNCTIONING", False, False, 1),
            ("PART-A PANCHAYATI RAJ INSTITUTIONS", False, False, 1),
            ("Chapter-1 Introduction", False, False, 1),
            ("1.2 Audit objectives", False, True, 2),
            ("2.3.1 Receipts of the State", False, True, 3),
            ("Appendix 4.1 Avoidable expenditure", True, False, 2),
            ("List of Appendices", False, True, 1),
            ("I Targets and Actual Production", True, False, 2),
        ],
    )
    def test_level_from_numbering(self, title, in_annexures, in_chapter, level):
        assert _level(title, in_annexures, in_chapter) == level


# --- page map ----------------------------------------------------------------


def _numbered_report(path, footer="{n} | P a g e", footnote_offset=None):
    """Front matter i-iii, a blank page, then body pages numbered 1-8 in the footer."""
    doc = fitz.open()
    for numeral in ("i", "ii", "iii"):
        page = doc.new_page()
        page.insert_text((72, 100), "Preface text")
        page.insert_text((290, 800), numeral)
    doc.new_page()  # unnumbered blank
    for n in range(1, 9):
        page = doc.new_page()
        page.insert_text((72, 100), f"Body page {n}")
        if footnote_offset is not None:
            # A footnote marker inside the footer band, numbered unlike the page
            page.insert_text((72, 760), str(n + footnote_offset), fontsize=6)
            page.insert_text((80, 760), "Footnote text", fontsize=9)
        page.insert_text((450, 805), footer.format(n=n))
    doc.save(path)
    return path


class TestBuildPrintedPageMap:
    def test_page_suffix_and_roman_front_matter(self, tmp_path):
        doc = fitz.open(_numbered_report(str(tmp_path / "r.pdf")))
        labels = build_printed_page_map(doc)
        assert labels[0] == "i" and labels[2] == "iii"
        assert 3 not in labels  # the blank page
        assert labels[4] == "1" and labels[11] == "8"

    def test_footnote_markers_do_not_label_pages(self, tmp_path):
        doc = fitz.open(
            _numbered_report(str(tmp_path / "r.pdf"), footer="{n}", footnote_offset=5)
        )
        labels = build_printed_page_map(doc)
        assert [labels[i] for i in range(4, 12)] == [str(n) for n in range(1, 9)]

    @pytest.mark.parametrize("footer", ["Page {n}", "Page {n} of 8", "- {n} -"])
    def test_other_footer_forms(self, tmp_path, footer):
        doc = fitz.open(_numbered_report(str(tmp_path / "r.pdf"), footer=footer))
        assert build_printed_page_map(doc)[6] == "3"

    def test_lone_number_in_body_ignored(self, tmp_path):
        doc = fitz.open()
        for n in range(1, 6):
            page = doc.new_page()
            page.insert_text(
                (72, 400), str(40 + n)
            )  # a number mid-page, not in the band
        assert build_printed_page_map(doc) == {}


class TestLogicalLabels:
    def test_interpolates_only_inside_a_run(self):
        labels = {0: "i", 1: "ii", 3: "iv", 5: "1", 8: "4", 9: "7"}
        out = interpolate_page_labels(labels, 11)
        assert out[2] == "iii"  # same roman offset either side
        assert out[4] is None  # roman before, arabic after
        assert out[6] == "2" and out[7] == "3"  # same arabic offset
        assert out[10] is None  # after the last detected page: never physical + 1

    def test_uppercase_roman_kept(self):
        assert interpolate_page_labels({0: "I", 2: "III"}, 3)[1] == "II"

    def test_printed_numbers_beat_wrong_pdf_labels(self, tmp_path):
        doc = fitz.open(_numbered_report(str(tmp_path / "r.pdf")))
        doc.set_page_labels(
            [{"startpage": 0, "prefix": "", "style": "D", "firstpagenum": 1}]
        )
        out = logical_page_labels(doc)
        assert out[4] == "1"  # printed "1 | P a g e", PDF label says "5"
        assert out[3] is None  # the blank page: PDF labels disagree, so not trusted

    def test_agreeing_pdf_labels_fill_gaps(self, tmp_path):
        doc = fitz.open(_numbered_report(str(tmp_path / "r.pdf")))
        doc.set_page_labels(
            [
                {"startpage": 0, "prefix": "", "style": "r", "firstpagenum": 1},
                {"startpage": 4, "prefix": "", "style": "D", "firstpagenum": 1},
            ]
        )
        assert logical_page_labels(doc)[3] == "iv"


# --- real reports ------------------------------------------------------------


def _pdf(prefix):
    matches = sorted(PDF_DIR.glob(f"{prefix}*.pdf")) if PDF_DIR.is_dir() else []
    if not matches:
        pytest.skip(f"{prefix} PDF not under {PDF_DIR} (set CAG_REVIEW_PDF_DIR)")
    return fitz.open(str(matches[0]))


def _titles(doc):
    toc, confidence = parse_printed_toc(doc, "test")
    return toc, {title: (level, page) for level, title, page in toc}, confidence


PARA_LEFT_IN_TITLE = r"\s\d{1,2}\.\d{1,2}(\.\d+)*$"


class TestRealReports:
    def test_odisha_three_column_contents(self):
        toc, by_title, confidence = _titles(_pdf("OD_2025"))
        assert by_title["Chapter-1 Introduction"][0] == 1
        assert by_title["1.2 Audit objectives"][0] == 2
        assert "3.1 Comparative view of the indicators related to education" in by_title
        assert not any(
            __import__("re").search(PARA_LEFT_IN_TITLE, t) for _, t, _ in toc
        )
        assert confidence >= 0.9

    def test_jharkhand_headers_and_centred_appendix(self):
        toc, by_title, _ = _titles(_pdf("JH_2025"))
        # The running header "State Finances Audit Report for the year ended ..." is dropped
        assert any(
            t.startswith("3.5 Audit of Budgetary provision of Grant No. 19")
            for _, t, _ in toc
        )
        assert not any("for the year ended" in t for _, t, _ in toc)
        assert (
            by_title[
                "Appendix 2.3 Summarised financial position of Government of Jharkhand as on 31.03.2024"
            ][0]
            == 2
        )
        assert "2.3.1 Receipts of the State" in by_title

    def test_bihar_roman_chapters_and_appendix_table(self):
        toc, by_title, _ = _titles(_pdf("BR_2024"))
        chapters = [
            t
            for level, t, _ in toc
            if level == 1 and t.startswith(("I ", "II ", "III ", "IV ", "V "))
        ]
        assert len(chapters) == 5
        assert (
            by_title["Appendix 4.1 Avoidable expenditure of interest and penalty"][0]
            == 2
        )
        assert not any(
            "Reference to" in t or "Audit Report (Local" in t for _, t, _ in toc
        )

    def test_hp_2022_page_suffix_numbers_and_verification(self):
        doc = _pdf("HP_2022")
        labels = build_printed_page_map(doc)
        assert (
            labels[18] == "1" and labels[22] == "5"
        )  # footnote markers "1", "2" sit above
        toc, by_title, confidence = _titles(doc)
        assert confidence >= 0.9  # 18% before "N | P a g e" was read
        assert (
            by_title[
                "1.6 Financial reporting and accountability framework of PRIs (Internal Control System)"
            ][0]
            == 2
        )

    def test_hp_2019_contents_verified(self):
        doc = _pdf("HP_2019")
        assert build_printed_page_map(doc)[30] == "16"
        toc, by_title, confidence = _titles(doc)
        assert confidence >= 0.9
        assert (
            by_title["CHAPTER-2 RESULTS OF AUDIT OF PANCHAYATI RAJ INSTITUTIONS"][0]
            == 1
        )

    def test_union_centred_chapter_title(self):
        _, by_title, _ = _titles(_pdf("2025_08"))
        assert (
            "Chapter III Ocean Observation Network – Deployment and Maintenance of Platforms"
            in by_title
        )

    def test_union_numbered_chapters(self):
        toc, by_title, _ = _titles(_pdf("2023_19"))
        assert len(toc) == 10
        assert by_title["1 Introduction"][0] == 1
