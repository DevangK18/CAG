"""
Integration tests for OCRService: real ocrmypdf/tesseract runs on a small
generated scan, and the Phase 2-3 chain (triage, OCR, cache).

Tests that run OCR are skipped when ocrmypdf or tesseract is not on PATH.
"""

import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import fitz
import pytest

from src.core.data_contracts import DocumentTask
from src.parsing_pipeline.config import get_config
from src.parsing_pipeline.modules.ocr_service import OCRService
from src.parsing_pipeline.modules.triage_service import TriageCache, TriageService

HAS_OCR = bool(shutil.which("ocrmypdf") and shutil.which("tesseract"))
requires_ocr = pytest.mark.skipif(not HAS_OCR, reason="ocrmypdf and tesseract must be on PATH")

SCAN_LINES = [
    "Report of the Comptroller and Auditor General of India",
    "Compliance Audit of the Department of Revenue",
    "The audit observed short levy of stamp duty in several cases.",
    "Registering officers did not apply the market value guidelines,",
    "which resulted in under-valuation of properties and loss of revenue.",
    "The department accepted the observations and initiated recovery.",
    "Recommendation: the department should strengthen internal controls.",
]


def _installed_tesseract_languages() -> set:
    out = subprocess.run(
        ["tesseract", "--list-langs"], capture_output=True, text=True, check=True
    ).stdout
    # First line is a header ("List of available languages in ...")
    return {line.strip() for line in out.splitlines()[1:] if line.strip()}


def make_scanned_pdf(path: Path, pages: int = 2) -> Path:
    """Image-only PDF: each page is a picture of typed text, with no text layer."""
    doc = fitz.open()
    for i in range(pages):
        source = fitz.open()
        page = source.new_page()
        for j, line in enumerate(SCAN_LINES + [f"Page {i + 1}"]):
            page.insert_text((60, 100 + 30 * j), line, fontsize=14)
        pix = page.get_pixmap(dpi=200)
        source.close()
        scan = doc.new_page()
        scan.insert_image(scan.rect, pixmap=pix)
    doc.save(str(path))
    doc.close()
    return path


def _task(pdf: Path, classification=None, report_id="SCAN_2025_01_Test") -> DocumentTask:
    return DocumentTask(
        report_id=report_id,
        source_url="https://cag.gov.in/scanned-report.pdf",
        local_pdf_path=str(pdf),
        initial_metadata={"Title": "Scanned CAG Report"},
        classification=classification,
    )


@pytest.fixture
def ocr_service(tmp_path):
    """Service built from parsing_config.yaml, as main.py builds it."""
    return OCRService(output_dir=str(tmp_path / "processed" / "ocred"))


@pytest.fixture
def scanned_pdf(tmp_path):
    return make_scanned_pdf(tmp_path / "scanned_report.pdf")


def test_native_document_is_left_alone(ocr_service, tmp_path):
    task = _task(tmp_path / "native.pdf", classification="native_text")
    original = task.model_copy(deep=True)

    result = ocr_service.ocr_document(task)

    assert result.model_dump() == original.model_dump()
    assert not any(ocr_service.output_dir.iterdir())


def test_missing_input_fails(ocr_service, tmp_path):
    result = ocr_service.ocr_document(_task(tmp_path / "gone.pdf", classification="scanned"))

    assert result.processing_status == "failed_ocr"
    assert result.ocred_pdf_path is None
    assert "PDF path does not exist" in result.error_log[-1]


def test_output_directory_is_created(ocr_service):
    assert ocr_service.output_dir.is_dir()


def test_command_honours_language_override(tmp_path):
    service = OCRService(output_dir=str(tmp_path), language="eng+hin")
    command = service._construct_ocr_command("in.pdf", "out.pdf")

    assert command[command.index("--language") + 1] == "eng+hin"
    # The rest comes from parsing_config.yaml
    config = get_config().ocr
    assert command[command.index("--output-type") + 1] == config.output_type
    assert ("--force-ocr" in command) == config.force_ocr
    assert command[-2:] == ["in.pdf", "out.pdf"]


@pytest.mark.skipif(not shutil.which("tesseract"), reason="tesseract must be on PATH")
def test_configured_languages_are_installed():
    wanted = set(get_config().ocr.language.split("+"))
    missing = wanted - _installed_tesseract_languages()
    assert not missing, f"tesseract language data missing: {sorted(missing)}"


@requires_ocr
def test_scanned_pdf_gets_a_text_layer(ocr_service, scanned_pdf):
    result = ocr_service.ocr_document(_task(scanned_pdf, classification="scanned"))

    assert result.processing_status == "ocr_complete", result.error_log
    out = Path(result.ocred_pdf_path)
    assert out == ocr_service.output_path_for(result.report_id)
    assert result.error_log[-1] == "OCR processing completed successfully"
    with fitz.open(out) as doc:
        assert doc.page_count == 2
        text = " ".join(page.get_text() for page in doc)
    assert "Comptroller" in text and "Auditor" in text
    assert OCRService.is_complete_output(scanned_pdf, out)


@requires_ocr
def test_ocrmypdf_error_is_reported(tmp_path, scanned_pdf):
    # No tesseract language data is called "zzz"
    service = OCRService(output_dir=str(tmp_path / "ocred"), language="zzz")

    result = service.ocr_document(_task(scanned_pdf, classification="scanned"))

    assert result.processing_status == "failed_ocr"
    assert result.ocred_pdf_path is None
    assert "OCR command failed with return code" in result.error_log[-1]
    assert "zzz" in result.error_log[-1]  # ocrmypdf's stderr is kept


@requires_ocr
def test_rerun_reuses_complete_output(ocr_service, scanned_pdf):
    first = ocr_service.ocr_document(_task(scanned_pdf, classification="scanned"))
    assert first.processing_status == "ocr_complete", first.error_log

    with patch.object(ocr_service, "_execute_ocr_command") as run:
        second = ocr_service.ocr_document(_task(scanned_pdf, classification="scanned"))

    run.assert_not_called()
    assert second.processing_status == "ocr_complete"
    assert second.ocred_pdf_path == first.ocred_pdf_path
    assert "reused" in second.error_log[-1]


@requires_ocr
def test_triage_ocr_and_cache_chain(tmp_path, ocr_service, scanned_pdf):
    """Phases 2-3 as main.py runs them, then a second run served from the cache."""
    cache = TriageCache(tmp_path / ".cache")
    task = _task(scanned_pdf)
    assert cache.load(task) is None

    task = TriageService().triage_document(task)
    assert task.classification == "scanned"
    cache.store_triage(task)
    task = ocr_service.ocr_document(task)
    assert task.processing_status == "ocr_complete", task.error_log
    cache.store_ocr(task)

    # The OCR'd PDF is native text to triage
    ocred = TriageService().triage_document(_task(Path(task.ocred_pdf_path), report_id="ocred"))
    assert ocred.classification == "native_text"

    hit = cache.load(_task(scanned_pdf))
    assert hit is not None
    assert hit.classification == "scanned"
    assert hit.processing_status == "ocr_complete"
    assert hit.ocred_pdf_path == task.ocred_pdf_path

    # A cached OCR'd PDF that went missing sends the report back through OCR
    Path(task.ocred_pdf_path).unlink()
    assert cache.load(_task(scanned_pdf)) is None
