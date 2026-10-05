"""Unit tests for ScaffoldingService (Phase 4): TOC sources, page map and heading heuristics."""

from unittest.mock import Mock

import fitz
import pytest

from src.core.data_contracts import DocumentTask
from src.parsing_pipeline.modules.scaffolding_service import (
    ScaffoldingService,
    StyleProfile,
    TextBlock,
)

GOOD_BOOKMARKS = [
    [1, "Executive Summary", 1],
    [1, "Chapter 1: Introduction", 2],
    [2, "1.1 Audit Objectives", 3],
    [2, "1.2 Audit Scope", 4],
    [1, "Chapter 2: Findings", 6],
    [2, "2.1 Planning", 7],
    [1, "Annexure I", 10],
]


@pytest.fixture
def scaffolding_service(tmp_path, monkeypatch):
    """Service whose TOC rejection log (logs/rejected_toc.log) is written under tmp_path."""
    monkeypatch.chdir(tmp_path)
    return ScaffoldingService()


@pytest.fixture
def sample_task(tmp_path):
    return DocumentTask(
        report_id="report_001_test",
        source_url="https://example.com/test.pdf",
        local_pdf_path=str(tmp_path / "test.pdf"),
        initial_metadata={"Title": "Test Report"},
    )


def _make_pdf(path, pages=12, toc=None, labels=None, footers=None):
    """footers: {page index: printed page number text in the footer band}."""
    doc = fitz.open()
    for n in range(pages):
        page = doc.new_page()
        page.insert_text((72, 72), f"Page {n + 1} body text")
        if footers and n in footers:
            page.insert_text((290, page.rect.height - 30), str(footers[n]))
    if toc:
        # Each bookmark's heading is printed on its target page, as in a real report
        for i, (_, title, target) in enumerate(toc):
            doc[target - 1].insert_text((72, 120 + 14 * i), title)
        doc.set_toc(toc)
    if labels:
        doc.set_page_labels(labels)
    doc.save(str(path))
    doc.close()
    return path


def _block(text, size=12.0, flags=0, x=10, y=20, page=0, font="Times-Roman"):
    return TextBlock(
        page, (x, y, x + 200, y + 10), text, font, size, flags, 12.0, (x, y),
        len(text.split()), len(text),
    )


PROFILE = StyleProfile(12.0, ["Times"], {0}, {"width": 595.0, "left_margin": 72.0})


class TestScaffoldingServiceInit:
    def test_init_defaults(self, scaffolding_service):
        assert scaffolding_service.embed_toc_min_entries == 5
        assert scaffolding_service.body_text_percentile == 80.0
        assert scaffolding_service.heading_size_ratio == 1.4
        assert scaffolding_service.heading_min_length == 10
        assert 0 < scaffolding_service.bookmark_quality_threshold <= 1

    def test_init_custom(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        service = ScaffoldingService(
            embed_toc_min_entries=10,
            body_text_percentile=75.0,
            heading_size_ratio=1.6,
            heading_min_length=15,
        )
        assert service.embed_toc_min_entries == 10
        assert service.body_text_percentile == 75.0
        assert service.heading_size_ratio == 1.6
        assert service.heading_min_length == 15


class TestScaffoldingServicePdfPath:
    def test_get_pdf_path_local(self, scaffolding_service, sample_task):
        _make_pdf(sample_task.local_pdf_path, pages=1)
        assert scaffolding_service._get_pdf_path(sample_task) == sample_task.local_pdf_path

    def test_get_pdf_path_ocr(self, scaffolding_service, sample_task, tmp_path):
        sample_task.ocred_pdf_path = str(tmp_path / "ocred.pdf")
        with open(sample_task.ocred_pdf_path, "w") as f:
            f.write("mock")

        assert scaffolding_service._get_pdf_path(sample_task) == sample_task.ocred_pdf_path

    def test_get_pdf_path_none(self, scaffolding_service):
        task = DocumentTask(
            report_id="test",
            source_url="https://example.com/test.pdf",
            local_pdf_path="/nonexistent/path.pdf",
            initial_metadata={},
        )
        assert scaffolding_service._get_pdf_path(task) is None


class TestScaffoldingServiceEmbeddedToc:
    def _run(self, service, task, doc):
        task.scaffold = {"toc": [], "page_map": {}, "heading_positions": {}}
        return service._extract_embedded_toc(task, doc)

    def test_extract_embedded_toc_success(self, scaffolding_service, sample_task, tmp_path):
        doc = fitz.open(_make_pdf(tmp_path / "b.pdf", toc=GOOD_BOOKMARKS))

        result = self._run(scaffolding_service, sample_task, doc)

        toc = result.scaffold["toc"]
        assert len(toc) == 7
        # Bookmark pages are 1-indexed; the scaffold is 0-indexed
        assert toc[1] == [1, "Chapter 1: Introduction", 1]
        assert result.scaffold["toc_method"] == "embedded_bookmarks"
        assert result.scaffold["toc_quality"] >= 60
        assert "Embedded ToC extracted: 7 entries" in result.error_log[0]

    def test_extract_embedded_toc_inadequate(self, scaffolding_service, sample_task, tmp_path):
        doc = fitz.open(_make_pdf(tmp_path / "b.pdf", toc=[[1, "Chapter 1", 1], [1, "Chapter 2", 5]]))

        result = self._run(scaffolding_service, sample_task, doc)

        assert result.scaffold["toc"] == []
        assert result.scaffold["rejected_bookmark_metrics"]["entry_count"] == 2
        assert "Embedded ToC rejected: 2 entries" in result.error_log[0]

    def test_extract_embedded_toc_failure(self, scaffolding_service, sample_task):
        mock_doc = Mock()
        mock_doc.get_toc.side_effect = Exception("PDF error")

        result = self._run(scaffolding_service, sample_task, mock_doc)

        assert result.scaffold["toc"] == []
        assert "extraction failed: PDF error" in result.error_log[0]

    def test_bookmark_skips_blank_separator_page(self, tmp_path):
        doc = fitz.open()
        doc.new_page().insert_text((72, 72), "Cover")
        doc.new_page()  # blank separator the bookmark points at
        doc.new_page().insert_text((72, 72), "Chapter 1")
        assert ScaffoldingService._bookmark_page(doc, 2) == 2


class TestScoreEmbeddedToc:
    """Scored bookmark validation (replaced the boolean _validate_embedded_toc)."""

    def test_structured_bookmarks_pass_threshold(self, scaffolding_service):
        metrics = scaffolding_service._score_embedded_toc(GOOD_BOOKMARKS, 12)
        assert metrics.has_chapters and metrics.has_sections
        assert metrics.score() >= scaffolding_service.bookmark_quality_threshold * 100

    def test_few_flat_entries_fail_threshold(self, scaffolding_service):
        metrics = scaffolding_service._score_embedded_toc([[1, "Chap 1", 1], [1, "Chap 2", 5]], 12)
        assert metrics.score() < scaffolding_service.bookmark_quality_threshold * 100

    def test_file_assembly_bookmarks_penalised(self, scaffolding_service):
        assembly = [[1, f"0{n} Final_Report", n] for n in range(1, 8)]
        metrics = scaffolding_service._score_embedded_toc(assembly, 12)
        assert metrics.confidence < 1.0
        assert metrics.score() < scaffolding_service.bookmark_quality_threshold * 100

    def test_empty_toc(self, scaffolding_service):
        metrics = scaffolding_service._score_embedded_toc([], 12)
        assert metrics.entry_count == 0
        assert metrics.confidence == 0.0


class TestScaffoldingServicePageMappings:
    def test_build_page_mappings_from_printed_numbers(self, scaffolding_service, sample_task, tmp_path):
        # Cover unnumbered, front matter i-ii, body 1-4 (A-4-06)
        footers = {1: "i", 2: "ii", 3: "1", 4: "2", 5: "3", 6: "4"}
        doc = fitz.open(_make_pdf(tmp_path / "l.pdf", pages=7, footers=footers))
        sample_task.scaffold = {"toc": []}

        result = scaffolding_service._build_page_mappings(sample_task, doc)

        page_map = result.scaffold["page_map"]
        assert page_map[0] is None
        assert [page_map[i] for i in range(3, 7)] == ["1", "2", "3", "4"]

    def test_build_page_mappings_without_numbers_is_none(self, scaffolding_service, sample_task, tmp_path):
        doc = fitz.open(_make_pdf(tmp_path / "n.pdf", pages=3))
        sample_task.scaffold = {"toc": []}

        result = scaffolding_service._build_page_mappings(sample_task, doc)

        # Never physical + 1
        assert result.scaffold["page_map"] == {0: None, 1: None, 2: None}

    def test_merger_bookmarks_rejected(self, scaffolding_service, sample_task, tmp_path):
        junk = [[1, "1 Cover pages", 1], [1, "2 TOC", 1], [1, "Blank Page", 1],
                [1, "5 Chapter 1 HP ATIR", 3], [1, "Blank Page", 1], [1, "Binder1.pdf", 1]]
        doc = fitz.open(_make_pdf(tmp_path / "j.pdf", toc=junk))
        sample_task.scaffold = {"toc": [], "page_map": {}, "heading_positions": {}}
        result = scaffolding_service._extract_embedded_toc(sample_task, doc)
        assert result.scaffold["toc"] == []
        assert "merger bookmarks" in result.scaffold["bookmark_score"]["rejected"]


class TestValidateAndSetStatus:
    def test_validate_complete(self, scaffolding_service, sample_task):
        sample_task.scaffold = {"toc": [[1, "Chap 1", 0]], "page_map": {0: "1"}}
        result = scaffolding_service._validate_and_set_status(sample_task)
        assert result.processing_status == "scaffold_complete"

    def test_validate_toc_without_page_map_is_complete(self, scaffolding_service, sample_task):
        # The separate "scaffold_minimal" status was dropped; a TOC is enough
        sample_task.scaffold = {"toc": [[1, "Chap 1", 0]], "page_map": {}}
        result = scaffolding_service._validate_and_set_status(sample_task)
        assert result.processing_status == "scaffold_complete"

    def test_validate_partial_page_map_only(self, scaffolding_service, sample_task):
        sample_task.scaffold = {"toc": [], "page_map": {0: "1"}}
        result = scaffolding_service._validate_and_set_status(sample_task)
        assert result.processing_status == "scaffold_partial"

    def test_validate_failed(self, scaffolding_service, sample_task):
        sample_task.scaffold = {"toc": [], "page_map": {}}
        result = scaffolding_service._validate_and_set_status(sample_task)
        assert result.processing_status == "failed_scaffold"


class TestHeuristicTocCore:
    def test_extract_text_blocks(self, scaffolding_service):
        doc = fitz.open()
        for _ in range(3):
            page = doc.new_page()
            page.insert_text((72, 72), "Chapter 1", fontsize=16)
            page.insert_text((72, 200), "This is body text content", fontsize=11)

        text_blocks = scaffolding_service._extract_text_blocks(doc, 5)

        assert len(text_blocks) == 6
        assert {b.page_num for b in text_blocks} == {0, 1, 2}
        heading = next(b for b in text_blocks if b.text == "Chapter 1")
        assert heading.font_size == pytest.approx(16.0)
        assert any("body text" in b.text for b in text_blocks)

    def test_extract_text_blocks_respects_page_limit(self, scaffolding_service):
        doc = fitz.open()
        for _ in range(4):
            doc.new_page().insert_text((72, 72), "Text")
        assert {b.page_num for b in scaffolding_service._extract_text_blocks(doc, 2)} == {0, 1}

    def test_build_style_profile_basic(self, scaffolding_service):
        text_blocks = [
            _block("Chapter Title", 16.0, 16, font="Times-Bold"),
            _block("Body text content", 12.0, y=40),
            _block("More content", 12.0, y=70, page=1),
        ]

        profile = scaffolding_service._build_style_profile(text_blocks)

        assert isinstance(profile, StyleProfile)
        assert profile.body_font_size_baseline > 10.0
        assert profile.body_font_families[0] == "Times-Roman"
        assert "Times" in profile.body_font_families  # "Times-Bold" normalised
        assert "width" in profile.page_stats

    def test_calculate_heading_score_high(self, scaffolding_service):
        block = _block("Chapter Title", 18.0, 16, font="Times-Bold")
        assert scaffolding_service._calculate_heading_score(block, PROFILE) >= 100

    def test_calculate_heading_score_body_below_detection_threshold(self, scaffolding_service):
        # Body text at the left margin earns position and length points but stays
        # under the score of 75 that _detect_headings requires
        block = _block("This is body text", 12.0, x=80, y=100)
        assert scaffolding_service._calculate_heading_score(block, PROFILE) < 75

    def test_infer_hierarchy_few_candidates_all_level_one(self, scaffolding_service):
        candidates = [_block("Chapter 1", 16.0), _block("Section 1", 14.0, page=2)]
        assert set(scaffolding_service._infer_hierarchy(candidates).values()) == {1}

    def test_infer_hierarchy_by_font_size(self, scaffolding_service):
        chapter = _block("Chapter 1", 18.0)
        section = _block("1.1 Background", 14.0, y=60)
        subsection = _block("1.1.1 Scope", 12.0, y=90)
        levels = scaffolding_service._infer_hierarchy([chapter, section, subsection])
        assert levels[chapter] == 1 and levels[section] == 2 and levels[subsection] == 3

    def test_assign_heading_levels_quantile(self, scaffolding_service):
        sizes = [24.0, 20.0, 18.0, 16.0, 14.0, 12.0]
        levels = scaffolding_service._assign_heading_levels_quantile(sizes, 3)
        assert levels[0] == 1 and levels[-1] == 3
        assert levels == sorted(levels)
        assert scaffolding_service._assign_heading_levels_quantile([], 3) == []

    def test_construct_toc_basic(self, scaffolding_service):
        candidates = [
            _block("Section 1.1", 14.0, x=10, y=50, page=1),
            _block("Chapter 1\nIntroduction", 16.0, x=10, y=20, page=0),
        ]
        hierarchy_map = {candidates[0]: 2, candidates[1]: 1}

        toc, heading_positions = scaffolding_service._construct_toc(candidates, hierarchy_map)

        # Sorted by page, newlines collapsed
        assert toc == [[1, "Chapter 1 Introduction", 0], [2, "Section 1.1", 1]]
        assert heading_positions == {"0_Chapter 1 Introduction": 20, "1_Section 1.1": 50}

    def test_clean_toc_title_edge_cases(self, scaffolding_service):
        assert scaffolding_service._clean_toc_title("Chapter 1..") == "Chapter 1"
        assert scaffolding_service._clean_toc_title("   Extra   Spaces   ") == "Extra Spaces"
        assert scaffolding_service._clean_toc_title("Normal Title") == "Normal Title"
        assert scaffolding_service._clean_toc_title("Chapter I..........12") == "Chapter I"
        assert scaffolding_service._clean_toc_title("Chapter IV 77-99") == "Chapter IV"
        assert scaffolding_service._clean_toc_title("Contents i-xii") == "Contents"
        # A number after a label word is part of the title
        assert scaffolding_service._clean_toc_title("Annexure 4") == "Annexure 4"

    def test_clean_toc_title_trailing_dashes(self, scaffolding_service):
        assert scaffolding_service._clean_toc_title("Section A--") == "Section A"
        assert scaffolding_service._clean_toc_title("Audit findings: ") == "Audit findings"

    def test_heading_lines_of_one_banner_are_merged(self, scaffolding_service):
        blocks = [
            _block("Chapter-1", 20.0, 16, y=100),
            _block("Profile of Panchayati Raj", 20.0, 16, y=126),
            _block("Institutions", 20.0, 16, y=152),
            _block("1.1 Introduction", 14.0, 16, y=300),
        ]
        merged = scaffolding_service._merge_heading_lines(blocks)
        assert [b.text for b in merged] == [
            "Chapter-1 Profile of Panchayati Raj Institutions", "1.1 Introduction",
        ]

    @pytest.mark.parametrize("text,expected", [
        ("Total (iii) 1,00,000 4. Sh. Victor Bhisty", True),
        ("Municipal Council, Chamba (` in lakh) Sl. No", True),
        ("Chapter-2 Results of Audit", False),
        ("2.3 Utilisation of grants", False),
    ])
    def test_table_rows_are_not_headings(self, scaffolding_service, text, expected):
        assert scaffolding_service._looks_like_table_row(text) is expected

    def test_detect_headings_with_candidates(self, scaffolding_service):
        text_blocks = [
            _block("POTENTIAL HEADING", 18.0, 16, font="Times-Bold"),
            _block("This is definite body text", 12.0, y=40),
        ]

        candidates = scaffolding_service._detect_headings(text_blocks, PROFILE, "report_001")

        assert [c.text for c in candidates] == ["POTENTIAL HEADING"]

    def test_detect_headings_rejects_table_rows(self, scaffolding_service):
        rows = [_block("Mumbai 964 24329 25 6 12", 18.0, 16, font="Times-Bold")]
        assert scaffolding_service._detect_headings(rows, PROFILE, "report_001") == []


class TestScaffoldingServiceBuild:
    def test_build_scaffold_from_bookmarks(self, scaffolding_service, sample_task):
        _make_pdf(sample_task.local_pdf_path, pages=12, toc=GOOD_BOOKMARKS)

        result = scaffolding_service.build_scaffold(sample_task)

        assert result.processing_status == "scaffold_complete"
        assert result.scaffold["toc_method"] == "embedded_bookmarks"
        assert len(result.scaffold["toc"]) == 7
        assert len(result.scaffold["page_map"]) == 12

    def test_build_scaffold_without_toc_is_partial(self, scaffolding_service, sample_task):
        # No bookmarks, no contents page and too little text for the heuristic
        _make_pdf(sample_task.local_pdf_path, pages=3)

        result = scaffolding_service.build_scaffold(sample_task)

        assert result.processing_status == "scaffold_partial"
        assert result.scaffold["toc"] == []
        assert len(result.scaffold["page_map"]) == 3
        assert "Embedded ToC rejected" in result.error_log[0]

    def test_build_scaffold_no_valid_pdf(self, scaffolding_service):
        task = DocumentTask(
            report_id="test",
            source_url="https://example.com/test.pdf",
            local_pdf_path="",
            initial_metadata={},
        )

        result = scaffolding_service.build_scaffold(task)

        assert result.processing_status == "failed_scaffold"
        assert "No valid PDF path" in result.error_log[0]

    def test_build_scaffold_unreadable_pdf(self, scaffolding_service, sample_task):
        with open(sample_task.local_pdf_path, "wb") as f:
            f.write(b"not a pdf")

        result = scaffolding_service.build_scaffold(sample_task)

        assert result.processing_status == "failed_scaffold"
        assert any("Scaffolding failed with error" in m for m in result.error_log)


def test_normalize_font_family_variations(scaffolding_service):
    """Weight and style suffixes are removed; other family names are kept."""
    assert scaffolding_service._normalize_font_family("TimesNewRoman-Bold") == "TimesNewRoman"
    assert scaffolding_service._normalize_font_family("Arial,Bold") == "Arial"
    assert scaffolding_service._normalize_font_family("Helvetica") == "Helvetica"
    assert scaffolding_service._normalize_font_family("Courier,Italic") == "Courier"
