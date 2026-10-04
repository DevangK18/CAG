"""
Integration tests for LayoutAnalysisService: real Docling conversion of small
generated PDFs.

Docling loads its layout and TableFormer models (slow, and downloaded on first
use), so these run only when CAG_RUN_DOCLING_TESTS=1 and the models are already
in the Hugging Face cache.
"""

import os
from pathlib import Path

import fitz
import pytest

from src.core.data_contracts import DocumentTask
from src.parsing_pipeline.config import LayoutAnalysisConfig


def _docling_models_cached() -> bool:
    hub = Path(os.getenv("HF_HOME", Path.home() / ".cache" / "huggingface")) / "hub"
    return any(hub.glob("models--docling-project--docling-*")) or any(
        hub.glob("models--ds4sd--docling-*")
    )


pytestmark = pytest.mark.skipif(
    os.getenv("CAG_RUN_DOCLING_TESTS") != "1" or not _docling_models_cached(),
    reason="needs Docling models in the Hugging Face cache and CAG_RUN_DOCLING_TESTS=1",
)


@pytest.fixture(scope="module")
def layout_service():
    """One converter for the module: loading Docling models dominates the run time."""
    from src.parsing_pipeline.modules.layout_analysis_service import LayoutAnalysisService

    return LayoutAnalysisService(config=LayoutAnalysisConfig(accelerator_device="cpu"))


def _write_pdf(path: Path, pages: int = 1, label: str = "Content") -> Path:
    doc = fitz.open()
    for n in range(pages):
        page = doc.new_page()
        page.insert_text((72, 72), f"Chapter {n + 1}: Test Report Title", fontsize=18)
        page.insert_text((72, 120), f"{label} on page {n + 1}. This is a sample paragraph of text.")
        page.insert_text((72, 140), "It contains multiple lines and different content.")
    doc.save(str(path))
    doc.close()
    return path


def _task(pdf_path: Path, report_id: str = "report_real_pdf_test", **kwargs) -> DocumentTask:
    return DocumentTask(
        report_id=report_id,
        source_url="file://" + str(pdf_path),
        local_pdf_path=str(pdf_path),
        initial_metadata={"Title": "Real PDF Test Report"},
        **kwargs,
    )


def test_analyze_layout_real_pdf(layout_service, tmp_path):
    result = layout_service.analyze_layout(_task(_write_pdf(tmp_path / "real.pdf")))

    assert result.processing_status == "layout_complete"
    assert result.layout and 0 in result.layout
    for block in result.layout[0]:
        assert {"bbox", "label", "confidence", "content_type", "docling_table_available"} <= set(block)
        assert len(block["bbox"]) == 4
        assert block["confidence"] >= layout_service.confidence_threshold
        # Top-left origin: y grows downwards
        assert block["bbox"][1] <= block["bbox"][3]

    completion = [m for m in result.error_log if m.startswith("Layout analysis completed")]
    assert len(completion) == 1


def test_multiple_pages(layout_service, tmp_path):
    result = layout_service.analyze_layout(_task(_write_pdf(tmp_path / "multi.pdf", pages=3)))

    assert result.processing_status == "layout_complete"
    assert set(result.layout) == {0, 1, 2}


def test_ocred_pdf_preferred(layout_service, tmp_path):
    base = _write_pdf(tmp_path / "base.pdf", pages=1)
    ocred = _write_pdf(tmp_path / "ocred.pdf", pages=2)

    result = layout_service.analyze_layout(_task(base, ocred_pdf_path=str(ocred)))

    assert result.processing_status == "layout_complete"
    assert 1 in result.layout  # Only the OCR'd PDF has a second page


def test_missing_pdf_fails_cleanly(layout_service, tmp_path):
    result = layout_service.analyze_layout(_task(tmp_path / "nonexistent.pdf"))

    assert result.processing_status == "failed_layout"
    assert "PDF path not available" in result.error_log[0]


def test_converter_reused_and_deterministic(layout_service, tmp_path):
    pdf = _write_pdf(tmp_path / "same.pdf")
    first = layout_service.analyze_layout(_task(pdf, "report_a"))
    second = layout_service.analyze_layout(_task(pdf, "report_b"))

    assert first.layout == second.layout
