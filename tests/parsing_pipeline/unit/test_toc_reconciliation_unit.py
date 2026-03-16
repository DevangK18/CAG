"""Tests for Phase 5.5 TOC Reconciliation Service."""

import pytest
from difflib import SequenceMatcher
from unittest.mock import Mock, patch, MagicMock

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
    """Test quality score computation."""

    def setup_method(self):
        self.service = TOCReconciliationService()

    def test_empty_toc_zero_quality(self):
        """Empty TOC has zero quality."""
        score = self.service._assess_reconciled_quality([], [])
        assert score == 0

    def test_base_quality_for_any_toc(self):
        """Any TOC gets at least base quality."""
        toc = [[1, "Chapter I", 5]]
        score = self.service._assess_reconciled_quality(toc, [])
        assert score >= 40

    def test_multiple_levels_bonus(self):
        """Multiple hierarchy levels increase quality."""
        toc = [
            [1, "Chapter I", 5],
            [2, "1.1 Background", 7],
            [3, "1.1.1 Details", 8],
        ]
        docling_headers = [
            {"title": "Chapter I", "page": 5, "y_position": 72.0,
             "confidence": 0.9, "bbox": [50, 72, 500, 90], "level": 1},
        ]
        score = self.service._assess_reconciled_quality(toc, docling_headers)
        assert score >= 55  # Base + levels bonus

    def test_quality_capped_at_100(self):
        """Quality score cannot exceed 100."""
        toc = [[1, f"Chapter {i}", i*5] for i in range(1, 20)]
        docling_headers = [
            {"title": f"Chapter {i}", "page": i*5, "y_position": 72.0,
             "confidence": 0.9, "bbox": [50, 72, 500, 90], "level": 1}
            for i in range(1, 20)
        ]
        score = self.service._assess_reconciled_quality(toc, docling_headers)
        assert score <= 100


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
