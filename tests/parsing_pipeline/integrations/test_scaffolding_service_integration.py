"""
Integration tests for ScaffoldingService on real CAG report PDFs.

PDFs are taken from CAG_TEST_PDF_DIR, or data/raw/ under the repo root (searched
recursively). Neither is in git, so these are skipped when no PDFs are present.
"""

import os
import time
from pathlib import Path

import pytest

from src.core.data_contracts import DocumentTask
from src.parsing_pipeline.modules.scaffolding_service import ScaffoldingService

REPO_ROOT = Path(__file__).resolve().parents[3]
PDF_DIR = Path(os.getenv("CAG_TEST_PDF_DIR", REPO_ROOT / "data" / "raw"))
# The smallest few keep the run short
PDFS = sorted(PDF_DIR.rglob("*.pdf"), key=lambda p: p.stat().st_size)[:3] if PDF_DIR.is_dir() else []

pytestmark = pytest.mark.skipif(
    not PDFS, reason=f"no report PDFs under {PDF_DIR} (set CAG_TEST_PDF_DIR)"
)

VALID_STATUSES = {"scaffold_complete", "scaffold_partial"}


@pytest.fixture
def scaffolding_service(tmp_path, monkeypatch):
    """Service whose TOC rejection log is written under tmp_path."""
    monkeypatch.chdir(tmp_path)
    return ScaffoldingService()


def _task(pdf_path: Path, report_id: str = None) -> DocumentTask:
    return DocumentTask(
        report_id=report_id or pdf_path.stem[:40],
        source_url=f"https://example.com/{pdf_path.name}",
        local_pdf_path=str(pdf_path),
        initial_metadata={},
    )


@pytest.mark.parametrize("pdf_path", PDFS, ids=lambda p: p.stem[:30])
def test_scaffold_structure(scaffolding_service, pdf_path):
    import fitz

    with fitz.open(pdf_path) as doc:
        page_count = doc.page_count

    result = scaffolding_service.build_scaffold(_task(pdf_path))

    assert result.processing_status in VALID_STATUSES

    # Page map covers every physical page: its printed label, or None where no number
    # is printed (never physical + 1)
    page_map = result.scaffold["page_map"]
    assert sorted(page_map) == list(range(page_count))
    assert all(
        label is None or (isinstance(label, str) and label.strip())
        for label in page_map.values()
    )

    # TOC entries are [level, title, 0-indexed physical page]
    for level, title, page in result.scaffold["toc"]:
        assert isinstance(level, int) and level > 0
        assert isinstance(title, str) and title.strip()
        assert isinstance(page, int) and 0 <= page < page_count

    if result.scaffold["toc"]:
        assert result.scaffold["toc_method"] in {"embedded_bookmarks", "printed_toc", "heuristic"}
        assert isinstance(result.scaffold["toc_quality"], int)
        # The source and its score are recorded for the output
        assert result.scaffold["toc_source"] == result.scaffold["toc_method"]
        assert result.scaffold["toc_method"] in result.scaffold["toc_candidates"]


def test_scaffold_is_deterministic(scaffolding_service):
    first = scaffolding_service.build_scaffold(_task(PDFS[0], "consistency_1"))
    second = scaffolding_service.build_scaffold(_task(PDFS[0], "consistency_2"))

    assert first.processing_status == second.processing_status
    assert first.scaffold["toc"] == second.scaffold["toc"]
    assert first.scaffold["page_map"] == second.scaffold["page_map"]


def test_scaffold_time_bound(scaffolding_service):
    start = time.time()
    result = scaffolding_service.build_scaffold(_task(PDFS[0]))
    elapsed = time.time() - start

    assert result.processing_status in VALID_STATUSES
    assert elapsed < 30.0, f"Took {elapsed:.2f}s to build the scaffold"
