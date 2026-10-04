"""
Integration tests for ManifestIngestionService.process_manifest: Excel manifest
in, DocumentTasks and PDFs on disk out.

Downloads go through pytest-httpx, so nothing reaches cag.gov.in. The real
manifests are read from CAG_TEST_MANIFEST_DIR, or data/manifests/ under the
repo root; neither is in git, so that test is skipped when they are absent.
"""

import asyncio
import os
import re
from pathlib import Path

import fitz
import httpx
import pandas as pd
import pytest

from src.core.data_contracts import DocumentTask
from src.parsing_pipeline.modules.manifest_ingestion_service import ManifestIngestionService

REPO_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_DIR = Path(os.getenv("CAG_TEST_MANIFEST_DIR") or REPO_ROOT / "data" / "manifests")
REAL_MANIFESTS = sorted(MANIFEST_DIR.glob("*.xlsx")) if MANIFEST_DIR.is_dir() else []

# Union, State/Local and ATIR report ID shapes (_validate_report_id_format)
REPORT_ID_PATTERN = re.compile(
    r"^(\d{4}_\d{2}_|[A-Z]{2}_\d{4}_(\d{2}_)?|[A-Z]{2}_ATIR_\d{4}_|\d+_of_\d{4}_).+$"
)


def _pdf_bytes(*pages_text: str) -> bytes:
    doc = fitz.open()
    for text in pages_text:
        page = doc.new_page()
        if text:
            page.insert_text((72, 72), text)
    data = doc.tobytes()
    doc.close()
    return data


def _write_manifest(path: Path, rows, title_row: bool = True) -> Path:
    """CAG manifests carry a title row above the headers; title_row=False puts headers in row 1."""
    pd.DataFrame(rows).to_excel(path, index=False, startrow=1 if title_row else 0)
    return path


UNION_ROWS = [
    {
        "SL NO": 1, "Date": "2025-08-20", "Report_No": "2025/15",
        "Original Title": "Original Report 1", "Recommended Title": "CAG Report 1",
        "Government Type": "Union", "Union Department": "Railways",
        "Report Type": "Performance", "Sector": "Transport",
        "Report PDF": "https://example.com/report1.pdf",
    },
    {
        "SL NO": 2, "Date": "2025-08-18", "Report_No": None,
        "Original Title": "Original Report 2", "Recommended Title": None,
        "Government Type": "Union", "Union Department": "Civil",
        "Report Type": "Compliance", "Sector": "Finance",
        "Report PDF": "https://example.com/report2.pdf",
    },
    {
        "SL NO": 3, "Date": "2025-08-12", "Report_No": "2025/3",
        "Original Title": "Original Report 3", "Recommended Title": "CAG Report 3",
        "Government Type": "Union", "Union Department": "Science",
        "Report Type": "Performance", "Sector": "Science",
        "Report PDF": "https://example.com/report3.pdf",
    },
]

LOCAL_ROWS = [
    {
        "SL NO": 1, "Date": "2022-10-31", "Report_No": "06_2022",
        "Original Title": "Report No.6 of 2022 - Performance Audit",
        "Recommended Title": "Performance Audit of City Corporations",
        "Government Type": "Local Bodies", "State": "Karnataka", "State_code": "KA",
        "Report Type": "Performance", "Sector": "ULB", "Report PDF": "https://example.com/ka.pdf",
    },
    {
        "SL NO": 2, "Date": "2022-03-14", "Report_No": None,
        "Original Title": "Annual Technical Inspection Report on PRIs",
        "Recommended Title": "ATI report on PRIs in Himachal Pradesh",
        "Government Type": "Local Bodies", "State": "Himachal Pradesh", "State_code": "HP",
        "Report Type": "Compliance", "Sector": "LB", "Report PDF": "https://example.com/hp.pdf",
    },
    {
        "SL NO": 3, "Date": "2024-03-07", "Report_No": "03_2024",
        "Original Title": "Report on Local Government",
        "Recommended Title": "Local Government in Bihar",
        "Government Type": "Local Bodies", "State": "Bihar", "State_code": "BR",
        "Report Type": "Compliance", "Sector": "LB", "Report PDF": "https://example.com/br.pdf",
    },
]

KA_ID = "KA_2022_06_Performance_Audit_of_City_Corporations"
HP_ID = "HP_ATIR_2022_ATI_report_on_PRIs_in_Himachal_Pradesh"
BR_PLAIN_ID = "BR_2024_03_Local_Government_in_Bihar"
BR_ATIR_ID = "BR_ATIR_2024_Local_Government_in_Bihar"


def _mock_local_downloads(httpx_mock):
    httpx_mock.add_response(url="https://example.com/ka.pdf", content=_pdf_bytes("Performance Audit"))
    httpx_mock.add_response(url="https://example.com/hp.pdf", content=_pdf_bytes("ATI report"))
    # Nothing in the title says ATIR; the cover does
    httpx_mock.add_response(
        url="https://example.com/br.pdf",
        content=_pdf_bytes("", "", "Annual Technical Inspection Report on Local Bodies"),
    )


def _service(tmp_path) -> ManifestIngestionService:
    service = ManifestIngestionService(raw_data_dir=str(tmp_path / "raw"))
    service.DOWNLOAD_RETRY_BASE_WAIT = 0
    return service


@pytest.mark.anyio
async def test_union_manifest_downloads_and_builds_tasks(httpx_mock, tmp_path):
    for i in range(1, 4):
        httpx_mock.add_response(
            url=f"https://example.com/report{i}.pdf", content=f"PDF {i} content".encode()
        )
    manifest = _write_manifest(tmp_path / "CAG_Union_Reports.xlsx", UNION_ROWS)

    service = _service(tmp_path)
    tasks = await service.process_manifest(str(manifest))

    assert all(isinstance(t, DocumentTask) for t in tasks)
    assert [t.report_id for t in tasks] == [
        "2025_15_CAG_Report_1",
        "2025_02_Original_Report_2",  # no Report No: year from Date, serial from SL NO, original title
        "2025_03_CAG_Report_3",
    ]
    assert all(t.processing_status == "pending" for t in tasks)

    raw_dir = tmp_path / "raw" / "union"
    for i, task in enumerate(tasks, start=1):
        assert Path(task.local_pdf_path) == raw_dir / f"{task.report_id}.pdf"
        assert Path(task.local_pdf_path).read_bytes() == f"PDF {i} content".encode()
    assert not list(raw_dir.glob("*.part"))

    metadata = tasks[0].initial_metadata
    assert metadata["Title"] == "Original Report 1"
    assert metadata["Report No"] == "15 of 2025"
    assert metadata["Ministry"] == "Ministry of Railways"
    assert metadata["Report Type"] == "Performance Audit"
    assert metadata["Date"] == "2025-08-20"
    assert metadata["government_body_type"] == "union"
    assert metadata["tier_source"] == "Government Type column"
    assert metadata["audit_category"] == "performance"
    assert metadata["state_name"] is None
    assert tasks[1].initial_metadata["Report No"] is None


@pytest.mark.anyio
async def test_failed_download_does_not_stop_the_others(httpx_mock, tmp_path):
    httpx_mock.add_response(url="https://example.com/report1.pdf", content=b"PDF1")
    httpx_mock.add_response(url="https://example.com/report2.pdf", status_code=404)
    httpx_mock.add_response(url="https://example.com/report3.pdf", content=b"PDF3")
    # Headers in row 1: the loader falls back from the title-row layout
    manifest = _write_manifest(tmp_path / "CAG_Union_Reports.xlsx", UNION_ROWS, title_row=False)

    tasks = await _service(tmp_path).process_manifest(str(manifest))

    assert [t.processing_status for t in tasks] == ["pending", "failed_download", "pending"]
    failed = tasks[1]
    assert failed.local_pdf_path == ""
    assert "Download failed after retries" in failed.error_log[-1]
    raw_dir = tmp_path / "raw" / "union"
    assert sorted(p.name for p in raw_dir.iterdir()) == [
        "2025_03_CAG_Report_3.pdf", "2025_15_CAG_Report_1.pdf",
    ]
    # A 404 is not retried
    assert len(httpx_mock.get_requests(url="https://example.com/report2.pdf")) == 1


@pytest.mark.anyio
async def test_local_body_manifest_tiers_and_atir_detection(httpx_mock, tmp_path):
    _mock_local_downloads(httpx_mock)
    # The VM copies every manifest to manifest.xlsx: the tier comes from the rows
    manifest = _write_manifest(tmp_path / "manifest.xlsx", LOCAL_ROWS)

    service = _service(tmp_path)
    tasks = await service.process_manifest(str(manifest))

    assert service.government_body_type == "local_body"
    assert [t.report_id for t in tasks] == [KA_ID, HP_ID, BR_ATIR_ID]
    raw_dir = tmp_path / "raw" / "local_body"
    for task in tasks:
        assert Path(task.local_pdf_path).parent == raw_dir
        assert task.initial_metadata["government_body_type"] == "local_body"

    ka, hp, br = (t.initial_metadata for t in tasks)
    assert ka["state_name"] == "Karnataka"
    assert ka["audit_category"] == "performance"
    # ATIR from the title
    assert hp["audit_category"] == "atir"
    assert hp["Report Type"] == "Annual Technical Inspection Report"
    # ATIR from the cover text; the PDF keeps the name it was downloaded under
    assert br["audit_category"] == "atir"
    assert tasks[2].local_pdf_path == str(raw_dir / f"{BR_PLAIN_ID}.pdf")


@pytest.mark.anyio
async def test_second_run_reuses_pdfs_on_disk(httpx_mock, tmp_path):
    _mock_local_downloads(httpx_mock)
    manifest = _write_manifest(tmp_path / "manifest.xlsx", LOCAL_ROWS)
    first = await _service(tmp_path).process_manifest(str(manifest))
    requests_after_first = len(httpx_mock.get_requests())

    # No responses left: any download attempt would fail the test
    second = await _service(tmp_path).process_manifest(str(manifest))

    assert len(httpx_mock.get_requests()) == requests_after_first == 3
    assert [(t.report_id, t.local_pdf_path) for t in second] == [
        (t.report_id, t.local_pdf_path) for t in first
    ]
    assert all(t.processing_status == "pending" for t in second)


@pytest.mark.anyio
async def test_report_filter_downloads_only_the_selected_rows(httpx_mock, tmp_path):
    httpx_mock.add_response(url="https://example.com/hp.pdf", content=_pdf_bytes("ATI report"))
    manifest = _write_manifest(tmp_path / "manifest.xlsx", LOCAL_ROWS)

    tasks = await _service(tmp_path).process_manifest(str(manifest), report_filter=[HP_ID])

    assert [t.report_id for t in tasks] == [HP_ID]
    assert [str(r.url) for r in httpx_mock.get_requests()] == ["https://example.com/hp.pdf"]
    assert not (tmp_path / "raw" / "local_body" / f"{KA_ID}.pdf").exists()


@pytest.mark.anyio
async def test_downloads_run_concurrently_up_to_the_limit(httpx_mock, tmp_path):
    in_flight = 0
    peak = 0

    async def slow_pdf(request):
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0.05)
        in_flight -= 1
        return httpx.Response(200, content=b"%PDF-1.4 " + request.url.path.encode())

    rows = [
        {**UNION_ROWS[0], "SL NO": i, "Report_No": f"2025/{i}", "Recommended Title": f"Report {i}",
         "Report PDF": f"https://example.com/r{i}.pdf"}
        for i in range(1, 6)
    ]
    httpx_mock.add_callback(slow_pdf, is_reusable=True)
    manifest = _write_manifest(tmp_path / "CAG_Union_Reports.xlsx", rows)
    service = _service(tmp_path)
    service.MAX_CONCURRENT_DOWNLOADS = 2

    tasks = await service.process_manifest(str(manifest))

    assert peak == 2
    # Results stay in manifest order whatever order the downloads finish in
    assert [t.report_id for t in tasks] == [f"2025_{i:02d}_Report_{i}" for i in range(1, 6)]
    assert all(t.processing_status == "pending" for t in tasks)


class _DroppedConnection(httpx.AsyncByteStream):
    """Sends part of the body, then the connection drops."""

    async def __aiter__(self):
        yield b"%PDF-1.4 first half of the file"
        raise httpx.ReadError("connection reset by peer")


@pytest.mark.anyio
async def test_interrupted_download_is_not_taken_for_a_pdf_next_run(httpx_mock, tmp_path):
    url = "https://example.com/report1.pdf"
    for _ in range(ManifestIngestionService.DOWNLOAD_ATTEMPTS):
        httpx_mock.add_callback(lambda request: httpx.Response(200, stream=_DroppedConnection()), url=url)
    manifest = _write_manifest(tmp_path / "CAG_Union_Reports.xlsx", UNION_ROWS[:1])

    [task] = await _service(tmp_path).process_manifest(str(manifest))

    assert task.processing_status == "failed_download"
    raw_dir = tmp_path / "raw" / "union"
    assert list(raw_dir.iterdir()) == []  # neither the partial PDF nor its .part file

    # The next run downloads it again instead of resolving a truncated file
    httpx_mock.add_response(url=url, content=b"%PDF-1.4 the whole file")
    [task] = await _service(tmp_path).process_manifest(str(manifest))

    assert task.processing_status == "pending"
    assert Path(task.local_pdf_path).read_bytes() == b"%PDF-1.4 the whole file"


@pytest.mark.skipif(
    not REAL_MANIFESTS, reason=f"no manifests under {MANIFEST_DIR} (set CAG_TEST_MANIFEST_DIR)"
)
@pytest.mark.parametrize("manifest_path", REAL_MANIFESTS, ids=lambda p: p.stem[:30])
def test_real_manifest_gives_unique_valid_report_ids(manifest_path, tmp_path):
    service = ManifestIngestionService(raw_data_dir=str(tmp_path / "raw"))
    df = service.load_manifest(str(manifest_path))

    assert len(df) > 0
    ids = [service._build_report_id(row) for _, row in df.iterrows()]
    assert len(set(ids)) == len(ids)
    bad = [i for i in ids if not REPORT_ID_PATTERN.match(i)]
    assert not bad
    for _, row in df.iterrows():
        metadata = service._build_metadata(row, row["Title"])
        assert metadata["government_body_type"] in ("union", "state", "local_body")
        if metadata["government_body_type"] != "union":
            assert metadata["state_name"]
