import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, Mock
import fitz
from services.parsing_pipeline.src.modules.scaffolding_service import (
    ScaffoldingService,
    TextBlock,
    StyleProfile,
)
from services.parsing_pipeline.src.modules.data_contracts import DocumentTask


@pytest.fixture
def scaffolding_service():
    """ScaffoldingService fixture with default parameters."""
    return ScaffoldingService()


@pytest.fixture
def sample_task(tmp_path):
    """Sample DocumentTask fixture with a valid file path."""
    return DocumentTask(
        report_id="report_001_test",
        source_url="https://example.com/test.pdf",
        local_pdf_path=str(tmp_path / "test.pdf"),
        initial_metadata={"Title": "Test Report"},
    )


class TestScaffoldingServiceInit:
    """Test ScaffoldingService initialization."""

    def test_init_defaults(self):
        """Test service initialization with default parameters."""
        service = ScaffoldingService()
        assert service.embed_toc_min_entries == 5
        assert service.body_text_percentile == 80.0
        assert service.heading_size_ratio == 1.4
        assert service.heading_min_length == 10

    def test_init_custom(self):
        """Test service initialization with custom parameters."""
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
    """Test PDF path resolution."""

    def test_get_pdf_path_local(self, scaffolding_service, sample_task):
        """Test path selection with only local PDF."""
        result = scaffolding_service._get_pdf_path(sample_task)
        assert result == sample_task.local_pdf_path

    def test_get_pdf_path_ocr(self, scaffolding_service, sample_task, tmp_path):
        """Test path selection preferring OCR'd PDF."""
        sample_task.ocred_pdf_path = str(tmp_path / "ocred.pdf")
        with open(sample_task.ocred_pdf_path, "w") as f:
            f.write("mock")

        result = scaffolding_service._get_pdf_path(sample_task)
        assert result == sample_task.ocred_pdf_path

    def test_get_pdf_path_none(self, scaffolding_service):
        """Test path selection with no valid paths."""
        task = DocumentTask(
            report_id="test",
            source_url="https://example.com/test.pdf",
            local_pdf_path="/nonexistent/path.pdf",
            initial_metadata={},
        )
        result = scaffolding_service._get_pdf_path(task)
        assert result is None


@patch("fitz.Document")
class TestScaffoldingServiceEmbeddedToc:
    """Test embedded ToC extraction."""

    def test_extract_embedded_toc_success(
        self, mock_fitz_doc, scaffolding_service, sample_task
    ):
        """Test successful embedded ToC extraction."""
        mock_toc = [[1, "Chapter 1", 0], [2, "Section 1.1", 1]]
        mock_doc = Mock()
        mock_doc.get_toc.return_value = mock_toc
        mock_fitz_doc.return_value = mock_doc

        result = scaffolding_service._extract_embedded_toc(sample_task, mock_doc)

        assert result.scaffold["toc"] == mock_toc
        assert "Embedded ToC extracted successfully: 2 entries" in result.error_log[0]

    def test_extract_embedded_toc_inadequate(
        self, mock_fitz_doc, scaffolding_service, sample_task
    ):
        """Test embedded ToC validation fails."""
        # Only level 1 entries, no hierarchy
        mock_toc = [[1, "Chapter 1", 0], [1, "Chapter 2", 5]]
        mock_doc = Mock()
        mock_doc.get_toc.return_value = mock_toc
        mock_fitz_doc.return_value = mock_doc

        result = scaffolding_service._extract_embedded_toc(sample_task, mock_doc)

        assert result.scaffold["toc"] == []  # Trigger heuristic
        assert (
            "inadequate: 2 entries, proceeding to heuristic generation"
            in result.error_log[0]
        )

    def test_extract_embedded_toc_failure(
        self, mock_fitz_doc, scaffolding_service, sample_task
    ):
        """Test embedded ToC extraction failure."""
        mock_doc = Mock()
        mock_doc.get_toc.side_effect = Exception("PDF error")
        mock_fitz_doc.return_value = mock_doc

        result = scaffolding_service._extract_embedded_toc(sample_task, mock_doc)

        assert result.scaffold["toc"] == []
        assert "extraction failed: PDF error" in result.error_log[0]


class TestValidateEmbeddedToc:
    """Test embedded ToC validation logic."""

    def test_validate_sufficient_entries_and_hierarchy(self, scaffolding_service):
        """Test validation passes with sufficient entries and hierarchy."""
        toc = [[1, "Chap 1", 0], [2, "Sec 1.1", 1], [2, "Sec 1.2", 3], [1, "Chap 2", 5]]
        assert scaffolding_service._validate_embedded_toc(toc) is True

    def test_validate_insufficient_entries(self, scaffolding_service):
        """Test validation fails with too few entries."""
        toc = [[1, "Chap 1", 0], [1, "Chap 2", 5]]  # Only 2 entries
        assert scaffolding_service._validate_embedded_toc(toc) is False

    def test_validate_no_hierarchy(self, scaffolding_service):
        """Test validation fails with no hierarchy."""
        toc = [[1, "Chap 1", 0], [1, "Chap 2", 5], [1, "Chap 3", 10]]  # All level 1
        assert scaffolding_service._validate_embedded_toc(toc) is False


@patch("fitz.Document")
class TestScaffoldingServicePageMappings:
    """Test page number mappings."""

    def test_build_page_mappings_success(
        self, mock_fitz_doc, scaffolding_service, sample_task
    ):
        """Test successful page mapping creation."""
        page_labels = [{"start": 0, "style": "D", "prefix": "", "first": 1}]
        mock_doc = Mock()
        mock_doc.get_page_labels.return_value = page_labels
        mock_doc.page_count = 5
        mock_fitz_doc.return_value = mock_doc

        result = scaffolding_service._build_page_mappings(sample_task, mock_doc)

        assert len(result.scaffold["page_map"]) == 5
        assert result.scaffold["page_map"][0] == "1"
        assert result.scaffold["page_map"][4] == "5"
        assert "Page mappings created: 5 entries" in result.error_log[0]

    def test_build_page_mappings_empty_labels(
        self, mock_fitz_doc, scaffolding_service, sample_task
    ):
        """Test page mapping with no labels (default numbering)."""
        mock_doc = Mock()
        mock_doc.get_page_labels.return_value = []
        mock_doc.page_count = 3
        mock_fitz_doc.return_value = mock_doc

        result = scaffolding_service._build_page_mappings(sample_task, mock_doc)

        assert result.scaffold["page_map"] == {0: "1", 1: "2", 2: "3"}

    def test_build_page_mappings_failure(
        self, mock_fitz_doc, scaffolding_service, sample_task
    ):
        """Test page mapping failure."""
        mock_doc = Mock()
        mock_doc.get_page_labels.side_effect = Exception("PDF error")
        mock_fitz_doc.return_value = mock_doc

        result = scaffolding_service._build_page_mappings(sample_task, mock_doc)

        assert result.scaffold["page_map"] == {}
        assert "Page mapping failed: PDF error" in result.error_log[0]


class TestPageNumberFormatting:
    """Test page number formatting logic."""

    def test_format_page_number_arabic(self, scaffolding_service):
        """Test Arabic decimal formatting."""
        result = scaffolding_service._format_page_number("D", "", 25)
        assert result == "25"

    def test_format_page_number_roman_upper(self, scaffolding_service):
        """Test Roman numeral uppercase."""
        result = scaffolding_service._format_page_number("R", "", 5)
        assert result == "V"

    def test_format_page_number_roman_lower(self, scaffolding_service):
        """Test Roman numeral lowercase."""
        result = scaffolding_service._format_page_number("r", "", 10)
        assert result == "x"

    def test_format_page_number_letters_upper(self, scaffolding_service):
        """Test letter sequence uppercase."""
        result = scaffolding_service._format_page_number("A", "", 1)
        assert result == "A"
        result = scaffolding_service._format_page_number("A", "", 27)
        assert result == "AA"

    def test_format_page_number_with_prefix(self, scaffolding_service):
        """Test formatting with prefix."""
        result = scaffolding_service._format_page_number("D", "Chap ", 3)
        assert result == "Chap 3"

    def test_int_to_roman_edge_cases(self, scaffolding_service):
        """Test Roman numeral conversion edge cases."""
        assert scaffolding_service._int_to_roman(1) == "I"
        assert scaffolding_service._int_to_roman(4999) == "MMMMCMXCIX"
        assert scaffolding_service._int_to_roman(5000) == "5000"  # Fallback

    def test_int_to_letters_basic(self, scaffolding_service):
        """Test letter sequence conversion."""
        assert scaffolding_service._int_to_letters(1) == "A"
        assert scaffolding_service._int_to_letters(26) == "Z"
        assert scaffolding_service._int_to_letters(27) == "AA"


class TestValidateAndSetStatus:
    """Test final status setting logic."""

    def test_validate_complete(self, scaffolding_service, sample_task):
        """Test complete scaffold status."""
        sample_task.scaffold = {"toc": [[1, "Chap 1", 0]], "page_map": {0: "1"}}
        result = scaffolding_service._validate_and_set_status(sample_task)
        assert result.processing_status == "scaffold_complete"

    def test_validate_minimal_toc_only(self, scaffolding_service, sample_task):
        """Test ToC-only status."""
        sample_task.scaffold = {"toc": [[1, "Chap 1", 0]], "page_map": {}}
        result = scaffolding_service._validate_and_set_status(sample_task)
        assert result.processing_status == "scaffold_minimal"

    def test_validate_partial_page_map_only(self, scaffolding_service, sample_task):
        """Test page map-only status."""
        sample_task.scaffold = {"toc": [], "page_map": {0: "1"}}
        result = scaffolding_service._validate_and_set_status(sample_task)
        assert result.processing_status == "scaffold_partial"

    def test_validate_failed(self, scaffolding_service, sample_task):
        """Test failed scaffold status."""
        sample_task.scaffold = {"toc": [], "page_map": {}}
        result = scaffolding_service._validate_and_set_status(sample_task)
        assert result.processing_status == "failed_scaffold"


class TestHeuristicTocCore:
    """Test core heuristic ToC generation components."""

    def test_extract_text_blocks_sufficient_content(self, scaffolding_service):
        """Test text block extraction with mock PDF."""
        mock_doc = Mock()
        mock_page = Mock()

        # Mock text dict structure
        mock_text_dict = {
            "blocks": [
                {
                    "type": 0,
                    "bbox": [10, 20, 100, 30],
                    "lines": [
                        {
                            "spans": [
                                {
                                    "text": "Chapter 1",
                                    "size": 16.0,
                                    "font": "Times-Bold",
                                    "flags": 16,
                                }
                            ]
                        }
                    ],
                },
                {
                    "type": 0,
                    "bbox": [10, 40, 200, 50],
                    "lines": [
                        {
                            "spans": [
                                {
                                    "text": "This is body text content",
                                    "size": 12.0,
                                    "font": "Times-Roman",
                                    "flags": 0,
                                }
                            ]
                        }
                    ],
                },
            ]
        }
        mock_page.get_text.return_value = mock_text_dict

        # Mock 3-page document
        def mock_load_page(page_num):
            mock_page.page_num = page_num
            return mock_page

        mock_doc.load_page.side_effect = mock_load_page
        mock_doc.page_count = 3

        with patch("fitz.Document", return_value=mock_doc):
            text_blocks = scaffolding_service._extract_text_blocks(mock_doc, 5)

        assert len(text_blocks) >= 2  # At least 2 text blocks
        # Verify text content extraction
        assert any("Chapter 1" in block.text for block in text_blocks)
        assert any("body text" in block.text for block in text_blocks)

    def test_build_style_profile_basic(self, scaffolding_service):
        """Test basic style profile construction."""
        text_blocks = [
            TextBlock(
                0,
                (10, 20, 200, 30),
                "Chapter Title",
                "Times-Bold",
                16.0,
                16,
                12.0,
                (10, 20),
                2,
                13,
            ),
            TextBlock(
                0,
                (10, 40, 400, 50),
                "Body text content",
                "Times-Roman",
                12.0,
                0,
                12.0,
                (10, 40),
                3,
                17,
            ),
            TextBlock(
                1,
                (10, 70, 300, 80),
                "More content",
                "Times-Roman",
                12.0,
                0,
                12.0,
                (10, 70),
                2,
                12,
            ),
        ]

        profile = scaffolding_service._build_style_profile(text_blocks)

        assert isinstance(profile, StyleProfile)
        assert profile.body_font_size_baseline > 10.0
        assert "Times" in profile.body_font_families[0]
        assert profile.body_text_flags is not None
        assert "width" in profile.page_stats

    def test_calculate_heading_score_high(self, scaffolding_service):
        """Test heading score calculation for likely heading."""
        block = TextBlock(
            0,
            (10, 20, 200, 30),
            "Chapter Title",
            "Times-Bold",
            18.0,
            16,
            12.0,
            (10, 20),
            2,
            13,
        )

        style_profile = StyleProfile(
            12.0, ["Times"], {0}, {"width": 595.0, "left_margin": 72.0}
        )

        score = scaffolding_service._calculate_heading_score(block, style_profile)
        assert score >= 100  # Should be high score (>100)

    def test_calculate_heading_score_low(self, scaffolding_service):
        """Test heading score calculation for body text."""
        block = TextBlock(
            0,
            (80, 100, 400, 110),
            "This is body text",
            "Times-Roman",
            12.0,
            0,
            12.0,
            (80, 100),
            4,
            17,
        )

        style_profile = StyleProfile(
            12.0, ["Times"], {0}, {"width": 595.0, "left_margin": 72.0}
        )

        score = scaffolding_service._calculate_heading_score(block, style_profile)
        assert score < 50  # Should be low score (<50)

    @patch("sklearn.cluster.KMeans")
    def test_infer_hierarchy_simple(self, mock_kmeans, scaffolding_service):
        """Test hierarchy inference with few candidates."""
        heading_candidates = [
            TextBlock(
                0,
                (10, 20, 200, 30),
                "Chapter 1",
                "Times-Bold",
                16.0,
                16,
                12.0,
                (10, 20),
                2,
                9,
            ),
            TextBlock(
                2,
                (10, 50, 180, 60),
                "Section 1",
                "Times-Bold",
                14.0,
                16,
                12.0,
                (10, 50),
                2,
                8,
            ),
        ]

        # Mock K-means to return 2 clusters
        mock_kmeans_instance = Mock()
        mock_kmeans_instance.fit_predict.return_value = [0, 1]  # Different clusters
        mock_kmeans_instance.cluster_centers_ = [[16.0], [14.0]]
        mock_kmeans.return_value = mock_kmeans_instance

        hierarchy_map = scaffolding_service._infer_hierarchy(heading_candidates)

        assert len(hierarchy_map) == 2
        assert all(
            isinstance(level, int) and level >= 1 for level in hierarchy_map.values()
        )

    def test_construct_toc_basic(self, scaffolding_service):
        """Test basic ToC construction."""
        candidates = [
            TextBlock(
                0,
                (10, 20, 200, 30),
                "Chapter 1\nIntroduction",
                "Times",
                16.0,
                0,
                12.0,
                (10, 20),
                2,
                20,
            ),
            TextBlock(
                1,
                (10, 50, 150, 60),
                "Section 1.1",
                "Times",
                14.0,
                0,
                12.0,
                (10, 50),
                2,
                11,
            ),
        ]

        hierarchy_map = {candidates[0]: 1, candidates[1]: 2}

        toc = scaffolding_service._construct_toc(candidates, hierarchy_map)

        assert len(toc) == 2
        assert toc[0] == [
            1,
            "Chapter 1 Introduction",
            0,
        ]  # Title cleaned, hyphen removed
        assert toc[1] == [2, "Section 1.1", 1]

    def test_clean_toc_title_edge_cases(self, scaffolding_service):
        """Test ToC title cleaning various edge cases."""
        assert scaffolding_service._clean_toc_title("Chapter 1..") == "Chapter 1"
        assert scaffolding_service._clean_toc_title("Section A--") == "Section A"
        assert (
            scaffolding_service._clean_toc_title("   Extra   Spaces   ")
            == "Extra Spaces"
        )
        assert scaffolding_service._clean_toc_title("Normal Title") == "Normal Title"

    @patch("sklearn.cluster.KMeans")
    def test_detect_headings_with_candidates(self, mock_kmeans, scaffolding_service):
        """Test heading detection returns candidates above threshold."""
        # Mock K-means for hierarchy (not directly used in detect_headings)
        mock_kmeans.return_value.cluster_centers_ = [[16.0], [12.0]]

        text_blocks = [
            TextBlock(
                0,
                (10, 20, 200, 30),
                "POTENTIAL HEADING",
                "Times-Bold",
                18.0,
                16,
                12.0,
                (10, 20),
                2,
                16,
            ),
            TextBlock(
                0,
                (10, 40, 400, 50),
                "This is definite body text",
                "Times-Roman",
                12.0,
                0,
                12.0,
                (10, 40),
                5,
                24,
            ),
        ]

        style_profile = StyleProfile(
            12.0, ["Times-Roman"], {0}, {"width": 595.0, "left_margin": 72.0}
        )

        candidates = scaffolding_service._detect_headings(text_blocks, style_profile)

        assert len(candidates) > 0  # Should detect at least one heading candidate


@patch("fitz.Document")
class TestScaffoldingServiceIntegration:
    """Integration tests for complete scaffold building."""

    def test_build_scaffold_complete_flow(
        self, mock_fitz_doc, scaffolding_service, sample_task, tmp_path
    ):
        """Test complete scaffold building with embedded ToC."""
        # Create a mock PDF file
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(b"mock pdf content")
        sample_task.local_pdf_path = str(pdf_path)

        # Mock embedded ToC and page labels
        mock_toc = [[1, "Chapter 1", 0], [2, "Section 1.1", 1], [1, "Chapter 2", 3]]
        page_labels = [{"start": 0, "style": "D", "prefix": "", "first": 1}]

        mock_doc = Mock()
        mock_doc.get_toc.return_value = mock_toc
        mock_doc.get_page_labels.return_value = page_labels
        mock_doc.page_count = 5
        mock_doc.close = Mock()
        mock_fitz_doc.return_value = mock_doc

        result = scaffolding_service.build_scaffold(sample_task)

        assert result.processing_status == "scaffold_complete"
        assert len(result.scaffold["toc"]) == 3
        assert len(result.scaffold["page_map"]) == 5

    def test_build_scaffold_heuristic_fallback(
        self, mock_fitz_doc, scaffolding_service, sample_task, tmp_path
    ):
        """Test scaffold building with heuristic fallback."""
        # Create mock PDF
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(b"mock pdf content")
        sample_task.local_pdf_path = str(pdf_path)

        # Mock failed embedded ToC + page labels
        page_labels = [{"start": 0, "style": "D", "prefix": "", "first": 1}]

        mock_doc = Mock()
        mock_doc.get_toc.side_effect = Exception("No embedded ToC")
        mock_doc.get_page_labels.return_value = page_labels
        mock_doc.page_count = 3
        mock_doc.close = Mock()
        mock_fitz_doc.return_value = mock_doc

        result = scaffolding_service.build_scaffold(sample_task)

        assert result.processing_status == "scaffold_partial"  # Page map only, no ToC
        assert result.scaffold["toc"] == []  # Heuristic failed (insufficient content)
        assert len(result.scaffold["page_map"]) == 3
        assert "extraction failed" in result.error_log[0]

    def test_build_scaffold_no_valid_pdf(self, scaffolding_service):
        """Test scaffold building with no valid PDF path."""
        task = DocumentTask(
            report_id="test",
            source_url="https://example.com/test.pdf",
            local_pdf_path="",
            initial_metadata={},
        )

        result = scaffolding_service.build_scaffold(task)

        assert result.processing_status == "failed_scaffold"
        assert "No valid PDF path" in result.error_log[0]


def test_normalize_font_family_variations(scaffolding_service):
    """Test font family normalization removes weight suffixes."""
    assert (
        scaffolding_service._normalize_font_family("TimesNewRoman-Bold")
        == "TimesNewRoman"
    )
    assert scaffolding_service._normalize_font_family("Arial-Black") == "Arial"
    assert scaffolding_service._normalize_font_family("Helvetica") == "Helvetica"
    assert scaffolding_service._normalize_font_family("Courier,Italic") == "Courier"
