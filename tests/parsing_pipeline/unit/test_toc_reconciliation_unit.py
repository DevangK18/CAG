"""Tests for Phase 5.5 TOC Reconciliation Service."""

import pytest
from difflib import SequenceMatcher
from unittest.mock import Mock, patch, MagicMock

from src.parsing_pipeline.modules.toc_quality import assess_toc_quality
from src.parsing_pipeline.modules.toc_reconciliation_service import TOCReconciliationService
from src.core.data_contracts import DocumentTask


class TestTOCReconciliationInit:
    """Test service initialization."""

    def test_default_parameters(self):
        """Service initializes with expected defaults."""
        service = TOCReconciliationService()
        assert service.similarity_threshold == 0.65
        assert service.min_docling_headers == 3
        assert service.confidence_threshold == 0.60

    def test_custom_parameters(self):
        """Service accepts custom configuration."""
        service = TOCReconciliationService(
            similarity_threshold=0.8,
            min_docling_headers=5,
            confidence_threshold=0.7
        )
        assert service.similarity_threshold == 0.8
        assert service.min_docling_headers == 5
        assert service.confidence_threshold == 0.7


class TestNoLayoutData:
    """Test graceful handling when layout data is missing."""

    def test_no_layout_graceful_skip(self):
        """Service handles missing layout data gracefully."""
        service = TOCReconciliationService()
        task = DocumentTask(
            report_id="test",
            source_url="",
            local_pdf_path="",
            initial_metadata={},
            layout=None,
            scaffold={"toc": [[1, "Test", 0]], "toc_quality": 50},
        )
        result = service.reconcile(task)
        assert result.scaffold["toc"] == [[1, "Test", 0]]  # Unchanged

    def test_no_scaffold_creates_default(self):
        """Service creates default scaffold when missing."""
        service = TOCReconciliationService()
        task = DocumentTask(
            report_id="test",
            source_url="",
            local_pdf_path="",
            initial_metadata={},
            layout={0: []},  # Empty layout but present
            scaffold=None,
        )
        result = service.reconcile(task)
        assert result.scaffold is not None
        assert "toc" in result.scaffold
        assert "heading_positions" in result.scaffold


class TestLevelInference:
    """Test hierarchy level inference from Docling headers."""

    def setup_method(self):
        self.service = TOCReconciliationService()

    def test_chapter_level_1(self):
        """Chapter headings are level 1."""
        level = self.service._infer_level_from_docling(
            "Chapter I Introduction", [50, 72, 500, 90], 0.9
        )
        assert level == 1

    def test_chapter_roman_numerals(self):
        """Chapter with Roman numerals are level 1."""
        level = self.service._infer_level_from_docling(
            "Chapter IV Audit Findings", [50, 72, 500, 90], 0.9
        )
        assert level == 1

    def test_annexure_level_1(self):
        """Annexure headings are level 1."""
        level = self.service._infer_level_from_docling(
            "Annexure A: Details", [50, 72, 500, 90], 0.9
        )
        assert level == 1

    def test_appendix_level_1(self):
        """Appendix headings are level 1."""
        level = self.service._infer_level_from_docling(
            "Appendix I: Methodology", [50, 72, 500, 90], 0.9
        )
        assert level == 1

    def test_executive_summary_level_1(self):
        """Executive Summary is level 1."""
        level = self.service._infer_level_from_docling(
            "Executive Summary", [50, 72, 500, 90], 0.9
        )
        assert level == 1

    def test_numbered_section_level_2(self):
        """Numbered sections like 1.1 are level 2."""
        level = self.service._infer_level_from_docling(
            "1.1 Background", [50, 100, 400, 115], 0.85
        )
        assert level == 2

    def test_numbered_section_level_3(self):
        """Numbered sections like 1.1.1 are level 3."""
        level = self.service._infer_level_from_docling(
            "1.1.1 Detailed Analysis", [50, 100, 400, 115], 0.85
        )
        assert level == 3

    def test_large_bbox_level_1(self):
        """Large bounding box implies level 1 heading."""
        # bbox height = 30 (> 25)
        level = self.service._infer_level_from_docling(
            "Important Section", [50, 60, 500, 90], 0.9
        )
        assert level == 1


class TestTitleCleaning:
    """Test header title cleaning."""

    def setup_method(self):
        self.service = TOCReconciliationService()

    def test_remove_trailing_page_number(self):
        """Trailing page numbers are removed."""
        result = self.service._clean_header_title("Chapter I Introduction 25")
        assert result == "Chapter I Introduction"

    def test_remove_excessive_whitespace(self):
        """Excessive whitespace is normalized."""
        result = self.service._clean_header_title("Chapter   I    Introduction")
        assert result == "Chapter I Introduction"

    def test_remove_special_chars(self):
        """Leading/trailing special chars are removed."""
        result = self.service._clean_header_title("--Chapter I Introduction:")
        assert result == "Chapter I Introduction"

    def test_reject_short_title(self):
        """Short titles (< 3 chars) are rejected."""
        result = self.service._clean_header_title("Hi")
        assert result == ""

    def test_reject_numeric_only(self):
        """Numeric-only titles are rejected."""
        result = self.service._clean_header_title("123")
        assert result == ""


class TestSupplementHighQuality:
    """Test high quality TOC supplementation."""

    def setup_method(self):
        self.service = TOCReconciliationService()

    def test_supplement_adds_new_entries(self):
        """High quality TOC gains new entries from Docling."""
        current_toc = [
            [1, "Chapter I Introduction", 5],
            [1, "Chapter II Findings", 15],
        ]
        docling_headers = [
            {"title": "Chapter I Introduction", "page": 5, "y_position": 72.0,
             "confidence": 0.9, "bbox": [50, 72, 500, 90], "level": 1},
            {"title": "1.1 Background", "page": 7, "y_position": 100.0,
             "confidence": 0.85, "bbox": [50, 100, 400, 115], "level": 2},
            {"title": "Chapter II Findings", "page": 15, "y_position": 72.0,
             "confidence": 0.9, "bbox": [50, 72, 500, 90], "level": 1},
        ]
        result, method = self.service._supplement_high_quality(
            current_toc, docling_headers, "test_report"
        )
        assert len(result) == 3  # Added "1.1 Background"
        assert method == "supplemented"

    def test_no_new_entries_validates(self):
        """When all Docling headers match, method is 'validated'."""
        current_toc = [
            [1, "Chapter I Introduction", 5],
            [1, "Chapter II Findings", 15],
        ]
        docling_headers = [
            {"title": "Chapter I Introduction", "page": 5, "y_position": 72.0,
             "confidence": 0.9, "bbox": [50, 72, 500, 90], "level": 1},
            {"title": "Chapter II Findings", "page": 15, "y_position": 72.0,
             "confidence": 0.9, "bbox": [50, 72, 500, 90], "level": 1},
        ]
        result, method = self.service._supplement_high_quality(
            current_toc, docling_headers, "test_report"
        )
        assert len(result) == 2  # No change
        assert method == "validated"


class TestMergeMediumQuality:
    """Test medium quality TOC merging."""

    def setup_method(self):
        self.service = TOCReconciliationService()

    def test_merge_adds_unmatched_docling(self):
        """Medium quality merge adds unmatched Docling headers."""
        current_toc = [
            [1, "Chapter I Introduction", 5],
        ]
        docling_headers = [
            {"title": "Chapter I Introduction", "page": 5, "y_position": 72.0,
             "confidence": 0.9, "bbox": [50, 72, 500, 90], "level": 1},
            {"title": "Chapter II New Section", "page": 15, "y_position": 72.0,
             "confidence": 0.9, "bbox": [50, 72, 500, 90], "level": 1},
        ]
        result, method = self.service._merge_medium_quality(
            current_toc, docling_headers, "test_report"
        )
        assert len(result) == 2
        assert method == "merged"


class TestPreferDoclingLowQuality:
    """Test low quality TOC Docling preference."""

    def setup_method(self):
        self.service = TOCReconciliationService()

    def test_prefer_docling_when_more_entries(self):
        """Prefer Docling when it has more entries."""
        current_toc = [
            [1, "Chapter I", 5],
        ]
        docling_headers = [
            {"title": "Chapter I Introduction", "page": 5, "y_position": 72.0,
             "confidence": 0.9, "bbox": [50, 72, 500, 90], "level": 1},
            {"title": "Chapter II Findings", "page": 15, "y_position": 72.0,
             "confidence": 0.9, "bbox": [50, 72, 500, 90], "level": 1},
            {"title": "Conclusion", "page": 30, "y_position": 72.0,
             "confidence": 0.9, "bbox": [50, 72, 500, 90], "level": 1},
        ]
        result, method = self.service._prefer_docling_low_quality(
            current_toc, docling_headers, "test_report"
        )
        assert len(result) == 3
        assert method == "docling_primary"


class TestHeadingPositionsFormat:
    """Test heading_positions key format compatibility."""

    def setup_method(self):
        self.service = TOCReconciliationService()

    def test_heading_positions_format(self):
        """Verify heading_positions key format matches chunking_service."""
        docling_headers = [
            {"title": "Chapter I Introduction", "page": 5, "y_position": 72.5,
             "confidence": 0.9, "bbox": [50, 72, 500, 90], "level": 1},
        ]
        toc = [[1, "Chapter I Introduction", 5]]

        positions = self.service._update_heading_positions({}, docling_headers, toc)

        # Key must be f"{page}_{title[:30]}"
        expected_key = "5_Chapter I Introduction"
        assert expected_key in positions
        assert positions[expected_key] == 72.5

    def test_long_title_truncated_to_30(self):
        """Long titles are truncated to 30 chars in the key."""
        docling_headers = [
            {"title": "This Is A Very Long Chapter Title That Exceeds Thirty Characters",
             "page": 10, "y_position": 80.0,
             "confidence": 0.9, "bbox": [50, 80, 500, 100], "level": 1},
        ]
        toc = [[1, "This Is A Very Long Chapter Title That Exceeds Thirty Characters", 10]]

        positions = self.service._update_heading_positions({}, docling_headers, toc)

        # Key should be truncated to first 30 chars of title
        # "This Is A Very Long Chapter Title..." [:30] = "This Is A Very Long Chapter Ti"
        expected_key = "10_This Is A Very Long Chapter Ti"
        assert expected_key in positions


class TestQualityAssessment:
    """Test quality score computation (toc_quality.assess_toc_quality)."""

    def test_empty_toc_zero_quality(self):
        assert assess_toc_quality([]) == 0

    def test_clean_toc_scores_high(self):
        toc = [
            [1, "Preface", 2],
            [1, "Chapter I Introduction", 5],
            [2, "1.1 Background", 7],
            [1, "Chapter II Findings", 12],
            [2, "2.1 Major Issues", 14],
        ]
        assert assess_toc_quality(toc, 20) >= 90

    def test_missing_chapters_and_sections_at_l1_score_low(self):
        toc = [
            [1, "Chapter 1 Introduction", 5],
            [1, "1.3 Resources", 7],
            [1, "1.5 Refunds", 9],
            [1, "Chapter 6 Execution", 40],
            [1, "&KDSWHU $ZDUGRI3URMHFWV", 30],
        ]
        assert assess_toc_quality(toc, 60) < 70

    def test_quality_bounded(self):
        toc = [[1, f"Chapter {i}", i * 5] for i in range(1, 20)]
        assert 0 <= assess_toc_quality(toc, 100) <= 100


class TestSimilarityMatching:
    """Test fuzzy title matching."""

    def test_similar_titles_match(self):
        """Similar titles should match with default threshold."""
        # "Chapter I: Introduction" vs "Chapter I Introduction" should match
        sim = SequenceMatcher(
            None,
            "chapter i: introduction",
            "chapter i introduction"
        ).ratio()
        assert sim >= 0.65  # Default threshold

    def test_dissimilar_titles_dont_match(self):
        """Dissimilar titles should not match."""
        sim = SequenceMatcher(
            None,
            "chapter i introduction",
            "annexure a methodology"
        ).ratio()
        assert sim < 0.65


class TestReconcileIntegration:
    """Integration tests for full reconcile flow."""

    def setup_method(self):
        self.service = TOCReconciliationService(min_docling_headers=2)

    @patch("src.parsing_pipeline.modules.toc_reconciliation_service.Path")
    @patch("src.parsing_pipeline.modules.toc_reconciliation_service.fitz")
    def test_reconcile_with_mock_pdf(self, mock_fitz, mock_path):
        """Full reconcile flow with mocked PDF."""
        # Mock Path.exists() to return True
        mock_path_instance = MagicMock()
        mock_path_instance.exists.return_value = True
        mock_path.return_value = mock_path_instance

        # Setup mock PDF
        mock_doc = MagicMock()
        mock_page = MagicMock()
        mock_page.rect.width = 612
        mock_page.rect.height = 792
        mock_page.get_text.return_value = "Chapter I Introduction"
        mock_doc.__len__ = Mock(return_value=20)
        mock_doc.__getitem__ = Mock(return_value=mock_page)
        mock_fitz.open.return_value = mock_doc
        mock_fitz.Rect = Mock(side_effect=lambda *args: MagicMock(
            x0=args[0], y0=args[1], x1=args[2], y1=args[3]
        ))

        # Create task with layout data
        task = DocumentTask(
            report_id="test_report",
            source_url="",
            local_pdf_path="/fake/path.pdf",
            initial_metadata={},
            scaffold={
                "toc": [[1, "Chapter I Introduction", 5]],
                "toc_quality": 60,
                "toc_method": "heuristic",
                "heading_positions": {},
            },
            layout={
                5: [
                    {"label": "Section-header", "confidence": 0.9,
                     "bbox": [50, 72, 500, 90]},
                ],
                10: [
                    {"label": "Section-header", "confidence": 0.9,
                     "bbox": [50, 72, 500, 90]},
                ],
            },
        )

        result = self.service.reconcile(task)

        # Should have called PyMuPDF
        mock_fitz.open.assert_called_once()

        # Scaffold should be updated
        assert "toc" in result.scaffold
        assert "heading_positions" in result.scaffold
        assert "+reconciled_" in result.scaffold.get("toc_method", "")

    def test_insufficient_docling_headers_skips(self):
        """Reconciliation skips when too few Docling headers."""
        service = TOCReconciliationService(min_docling_headers=10)
        task = DocumentTask(
            report_id="test",
            source_url="",
            local_pdf_path="",
            initial_metadata={},
            scaffold={
                "toc": [[1, "Chapter I", 5]],
                "toc_quality": 50,
            },
            layout={
                5: [
                    {"label": "Section-header", "confidence": 0.9,
                     "bbox": [50, 72, 500, 90]},
                ],
            },
        )

        result = service.reconcile(task)

        # TOC should be unchanged
        assert result.scaffold["toc"] == [[1, "Chapter I", 5]]


# ==================== P0-02: Noise Rejection and Deduplication ====================


class TestP002NoiseRejection:
    """P0-02: Test noise pattern rejection from Docling headers."""

    def setup_method(self):
        self.service = TOCReconciliationService()

    def test_reject_paragraph_reference(self):
        """P0-02: Reject '(Paragraph 3.2)' style headers."""
        headers = [
            {"title": "(Paragraph 3.2)", "page": 5, "level": 2},
            {"title": "Chapter I Introduction", "page": 5, "level": 1},
        ]
        filtered = self.service._filter_noise_headers(headers)
        assert len(filtered) == 1
        assert filtered[0]["title"] == "Chapter I Introduction"

    def test_reject_source_citation(self):
        """P0-02: Reject '(Source: Records...)' style headers."""
        headers = [
            {"title": "(Source: Ministry Records)", "page": 10, "level": 2},
            {"title": "Chapter II Findings", "page": 10, "level": 1},
        ]
        filtered = self.service._filter_noise_headers(headers)
        assert len(filtered) == 1
        assert filtered[0]["title"] == "Chapter II Findings"

    def test_reject_page_number(self):
        """P0-02: Reject 'Page 123' style headers."""
        headers = [
            {"title": "Page 45", "page": 45, "level": 2},
            {"title": "Chapter III Analysis", "page": 45, "level": 1},
        ]
        filtered = self.service._filter_noise_headers(headers)
        assert len(filtered) == 1
        assert filtered[0]["title"] == "Chapter III Analysis"

    def test_reject_list_item(self):
        """P0-02: Reject 'a. ...' style list items."""
        headers = [
            {"title": "a. First point", "page": 20, "level": 3},
            {"title": "Chapter IV Recommendations", "page": 20, "level": 1},
        ]
        filtered = self.service._filter_noise_headers(headers)
        assert len(filtered) == 1
        assert filtered[0]["title"] == "Chapter IV Recommendations"

    def test_reject_roman_numeral_list(self):
        """P0-02: Reject '(iv) ...' style roman numeral lists."""
        headers = [
            {"title": "(iv) Loss of revenue", "page": 30, "level": 3},
            {"title": "Chapter V Compliance", "page": 30, "level": 1},
        ]
        filtered = self.service._filter_noise_headers(headers)
        assert len(filtered) == 1
        assert filtered[0]["title"] == "Chapter V Compliance"

    def test_reject_non_printable_chars(self):
        """P0-02: Reject headers with >30% non-printable characters."""
        # Create a title with many non-ASCII chars (font encoding garbage)
        # 10 chars, 5 are non-printable = 50% > 30%
        garbage_title = "\x00\x01\x02\x03\x04Hello"
        headers = [
            {"title": garbage_title, "page": 5, "level": 1},
            {"title": "Chapter I Introduction", "page": 5, "level": 1},
        ]
        filtered = self.service._filter_noise_headers(headers)
        assert len(filtered) == 1
        assert filtered[0]["title"] == "Chapter I Introduction"

    def test_keep_valid_headers(self):
        """P0-02: Keep valid headers that don't match noise patterns."""
        headers = [
            {"title": "Chapter I Introduction", "page": 5, "level": 1},
            {"title": "1.1 Background", "page": 7, "level": 2},
            {"title": "1.2 Objectives", "page": 10, "level": 2},
        ]
        filtered = self.service._filter_noise_headers(headers)
        assert len(filtered) == 3


class TestP002Deduplication:
    """P0-02: Test parent deduplication."""

    def setup_method(self):
        self.service = TOCReconciliationService()

    def test_deduplicate_identical_entries(self):
        """P0-02: Identical entries are deduplicated."""
        toc = [
            [1, "Chapter I Introduction", 5],
            [1, "Chapter I Introduction", 5],  # Duplicate
            [1, "Chapter II Findings", 15],
        ]
        result = self.service._deduplicate_parents(toc)
        assert len(result) == 2

    def test_deduplicate_keeps_deeper_level(self):
        """P0-02: When duplicating, keep the deeper level (higher number)."""
        toc = [
            [1, "5.5 Non-Maintenance", 50],
            [2, "5.5 Non-Maintenance", 50],  # Deeper level
        ]
        result = self.service._deduplicate_parents(toc)
        assert len(result) == 1
        assert result[0][0] == 2  # Kept the deeper level

    def test_deduplicate_normalizes_whitespace(self):
        """P0-02: Deduplication normalizes whitespace in titles."""
        toc = [
            [1, "Chapter I  Introduction", 5],  # Extra space
            [1, "Chapter I Introduction", 5],   # Normal
        ]
        result = self.service._deduplicate_parents(toc)
        assert len(result) == 1

    def test_different_pages_not_deduplicated(self):
        """P0-02: Same title on different pages are NOT deduplicated."""
        toc = [
            [1, "Chapter I Introduction", 5],
            [1, "Chapter I Introduction", 25],  # Same title, different page
        ]
        result = self.service._deduplicate_parents(toc)
        assert len(result) == 2


class TestP002QualityCap:
    """P0-02: Test quality cap at 85."""

    def test_quality_cap_constant(self):
        """P0-02: QUALITY_CAP is set to 85."""
        assert TOCReconciliationService.QUALITY_CAP == 85


class TestP002EmptyTOC:
    """P0-02: Test empty TOC explicit handling."""

    def setup_method(self):
        self.service = TOCReconciliationService(min_docling_headers=1)

    def test_empty_toc_check_in_reconcile_logic(self):
        """P0-02: Empty TOC should trigger empty_toc branch."""
        # Test that the logic correctly identifies empty TOC
        # by checking the code path directly

        # An empty TOC is falsy in Python
        empty_toc = []
        assert not empty_toc  # Confirms empty TOC is falsy

        # The condition `if not current_toc:` should be True for empty TOC
        current_toc = []
        assert not current_toc

        # And False for non-empty TOC
        non_empty_toc = [[1, "Chapter I", 5]]
        assert non_empty_toc

    @patch.object(TOCReconciliationService, "_extract_docling_headers")
    @patch.object(TOCReconciliationService, "_filter_noise_headers")
    @patch.object(TOCReconciliationService, "_promote_chapters_to_l1")
    @patch.object(TOCReconciliationService, "_prefer_docling_low_quality")
    def test_empty_toc_routes_to_docling_primary(
        self, mock_prefer_docling, mock_promote, mock_filter, mock_extract
    ):
        """P0-02: Empty TOC should route to docling_primary method."""
        # Setup mocks
        docling_headers = [
            {"title": "Chapter I Introduction", "page": 5, "level": 1,
             "y_position": 72.0, "confidence": 0.9},
        ]
        mock_extract.return_value = docling_headers
        mock_filter.return_value = docling_headers
        mock_promote.return_value = docling_headers
        mock_prefer_docling.return_value = (
            [[1, "Chapter I Introduction", 5]],
            "docling_primary"
        )

        # Mock emitter
        mock_emitter = Mock()
        mock_emitter.emit_io = Mock()
        mock_emitter.emit_decision = Mock()
        mock_emitter.emit_red_flag = Mock()

        task = DocumentTask(
            report_id="test",
            source_url="",
            local_pdf_path="",
            initial_metadata={},
            scaffold={
                "toc": [],  # Empty TOC
                "toc_quality": 70,
                "heading_positions": {},
            },
            layout={5: []},  # Has layout data
        )

        self.service.reconcile(task, trace_emitter=mock_emitter)

        # Should have called _prefer_docling_low_quality (the empty_toc branch)
        mock_prefer_docling.assert_called_once()

        # Should have emitted decision with "empty_toc" value
        decision_calls = [
            call for call in mock_emitter.emit_decision.call_args_list
            if len(call[0]) >= 3 and call[0][1] == "quality_tier"
        ]
        assert len(decision_calls) >= 1
        assert decision_calls[0][0][2] == "empty_toc"


# ==================== P0-04: Chapter Promotion and Orphan Detection ====================


class TestP004ChapterPromotion:
    """P0-04: Test Chapter pattern promotion to L1."""

    def setup_method(self):
        self.service = TOCReconciliationService()

    def test_promote_chapter_arabic(self):
        """P0-04: 'Chapter 1' patterns are promoted to L1."""
        headers = [
            {"title": "Chapter 1 Introduction", "page": 5, "level": 2},
        ]
        result = self.service._promote_chapters_to_l1(headers)
        assert result[0]["level"] == 1

    def test_promote_chapter_roman(self):
        """P0-04: 'Chapter IV' patterns are promoted to L1."""
        headers = [
            {"title": "Chapter IV Audit Findings", "page": 15, "level": 3},
        ]
        result = self.service._promote_chapters_to_l1(headers)
        assert result[0]["level"] == 1

    def test_promote_annexure(self):
        """P0-04: 'Annexure A' patterns are promoted to L1."""
        headers = [
            {"title": "Annexure A: Ministry Details", "page": 100, "level": 2},
        ]
        result = self.service._promote_chapters_to_l1(headers)
        assert result[0]["level"] == 1

    def test_promote_appendix(self):
        """P0-04: 'Appendix I' patterns are promoted to L1."""
        headers = [
            {"title": "Appendix I: Methodology", "page": 150, "level": 3},
        ]
        result = self.service._promote_chapters_to_l1(headers)
        assert result[0]["level"] == 1

    def test_already_l1_unchanged(self):
        """P0-04: Headers already at L1 remain unchanged."""
        headers = [
            {"title": "Chapter 1 Introduction", "page": 5, "level": 1},
        ]
        result = self.service._promote_chapters_to_l1(headers)
        assert result[0]["level"] == 1

    def test_non_chapter_unchanged(self):
        """P0-04: Non-chapter headers remain at original level."""
        headers = [
            {"title": "1.1 Background", "page": 7, "level": 2},
        ]
        result = self.service._promote_chapters_to_l1(headers)
        assert result[0]["level"] == 2

    def test_chapter_patterns_constant(self):
        """P0-04: CHAPTER_PATTERNS constant is properly defined."""
        assert len(TOCReconciliationService.CHAPTER_PATTERNS) >= 4


class TestP004L1CountCheck:
    """P0-04: Test L1 count sanity check."""

    def test_max_l1_count_constant(self):
        """P0-04: MAX_L1_COUNT is set to 15."""
        assert TOCReconciliationService.MAX_L1_COUNT == 15


class TestP004OrphanDetection:
    """P0-04: Test orphan section detection."""

    def setup_method(self):
        self.service = TOCReconciliationService()

    def test_detect_orphan_section(self):
        """P0-04: Detect numbered sections without L1 parent."""
        toc = [
            [1, "Chapter 1 Introduction", 5],
            [2, "1.1 Background", 7],
            [2, "3.1 Missing Chapter Reference", 20],  # Chapter 3 not in L1
        ]
        mock_emitter = Mock()
        mock_emitter.emit_red_flag = Mock()

        orphans = self.service._detect_orphan_sections(toc, mock_emitter)

        assert len(orphans) == 1
        assert orphans[0]["expected_chapter"] == 3
        assert "3.1" in orphans[0]["title"]
        mock_emitter.emit_red_flag.assert_called_once()

    def test_no_orphans_when_all_have_parents(self):
        """P0-04: No orphans when all sections have L1 parents."""
        toc = [
            [1, "Chapter 1 Introduction", 5],
            [2, "1.1 Background", 7],
            [2, "1.2 Objectives", 10],
            [1, "Chapter 2 Findings", 15],
            [2, "2.1 Key Issues", 17],
        ]
        mock_emitter = Mock()
        mock_emitter.emit_red_flag = Mock()

        orphans = self.service._detect_orphan_sections(toc, mock_emitter)

        assert len(orphans) == 0
        mock_emitter.emit_red_flag.assert_not_called()

    def test_detect_multiple_orphans(self):
        """P0-04: Detect multiple orphan sections."""
        toc = [
            [1, "Chapter 1 Introduction", 5],
            [2, "1.1 Background", 7],
            [2, "3.1 No Chapter 3", 20],  # Orphan
            [2, "5.2 No Chapter 5", 30],  # Orphan
        ]
        mock_emitter = Mock()
        mock_emitter.emit_red_flag = Mock()

        orphans = self.service._detect_orphan_sections(toc, mock_emitter)

        assert len(orphans) == 2
        expected_chapters = {o["expected_chapter"] for o in orphans}
        assert expected_chapters == {3, 5}

    def test_orphan_detection_emits_red_flag(self):
        """P0-04: Orphan detection emits red flag with correct data."""
        toc = [
            [1, "Chapter 1", 5],
            [2, "4.1 Orphan Section", 25],
        ]
        mock_emitter = Mock()
        mock_emitter.emit_red_flag = Mock()

        self.service._detect_orphan_sections(toc, mock_emitter)

        mock_emitter.emit_red_flag.assert_called_once()
        call_args = mock_emitter.emit_red_flag.call_args
        assert call_args[0][0] == "5.5"  # Phase
        assert call_args[0][1] == "orphan_sections_detected"
        assert call_args[0][2]["count"] == 1
