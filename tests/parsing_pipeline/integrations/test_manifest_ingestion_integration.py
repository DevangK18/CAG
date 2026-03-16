import pytest
import pandas as pd
import tempfile
import os
from ..src.modules.manifest_ingestion_service import ManifestIngestionService
from ..src.modules.data_contracts import DocumentTask


@pytest.mark.anyio
async def test_process_manifest_integration(httpx_mock, test_raw_dir):
    """Integration test for process_manifest with mocked downloads."""
    # Mock multiple HTTP responses
    for i in range(1, 4):
        httpx_mock.add_response(
            method="GET",
            url=f"https://example.com/report{i}.pdf",
            status_code=200,
            content=f"PDF {i} content".encode(),
        )

    # Sample manifest data
    manifest_df = """
SL NO,Date,Original Title,Recommended Title,Government Type,Union Department,Report Type,Sector,Report PDF
1,2025-08-20,Original Report 1,CAG Report 1,Union,Railways,Performance,Transport,https://example.com/report1.pdf
2,2025-08-18,Original Report 2,,Union,Civil,Compliance,Finance,https://example.com/report2.pdf
3,2025-08-12,Original Report 3,CAG Report 3,Union,Scientific,Performance,Science,https://example.com/report3.pdf
"""

    # Create temp Excel file
    import tempfile
    import pandas as pd
    from pathlib import Path

    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        # Write data starting row 2 (header at 1-based row 2)
        with pd.ExcelWriter(tmp.name, engine="openpyxl") as writer:
            data_lines = [line.split(",") for line in manifest_df.strip().split("\n")]
            headers = data_lines[0]
            data = data_lines[1:]
            df = pd.DataFrame(data, columns=headers)
            df.to_excel(writer, index=False, startrow=1)
        tmp_path = Path(tmp.name)

    try:
        service = ManifestIngestionService(raw_data_dir=str(test_raw_dir))
        tasks = await service.process_manifest(str(tmp_path))

        # Verify results
        assert len(tasks) == 3
        assert all(isinstance(task, DocumentTask) for task in tasks)

        # Check reports
        ids = [task.report_id for task in tasks]
        assert "report_001_cag_report_1" in ids  # Recommended title preferred
        assert "report_002_original_report_2" in ids  # Fallback to original
        assert "report_003_cag_report_3" in ids

        # Check all successful
        assert all(task.processing_status == "pending" for task in tasks)

        # Check metadata types
        task = next(t for t in tasks if t.report_id == "report_001_cag_report_1")
        metadata = task.initial_metadata
        assert isinstance(metadata["SL NO"], (int, float))  # Accept either int or float
        assert isinstance(metadata["Date"], str)  # JSON serializes to str
        assert isinstance(metadata["Title"], str)
        assert isinstance(metadata["Report PDF"], str)

    finally:
        tmp_path.unlink(missing_ok=True)


@pytest.mark.anyio
async def test_process_manifest_partial_failure(httpx_mock, test_raw_dir):
    """Integration test with some downloads failing."""
    # Mock responses: 2 success, 1 failure
    httpx_mock.add_response(
        method="GET",
        url="https://example.com/report1.pdf",
        status_code=200,
        content=b"PDF1",
    )
    httpx_mock.add_response(
        method="GET", url="https://example.com/report2.pdf", status_code=404
    )
    httpx_mock.add_response(
        method="GET",
        url="https://example.com/report3.pdf",
        status_code=200,
        content=b"PDF3",
    )

    # Create mini manifest in temp file
    manifest_data = """SL NO,Title,Report PDF
1,Report 1,https://example.com/report1.pdf
2,Report 2,https://example.com/report2.pdf
3,Report 3,https://example.com/report3.pdf"""

    import pandas as pd
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        df = pd.DataFrame([line.split(",") for line in manifest_data.split("\n")])
        df.to_excel(tmp.name, index=False, header=False, startrow=1)
        tmp_path = tmp.name

    service = ManifestIngestionService(raw_data_dir=str(test_raw_dir))
    tasks = await service.process_manifest(tmp_path)

    # Verify 2 success, 1 failed
    successful = [t for t in tasks if t.processing_status == "pending"]
    failed = [t for t in tasks if t.processing_status == "failed_download"]
    assert len(successful) == 2
    assert len(failed) == 1

    # Clean up
    import os

    os.unlink(tmp_path)


@pytest.mark.anyio
async def test_process_manifest_real_excel_mock_http(httpx_mock, test_raw_dir):
    """E2E-like test using real Excel structure but mocked HTTP."""
    # Mock 5 responses for the 5 reports in CAG-Union Audit Reports.xlsx
    for i in range(1, 6):
        if i <= 3:  # Assume first 3 have real-like URLs
            url = f"https://cag.gov.in/webroot/uploads/download_audit_report/2025/report{i}.pdf"
        else:
            url = f"https://example.com/report{i}.pdf"  # Fallback
        httpx_mock.add_response(
            method="GET", url=url, status_code=200, content=b"Mock PDF content"
        )

    # Use the actual test Excel file path if exists, else create
    import pathlib

    excel_path = pathlib.Path("CAG-Union Audit Reports.xlsx")
    if not excel_path.exists():
        # Create test version
        df = pd.DataFrame(
            {
                "SL NO": [1.0, 2.0, 3.0],
                "Title": ["Test Report 1", "Test Report 2", "Test Report 3"],
                "Report PDF": [
                    "https://example.com/report1.pdf",
                    "https://example.com/report2.pdf",
                    "https://example.com/report3.pdf",
                ],
            }
        )
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
            df.to_excel(tmp.name, index=False, startrow=1)
            excel_path = tmp.name

    service = ManifestIngestionService(raw_data_dir=str(test_raw_dir))
    tasks = await service.process_manifest(str(excel_path))

    # Verify based on how many rows processed
    assert all(isinstance(task, DocumentTask) for task in tasks)
    assert all(task.processing_status == "pending" for task in tasks)

    # Clean up if temp
    if "tmp" in str(excel_path):
        os.unlink(excel_path)
