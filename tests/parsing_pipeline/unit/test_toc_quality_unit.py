"""
Unit tests for the content-based TOC quality score and its title predicates (A-TQ-01).

Titles are taken from the review corpus: PDF-merger bookmarks (HP_2022, KA, JH, 2023_11),
finding sentences and recommendation boxes promoted to headings, the HP_2019 heuristic
TOC (split chapter banners, table rows), and genuine printed contents and bookmarks.
"""

import fitz
import pytest

from src.parsing_pipeline.modules.toc_quality import (
    ACCEPT_THRESHOLD,
    assess_toc_quality,
    chapter_agreement,
    is_garbage_title,
    is_junk_title,
    is_sentence_like,
    is_table_row,
    junk_share,
    score_toc,
)

HP_2022_BOOKMARKS = [
    [1, "ATIR 2017-19_HP_English_Cover", 0],
    [1, "1 Cover pages", 2],
    [1, "2 TOC", 0],
    [1, "3 Preface", 0],
    [2, "Blank Page", 0],
    [1, "4 Overiew HP ATIR", 0],
    [1, "5 Chapter 1 HP ATIR", 0],
    [2, "Blank Page", 0],
    [1, "6 Chapter 2 HP ATIR", 0],
    [1, "7 Chapter 3 HP ATIR", 0],
    [1, "Blank Page", 141],
    [1, "Blank Page", 140],
    [1, "Binder1.pdf", 0],
    [2, "2 TOC", 4],
    [2, "3 Preface", 8],
]

HP_2019_HEURISTIC = [
    [1, "Overview", 7],
    [1, "Chapter-1", 11],
    [1, "Profile of Panchayati Raj", 11],
    [1, "Institutions", 11],
    [1, "Chapter-2", 21],
    [1, "Results of Audit of Panchayati", 21],
    [1, "Raj Institutions", 21],
    [1, "Chapter-3", 33],
    [1, "Profile of Urban Local Bodies", 33],
    [1, "Chapter-4", 41],
    [1, "Results of Audit of Urban Local", 41],
    [1, "Bodies", 41],
    [1, "Appendices", 51],
    [3, "Municipal Council, Chamba (` in lakh) Sl. No", 86],
    [3, "Total (iii) 1,00,000 4. Sh. Victor Bhisty", 86],
]

PRINTED_THREE_COLUMN = [
    [1, "Preface", 6],
    [1, "Executive Summary", 8],
    [1, "Chapter-1 Introduction", 12],
    [2, "1.1 Introduction", 12],
    [2, "1.2 Audit objectives", 14],
    [1, "Chapter-2 Planning and Financial Management", 18],
    [2, "2.1 Deficiencies in Planning", 18],
    [2, "2.2 Financial Management", 21],
    [1, "Appendices", 40],
    [2, "Appendix 2.1 Statement showing list of schools", 40],
]


class TestJunkTitles:
    @pytest.mark.parametrize(
        "title",
        [
            "Blank Page",
            "Binder1.pdf",
            "AGS ENG COVER.pdf",
            "Page 2",
            "2 TOC",
            "3 Preface",
            "5 Chapter 1 HP ATIR",
            "6.Chapter 1-Introduction",
            "10. Appendix Median",
            "02_Index",
            "05_Chapter I - IX",
            "4 separator_Executive Summary",
            "2.Inner Head",
            "1. Nagarothana Front Page English",
            "13. Nagarothana Back Page English",
            "PA Report_English",
            "00 Cover English",
        ],
    )
    def test_merger_bookmarks(self, title):
        assert is_junk_title(title)
        assert is_garbage_title(title)

    @pytest.mark.parametrize(
        "title",
        [
            "Contents",
            "Table of Contents",
            "Chapter 1 : Introduction",
            "1 Introduction",
            "2 Mandate, Audit Scope, and Methodology",
            "1.1 The FRBM Act",
            "Appendix 2.3 Summarised financial position",
            "Coverage of the Report",
        ],
    )
    def test_real_headings_are_not_junk(self, title):
        assert not is_junk_title(title)

    def test_junk_share(self):
        assert junk_share(HP_2022_BOOKMARKS) > 0.9
        assert junk_share(PRINTED_THREE_COLUMN) == 0


class TestSentenceLike:
    @pytest.mark.parametrize(
        "title",
        [
            "Four ULBs purchased different materials amounting to ₹9.79 lakh without inviting quotation",
            "MCorp. Shimla failed to realise lease money of ₹1.74 crore from shops and stalls",
            "Recommendation 3.1",
            "Recommendation No. 9",
            "The Department did not prepare the annual plans for the period.",
            "“Education is the most powerful weapon”",
            "Report of the Comptroller and Auditor General of India on Storage Management and Movement of Food grains",
            "(ii) Audit observed that the works were awarded without tender and without approval of the competent authority",
        ],
    )
    def test_sentences_and_boxes(self, title):
        assert is_sentence_like(title)
        assert is_garbage_title(title)

    @pytest.mark.parametrize(
        "title",
        [
            "1.2 Audit objectives",
            "3.8.3 Recommendation of the 15th Finance Commission",
            "Recommendations",
            "A) Planning and Financial Management",
            "a) Tendering procedure",
            "i. Direct Taxes",
            # Numbered printed sections may state an amount or run long
            "4.1.2.5 Additional discounts of ₹ 41.77 crore in a commercial site in addendum report by consultant",
            "8.5 Free and compulsory education to children belonging to Weaker Sections and Disadvantaged Groups (WS&DG)",
            "Appendix 3 Audit coverage- Details of Panchayati Raj Institutions and Urban Local Bodies audited during 2017-18",
        ],
    )
    def test_headings_are_not_sentences(self, title):
        assert not is_sentence_like(title)
        assert not is_garbage_title(title)


class TestTableRows:
    def test_table_rows(self):
        assert is_table_row("Municipal Council, Chamba (` in lakh) Sl. No")
        assert is_table_row("Total (iii) 1,00,000 4. Sh. Victor Bhisty")

    def test_amount_in_numbered_heading_is_not_a_row(self):
        assert not is_table_row(
            "3.6.12.1 Non-utilisation and parking of funds in Personal Ledger Accounts ₹ 1,902.05 crore"
        )


class TestGarbageTitleUnchanged:
    """Cases the score caught before this change still count."""

    @pytest.mark.parametrize(
        "title",
        [
            "ab",
            "lowercase start fragment",
            "(Para 3.1 and 3.2)",
            "(₹ in crore)",
            "&KDSWHU $ZDUGRI3URMHFWV",
            "12,345 67.8 90",
        ],
    )
    def test_still_garbage(self, title):
        assert is_garbage_title(title)

    def test_long_appendix_title_is_not_garbage(self):
        # HP_2022's Appendix 5, 39 words
        title = (
            "Appendix 5 Difference between figures of balance in bank pass book and that of uploaded on "
            "PRIASoft during 2016-17 and difference between figures of receipt and expenditure furnished "
            "to audit by test-checked PRIs and that of uploaded on PRIASoft during 2017-18"
        )
        assert len(title) > 160
        assert not is_garbage_title(title)


class TestScore:
    def test_backward_compatible_signature(self):
        assert assess_toc_quality([]) == 0
        assert isinstance(assess_toc_quality(PRINTED_THREE_COLUMN, 60), int)

    def test_genuine_contents_pass(self):
        result = score_toc(PRINTED_THREE_COLUMN, 60)
        assert result["score"] >= 90
        assert result["score"] == assess_toc_quality(PRINTED_THREE_COLUMN, 60)

    def test_merger_bookmarks_fail(self):
        result = score_toc(HP_2022_BOOKMARKS, 142)
        assert result["score"] < ACCEPT_THRESHOLD
        assert result["deductions"]["junk_titles"] > 50
        assert result["counts"]["junk"] >= 13

    def test_split_banners_and_table_rows_fail(self):
        result = score_toc(HP_2019_HEURISTIC, 90)
        assert result["score"] < ACCEPT_THRESHOLD
        assert {"split_headings", "l1_same_page", "table_rows"} <= set(
            result["deductions"]
        )

    def test_para_number_left_in_titles(self):
        toc = [[1, "Chapter-1 Introduction Introduction 1.1", 3]] + [
            [1, f"Audit topic number {i} {i}.{i}", 3 + i] for i in range(1, 8)
        ]
        result = score_toc(toc, 40)
        assert result["counts"]["merged_or_para_in_title"] == 8
        assert result["deductions"]["merged_or_para_in_title"] == 40

    def test_duplicate_chapters_and_wrong_section_prefix(self):
        toc = [
            [1, "Chapter 1 Introduction", 2],
            [2, "1.1 Background", 2],
            [1, "Chapter-1 Introduction", 3],
            [1, "Chapter 2 Findings", 5],
            [2, "3.1 Misplaced section", 6],
            [2, "2.2 Findings proper", 7],
        ]
        result = score_toc(toc, 10)
        assert result["counts"]["duplicate_chapters"] == 1
        assert result["counts"]["section_chapter_mismatch"] == 1

    def test_density(self):
        toc = [[1, "Chapter 1 Overview", 0]] + [
            [2, f"1.{i} Topic {i}", i // 3] for i in range(1, 40)
        ]
        result = score_toc(toc, 10)
        assert result["counts"]["entries_per_page"] == 4.0
        assert result["deductions"]["density"] == 30

    def test_verification_against_document(self, tmp_path):
        doc = fitz.open()
        for heading in (
            "Preface",
            "Chapter 1 Introduction",
            "1.1 Background",
            "Chapter 2 Findings",
            "2.1 Issues",
        ):
            doc.new_page().insert_text((72, 100), heading)
        good = [
            [1, "Preface", 0],
            [1, "Chapter 1 Introduction", 1],
            [2, "1.1 Background", 2],
            [1, "Chapter 2 Findings", 3],
            [2, "2.1 Issues", 4],
        ]
        wrong = [[level, title, 0] for level, title, _ in good[1:]] + [
            [1, "Glossary", 0]
        ]
        assert score_toc(good, 5, doc)["counts"]["verified"] == 1.0
        bad = score_toc(wrong, 5, doc)
        assert bad["counts"]["verified"] < 0.5
        assert bad["deductions"]["unverified"] > 25


class TestChapterAgreement:
    PRINTED = [
        [1, "Preface", 4],
        [1, "Chapter 1: Introduction", 14],
        [1, "Chapter 2: FRBM Targets and Achievements", 20],
        [1, "Chapter 3: Disclosures and Transparency", 42],
    ]

    def test_bookmarks_that_list_the_same_chapters(self):
        bookmarks = [
            [1, "Contents", 2],
            [1, "Chapter 1 : Introduction", 14],
            [2, "1.1 The FRBM Act", 14],
            [1, "Chapter 2 : FRBM Targets and Achievements", 20],
            [1, "Chapter 3 Disclosures and Transparency", 42],
        ]
        assert chapter_agreement(self.PRINTED, bookmarks) == 1.0

    def test_merger_bookmarks_do_not_agree(self):
        assert chapter_agreement(self.PRINTED, HP_2022_BOOKMARKS) == 0.0
        assert chapter_agreement([], HP_2022_BOOKMARKS) == 0.0
