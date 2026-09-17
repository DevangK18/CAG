import pytest
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock
from ..src.modules.ocr_service import OCRService
from ..src.modules.data_contracts import DocumentTask


@pytest.fixture
def ocr_service(tmp_path):
    """OCRService fixture with temporary output directory."""
    return OCRService(output_dir=str(tmp_path / "ocr_output"))


@pytest.fixture
def mock_document_task():
    """Create a mock DocumentTask with scanned classification."""
    return DocumentTask(
        report_id="report_001_test",
        source_url="https://example.com/test.pdf",
        local_pdf_path="test.pdf",
        initial_metadata={},
        classification="scanned",
    )


@pytest.fixture
def mock_native_task():
    """Create a mock DocumentTask with native classification."""
    return DocumentTask(
        report_id="report_002_native",
        source_url="https://example.com/native.pdf",
        local_pdf_path="native.pdf",
        initial_metadata={},
        classification="native_text",
    )


def test_ocr_service_init(tmp_path):
    """Test OCRService initialization creates output directory."""
    output_dir = tmp_path / "test_ocr"
    service = OCRService(output_dir=str(output_dir))

    assert output_dir.exists()
    assert service.output_dir == output_dir


@pytest.mark.parametrize(
    "input_path,output_path,expected_command",
    [
        (
            "/path/to/input.pdf",
            "/path/to/output.pdf",
            [
                "ocrmypdf",
                "--force-ocr",
                "--language",
                "eng+hin",
                "--output-type",
                "pdfa",
                "/path/to/input.pdf",
                "/path/to/output.pdf",
            ],
        ),
        (
            "simple_input.pdf",
            "simple_output.pdf",
            [
                "ocrmypdf",
                "--force-ocr",
                "--language",
                "eng+hin",
                "--output-type",
                "pdfa",
                "simple_input.pdf",
                "simple_output.pdf",
            ],
        ),
    ],
)
def test_construct_ocr_command(ocr_service, input_path, output_path, expected_command):
    """Test OCR command construction with proper arguments."""
    result = ocr_service._construct_ocr_command(input_path, output_path)
    assert result == expected_command


@patch("subprocess.run")
def test_execute_ocr_command_success(mock_subprocess_run, ocr_service):
    """Test successful OCR command execution."""
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = b"Success output"
    mock_result.stderr = b""

    mock_subprocess_run.return_value = mock_result

    command = ["ocrmypdf", "--test"]
    result = ocr_service._execute_ocr_command(command)

    assert result == mock_result
    mock_subprocess_run.assert_called_once_with(
        command,
        capture_output=True,
        text=False,
        timeout=600,
    )


@patch("subprocess.run")
def test_execute_ocr_command_failure(mock_subprocess_run, ocr_service):
    """Test failed OCR command execution."""
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stdout = b""
    mock_result.stderr = b"OCR error message"

    mock_subprocess_run.return_value = mock_result

    command = ["ocrmypdf", "--test"]
    result = ocr_service._execute_ocr_command(command)

    assert result == mock_result


@pytest.mark.parametrize(
    "file_exists,file_size,header,expected",
    [
        (True, 1500, b"%PDF-1.4\n", True),  # Valid PDF
        (False, 0, b"", False),  # File doesn't exist
        (True, 500, b"%PDF-1.4\n", False),  # Too small
        (True, 1500, b"not pdf content", False),  # Wrong header
    ],
)
def test_validate_ocr_output(
    ocr_service, tmp_path, file_exists, file_size, header, expected, mock_document_task
):
    """Test OCR output validation with different scenarios."""
    output_path = tmp_path / "test_output.pdf"

    if file_exists:
        output_path.write_bytes(header + b"x" * (file_size - len(header)))
    # If file doesn't exist, don't create it

    result = ocr_service._validate_ocr_output(str(output_path), mock_document_task)
    assert result == expected

    if not expected and file_exists:
        # Check that errors were logged - patterns include "failed", "small", "does not appear"
        assert any(
            "failed" in msg.lower()
            or "small" in msg.lower()
            or "does not" in msg.lower()
            for msg in mock_document_task.error_log
        )


def test_ocr_document_native_text_skip(ocr_service, mock_native_task):
    """Test that native text documents are skipped."""
    result = ocr_service.ocr_document(mock_native_task)

    assert result == mock_native_task
    assert "not classified as scanned" in mock_native_task.error_log[0]
    assert result.ocred_pdf_path is None


@patch("pathlib.Path.exists")
def test_ocr_document_missing_file(mock_path_exists, ocr_service, mock_document_task):
    """Test handling of missing PDF file."""
    mock_path_exists.return_value = False

    result = ocr_service.ocr_document(mock_document_task)

    assert result.processing_status == "failed_ocr"
    assert "PDF path does not exist" in result.error_log[0]


@patch(
    "services.parsing_pipeline.src.modules.ocr_service.OCRService._execute_ocr_command"
)
@patch(
    "services.parsing_pipeline.src.modules.ocr_service.OCRService._validate_ocr_output"
)
@patch("pathlib.Path.exists")
def test_ocr_document_success(
    mock_path_exists,
    mock_validate_output,
    mock_execute_command,
    ocr_service,
    mock_document_task,
    tmp_path,
):
    """Test successful OCR document processing."""
    mock_path_exists.return_value = True

    # Mock successful command execution
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stderr = b""
    mock_execute_command.return_value = mock_result

    # Mock successful validation
    mock_validate_output.return_value = True

    # Set output directory for this test
    ocr_service.output_dir = tmp_path

    result = ocr_service.ocr_document(mock_document_task)

    assert result.processing_status == "ocr_complete"
    expected_path = str(tmp_path / f"{mock_document_task.report_id}_ocred.pdf")
    assert result.ocred_pdf_path == expected_path
    assert "OCR processing completed successfully" in result.error_log
    assert "OCR output validation passed" in result.error_log
    mock_execute_command.assert_called_once()


@patch(
    "services.parsing_pipeline.src.modules.ocr_service.OCRService._execute_ocr_command"
)
@patch("pathlib.Path.exists")
def test_ocr_document_ocr_failure(
    mock_path_exists, mock_execute_command, ocr_service, mock_document_task
):
    """Test OCR failure handling."""
    mock_path_exists.return_value = True

    # Mock failed command execution
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stderr = b"OCR command failed"
    mock_execute_command.return_value = mock_result

    result = ocr_service.ocr_document(mock_document_task)

    assert result.processing_status == "failed_ocr"
    assert "OCR command failed with return code 1" in result.error_log[-1]
    assert result.ocred_pdf_path is None


@patch(
    "services.parsing_pipeline.src.modules.ocr_service.OCRService._execute_ocr_command"
)
@patch(
    "services.parsing_pipeline.src.modules.ocr_service.OCRService._validate_ocr_output"
)
@patch("pathlib.Path.exists")
def test_ocr_document_validation_failure(
    mock_path_exists,
    mock_validate_output,
    mock_execute_command,
    ocr_service,
    mock_document_task,
    tmp_path,
):
    """Test OCR validation failure handling."""
    mock_path_exists.return_value = True

    # Mock successful command execution
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stderr = b""
    mock_execute_command.return_value = mock_result

    # Mock failed validation
    mock_validate_output.return_value = False

    # Set output directory for this test
    ocr_service.output_dir = tmp_path

    result = ocr_service.ocr_document(mock_document_task)

    assert (
        result.processing_status == "ocr_complete"
    )  # Still complete, but logged warning
    expected_path = str(tmp_path / f"{mock_document_task.report_id}_ocred.pdf")
    assert result.ocred_pdf_path == expected_path
    assert "OCR output validation failed" in result.error_log[-1]


@patch(
    "services.parsing_pipeline.src.modules.ocr_service.OCRService._execute_ocr_command"
)
def test_ocr_document_timeout_exception(
    mock_execute_command, ocr_service, mock_document_task
):
    """Test OCR processing with timeout/subprocess exception."""
    mock_execute_command.side_effect = subprocess.TimeoutExpired(cmd=[], timeout=600)

    with patch("pathlib.Path.exists", return_value=True):
        result = ocr_service.ocr_document(mock_document_task)

    assert result.processing_status == "failed_ocr"
    assert "OCR processing failed with exception" in result.error_log[0]
