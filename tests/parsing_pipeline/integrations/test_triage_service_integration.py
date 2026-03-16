import pytest
from pathlib import Path
from services.parsing_pipeline.src.modules.triage_service import TriageService
from services.parsing_pipeline.src.modules.data_contracts import DocumentTask


@pytest.fixture
def triage_service():
    """TriageService fixture with conservative settings for testing."""
    return TriageService(sample_pages=10, text_threshold=150)


def test_triage_real_pdf_solar_parks(triage_service):
    """Integration test with actual CAG-Union Audit Reports.xlsx PDF file."""
    pdf_path = Path(
        "data/raw/report_004_solar_parks_and_ultra_mega_solar_power_projects_a.pdf"
    )

    # Check if the file exists (some PDFs might not be available)
    if not pdf_path.exists():
        pytest.skip(f"Test PDF not found: {pdf_path}")

    task = DocumentTask(
        report_id="report_004_solar_parks",
        source_url="https://example.com/solar.pdf",
        local_pdf_path=str(pdf_path),
        initial_metadata={"Title": "Solar Parks Report"},
    )

    result = triage_service.triage_document(task)

    # For CAG audit reports, we expect native text (OCR was already applied if needed)
    assert result.classification in ["native_text", "scanned"]
    assert result.processing_status in ["triaged_native", "triaged_scanned"]
    assert len(result.error_log) == 0


def test_triage_real_pdf_cleanliness(triage_service):
    """Integration test with actual CAG-Union Audit Reports.xlsx PDF file."""
    pdf_path = Path(
        "data/raw/report_001_cag_report_on_cleanliness_and_sanitation_in_indian.pdf"
    )

    if not pdf_path.exists():
        pytest.skip(f"Test PDF not found: {pdf_path}")

    task = DocumentTask(
        report_id="report_001_cleanliness",
        source_url="https://example.com/cleanliness.pdf",
        local_pdf_path=str(pdf_path),
        initial_metadata={"Title": "Cleanliness Report"},
    )

    result = triage_service.triage_document(task)

    # Verify the result structure
    assert result.classification in ["native_text", "scanned"]
    assert result.processing_status in ["triaged_native", "triaged_scanned"]
    assert len(result.error_log) == 0
    assert result.report_id == "report_001_cleanliness"


@pytest.mark.parametrize(
    "pdf_filename",
    [
        "report_001_cag_report_on_cleanliness_and_sanitation_in_indian.pdf",
        "report_002_direct_taxes_audit_report_union_government_revenu.pdf",
        "report_003_cag_report_on_fiscal_responsibility_and_budget_man.pdf",
        "report_004_solar_parks_and_ultra_mega_solar_power_projects_a.pdf",
        "report_005_cag_report_on_indian_national_centre_for_ocean_inf.pdf",
    ],
)
def test_triage_all_pilot_pdfs(triage_service, pdf_filename):
    """Integration test with all 5 pilot PDFs from the manifest."""
    pdf_path = Path(f"data/raw/{pdf_filename}")

    if not pdf_path.exists():
        pytest.skip(f"Pilot PDF not found: {pdf_path}")

    # Extract report ID from filename
    report_id = pdf_filename.split(".")[0]

    task = DocumentTask(
        report_id=report_id,
        source_url=f"https://example.com/{report_id}.pdf",
        local_pdf_path=str(pdf_path),
        initial_metadata={"Title": f"Pilot Report {report_id}"},
    )

    result = triage_service.triage_document(task)

    # All results should be valid (either native or scanned)
    assert result.classification in ["native_text", "scanned"]
    assert result.processing_status in ["triaged_native", "triaged_scanned"]
    assert len(result.error_log) == 0
    assert result.report_id == report_id


def test_triage_service_consistency(triage_service):
    """Test that triage is consistent across multiple runs on same file."""
    pdf_path = Path(
        "data/raw/report_001_cag_report_on_cleanliness_and_sanitation_in_indian.pdf"
    )

    if not pdf_path.exists():
        pytest.skip("Test PDF not found")

    task1 = DocumentTask(
        report_id="test_consistency_1",
        source_url="https://example.com/test.pdf",
        local_pdf_path=str(pdf_path),
        initial_metadata={},
    )

    task2 = DocumentTask(
        report_id="test_consistency_2",
        source_url="https://example.com/test.pdf",
        local_pdf_path=str(pdf_path),
        initial_metadata={},
    )

    result1 = triage_service.triage_document(task1)
    result2 = triage_service.triage_document(task2)

    # Both should classify the same way
    assert result1.classification == result2.classification
    assert result1.processing_status == result2.processing_status
    assert len(result1.error_log) == len(result2.error_log) == 0


def test_triage_error_handling_corrupted():
    """Test error handling with a potentially corrupted PDF path."""
    service = TriageService()

    # Use a text file as PDF to simulate corruption
    text_file_path = Path("README.md")

    if not text_file_path.exists():
        pytest.skip("README.md not found for corruption test")

    task = DocumentTask(
        report_id="test_corrupted",
        source_url="https://example.com/test.pdf",
        local_pdf_path=str(text_file_path),  # Wrong file type, should fail
        initial_metadata={},
    )

    result = service.triage_document(task)

    # Should fail gracefully without crashing
    assert result.classification is None
    assert result.processing_status == "failed_triage"
    assert len(result.error_log) == 1
    assert "Triage failed with error" in result.error_log[0]
