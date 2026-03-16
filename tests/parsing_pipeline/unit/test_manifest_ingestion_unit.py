import pytest
import pandas as pd
from pathlib import Path
from ..src.modules.manifest_ingestion_service import ManifestIngestionService
from ..src.modules.data_contracts import DocumentTask
from unittest.mock import patch, MagicMock


@pytest.fixture
def service(test_raw_dir):
    """ManifestIngestionService fixture."""
    return ManifestIngestionService(raw_data_dir=str(test_raw_dir))


@pytest.mark.parametrize(
    "title,expected",
    [
        ("Cleanliness Report", "cleanliness_report"),
        ("Report 123!", "report_123"),
        ("Test & Trial", "test__trial"),  # & removed -> extra spaces -> __
        ("", ""),
        ("   ", ""),
        ("CAFÉ", "cafe"),  # Accents removed
    ],
)
def test_sanitize_filename(service, title, expected):
    """Test filename sanitization."""
    result = service._sanitize_filename(title)
    assert result == expected


def test_load_manifest_success(service, temp_dir):
    """Test successful manifest loading with column renaming."""
    # Create a mock DataFrame
    data = {
        "  SL NO": [1.0, 2.0],
        "Original Title": ["Title 1", "Title 2"],
        "Report PDF": ["url1", "url2"],
    }
    mock_df = pd.DataFrame(data)

    with patch("pandas.read_excel", return_value=mock_df):
        df = service.load_manifest("dummy.xlsx")

        assert "SL NO" in df.columns
        assert "Title" in df.columns
        assert "Report PDF" in df.columns
        assert df["SL NO"].tolist() == [1.0, 2.0]


def test_load_manifest_missing_file(service):
    """Test error on missing manifest file."""
    with pytest.raises(ValueError, match="Failed to load manifest"):
        service.load_manifest("nonexistent.xlsx")


def test_load_manifest_missing_columns(service, temp_dir):
    """Test error on missing required columns."""
    data = {"Wrong Column": [1, 2]}
    mock_df = pd.DataFrame(data)

    with patch("pandas.read_excel", return_value=mock_df):
        with pytest.raises(ValueError, match="Missing required columns"):
            service.load_manifest("dummy.xlsx")


@patch("pathlib.Path.mkdir", MagicMock())
def test_service_init(test_raw_dir):
    """Test service initialization."""
    service = ManifestIngestionService(raw_data_dir=str(test_raw_dir))
    assert service.raw_data_dir == Path(test_raw_dir)


@pytest.mark.anyio
async def test_download_pdf_success(httpx_mock, test_raw_dir, temp_dir):
    """Test successful PDF download with filename generation."""
    # Mock HTTP response
    pdf_content = b"PDF content here"
    httpx_mock.add_response(
        method="GET",
        url="https://example.com/report1.pdf",
        status_code=200,
        content=pdf_content,
    )

    service = ManifestIngestionService(raw_data_dir=str(test_raw_dir))
    row = pd.Series(
        {
            "SL NO": 1,
            "Title": "Test Report",
            "Recommended Title": None,
            "Report PDF": "https://example.com/report1.pdf",
        }
    )

    # Mock client
    import httpx

    client = httpx.AsyncClient()
    task = await service._download_pdf(client, row)
    await client.aclose()

    assert isinstance(task, DocumentTask)
    assert task.report_id == "report_001_test_report"
    assert task.source_url == "https://example.com/report1.pdf"
    assert Path(task.local_pdf_path).name == "report_001_test_report.pdf"
    assert Path(task.local_pdf_path).exists()
    assert task.processing_status == "pending"


@pytest.mark.anyio
async def test_download_pdf_failure_retry(httpx_mock, test_raw_dir):
    """Test PDF download failure with retries."""
    # Mock 404 responses to trigger tenacity retries
    httpx_mock.add_response(
        method="GET",
        url="https://example.com/fail.pdf",
        status_code=404,
    )

    service = ManifestIngestionService(raw_data_dir=str(test_raw_dir))
    row = pd.Series(
        {
            "SL NO": 1,
            "Title": "Fail Report",
            "Recommended Title": None,
            "Report PDF": "https://example.com/fail.pdf",
        }
    )

    import httpx
    from tenacity import RetryError, stop_after_attempt

    client = httpx.AsyncClient()

    task = await service._download_pdf(client, row)

    assert task is not None
    assert task.processing_status == "failed_download"
    assert "Download failed after retries" in task.error_log[0]
    assert len(task.error_log) == 1

    await client.aclose()


@pytest.mark.anyio
async def test_download_pdf_network_error(httpx_mock, test_raw_dir):
    """Test PDF download with network error, creates failed DocumentTask."""
    # No mock response = network error

    service = ManifestIngestionService(raw_data_dir=str(test_raw_dir))
    row = pd.Series(
        {
            "SL NO": 2,
            "Title": "Network Error Report",
            "Recommended Title": "Net Error CAG",
            "Report PDF": "https://broken.example.com/report2.pdf",
        }
    )

    import httpx

    client = httpx.AsyncClient()

    # Should not raise but create DocumentTask with failed status
    task = await service._download_pdf(client, row)
    await client.aclose()

    assert isinstance(task, DocumentTask)
    assert task.report_id == "report_002_net_error_cag"
    assert task.source_url == "https://broken.example.com/report2.pdf"
    assert task.local_pdf_path == ""
    assert task.processing_status == "failed_download"
    assert len(task.error_log) == 1
    assert "Download failed after retries" in task.error_log[0]
