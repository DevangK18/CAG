"""
Unit tests for TriageService: PDF classification based on text density.

Tests both the original functionality and P0-05 improvements:
- Blank page skipping (<20 chars threshold)
- Median instead of mean for robustness to outliers
- Widened borderline band (0.4-1.5)
- Mid-document sampling to skip heavy front-matter
"""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, Mock

from src.parsing_pipeline.modules.triage_service import TriageService
from src.core.data_contracts import DocumentTask


@pytest.fixture
def triage_service():
    """TriageService fixture with default parameters."""
    return TriageService()


@pytest.fixture
def legacy_triage_service():
    """TriageService fixture with P0-05 features disabled for backward compat tests."""
    return TriageService(
        skip_blank_pages=False,
        use_median=False,
        sample_mid_document=False,
    )


@pytest.fixture
def sample_task():
    """Sample DocumentTask fixture."""
    return DocumentTask(
        report_id="report_001_test",
        source_url="https://example.com/test.pdf",
        local_pdf_path="/tmp/test.pdf",
        initial_metadata={"Title": "Test Report"},
    )


# ==================== INITIALIZATION TESTS ====================


def test_service_init_defaults():
    """Test service initialization with default parameters."""
    service = TriageService()
    assert service.sample_pages == 10
    assert service.text_threshold == 150
    # P0-05 defaults
    assert service.skip_blank_pages is True
    assert service.use_median is True
    assert service.sample_mid_document is True


def test_service_init_custom():
    """Test service initialization with custom parameters."""
    service = TriageService(sample_pages=5, text_threshold=200)
    assert service.sample_pages == 5
    assert service.text_threshold == 200


def test_service_init_p0_05_options():
    """Test P0-05 options can be disabled."""
    service = TriageService(
        skip_blank_pages=False,
        use_median=False,
        sample_mid_document=False,
    )
    assert service.skip_blank_pages is False
    assert service.use_median is False
    assert service.sample_mid_document is False


def test_p0_05_constants():
    """Test P0-05 class constants are correctly defined."""
    assert TriageService.BLANK_PAGE_THRESHOLD == 20
    assert TriageService.BORDERLINE_BAND_LOW == 0.4
    assert TriageService.BORDERLINE_BAND_HIGH == 1.5
    assert TriageService.MID_DOCUMENT_START_PAGE == 10


# ==================== ERROR HANDLING TESTS ====================


def test_triage_nonexistent_file(triage_service, sample_task):
    """Test triage with nonexistent file path."""
    sample_task.local_pdf_path = "/nonexistent/path.pdf"

    result = triage_service.triage_document(sample_task)

    assert result.classification is None
    assert result.processing_status == "failed_triage"
    assert len(result.error_log) == 1
    assert "does not exist" in result.error_log[0]


def test_triage_empty_path(triage_service):
    """Test triage with empty path."""
    task = DocumentTask(
        report_id="test",
        source_url="https://example.com/test.pdf",
        local_pdf_path="",
        initial_metadata={},
    )

    result = triage_service.triage_document(task)

    assert result.classification is None
    assert result.processing_status == "failed_triage"
    assert "does not exist" in result.error_log[0]


@patch("src.parsing_pipeline.modules.triage_service.Path")
@patch("src.parsing_pipeline.modules.triage_service.fitz.Document")
def test_triage_empty_pages(mock_fitz_doc, mock_path, triage_service, sample_task):
    """Test error handling when document has no pages."""
    # Mock Path.exists() to return True
    mock_path_instance = MagicMock()
    mock_path_instance.exists.return_value = True
    mock_path.return_value = mock_path_instance

    mock_doc = Mock()
    mock_doc.page_count = 0
    mock_doc.close = Mock()
    mock_fitz_doc.return_value = mock_doc

    result = triage_service.triage_document(sample_task)

    assert result.classification is None
    assert result.processing_status == "failed_triage"
    assert "has no pages" in result.error_log[0]


@patch("src.parsing_pipeline.modules.triage_service.Path")
@patch("src.parsing_pipeline.modules.triage_service.fitz.Document")
def test_triage_fitz_exception(mock_fitz_doc, mock_path, triage_service, sample_task):
    """Test error handling when fitz throws an exception (corrupted PDF)."""
    # Mock Path.exists() to return True
    mock_path_instance = MagicMock()
    mock_path_instance.exists.return_value = True
    mock_path.return_value = mock_path_instance

    mock_fitz_doc.side_effect = Exception("Corrupted PDF file")

    result = triage_service.triage_document(sample_task)

    assert result.classification is None
    assert result.processing_status == "failed_triage"
    assert "Triage failed with error" in result.error_log[0]


# ==================== BASIC CLASSIFICATION TESTS ====================


@patch("src.parsing_pipeline.modules.triage_service.Path")
@patch("src.parsing_pipeline.modules.triage_service.fitz.Document")
def test_triage_native_text_classification(mock_fitz_doc, mock_path, sample_task):
    """Test classification as native_text with sufficient text density."""
    # Mock Path.exists() to return True
    mock_path_instance = MagicMock()
    mock_path_instance.exists.return_value = True
    mock_path.return_value = mock_path_instance

    # Use legacy service without P0-05 mid-document sampling for simpler assertion
    service = TriageService(sample_mid_document=False)

    # Mock page with rich text content (>150 non-whitespace chars)
    # Need enough characters after removing whitespace
    mock_page = Mock()
    mock_page.get_text.return_value = "A" * 200  # 200 non-whitespace chars

    mock_doc = Mock()
    mock_doc.load_page.return_value = mock_page
    mock_doc.page_count = 5
    mock_doc.close = Mock()
    mock_fitz_doc.return_value = mock_doc

    result = service.triage_document(sample_task)

    assert result.classification == "native_text"
    assert result.processing_status == "triaged_native"


@patch("src.parsing_pipeline.modules.triage_service.Path")
@patch("src.parsing_pipeline.modules.triage_service.fitz.Document")
def test_triage_scanned_classification(mock_fitz_doc, mock_path, legacy_triage_service, sample_task):
    """Test classification as scanned with insufficient text density."""
    # Mock Path.exists() to return True
    mock_path_instance = MagicMock()
    mock_path_instance.exists.return_value = True
    mock_path.return_value = mock_path_instance

    # Mock page with minimal text (simulating OCR scan)
    mock_page = Mock()
    mock_page.get_text.return_value = "Page 1"

    mock_doc = Mock()
    mock_doc.load_page.return_value = mock_page
    mock_doc.page_count = 10
    mock_doc.close = Mock()
    mock_fitz_doc.return_value = mock_doc

    result = legacy_triage_service.triage_document(sample_task)

    assert result.classification == "scanned"
    assert result.processing_status == "triaged_scanned"


# ==================== P0-05: BLANK PAGE SKIPPING TESTS ====================


@patch("src.parsing_pipeline.modules.triage_service.Path")
@patch("src.parsing_pipeline.modules.triage_service.fitz.Document")
def test_p0_05_skip_blank_pages_classifies_native(mock_fitz_doc, mock_path, sample_task):
    """
    P0-05: Blank pages should be skipped when computing text density.
    Document with 5 blank pages + 5 rich pages should classify as native_text.
    """
    mock_path_instance = MagicMock()
    mock_path_instance.exists.return_value = True
    mock_path.return_value = mock_path_instance

    service = TriageService(sample_mid_document=False)  # Disable mid-doc for clarity

    # Create mixed pages: 5 blank (< 20 chars) + 5 rich (> 150 chars)
    blank_page = Mock()
    blank_page.get_text.return_value = "Page"  # 4 chars - blank

    rich_page = Mock()
    rich_page.get_text.return_value = "A" * 200  # 200 chars - rich

    mock_pages = [blank_page] * 5 + [rich_page] * 5

    mock_doc = Mock()
    mock_doc.load_page.side_effect = lambda i: mock_pages[i]
    mock_doc.page_count = 10
    mock_doc.close = Mock()
    mock_fitz_doc.return_value = mock_doc

    result = service.triage_document(sample_task)

    # With blank-page skipping, median/mean of rich pages (200) > threshold (150)
    assert result.classification == "native_text"
    assert result.processing_status == "triaged_native"


@patch("src.parsing_pipeline.modules.triage_service.Path")
@patch("src.parsing_pipeline.modules.triage_service.fitz.Document")
def test_p0_05_without_blank_skip_classifies_scanned(mock_fitz_doc, mock_path, sample_task):
    """
    P0-05 disabled: Same document WITHOUT blank-page skipping should classify as scanned
    because the blank pages drag down the average.
    """
    mock_path_instance = MagicMock()
    mock_path_instance.exists.return_value = True
    mock_path.return_value = mock_path_instance

    service = TriageService(
        skip_blank_pages=False,
        use_median=False,
        sample_mid_document=False,
    )

    # Create mixed pages: 8 blank (< 20 chars) + 2 rich (> 150 chars)
    blank_page = Mock()
    blank_page.get_text.return_value = "Hi"  # 2 chars - blank

    rich_page = Mock()
    rich_page.get_text.return_value = "A" * 200  # 200 chars - rich

    mock_pages = [blank_page] * 8 + [rich_page] * 2

    mock_doc = Mock()
    mock_doc.load_page.side_effect = lambda i: mock_pages[i]
    mock_doc.page_count = 10
    mock_doc.close = Mock()
    mock_fitz_doc.return_value = mock_doc

    result = service.triage_document(sample_task)

    # Without blank-page skipping: avg = (8*2 + 2*200)/10 = 41.6 < 150
    assert result.classification == "scanned"


@patch("src.parsing_pipeline.modules.triage_service.Path")
@patch("src.parsing_pipeline.modules.triage_service.fitz.Document")
def test_p0_05_all_blank_pages_fallback(mock_fitz_doc, mock_path, sample_task):
    """
    P0-05: If ALL pages are blank, fall back to including them in the sample.
    This ensures we don't divide by zero.
    """
    mock_path_instance = MagicMock()
    mock_path_instance.exists.return_value = True
    mock_path.return_value = mock_path_instance

    service = TriageService(sample_mid_document=False)

    blank_page = Mock()
    blank_page.get_text.return_value = "X"  # 1 char - all pages blank

    mock_doc = Mock()
    mock_doc.load_page.return_value = blank_page
    mock_doc.page_count = 5
    mock_doc.close = Mock()
    mock_fitz_doc.return_value = mock_doc

    result = service.triage_document(sample_task)

    # All blank → fallback to mean of 1 char/page → scanned
    assert result.classification == "scanned"
    assert result.processing_status == "triaged_scanned"


# ==================== P0-05: MEDIAN VS MEAN TESTS ====================


@patch("src.parsing_pipeline.modules.triage_service.Path")
@patch("src.parsing_pipeline.modules.triage_service.fitz.Document")
def test_p0_05_median_robust_to_outliers(mock_fitz_doc, mock_path, sample_task):
    """
    P0-05: Median should be robust to outlier pages.
    9 pages with 200 chars + 1 page with 20,000 chars → median = 200 (not inflated).
    """
    mock_path_instance = MagicMock()
    mock_path_instance.exists.return_value = True
    mock_path.return_value = mock_path_instance

    service = TriageService(sample_mid_document=False)

    normal_page = Mock()
    normal_page.get_text.return_value = "A" * 200

    outlier_page = Mock()
    outlier_page.get_text.return_value = "B" * 20000

    # 9 normal + 1 outlier
    mock_pages = [normal_page] * 9 + [outlier_page]

    mock_doc = Mock()
    mock_doc.load_page.side_effect = lambda i: mock_pages[i]
    mock_doc.page_count = 10
    mock_doc.close = Mock()
    mock_fitz_doc.return_value = mock_doc

    result = service.triage_document(sample_task)

    # Median of [200,200,200,200,200,200,200,200,200,20000] = 200
    # Mean would be 2180, which is > threshold but misrepresents the document
    assert result.classification == "native_text"


@patch("src.parsing_pipeline.modules.triage_service.Path")
@patch("src.parsing_pipeline.modules.triage_service.fitz.Document")
def test_p0_05_mean_inflated_by_outliers(mock_fitz_doc, mock_path, sample_task):
    """
    P0-05: With use_median=False, outliers inflate the mean.
    """
    mock_path_instance = MagicMock()
    mock_path_instance.exists.return_value = True
    mock_path.return_value = mock_path_instance

    service = TriageService(
        skip_blank_pages=False,
        use_median=False,
        sample_mid_document=False,
    )

    low_page = Mock()
    low_page.get_text.return_value = "A" * 50  # Below threshold individually

    high_outlier = Mock()
    high_outlier.get_text.return_value = "B" * 2000  # High outlier

    # 9 low + 1 high outlier
    mock_pages = [low_page] * 9 + [high_outlier]

    mock_doc = Mock()
    mock_doc.load_page.side_effect = lambda i: mock_pages[i]
    mock_doc.page_count = 10
    mock_doc.close = Mock()
    mock_fitz_doc.return_value = mock_doc

    result = service.triage_document(sample_task)

    # Mean = (9*50 + 2000)/10 = 245 > 150 → native_text (incorrectly)
    assert result.classification == "native_text"


# ==================== P0-05: MID-DOCUMENT SAMPLING TESTS ====================


@patch("src.parsing_pipeline.modules.triage_service.Path")
@patch("src.parsing_pipeline.modules.triage_service.fitz.Document")
def test_p0_05_mid_document_sampling_skips_frontmatter(mock_fitz_doc, mock_path, sample_task):
    """
    P0-05: Mid-document sampling should skip heavy front-matter.
    Pages 0-9: blank (front-matter), Pages 10-19: rich text.
    """
    mock_path_instance = MagicMock()
    mock_path_instance.exists.return_value = True
    mock_path.return_value = mock_path_instance

    service = TriageService()  # All P0-05 features enabled

    blank_page = Mock()
    blank_page.get_text.return_value = ""  # 0 chars

    rich_page = Mock()
    rich_page.get_text.return_value = "Content " * 50  # 400 chars

    # 10 blank front-matter + 20 rich content pages
    mock_pages = [blank_page] * 10 + [rich_page] * 20

    mock_doc = Mock()
    mock_doc.load_page.side_effect = lambda i: mock_pages[i]
    mock_doc.page_count = 30
    mock_doc.close = Mock()
    mock_fitz_doc.return_value = mock_doc

    result = service.triage_document(sample_task)

    # With mid-document sampling (start at page 10), should sample rich pages
    assert result.classification == "native_text"


@patch("src.parsing_pipeline.modules.triage_service.Path")
@patch("src.parsing_pipeline.modules.triage_service.fitz.Document")
def test_p0_05_short_document_samples_from_start(mock_fitz_doc, mock_path, sample_task):
    """
    P0-05: Short documents should fall back to sampling from start.
    """
    mock_path_instance = MagicMock()
    mock_path_instance.exists.return_value = True
    mock_path.return_value = mock_path_instance

    service = TriageService()

    rich_page = Mock()
    rich_page.get_text.return_value = "A" * 200

    mock_doc = Mock()
    mock_doc.load_page.return_value = rich_page
    mock_doc.page_count = 15  # Too short for mid-doc sampling (needs > 10 + sample_pages)
    mock_doc.close = Mock()
    mock_fitz_doc.return_value = mock_doc

    result = service.triage_document(sample_task)

    # Should start from page 0 since document is short
    assert result.classification == "native_text"
    # Verify pages were loaded from start
    mock_doc.load_page.assert_any_call(0)


# ==================== P0-05: BORDERLINE BAND TESTS ====================


@patch("src.parsing_pipeline.modules.triage_service.Path")
@patch("src.parsing_pipeline.modules.triage_service.fitz.Document")
def test_p0_05_borderline_band_widened(mock_fitz_doc, mock_path, sample_task):
    """
    P0-05: Borderline band is widened from 0.7-1.3 to 0.4-1.5.
    A ratio of 0.56 (84 chars vs 150 threshold) should now trigger borderline flag.
    """
    mock_path_instance = MagicMock()
    mock_path_instance.exists.return_value = True
    mock_path.return_value = mock_path_instance

    service = TriageService(sample_mid_document=False)

    # Create a page that produces exactly 84 chars
    # Ratio = 84/150 = 0.56, which is in [0.4, 1.5] but was outside [0.7, 1.3]
    page = Mock()
    page.get_text.return_value = "A" * 84

    mock_doc = Mock()
    mock_doc.load_page.return_value = page
    mock_doc.page_count = 5
    mock_doc.close = Mock()
    mock_fitz_doc.return_value = mock_doc

    # Use a mock emitter to capture red flags
    mock_emitter = Mock()
    mock_emitter.emit_io = Mock()
    mock_emitter.emit_sample = Mock()
    mock_emitter.emit_decision = Mock()
    mock_emitter.emit_red_flag = Mock()

    result = service.triage_document(sample_task, trace_emitter=mock_emitter)

    # Classification should be scanned (84 < 150)
    assert result.classification == "scanned"

    # Borderline flag should have been emitted
    mock_emitter.emit_red_flag.assert_called_once()
    call_args = mock_emitter.emit_red_flag.call_args
    assert call_args[0][0] == "2"  # Phase
    assert call_args[0][1] == "borderline_classification"  # Flag name
    assert call_args[0][2]["ratio"] == 0.56


@patch("src.parsing_pipeline.modules.triage_service.Path")
@patch("src.parsing_pipeline.modules.triage_service.fitz.Document")
def test_p0_05_borderline_includes_p0_05_metadata(mock_fitz_doc, mock_path, sample_task):
    """
    P0-05: Borderline flag should include P0-05 specific metadata.
    """
    mock_path_instance = MagicMock()
    mock_path_instance.exists.return_value = True
    mock_path.return_value = mock_path_instance

    service = TriageService(sample_mid_document=False)

    # Mixed: 3 blank + 7 with 100 chars
    blank_page = Mock()
    blank_page.get_text.return_value = "X"  # 1 char - blank

    content_page = Mock()
    content_page.get_text.return_value = "A" * 100  # 100 chars

    mock_pages = [blank_page] * 3 + [content_page] * 7

    mock_doc = Mock()
    mock_doc.load_page.side_effect = lambda i: mock_pages[i]
    mock_doc.page_count = 10
    mock_doc.close = Mock()
    mock_fitz_doc.return_value = mock_doc

    mock_emitter = Mock()
    mock_emitter.emit_io = Mock()
    mock_emitter.emit_sample = Mock()
    mock_emitter.emit_decision = Mock()
    mock_emitter.emit_red_flag = Mock()

    result = service.triage_document(sample_task, trace_emitter=mock_emitter)

    # Borderline flag should include sampled_pages and blank_pages_skipped
    mock_emitter.emit_red_flag.assert_called_once()
    flag_data = mock_emitter.emit_red_flag.call_args[0][2]
    assert "sampled_pages" in flag_data
    assert "blank_pages_skipped" in flag_data
    assert flag_data["blank_pages_skipped"] == 3  # 3 blank pages skipped


# ==================== PARAMETRIZED CLASSIFICATION TESTS ====================


@pytest.mark.parametrize(
    "page_texts,expected_classification",
    [
        (["Short text"], "scanned"),  # Low density
        (
            ["This is a longer sample text with more content to test classification" * 3],
            "native_text",
        ),  # High density
        (
            ["Page one", "Page two", "Page three", "Page four", "Page five"],
            "scanned",
        ),  # Low per-page density
        (["" for _ in range(10)], "scanned"),  # Empty pages (fallback)
    ],
)
@patch("src.parsing_pipeline.modules.triage_service.Path")
@patch("src.parsing_pipeline.modules.triage_service.fitz.Document")
def test_triage_parametrized_classification(
    mock_fitz_doc, mock_path, sample_task, page_texts, expected_classification
):
    """Parametrized test for various text densities."""
    mock_path_instance = MagicMock()
    mock_path_instance.exists.return_value = True
    mock_path.return_value = mock_path_instance

    service = TriageService(sample_mid_document=False)

    # Create mock pages with different text contents
    mock_pages = []
    for text in page_texts:
        mock_page = Mock()
        mock_page.get_text.return_value = text
        mock_pages.append(mock_page)

    mock_doc = Mock()
    mock_doc.load_page.side_effect = mock_pages
    mock_doc.page_count = len(page_texts)
    mock_doc.close = Mock()
    mock_fitz_doc.return_value = mock_doc

    result = service.triage_document(sample_task)

    assert result.classification == expected_classification
    expected_status = (
        "triaged_native"
        if expected_classification == "native_text"
        else "triaged_scanned"
    )
    assert result.processing_status == expected_status


# ==================== INTEGRATION SCENARIO: UNION 2025_4 ====================


@patch("src.parsing_pipeline.modules.triage_service.Path")
@patch("src.parsing_pipeline.modules.triage_service.fitz.Document")
def test_p0_05_union_2025_4_scenario(mock_fitz_doc, mock_path, sample_task):
    """
    P0-05: Simulates Union 2025_4 scenario where ~30 front-matter pages
    have minimal text, but the overall document is native_text.

    Without P0-05: avg chars from first 10 pages → ~30 chars → scanned (WRONG)
    With P0-05: sample from page 10, skip blanks, use median → native_text (CORRECT)
    """
    mock_path_instance = MagicMock()
    mock_path_instance.exists.return_value = True
    mock_path.return_value = mock_path_instance

    service = TriageService()  # All P0-05 features enabled

    # Simulate Union 2025_4:
    # - Pages 0-29: Front-matter with ~10 chars each
    # - Pages 30+: Content with ~500 chars each
    frontmatter_page = Mock()
    frontmatter_page.get_text.return_value = "CAG Report"  # 10 chars

    content_page = Mock()
    content_page.get_text.return_value = "Audit findings " * 35  # ~500 chars

    # 30 front-matter + 100 content pages
    mock_pages = [frontmatter_page] * 30 + [content_page] * 100

    mock_doc = Mock()
    mock_doc.load_page.side_effect = lambda i: mock_pages[i]
    mock_doc.page_count = 130
    mock_doc.close = Mock()
    mock_fitz_doc.return_value = mock_doc

    result = service.triage_document(sample_task)

    # With P0-05: starts at page 10, but these are still front-matter (< 20 chars)
    # Continue sampling until we get 10 non-blank pages from content section
    # Even front-matter with 10 chars is < 20, so will be skipped until page 30+
    assert result.classification == "native_text"
    assert result.processing_status == "triaged_native"


@patch("src.parsing_pipeline.modules.triage_service.Path")
@patch("src.parsing_pipeline.modules.triage_service.fitz.Document")
def test_p0_05_union_2025_4_without_p0_05_fails(mock_fitz_doc, mock_path, sample_task):
    """
    P0-05 disabled: Same Union 2025_4 scenario should classify as scanned (WRONG).
    """
    mock_path_instance = MagicMock()
    mock_path_instance.exists.return_value = True
    mock_path.return_value = mock_path_instance

    service = TriageService(
        skip_blank_pages=False,
        use_median=False,
        sample_mid_document=False,
    )

    frontmatter_page = Mock()
    frontmatter_page.get_text.return_value = "CAG Report"  # 10 chars

    content_page = Mock()
    content_page.get_text.return_value = "Audit findings " * 35  # ~500 chars

    mock_pages = [frontmatter_page] * 30 + [content_page] * 100

    mock_doc = Mock()
    mock_doc.load_page.side_effect = lambda i: mock_pages[i]
    mock_doc.page_count = 130
    mock_doc.close = Mock()
    mock_fitz_doc.return_value = mock_doc

    result = service.triage_document(sample_task)

    # Without P0-05: samples first 10 pages (all front-matter with 10 chars)
    # Mean = 10 < 150 → scanned (WRONG classification)
    assert result.classification == "scanned"
