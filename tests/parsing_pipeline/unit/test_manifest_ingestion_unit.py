import pytest
import pandas as pd
from pathlib import Path
from src.parsing_pipeline.modules.manifest_ingestion_service import ManifestIngestionService
from src.core.data_contracts import DocumentTask
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


# ==================== P0-06: Report ID Generation Tests ====================


class TestReportIdZeroPadding:
    """P0-06: Test zero-padding normalization for report IDs."""

    def test_union_report_id_zero_padding(self, tmp_path):
        """Test Union report ID has zero-padded number."""
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir()
        service = ManifestIngestionService(raw_data_dir=str(raw_dir))
        service.government_body_type = "union"  # Set for test

        row = pd.Series({
            "SL NO": 1,
            "Title": "Test Report",
            "Recommended Title": "Performance Audit",
            "Report No": "4 of 2025",
            "Date": "2025-01-15",
            "Report PDF": "https://example.com/report.pdf",
        })

        report_id = service._build_report_id(row)
        # Should be 2025_04_... not 2025_4_...
        assert "_04_" in report_id
        assert "_4_" not in report_id.replace("_04_", "")

    def test_state_report_id_zero_padding(self, tmp_path):
        """Test State report ID has zero-padded number."""
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir()
        service = ManifestIngestionService(raw_data_dir=str(raw_dir))
        service.government_body_type = "state"  # Set for test

        row = pd.Series({
            "SL NO": 1,
            "Title": "Test Report",
            "Recommended Title": "Compliance Audit",
            "Report No": "3 of 2024",
            "State Name": "Odisha",
            "Date": "2024-06-15",
            "Report PDF": "https://example.com/report.pdf",
        })

        report_id = service._build_report_id(row)
        # Should be OD_2024_03_... not OD_2024_3_...
        assert "_03_" in report_id

    def test_double_digit_unchanged(self, tmp_path):
        """Test double-digit numbers remain unchanged."""
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir()
        service = ManifestIngestionService(raw_data_dir=str(raw_dir))
        service.government_body_type = "union"  # Set for test

        row = pd.Series({
            "SL NO": 1,
            "Title": "Test Report",
            "Recommended Title": "Performance Audit",
            "Report No": "15 of 2025",
            "Date": "2025-01-15",
            "Report PDF": "https://example.com/report.pdf",
        })

        report_id = service._build_report_id(row)
        # Should be 2025_15_... (15 stays as is)
        assert "_15_" in report_id


class TestReportIdValidation:
    """P0-06: Test report ID format validation."""

    def test_valid_union_format(self, tmp_path, caplog):
        """Test valid Union format passes validation."""
        import logging
        caplog.set_level(logging.WARNING)

        raw_dir = tmp_path / "raw"
        raw_dir.mkdir()
        service = ManifestIngestionService(raw_data_dir=str(raw_dir))
        service.government_body_type = "union"  # Set for test

        row = pd.Series({
            "SL NO": 1,
            "Title": "Test Report",
            "Recommended Title": "Performance Audit",
            "Report No": "4 of 2025",
            "Date": "2025-01-15",
            "Report PDF": "https://example.com/report.pdf",
        })

        report_id = service._build_report_id(row)
        # Should not log warning
        assert "P0-06" not in caplog.text

    def test_valid_state_format(self, tmp_path, caplog):
        """Test valid State format passes validation."""
        import logging
        caplog.set_level(logging.WARNING)

        raw_dir = tmp_path / "raw"
        raw_dir.mkdir()
        service = ManifestIngestionService(raw_data_dir=str(raw_dir))
        service.government_body_type = "state"  # Set for test

        row = pd.Series({
            "SL NO": 1,
            "Title": "Test Report",
            "Recommended Title": "Compliance Audit",
            "Report No": "1 of 2024",
            "State Name": "Kerala",
            "Date": "2024-06-15",
            "Report PDF": "https://example.com/report.pdf",
        })

        report_id = service._build_report_id(row)
        # Should be KL_2024_01_... and not trigger warning
        assert report_id.startswith("KL_2024_01_")


class TestLegacyReportIdCheck:
    """P0-06: Test legacy report ID fallback."""

    def test_check_legacy_format(self, tmp_path):
        """Test detection of legacy format files."""
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir()
        service = ManifestIngestionService(raw_data_dir=str(raw_dir))

        # Create a legacy format file
        legacy_path = raw_dir / "2025_4_Test_Report.pdf"
        legacy_path.write_text("test")

        # Check if legacy path is found for canonical ID
        result = service._check_legacy_report_id("2025_04_Test_Report")
        assert result is not None
        assert result.exists()
        assert result.name == "2025_4_Test_Report.pdf"

    def test_no_legacy_when_canonical_format(self, tmp_path):
        """Test no legacy path when already canonical."""
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir()
        service = ManifestIngestionService(raw_data_dir=str(raw_dir))

        # No legacy file exists
        result = service._check_legacy_report_id("2025_04_Test_Report")
        assert result is None
