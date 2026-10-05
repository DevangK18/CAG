"""Phase 4 source selection on real reports (A-4-02): skipped without the review corpus."""

import os
from pathlib import Path

import pytest

from src.core.data_contracts import DocumentTask
from src.parsing_pipeline.modules.scaffolding_service import ScaffoldingService

REPO_ROOT = Path(__file__).resolve().parents[3]
PDF_DIR = Path(os.getenv("CAG_REVIEW_PDF_DIR") or REPO_ROOT / "data" / "review_corpus" / "pdfs")


def _pdf(prefix):
    hits = sorted(PDF_DIR.glob(f"{prefix}*.pdf")) if PDF_DIR.exists() else []
    if not hits:
        pytest.skip(f"{prefix} PDF not available")
    return str(hits[0])


@pytest.mark.parametrize("prefix,method", [
    # Junk merger bookmarks used to win; the verified printed contents page now does
    ("HP_2022", "printed_toc"),
    ("KA_2022_06", "printed_toc"),
    # Real Word bookmarks, richer than the chapters-only contents page and agreeing with it
    ("2024_01", "embedded_bookmarks"),
])
def test_contents_source(prefix, method, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    task = DocumentTask(report_id=prefix, source_url="", local_pdf_path=_pdf(prefix), initial_metadata={})
    task = ScaffoldingService().build_scaffold(task)
    assert task.scaffold["toc_method"] == method
    titles = [e[1] for e in task.scaffold["toc"]]
    assert not any(t in ("Blank Page", "Binder1.pdf") or t.endswith(".pdf") for t in titles)
