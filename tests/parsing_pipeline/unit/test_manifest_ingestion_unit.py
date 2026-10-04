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
        ("Cleanliness Report", "Cleanliness_Report"),  # case is kept
        ("Report 123!", "Report_123"),
        ("Test & Trial", "Test__Trial"),  # & removed -> extra spaces -> __
        ("", ""),
        ("   ", ""),
        ("CAFÉ", "CAFE"),  # Accents removed
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
    # Union row with no Report No and no Date: year 0000, serial from SL NO
    assert task.report_id == "0000_01_Test_Report"
    assert task.source_url == "https://example.com/report1.pdf"
    assert Path(task.local_pdf_path).name == "0000_01_Test_Report.pdf"
    assert Path(task.local_pdf_path).read_bytes() == pdf_content
    assert not list(Path(task.local_pdf_path).parent.glob("*.part"))
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
    # A 404 is not retried
    assert len(httpx_mock.get_requests()) == 1

    await client.aclose()


@pytest.mark.anyio
@pytest.mark.httpx_mock(assert_all_requests_were_expected=False)
async def test_download_pdf_network_error(httpx_mock, test_raw_dir):
    """Test PDF download with network error, creates failed DocumentTask."""
    # No mock response = network error

    service = ManifestIngestionService(raw_data_dir=str(test_raw_dir))
    service.DOWNLOAD_RETRY_BASE_WAIT = 0
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
    assert task.report_id == "0000_02_Net_Error_CAG"
    assert task.source_url == "https://broken.example.com/report2.pdf"
    assert task.local_pdf_path == ""
    assert task.processing_status == "failed_download"
    assert len(task.error_log) == 1
    assert "Download failed after retries" in task.error_log[0]
    # Transport errors are retried
    assert len(httpx_mock.get_requests()) == 3


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


class TestGovernmentBodyTypeColumn:
    """The VM copies every manifest to manifest.xlsx, so the column must decide the tier."""

    @pytest.mark.parametrize(
        "value,expected",
        [
            ("Union", "union"),
            ("State", "state"),
            ("Local Bodies", "local_body"),
            ("Local Body", "local_body"),
            ("local_body", "local_body"),
            ("State Government", "state"),
            ("Unknown", None),
        ],
    )
    def test_normalize_values(self, value, expected):
        from src.parsing_pipeline.modules.manifest_ingestion_service import normalize_government_body_type

        assert normalize_government_body_type(value) == expected

    def test_local_manifest_named_manifest_xlsx(self, tmp_path):
        path = tmp_path / "manifest.xlsx"
        pd.DataFrame([{
            "SL NO": 1,
            "Date": "2022-10-31",
            "Report_No": "06_2022",
            "Original Title": "Report No.6 of 2022",
            "Recommended Title": "Performance Audit of City Corporations",
            "Government Type": "Local Bodies",
            "State": "Karnataka",
            "State_code": "KA",
            "Report Type": "Performance",
            "Sector": "Urban Local Bodies",
            "Report PDF": "https://example.com/report.pdf",
        }]).to_excel(path, index=False)

        service = ManifestIngestionService(raw_data_dir=str(tmp_path / "raw"))
        df = service.load_manifest(str(path))

        assert service.government_body_type == "local_body"
        assert service.raw_data_dir == tmp_path / "raw" / "local_body"
        assert service._build_report_id(df.iloc[0]).startswith("KA_2022_06_")


# ==================== ATIR detection (A-1-03) ====================


def _local_row(**overrides):
    row = {
        "SL NO": 4,
        "Date": "2022-03-14",
        "Report No": None,
        "Title": (
            "Government of Himachal Pradesh: Annual Technical Inspection Report on Panchayati "
            "Raj Institutions and Urban Local Bodies for the years ended 31 March 2018 and 31 March 2019"
        ),
        "Recommended Title": (
            "ATI report on Panchayati Raj Institution and Urban Local Bodies in Himachal Pradesh "
            "for the years ended 31 March 2018 and 31 March 2019"
        ),
        "State Name": "Himachal Pradesh",
        "State Code": "HP",
        "Report Type": "Compliance Audit",
        "Sector": "Local Bodies",
        "Report PDF": "https://example.com/hp.pdf",
        "_tier": "local_body",
    }
    row.update(overrides)
    return pd.Series(row)


def _make_pdf(path, pages_text):
    import fitz

    doc = fitz.open()
    for text in pages_text:
        page = doc.new_page()
        if text:
            page.insert_text((72, 72), text)
    doc.save(str(path))
    doc.close()
    return path


class TestAtirDetection:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("ATI report on Panchayati Raj Institution", True),
            ("Annual Technical Inspection on Panchayati Raj Institutions", True),
            ("Report of 2018 - ATIR on Local Bodies", True),
            ("Report on Local Government for the year ended March 2022", False),
            ("Performance Audit of City Corporations", False),
        ],
    )
    def test_is_atir_text(self, text, expected):
        from src.parsing_pipeline.modules.manifest_ingestion_service import is_atir_text

        assert is_atir_text(text) is expected

    def test_title_gives_atir_id_category_and_type(self, tmp_path):
        service = ManifestIngestionService(raw_data_dir=str(tmp_path))
        row = _local_row()

        assert service._build_report_id(row) == (
            "HP_ATIR_2022_ATI_report_on_Panchayati_Raj_Institution_and_Urban_Local_Bodies_in_Himachal_Prad"
        )
        metadata = service._build_metadata(row, row["Title"])
        assert metadata["audit_category"] == "atir"
        assert metadata["Report Type"] == "Annual Technical Inspection Report"
        assert metadata["government_body_type"] == "local_body"

    def test_year_from_report_designation(self, tmp_path):
        service = ManifestIngestionService(raw_data_dir=str(tmp_path))
        row = _local_row(
            Date="2019-08-29",
            Title="Report of 2017 - Annual Technical Inspection on Panchayati Raj Institutions",
            **{"Recommended Title": "Annual Technical Inspection on Panchayati Raj Institutions"},
        )
        # "Report of 2017" is the report's own year; Date is the publication year
        assert service._build_report_id(row).startswith("HP_ATIR_2017_")
        assert service._build_report_id(row, atir=False, designation_year=False).startswith("HP_2019_")

    def test_audit_category_column_wins(self, tmp_path):
        service = ManifestIngestionService(raw_data_dir=str(tmp_path))
        row = _local_row(**{"Audit Category": "compliance"})
        assert service._build_metadata(row, row["Title"])["audit_category"] == "compliance"
        assert "_ATIR_" not in service._build_report_id(row)

    def test_union_title_not_treated_as_atir(self, tmp_path):
        service = ManifestIngestionService(raw_data_dir=str(tmp_path))
        row = _local_row(_tier="union", **{"Report No": "5 of 2022"})
        assert service._build_metadata(row, row["Title"])["audit_category"] == "compliance"
        assert service._build_report_id(row).startswith("2022_05_")

    def test_report_type_infers_atir(self):
        from src.parsing_pipeline.modules.manifest_ingestion_service import (
            infer_audit_category_from_report_type,
        )

        assert infer_audit_category_from_report_type("ATIR") == "atir"
        assert infer_audit_category_from_report_type("Compliance Audit") == "compliance"

    @pytest.mark.anyio
    async def test_cover_text_detects_atir(self, tmp_path):
        service = ManifestIngestionService(raw_data_dir=str(tmp_path))
        row = _local_row(
            Title="Report on Local Bodies of Himachal Pradesh",
            **{"Recommended Title": "Local Bodies of Himachal Pradesh"},
        )
        plain_id = service._build_report_id(row)
        assert "_ATIR_" not in plain_id
        raw_dir = tmp_path / "local_body"
        raw_dir.mkdir()
        _make_pdf(raw_dir / f"{plain_id}.pdf", ["", "", "Annual Technical Inspection Report"])

        task = await service._download_pdf(MagicMock(), row)

        assert task.report_id == "HP_ATIR_2022_Local_Bodies_of_Himachal_Pradesh"
        assert task.initial_metadata["audit_category"] == "atir"
        assert task.local_pdf_path == str(raw_dir / f"{plain_id}.pdf")

    @pytest.mark.anyio
    async def test_cover_without_atir_keeps_id(self, tmp_path):
        service = ManifestIngestionService(raw_data_dir=str(tmp_path))
        row = _local_row(
            Title="Report on Local Bodies of Himachal Pradesh",
            **{"Recommended Title": "Local Bodies of Himachal Pradesh"},
        )
        raw_dir = tmp_path / "local_body"
        raw_dir.mkdir()
        plain_id = service._build_report_id(row)
        _make_pdf(raw_dir / f"{plain_id}.pdf", ["Report on Local Government"])

        task = await service._download_pdf(MagicMock(), row)

        assert task.report_id == plain_id
        assert task.initial_metadata["audit_category"] == "compliance"

    @pytest.mark.anyio
    async def test_pdf_saved_under_pre_atir_id_is_found(self, tmp_path):
        service = ManifestIngestionService(raw_data_dir=str(tmp_path))
        row = _local_row()
        raw_dir = tmp_path / "local_body"
        raw_dir.mkdir()
        old = raw_dir / (
            "HP_2022_ATI_report_on_Panchayati_Raj_Institution_and_Urban_Local_Bodies_in_Himachal_Prad.pdf"
        )
        _make_pdf(old, ["cover"])

        task = await service._download_pdf(MagicMock(), row)

        assert task.report_id.startswith("HP_ATIR_2022_")
        assert task.local_pdf_path == str(old)

    @pytest.mark.anyio
    async def test_pdf_named_after_recommended_title_is_found(self, tmp_path):
        service = ManifestIngestionService(raw_data_dir=str(tmp_path))
        row = _local_row()
        raw_dir = tmp_path / "local_body"
        raw_dir.mkdir()
        named = raw_dir / f"{row['Recommended Title']}.pdf"
        _make_pdf(named, ["cover"])

        task = await service._download_pdf(MagicMock(), row)

        assert task.local_pdf_path == str(named)


# ==================== Filter before download (A-1-02) ====================


def _write_local_manifest(path):
    pd.DataFrame([
        {
            "SL NO": 1, "Date": "2022-10-31", "Report_No": "06_2022",
            "Original Title": "Report No.6 of 2022 - Performance Audit",
            "Recommended Title": "Performance Audit of City Corporations",
            "Government Type": "Local Bodies", "State": "Karnataka", "State_code": "KA",
            "Report Type": "Performance", "Sector": "ULB", "Report PDF": "https://example.com/1.pdf",
        },
        {
            "SL NO": 2, "Date": "2022-03-14", "Report_No": None,
            "Original Title": "Annual Technical Inspection Report on PRIs",
            "Recommended Title": "ATI report on PRIs in Himachal Pradesh",
            "Government Type": "Local Bodies", "State": "Himachal Pradesh", "State_code": "HP",
            "Report Type": "Compliance", "Sector": "LB", "Report PDF": "https://example.com/2.pdf",
        },
        {
            "SL NO": 3, "Date": "2024-03-07", "Report_No": "03_2024",
            "Original Title": "Report on Local Government",
            "Recommended Title": "Local Government in Bihar",
            "Government Type": "Local Bodies", "State": "Bihar", "State_code": "BR",
            "Report Type": "Compliance", "Sector": "LB", "Report PDF": "https://example.com/3.pdf",
        },
    ]).to_excel(path, index=False)
    return path


class TestReportFilterBeforeDownload:
    @pytest.mark.anyio
    async def test_only_matching_rows_are_resolved(self, tmp_path):
        manifest = _write_local_manifest(tmp_path / "manifest.xlsx")
        service = ManifestIngestionService(raw_data_dir=str(tmp_path / "raw"))
        seen = []

        async def fake_download(client, row):
            seen.append(row["SL NO"])
            return DocumentTask(
                report_id=service._build_report_id(row), source_url="",
                local_pdf_path="x.pdf", initial_metadata={},
            )

        service._download_pdf = fake_download
        tasks = await service.process_manifest(
            str(manifest), report_filter=["HP_ATIR_2022_ATI_report_on_PRIs_in_Himachal_Pradesh"]
        )

        assert seen == [2]
        assert [t.report_id for t in tasks] == ["HP_ATIR_2022_ATI_report_on_PRIs_in_Himachal_Pradesh"]

    @pytest.mark.anyio
    async def test_filter_keeps_rows_the_cover_check_could_rename(self, tmp_path):
        manifest = _write_local_manifest(tmp_path / "manifest.xlsx")
        service = ManifestIngestionService(raw_data_dir=str(tmp_path / "raw"))
        seen = []

        async def fake_download(client, row):
            seen.append(row["SL NO"])
            return DocumentTask(report_id="x", source_url="", local_pdf_path="", initial_metadata={})

        service._download_pdf = fake_download
        await service.process_manifest(
            str(manifest), report_filter=["BR_ATIR_2024_Local_Government_in_Bihar"]
        )
        assert seen == [3]

    @pytest.mark.anyio
    async def test_no_filter_keeps_manifest_order(self, tmp_path):
        manifest = _write_local_manifest(tmp_path / "manifest.xlsx")
        service = ManifestIngestionService(raw_data_dir=str(tmp_path / "raw"))

        async def fake_download(client, row):
            return DocumentTask(
                report_id=str(row["SL NO"]), source_url="", local_pdf_path="", initial_metadata={}
            )

        service._download_pdf = fake_download
        tasks = await service.process_manifest(str(manifest))
        assert [t.report_id for t in tasks] == ["1", "2", "3"]


# ==================== Tier from all rows (A-1-05) ====================


class TestTierFromAllRows:
    def test_mixed_tiers_warn_and_stay_per_row(self, tmp_path, caplog):
        import logging

        path = tmp_path / "manifest.xlsx"
        base = {
            "Date": "2025-01-01", "Report_No": "01_2025", "Report Type": "Compliance",
            "Sector": "X", "State": "Odisha", "State_code": "OD", "Report PDF": "https://e.com/a.pdf",
        }
        pd.DataFrame([
            {**base, "SL NO": 1, "Original Title": "A", "Recommended Title": "State One", "Government Type": "State"},
            {**base, "SL NO": 2, "Original Title": "B", "Recommended Title": "Local One", "Government Type": "Local Bodies"},
            {**base, "SL NO": 3, "Original Title": "C", "Recommended Title": "Local Two", "Government Type": "Local Bodies"},
            {**base, "SL NO": 4, "Original Title": "D", "Recommended Title": "No Tier", "Government Type": None},
        ]).to_excel(path, index=False)

        service = ManifestIngestionService(raw_data_dir=str(tmp_path / "raw"))
        with caplog.at_level(logging.WARNING):
            df = service.load_manifest(str(path))

        assert "mixes tiers" in caplog.text
        # Most common tier wins for the manifest; each row keeps its own
        assert service.government_body_type == "local_body"
        assert list(df["_tier"]) == ["state", "local_body", "local_body", "local_body"]
        assert service._build_metadata(df.iloc[0], "A")["government_body_type"] == "state"
        # tier_source says where each row's tier came from (main.py traces it)
        sources = [service._build_metadata(r, "x")["tier_source"] for _, r in df.iterrows()]
        assert sources == ["Government Type column"] * 3 + ["majority of manifest rows"]

    @pytest.mark.parametrize(
        "filename,expected",
        [("Local_Examples.xlsx", "manifest filename"), ("manifest.xlsx", "default")],
    )
    def test_tier_source_without_column(self, tmp_path, filename, expected):
        path = tmp_path / filename
        pd.DataFrame([{"SL NO": 1, "Original Title": "A", "Report PDF": "u"}]).to_excel(path, index=False)
        service = ManifestIngestionService(raw_data_dir=str(tmp_path / "raw"))
        df = service.load_manifest(str(path))
        assert service._build_metadata(df.iloc[0], "A")["tier_source"] == expected

    def test_single_tier_manifest_unchanged(self, tmp_path):
        path = _write_local_manifest(tmp_path / "manifest.xlsx")
        service = ManifestIngestionService(raw_data_dir=str(tmp_path / "raw"))
        df = service.load_manifest(str(path))
        assert service.government_body_type == "local_body"
        assert set(df["_tier"]) == {"local_body"}


# ==================== Download robustness (A-1-06) ====================


@pytest.mark.anyio
async def test_download_retries_server_error(httpx_mock, tmp_path):
    import httpx

    url = "https://example.com/flaky.pdf"
    httpx_mock.add_response(method="GET", url=url, status_code=503)
    httpx_mock.add_response(method="GET", url=url, status_code=200, content=b"%PDF-1.4 data")
    service = ManifestIngestionService(raw_data_dir=str(tmp_path))
    service.DOWNLOAD_RETRY_BASE_WAIT = 0
    target = tmp_path / "flaky.pdf"

    async with httpx.AsyncClient() as client:
        await service._fetch_pdf(client, url, target)

    assert target.read_bytes() == b"%PDF-1.4 data"
    assert not (tmp_path / "flaky.pdf.part").exists()


@pytest.mark.anyio
async def test_failed_download_leaves_no_file(httpx_mock, tmp_path):
    import httpx

    url = "https://example.com/missing.pdf"
    httpx_mock.add_response(method="GET", url=url, status_code=404)
    service = ManifestIngestionService(raw_data_dir=str(tmp_path))
    target = tmp_path / "missing.pdf"

    async with httpx.AsyncClient() as client:
        with pytest.raises(httpx.HTTPStatusError):
            await service._fetch_pdf(client, url, target)

    assert not target.exists()
    assert not (tmp_path / "missing.pdf.part").exists()


def test_clean_report_no_formats(tmp_path):
    service = ManifestIngestionService(raw_data_dir=str(tmp_path))
    df = service._clean_metadata(pd.DataFrame({"Report No": ["Report No. 15 of 2025", "2025/7", "Report of 2017"]}))
    assert list(df["Report No"]) == ["Report No. 15 of 2025", "7 of 2025", "Report of 2017"]
