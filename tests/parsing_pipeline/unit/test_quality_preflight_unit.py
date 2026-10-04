"""
Unit tests for the per-report preflight checks (C-8-10, X-01):
- check_report grades a clean report ok and flags real defects
- structure checks: duplicate parent IDs, children outside parent pages, largest parent share
- run_quality_checks never raises (missing PDF, malformed JSON, footnote_index dict)
- the preflight CLI is a thin front end over the module
"""

import json
import subprocess
import sys
from pathlib import Path

import fitz
import pytest

from src.parsing_pipeline.modules.validation_service import ValidationService, run_quality_checks
from src.parsing_pipeline.quality import THRESHOLDS, check_report, grade, summarize

REPO = Path(__file__).resolve().parents[3]

PAGE_TEXT = [
    "The Department did not collect revenue of 12,345.67 lakh from the contractors during 2019-20 "
    "although the agreement required recovery within the stipulated period and the audit observed "
    "that the monitoring committee never met, the registers were incomplete, the inspection reports "
    "were missing and the penalty amounting to 98,765 was neither levied nor recovered from the agency.",
    "The Ministry stated that instructions had been issued to all field offices in 2021 and that "
    "recovery of 4,321.50 crore was in progress, but audit found that the reply was silent on the "
    "delay, the responsibility was not fixed, the records were not produced and the shortfall of "
    "56,789 units against the target was not explained by the implementing agency or the department.",
]


@pytest.fixture
def pdf_path(tmp_path):
    path = tmp_path / "report.pdf"
    doc = fitz.open()
    for text in PAGE_TEXT:
        page = doc.new_page()
        page.insert_textbox(fitz.Rect(50, 50, 550, 800), text, fontsize=11)
    doc.save(path)
    doc.close()
    return path


def _parent(chunk_id, pages, title="1.1 Revenue"):
    return {"chunk_id": chunk_id, "page_range_physical": pages, "toc_entry": title, "toc_level": 2}


def _child(i, parent_id, page, content, content_type="paragraph"):
    return {
        "chunk_id": f"c{i}",
        "parent_chunk_id": parent_id,
        "content_type": content_type,
        "content": content,
        "source_page_physical": page,
    }


def _report(parents=None, children=None):
    if parents is None:
        parents = [_parent(f"p{i}", [i // 2, i // 2], f"1.{i} Section") for i in range(4)]
    if children is None:
        # Two halves per page, one parent each, so no parent holds over 25% of children
        children = []
        for page, text in enumerate(PAGE_TEXT):
            cut = text.index(" ", len(text) // 2)
            children += [_child(2 * page, f"p{2 * page}", page, text[:cut]),
                         _child(2 * page + 1, f"p{2 * page + 1}", page, text[cut:])]
    return {
        "report_metadata": {"report_id": "XX_2025_01_Test"},
        "parent_chunks": parents,
        "child_chunks": children,
        "processing_stats": {"dlq_entries": []},
    }


class TestCheckReport:
    def test_clean_report_has_no_red_flags(self, pdf_path):
        result = check_report(_report(), pdf_path, max_chunk_chars=2000)
        assert result["report"] == "XX_2025_01_Test"
        assert result["word_recall"] == 1.0
        assert result["number_recall"] == 1.0
        assert result["status"] == "ok"
        assert result["red_flags"] == []
        assert set(result["grades"]) == set(THRESHOLDS)

    def test_dropped_page_fails_recall(self, pdf_path):
        report = _report(children=[_child(0, "p1", 0, PAGE_TEXT[0])])
        result = check_report(report, pdf_path, max_chunk_chars=2000)
        # Page 1 is within ±1 of page 0, so drop the shared context by citing page 0 only
        assert result["word_recall"] < 0.90 or result["number_recall"] < 0.85
        assert result["status"] == "FAIL"

    def test_reversed_and_oversized_chunks_flagged(self, pdf_path):
        reversed_text = " ".join(w[::-1] for w in "The Department of Revenue did not reply to the audit".split())
        children = [
            _child(0, "p1", 0, PAGE_TEXT[0]),
            _child(1, "p2", 1, PAGE_TEXT[1]),
            _child(2, "p2", 1, reversed_text),
        ]
        result = check_report(_report(children=children), pdf_path, max_chunk_chars=100)
        flagged = {f["check"]: f for f in result["red_flags"]}
        assert flagged["reversed_pct"]["grade"] == "FAIL"
        assert flagged["oversized_chunks"]["value"] == 2
        assert flagged["oversized_chunks"]["fail"] == THRESHOLDS["oversized_chunks"][1]

    def test_dlq_leak_counted(self, pdf_path):
        report = _report()
        report["processing_stats"]["dlq_entries"] = [{"page": 1}, {"page": 7}, {"page": None}, "junk"]
        result = check_report(report, pdf_path, max_chunk_chars=2000)
        assert result["dlq_leak"] == 1

    def test_null_cited_page_does_not_crash(self, pdf_path):
        children = [_child(0, "p1", 0, PAGE_TEXT[0]), _child(1, "p2", None, PAGE_TEXT[1])]
        result = check_report(_report(children=children), pdf_path, max_chunk_chars=2000)
        assert result["children"] == 2


class TestStructureChecks:
    def test_duplicate_parent_ids(self, pdf_path):
        parents = [_parent("p0", [0, 0])] * 3 + [_parent("p2", [1, 1]), _parent("p3", [1, 1])]
        result = check_report(_report(parents=parents), pdf_path, max_chunk_chars=2000)
        assert result["duplicate_parents"] == 2
        assert result["duplicate_parent_examples"] == ["p0"]
        assert result["grades"]["duplicate_parents"] == "FAIL"

    def test_children_outside_parent_pages(self, pdf_path):
        # p1 claims page 0 only, but its second child is cited on page 1
        children = [_child(0, "p1", 0, PAGE_TEXT[0]), _child(1, "p1", 1, PAGE_TEXT[1])]
        parents = [_parent("p1", [0, 0])]
        result = check_report(_report(parents=parents, children=children), pdf_path, max_chunk_chars=2000)
        assert result["outside_parent"] == 1
        assert result["outside_parent_pct"] == 50.0
        assert result["grades"]["outside_parent_pct"] == "FAIL"

    def test_largest_parent_share(self, pdf_path):
        children = [_child(0, "p1", 0, PAGE_TEXT[0]), _child(1, "p1", 0, "Short note on page zero.")]
        children += [_child(2, "p2", 1, PAGE_TEXT[1])]
        result = check_report(_report(children=children), pdf_path, max_chunk_chars=2000)
        assert result["largest_parent_pct"] == 66.7
        assert result["largest_parent_title"] == "1.1 Section"
        assert result["grades"]["largest_parent_pct"] == "FAIL"

    def test_missing_page_range_is_skipped(self, pdf_path):
        parents = [{"chunk_id": f"p{i}", "toc_entry": "1.1 Revenue"} for i in range(4)]
        result = check_report(_report(parents=parents), pdf_path, max_chunk_chars=2000)
        assert result["outside_parent"] == 0


class TestGrading:
    def test_recall_fails_below_and_counts_fail_above(self):
        result = {key: 0 for key in THRESHOLDS}
        result.update(word_recall=0.92, number_recall=0.80, garbage_titles=3, dlq_leak=1)
        grades = grade(result)
        assert grades["word_recall"] == "WARN"
        assert grades["number_recall"] == "FAIL"
        assert grades["garbage_titles"] == "WARN"
        assert grades["dlq_leak"] == "FAIL"
        assert grades["oversized_chunks"] == "ok"

    def test_summarize(self, pdf_path):
        parents = [_parent("p0", [0, 0]), _parent("p0", [0, 0]), _parent("p2", [1, 1]), _parent("p3", [1, 1])]
        result = check_report(_report(parents=parents), pdf_path, 2000)
        summary = summarize(result)
        assert summary["status"] == "FAIL"
        assert "duplicate_parents" in summary["fail"]
        assert summarize({"error": "boom"}) == {"status": "error", "error": "boom"}


class TestRunQualityChecks:
    def test_returns_result_with_timing(self, pdf_path):
        result = run_quality_checks(_report(), pdf_path)
        assert result["status"] == "ok"
        assert result["elapsed_s"] >= 0

    def test_missing_pdf_returns_error(self, tmp_path):
        assert "error" in run_quality_checks(_report(), tmp_path / "missing.pdf")
        assert "error" in run_quality_checks(_report(), None)

    def test_malformed_report_returns_error(self, pdf_path):
        result = run_quality_checks({"child_chunks": [None], "parent_chunks": []}, pdf_path)
        assert "error" in result

    def test_footnote_index_dict_does_not_crash(self, pdf_path):
        # Assembly writes footnote_index keyed by number; the old check iterated it as a list
        report = _report()
        report["footnote_index"] = {"1": {"footnote_number": "1", "text": "Source: records"}}
        result = ValidationService().validate_report(report, enrichment_data={}, pdf_path=pdf_path)
        assert result["status"] == "ok"

    def test_validate_report_without_pdf_returns_error(self):
        assert "error" in ValidationService().validate_report(_report(), enrichment_data={})


class TestCli:
    def test_cli_runs_module_checks(self, tmp_path, pdf_path):
        processed, pdfs = tmp_path / "processed", tmp_path / "pdfs"
        processed.mkdir()
        pdfs.mkdir()
        parents = [_parent("p0", [0, 0])] * 2 + [_parent(f"p{i}", [1, 1]) for i in (1, 2, 3)]
        (processed / "XX_2025_01_Test_chunks.json").write_text(json.dumps(_report(parents=parents)))
        pdf_path.rename(pdfs / "XX_2025_01_Test.pdf")
        out = tmp_path / "out.json"
        proc = subprocess.run(
            [sys.executable, str(REPO / "scripts/evaluation/preflight_check.py"),
             "--processed-dir", str(processed), "--pdf-dir", str(pdfs), "--json-out", str(out)],
            capture_output=True, text=True, cwd=REPO,
        )
        assert proc.returncode == 1, proc.stderr
        assert "1 report(s) checked, 1 failed: XX_2025" in proc.stdout
        results = json.loads(out.read_text())
        assert results[0]["report"] == "XX_2025"
        assert results[0]["grades"]["duplicate_parents"] == "FAIL"
