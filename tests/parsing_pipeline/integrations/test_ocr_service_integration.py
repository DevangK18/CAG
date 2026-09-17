import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
from ..src.modules.ocr_service import OCRService
from ..src.modules.data_contracts import DocumentTask


@pytest.fixture
def ocr_service(tmp_path):
    """OCRService fixture with temporary output directory."""
    output_dir = tmp_path / "processed" / "ocred"
    return OCRService(output_dir=str(output_dir))


@pytest.fixture
def sample_scanned_task(tmp_path):
    """Create a sample DocumentTask representing a scanned document with temp file."""
    pdf_file = tmp_path / "scanned_report.pdf"
    pdf_file.write_bytes(b"%PDF-1.4\nfake scanned pdf content")  # Mock PDF content

    return DocumentTask(
        report_id="report_001_scanned_test",
        source_url="https://cag.gov.in/scanned-report.pdf",
        local_pdf_path=str(pdf_file),
        initial_metadata={
            "Title": "Scanned CAG Report",
            "Government Type": "Union",
            "Union Department": "Railways",
        },
        classification="scanned",
    )


@pytest.fixture
def sample_native_task(tmp_path):
    """Create a sample DocumentTask representing a native text document."""
    pdf_file = tmp_path / "native_report.pdf"
    pdf_file.write_bytes(b"%PDF-1.4\nfake native pdf content")  # Mock PDF content

    return DocumentTask(
        report_id="report_002_native_test",
        source_url="https://cag.gov.in/native-report.pdf",
        local_pdf_path=str(pdf_file),
        initial_metadata={
            "Title": "Native CAG Report",
            "Government Type": "Union",
            "Union Department": "Finance",
        },
        classification="native_text",
    )


@pytest.mark.integration
def test_ocr_service_full_pipeline_native_skip(ocr_service, sample_native_task):
    """Integration test: Native documents should be skipped completely."""
    original_task = sample_native_task.model_copy()

    result = ocr_service.ocr_document(sample_native_task)

    # Task should be unchanged except for error logs
    assert result.report_id == original_task.report_id
    assert result.source_url == original_task.source_url
    assert result.local_pdf_path == original_task.local_pdf_path
    assert result.initial_metadata == original_task.initial_metadata
    assert result.classification == "native_text"
    assert result.ocred_pdf_path is None
    assert "scanned" in result.error_log[0] and "skipping" in result.error_log[0]


@patch(
    "services.parsing_pipeline.src.modules.ocr_service.OCRService._execute_ocr_command"
)
def test_ocr_service_integration_success(
    mock_execute_command, ocr_service, sample_scanned_task, tmp_path
):
    """Integration test: Successful OCR processing with file creation."""
    # Mock successful OCR command execution
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stderr = b""
    mock_execute_command.return_value = mock_result

    # Execute OCR
    result = ocr_service.ocr_document(sample_scanned_task)

    # Verify task status
    assert result.processing_status == "ocr_complete"
    assert result.ocred_pdf_path is not None

    # Verify output file path and naming
    ocred_file = Path(result.ocred_pdf_path)
    assert ocred_file.parent == ocr_service.output_dir
    assert ocred_file.name == f"{sample_scanned_task.report_id}_ocred.pdf"

    # Verify logs contain success messages
    error_logs = [log for log in result.error_log if not log.startswith("Document not")]
    assert any("OCR processing completed successfully" in log for log in error_logs)

    # Verify command was called with correct arguments
    expected_command = ocr_service._construct_ocr_command(
        sample_scanned_task.local_pdf_path, result.ocred_pdf_path
    )
    mock_execute_command.assert_called_once_with(expected_command)


@patch(
    "services.parsing_pipeline.src.modules.ocr_service.OCRService._execute_ocr_command"
)
def test_ocr_service_integration_ocr_failure(
    mock_execute_command, ocr_service, sample_scanned_task
):
    """Integration test: OCR command failure handling."""
    # Mock failed OCR command execution
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stderr = b"OCRmyPDF Error: Invalid input file format"
    mock_execute_command.return_value = mock_result

    # Execute OCR
    result = ocr_service.ocr_document(sample_scanned_task)

    # Verify task status
    assert result.processing_status == "failed_ocr"
    assert result.ocred_pdf_path is None

    # Verify error logging
    assert any(
        "OCR command failed with return code 1" in log for log in result.error_log
    )
    assert any(
        "OCRmyPDF Error: Invalid input file format" in log for log in result.error_log
    )


@pytest.mark.integration
def test_ocr_service_integration_missing_file(ocr_service, sample_scanned_task):
    """Integration test: Handling missing input PDF file."""
    # Delete the temp file to simulate missing file
    Path(sample_scanned_task.local_pdf_path).unlink()

    result = ocr_service.ocr_document(sample_scanned_task)

    assert result.processing_status == "failed_ocr"
    assert result.ocred_pdf_path is None
    assert any("PDF path does not exist" in log for log in result.error_log)


@patch(
    "services.parsing_pipeline.src.modules.ocr_service.OCRService._execute_ocr_command"
)
@patch(
    "services.parsing_pipeline.src.modules.ocr_service.OCRService._validate_ocr_output"
)
def test_ocr_service_integration_validation_warning(
    mock_validate_output, mock_execute_command, ocr_service, sample_scanned_task
):
    """Integration test: Successful OCR but validation warning."""
    # Mock successful command execution
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stderr = b""
    mock_execute_command.return_value = mock_result

    # Mock validation failure
    mock_validate_output.return_value = False

    result = ocr_service.ocr_document(sample_scanned_task)

    # Task should still be marked complete, but with validation warning
    assert result.processing_status == "ocr_complete"
    assert result.ocred_pdf_path is not None
    assert any("OCR output validation failed" in log for log in result.error_log)


@patch(
    "services.parsing_pipeline.src.modules.ocr_service.OCRService._validate_ocr_output"
)
@patch(
    "services.parsing_pipeline.src.modules.ocr_service.OCRService._execute_ocr_command"
)
def test_ocr_service_integration_multiple_documents(
    mock_execute_command, mock_validate_output, ocr_service, tmp_path
):
    """Integration test: Processing multiple scanned documents."""
    # Mock OCR execution to succeed
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stderr = b""
    mock_execute_command.return_value = mock_result

    # Mock validation to pass
    mock_validate_output.return_value = True

    # Create multiple tasks
    tasks = []
    for i in range(3):
        report_id = f"report_00{i}"
        pdf_file = tmp_path / f"scanned_{i}.pdf"
        pdf_file.write_bytes(f"%PDF-1.4\nfake scanned content {i}".encode())

        task = DocumentTask(
            report_id=report_id,
            source_url=f"https://cag.gov.in/report{i}.pdf",
            local_pdf_path=str(pdf_file),
            initial_metadata={"Title": f"Report {i}"},
            classification="scanned",
        )
        tasks.append(task)

    # Process all tasks
    results = [ocr_service.ocr_document(task) for task in tasks]

    # All should succeed
    for i, result in enumerate(results):
        assert result.processing_status == "ocr_complete"
        assert result.ocred_pdf_path is not None
        assert f"report_00{i}" == result.report_id


def test_ocr_service_integration_output_directory_creation(ocr_service, tmp_path):
    """Integration test: Output directory is created automatically."""
    # Check that output directory exists
    assert Path(ocr_service.output_dir).exists()
    assert Path(ocr_service.output_dir).is_dir()


def test_ocr_service_construct_command_bilingual_support(ocr_service, tmp_path):
    """Test that OCR command includes bilingual language support."""
    input_path = tmp_path / "input.pdf"
    output_path = tmp_path / "output.pdf"

    command = ocr_service._construct_ocr_command(str(input_path), str(output_path))

    # Verify bilingual language specification
    assert "--language" in command
    lang_idx = command.index("--language")
    assert command[lang_idx + 1] == "eng+hin"

    # Verify other key flags
    assert "--force-ocr" in command
    assert "--output-type" in command
    output_type_idx = command.index("--output-type")
    assert command[output_type_idx + 1] == "pdfa"
