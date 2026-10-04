import logging
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import patch

import fitz
import pytest

from src.core.data_contracts import DocumentTask
from src.parsing_pipeline.modules.ocr_service import OCRService

OCR_CONFIG = SimpleNamespace(language="eng", timeout=600, output_type="pdf", force_ocr=True)


def make_pdf(path, pages, text=None):
    """Write a PDF with `pages` pages; each page carries `text` if given."""
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page()
        if text:
            page.insert_text((72, 72), f"{text} page {i + 1}")
    doc.save(str(path))
    doc.close()
    return path


@pytest.fixture
def ocr_service(tmp_path):
    return OCRService(output_dir=str(tmp_path / "ocred"), config=OCR_CONFIG)


@pytest.fixture
def scanned_task(tmp_path):
    pdf = make_pdf(tmp_path / "scan.pdf", 4)
    return DocumentTask(
        report_id="CG_2025_01_Test",
        source_url="https://example.com/test.pdf",
        local_pdf_path=str(pdf),
        initial_metadata={},
        classification="scanned",
    )


def completed(returncode=0, stderr=b""):
    return subprocess.CompletedProcess(["ocrmypdf"], returncode, b"", stderr)


def test_init_creates_output_dir(tmp_path):
    service = OCRService(output_dir=str(tmp_path / "out"), config=OCR_CONFIG)
    assert (tmp_path / "out").is_dir()
    # An OCRConfig without the newer keys still works
    assert service.timeout_per_page == 8
    assert service.optimize is None


def test_construct_command_with_pdf_output_and_optimize(tmp_path):
    config = SimpleNamespace(**vars(OCR_CONFIG), optimize=0, timeout_per_page=8)
    service = OCRService(output_dir=str(tmp_path), config=config)
    assert service._construct_ocr_command("in.pdf", "out.pdf") == [
        "ocrmypdf", "--force-ocr", "--invalidate-digital-signatures",
        "--language", "eng", "--output-type", "pdf", "--optimize", "0",
        "in.pdf", "out.pdf",
    ]


def test_timeout_scales_with_pages(ocr_service):
    assert ocr_service.effective_timeout(10) == 600  # floor
    assert ocr_service.effective_timeout(129) == 1032  # 129 * 8


def test_native_document_skipped_without_error_log(ocr_service):
    task = DocumentTask(
        report_id="native", source_url="", local_pdf_path="x.pdf",
        initial_metadata={}, classification="native_text",
    )
    result = ocr_service.ocr_document(task)
    assert result.error_log == []
    assert result.ocred_pdf_path is None


def test_missing_pdf_fails_and_logs_error(ocr_service, caplog):
    task = DocumentTask(
        report_id="gone", source_url="", local_pdf_path="/nonexistent.pdf",
        initial_metadata={}, classification="scanned",
    )
    with caplog.at_level(logging.ERROR):
        result = ocr_service.ocr_document(task)
    assert result.processing_status == "failed_ocr"
    assert "PDF path does not exist" in result.error_log[-1]
    assert "OCR failed" in caplog.text


def test_success_uses_scaled_timeout(ocr_service, scanned_task):
    out = ocr_service.output_path_for(scanned_task.report_id)

    def fake_run(command, timeout=None):
        make_pdf(out, 4, text="Recognised text from the scanned page")
        return completed()

    with patch.object(ocr_service, "_execute_ocr_command", side_effect=fake_run) as run:
        result = ocr_service.ocr_document(scanned_task)

    assert result.processing_status == "ocr_complete"
    assert result.ocred_pdf_path == str(out)
    assert run.call_args.kwargs["timeout"] == 600


def test_complete_existing_output_is_reused(ocr_service, scanned_task):
    out = ocr_service.output_path_for(scanned_task.report_id)
    make_pdf(out, 4, text="Recognised text from the scanned page")

    with patch.object(ocr_service, "_execute_ocr_command") as run:
        result = ocr_service.ocr_document(scanned_task)

    run.assert_not_called()
    assert result.processing_status == "ocr_complete"
    assert result.ocred_pdf_path == str(out)
    assert "reused" in result.error_log[-1]


@pytest.mark.parametrize("pages,text", [(3, "Recognised text from the page"), (4, None)])
def test_incomplete_existing_output_is_redone(ocr_service, scanned_task, pages, text):
    out = ocr_service.output_path_for(scanned_task.report_id)
    make_pdf(out, pages, text=text)  # wrong page count, or no text layer

    def fake_run(command, timeout=None):
        make_pdf(out, 4, text="Recognised text from the scanned page")
        return completed()

    with patch.object(ocr_service, "_execute_ocr_command", side_effect=fake_run) as run:
        result = ocr_service.ocr_document(scanned_task)

    run.assert_called_once()
    assert result.processing_status == "ocr_complete"


def test_timeout_with_complete_output_succeeds(ocr_service, scanned_task):
    out = ocr_service.output_path_for(scanned_task.report_id)

    def fake_run(command, timeout=None):
        make_pdf(out, 4, text="Recognised text from the scanned page")
        raise subprocess.TimeoutExpired(cmd=command, timeout=timeout)

    with patch.object(ocr_service, "_execute_ocr_command", side_effect=fake_run):
        result = ocr_service.ocr_document(scanned_task)

    assert result.processing_status == "ocr_complete"
    assert result.ocred_pdf_path == str(out)


def test_timeout_without_output_fails(ocr_service, scanned_task, caplog):
    with patch.object(
        ocr_service, "_execute_ocr_command",
        side_effect=subprocess.TimeoutExpired(cmd=[], timeout=600),
    ), caplog.at_level(logging.ERROR):
        result = ocr_service.ocr_document(scanned_task)

    assert result.processing_status == "failed_ocr"
    assert result.ocred_pdf_path is None
    assert "timed out after 600s" in result.error_log[-1]
    assert "OCR failed" in caplog.text


def test_nonzero_exit_fails_with_stderr(ocr_service, scanned_task, caplog):
    with patch.object(
        ocr_service, "_execute_ocr_command",
        return_value=completed(2, b"PriorOcrFoundError: page already has text"),
    ), caplog.at_level(logging.ERROR):
        result = ocr_service.ocr_document(scanned_task)

    assert result.processing_status == "failed_ocr"
    assert "return code 2" in result.error_log[-1]
    assert "PriorOcrFoundError" in result.error_log[-1]
    assert "PriorOcrFoundError" in caplog.text


def test_exit_zero_with_bad_output_fails(ocr_service, scanned_task):
    out = ocr_service.output_path_for(scanned_task.report_id)

    def fake_run(command, timeout=None):
        out.write_bytes(b"%PDF-1.4\n" + b"x" * 2000)  # not a readable PDF
        return completed()

    with patch.object(ocr_service, "_execute_ocr_command", side_effect=fake_run):
        result = ocr_service.ocr_document(scanned_task)

    assert result.processing_status == "failed_ocr"
    assert "validation failed" in result.error_log[-1]


def test_unexpected_exception_fails(ocr_service, scanned_task):
    with patch.object(ocr_service, "_execute_ocr_command", side_effect=OSError("no ocrmypdf")):
        result = ocr_service.ocr_document(scanned_task)
    assert result.processing_status == "failed_ocr"
    assert "no ocrmypdf" in result.error_log[-1]


@pytest.mark.parametrize(
    "content,expected",
    [
        (None, "does not exist"),
        (b"%PDF-1.4\n", "too small"),
        (b"not pdf content" + b"x" * 2000, "not appear to be a valid PDF"),
    ],
)
def test_output_problem_reasons(tmp_path, content, expected):
    out = tmp_path / "out.pdf"
    if content is not None:
        out.write_bytes(content)
    assert expected in OCRService.output_problem(out, 4)


def test_is_complete_output(tmp_path):
    src = make_pdf(tmp_path / "in.pdf", 3)
    good = make_pdf(tmp_path / "good.pdf", 3, text="Some recognised text")
    short = make_pdf(tmp_path / "short.pdf", 2, text="Some recognised text")
    assert OCRService.is_complete_output(src, good)
    assert not OCRService.is_complete_output(src, short)
    assert not OCRService.is_complete_output(tmp_path / "missing.pdf", good)


def test_execute_returns_completed_process(ocr_service):
    result = ocr_service._execute_ocr_command(
        [sys.executable, "-c", "import sys; sys.stderr.write('warn')"], timeout=30
    )
    assert result.returncode == 0
    assert result.stderr == b"warn"


def test_execute_kills_on_timeout(ocr_service):
    with pytest.raises(subprocess.TimeoutExpired):
        ocr_service._execute_ocr_command(
            [sys.executable, "-c", "import time; time.sleep(30)"], timeout=0.5
        )
