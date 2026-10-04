"""
Integration tests for TriageService and TriageCache on real CAG report PDFs.

PDFs are taken from CAG_TEST_PDF_DIR, or data/raw/ under the repo root: the
smallest PDF in each tier directory (union, state, local_body), else the
smallest few anywhere below it. Neither is in git, so the real-PDF tests are
skipped when no PDFs are present.
"""

import os
import shutil
from pathlib import Path

import pytest

from src.core.data_contracts import DocumentTask
from src.parsing_pipeline.modules.triage_service import TriageCache, TriageService

REPO_ROOT = Path(__file__).resolve().parents[3]
PDF_DIR = Path(os.getenv("CAG_TEST_PDF_DIR") or REPO_ROOT / "data" / "raw")
TIERS = ("union", "state", "local_body")


def _smallest(pdfs, n):
    return sorted(pdfs, key=lambda p: p.stat().st_size)[:n]


def _sample_pdfs():
    if not PDF_DIR.is_dir():
        return []
    per_tier = [
        pdf for tier in TIERS if (PDF_DIR / tier).is_dir()
        for pdf in _smallest((PDF_DIR / tier).glob("*.pdf"), 1)
    ]
    return per_tier or _smallest(PDF_DIR.rglob("*.pdf"), 3)


PDFS = _sample_pdfs()
requires_pdfs = pytest.mark.skipif(
    not PDFS, reason=f"no report PDFs under {PDF_DIR} (set CAG_TEST_PDF_DIR)"
)


def _task(pdf_path, report_id=None) -> DocumentTask:
    pdf_path = Path(pdf_path)
    return DocumentTask(
        report_id=report_id or pdf_path.stem[:40],
        source_url=f"https://example.com/{pdf_path.name}",
        local_pdf_path=str(pdf_path),
        initial_metadata={},
    )


@pytest.fixture
def triage_service():
    """Service built from parsing_config.yaml, as main.py builds it."""
    return TriageService()


@requires_pdfs
@pytest.mark.parametrize("pdf_path", PDFS, ids=lambda p: f"{p.parent.name}-{p.stem[:25]}")
def test_triage_real_pdf(triage_service, pdf_path):
    result = triage_service.triage_document(_task(pdf_path, report_id="real_report"))

    assert result.error_log == []
    assert (result.classification, result.processing_status) in {
        ("native_text", "triaged_native"),
        ("scanned", "triaged_scanned"),
    }
    assert result.report_id == "real_report"


@requires_pdfs
def test_triage_is_repeatable(triage_service):
    pdf_path = PDFS[0]
    first = triage_service.triage_document(_task(pdf_path, "run_1"))
    second = triage_service.triage_document(_task(pdf_path, "run_2"))

    assert first.classification == second.classification
    assert first.processing_status == second.processing_status
    assert first.error_log == second.error_log == []


@requires_pdfs
def test_cache_follows_pdf_content(tmp_path, triage_service):
    """A cache hit needs the same bytes; a re-downloaded, changed PDF is triaged again."""
    pdf_path = shutil.copy(PDFS[0], tmp_path / "report.pdf")
    cache = TriageCache(tmp_path / ".cache")

    task = triage_service.triage_document(_task(pdf_path, "cached_report"))
    if task.classification == "scanned":
        pytest.skip("a scanned hit also needs an OCR'd PDF (see test_ocr_service_integration)")
    cache.store_triage(task)

    hit = cache.load(_task(pdf_path, "cached_report"))
    assert hit is not None
    assert hit.classification == task.classification
    assert hit.processing_status == "triage_complete"

    # Another run's cache instance, same PDF: still a hit
    assert TriageCache(tmp_path / ".cache").load(_task(pdf_path, "cached_report")) is not None

    with open(pdf_path, "ab") as f:
        f.write(b"\n% appended by a later download\n")
    assert TriageCache(tmp_path / ".cache").load(_task(pdf_path, "cached_report")) is None


def test_missing_pdf_fails(triage_service, tmp_path):
    result = triage_service.triage_document(_task(tmp_path / "gone.pdf"))

    assert result.classification is None
    assert result.processing_status == "failed_triage"
    assert "PDF path does not exist" in result.error_log[-1]


def test_corrupted_pdf_fails_without_raising(triage_service, tmp_path):
    corrupt = tmp_path / "corrupt.pdf"
    corrupt.write_bytes(b"This is not a PDF. " * 50)

    result = triage_service.triage_document(_task(corrupt))

    assert result.classification is None
    assert result.processing_status == "failed_triage"
    assert len(result.error_log) == 1
    assert "Triage failed with error" in result.error_log[0]
