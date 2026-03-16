import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, Mock
from services.parsing_pipeline.src.modules.triage_service import TriageService
from services.parsing_pipeline.src.modules.data_contracts import DocumentTask


@pytest.fixture
def triage_service():
    """TriageService fixture with default parameters."""
    return TriageService()


@pytest.fixture
def sample_task():
    """Sample DocumentTask fixture."""
    return DocumentTask(
        report_id="report_001_test",
        source_url="https://example.com/test.pdf",
        local_pdf_path="/tmp/test.pdf",
        initial_metadata={"Title": "Test Report"},
    )


def test_service_init_defaults():
    """Test service initialization with default parameters."""
    service = TriageService()
    assert service.sample_pages == 10
    assert service.text_threshold == 150


def test_service_init_custom():
    """Test service initialization with custom parameters."""
    service = TriageService(sample_pages=5, text_threshold=200)
    assert service.sample_pages == 5
    assert service.text_threshold == 200


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


@patch("fitz.Document")
def test_triage_native_text_classification(mock_fitz_doc, triage_service, sample_task):
    """Test classification as native_text with sufficient text density."""
    # Mock page with rich text content
    mock_page = Mock()
    mock_page.get_text.return_value = (
        "This is a sample page with sufficient text content to exceed the threshold"
    )

    mock_doc = Mock()
    mock_doc.load_page.return_value = mock_page
    mock_doc.page_count = 5  # Less than default sample_pages (10)
    mock_doc.close = Mock()
    mock_fitz_doc.return_value = mock_doc

    result = triage_service.triage_document(sample_task)

    assert result.classification == "native_text"
    assert result.processing_status == "triaged_native"

    # Verify 5 pages were sampled (page_count < sample_pages)
    assert mock_doc.load_page.call_count == 5


@patch("fitz.Document")
def test_triage_scanned_classification(mock_fitz_doc, triage_service, sample_task):
    """Test classification as scanned with insufficient text density."""
    # Mock page with minimal text (simulating OCR scan)
    mock_page = Mock()
    mock_page.get_text.return_value = "Page 1"

    mock_doc = Mock()
    mock_doc.load_page.return_value = mock_page
    mock_doc.page_count = 10  # Equal to default sample_pages
    mock_doc.close = Mock()
    mock_fitz_doc.return_value = mock_doc

    result = triage_service.triage_document(sample_task)

    assert result.classification == "scanned"
    assert result.processing_status == "triaged_scanned"

    # Verify 10 pages were sampled (page_count == sample_pages)
    assert mock_doc.load_page.call_count == 10


@patch("fitz.Document")
def test_triage_empty_pages(mock_fitz_doc, triage_service, sample_task):
    """Test error handling when document has no pages."""
    mock_doc = Mock()
    mock_doc.page_count = 0
    mock_doc.close = Mock()
    mock_fitz_doc.return_value = mock_doc

    result = triage_service.triage_document(sample_task)

    assert result.classification is None
    assert result.processing_status == "failed_triage"
    assert "has no pages" in result.error_log[0]


@patch("fitz.Document")
def test_triage_fitz_exception(mock_fitz_doc, triage_service, sample_task):
    """Test error handling when fitz throws an exception (corrupted PDF)."""
    mock_fitz_doc.side_effect = Exception("Corrupted PDF file")

    result = triage_service.triage_document(sample_task)

    assert result.classification is None
    assert result.processing_status == "failed_triage"
    assert "Triage failed with error" in result.error_log[0]


@pytest.mark.parametrize(
    "page_texts,expected_classification",
    [
        (["Short text"], "scanned"),  # Low density
        (
            ["This is a longer sample text with more content to test classification"],
            "native_text",
        ),  # High density
        (
            ["Page one", "Page two", "Page three", "Page four", "Page five"],
            "scanned",
        ),  # Low per-page density
        (["" for _ in range(10)], "scanned"),  # Empty pages
    ],
)
@patch("fitz.Document")
def test_triage_parametrized_classification(
    mock_fitz_doc, triage_service, sample_task, page_texts, expected_classification
):
    """Parametrized test for various text densities."""
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

    result = triage_service.triage_document(sample_task)

    assert result.classification == expected_classification
    expected_status = (
        "triaged_native"
        if expected_classification == "native_text"
        else "triaged_scanned"
    )
    assert result.processing_status == expected_status
