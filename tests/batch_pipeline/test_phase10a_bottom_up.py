"""Phase 10a bottom-up summaries and request order (stubbed Gemini, no calls)."""
import hashlib
import json
import threading
from pathlib import Path

import pytest

from src.batch_pipeline.phase10a_runner import Phase10aRun, write_content_summaries
from src.batch_pipeline.prompts.summary_variants import build_summary_input, key_tables, rank_findings
from src.batch_pipeline.summary_tree import build_tree, coverage

RID = "R_2025_01"
TEXT = "Audit observed that the works costing ₹4.20 crore remained incomplete for three years. "


def parent(pid, *path):
    return {"chunk_id": pid, "toc_entry": path[-1], "hierarchy": {f"level_{i + 1}": t for i, t in enumerate(path)},
            "page_range_physical": [1, 2]}


def child(i, pid, text, ctype="paragraph"):
    return {"chunk_id": f"c{i}", "parent_chunk_id": pid, "content_type": ctype, "content": text}


def report(rid=RID, long_section=False):
    parents = [
        parent("P1", "Chapter 1 Introduction"),
        parent("P2", "Chapter 2 Findings"),
        parent("P21", "Chapter 2 Findings", "2.1 Delays"),
        parent("P22", "Chapter 2 Findings", "2.2 Payments"),
        parent("P23", "Chapter 2 Findings", "2.3 Short note"),
        parent("P24", "Chapter 2 Findings", "2.4 Repeated"),
        parent("P3", "Chapter 3 Conclusion"),
        parent("P31", "Chapter 3 Conclusion", "3.1 Overall"),
    ]
    def text(tag, n):
        return f"[{tag}] " + TEXT * n

    children = [
        child(1, "P1", text("intro", 5)),
        child(2, "P2", text("ch2", 4)),
        child(3, "P21", text("2.1", 6)),
        child(4, "P22", text("2.2", 6)),
        child(5, "P23", "Short."),
        child(6, "P24", text("2.4", 6)),
        child(7, "P31", text("3.1", 5)),
        child(8, "P22", "| a | b |\n|---|---|\n| 1 | 2 |", "table_markdown"),
    ]
    if long_section:
        children += [child(100 + i, "P21", text(f"2.1 part {i}", 20)) for i in range(30)]
    return {"report_metadata": {"report_id": rid, "report_title": "Report", "government_body_type": "union"},
            "parent_chunks": parents, "child_chunks": children}


def test_tree_folds_short_text_skips_duplicates_and_covers_everything():
    data = report()
    data["child_chunks"][5]["content"] = data["child_chunks"][2]["content"]
    tree = build_tree(data)
    assert [tree.nodes[r].title for r in tree.roots] == [
        "Chapter 1 Introduction", "Chapter 2 Findings", "Chapter 3 Conclusion"]
    assert tree.nodes["P23"].skip == "folded" and "Short." in tree.nodes["P2"].folded_text
    assert tree.nodes["P24"].skip == "duplicate"
    order = [n.node_id for n in tree.summarised()]
    assert order.index("P21") < order.index("P2") and order.index("P31") < order.index("P3")
    cov = coverage(tree)
    assert cov["median_chapter_share"] == 1.0
    # Only the duplicate's text is behind no summary
    assert 0 < cov["text_behind_no_summary"] < 0.2


def test_single_child_without_text_inherits_its_summary():
    tree = build_tree(report())
    p3 = tree.nodes["P3"]
    assert p3.own_text == "" and tree.needs_call(p3) is False


def test_long_text_is_split_into_parts_summarised_first():
    tree = build_tree(report(long_section=True), max_part_chars=5000)
    parts = [n for n in tree.nodes.values() if n.part_of == "P21"]
    assert len(parts) >= 2 and tree.nodes["P21"].own_text == ""
    assert coverage(tree)["median_chapter_share"] == 1.0


class StubService:
    """BatchService stand-in: records every request and answers at once."""

    def __init__(self, tmp_path, delay_overview=False):
        from src.core.phase10_models import Phase10ModelConfig

        self.model_config = Phase10ModelConfig()
        self.models = {r: getattr(self.model_config, r)
                       for r in ("overview", "executive", "journalist", "deep_dive", "simple", "policy")}
        self.max_tokens = {r: 1000 for r in self.models}
        self.retry_pause_s = None
        self.batch_jobs_dir = tmp_path
        self.prompts, self.order, self.saved = {}, [], {}
        self._lock = threading.Lock()
        self.cache = {}

    def _read_chunks(self, path):
        return json.loads(json.dumps(self.cache[str(path)]))

    def _process_single_gemini(self, prompt, model, max_tokens, custom_id, tag, thinking=None):
        with self._lock:
            self.prompts[custom_id] = prompt
            self.order.append((tag, custom_id))
        content = '{"audit_scope": {"period": "2019-24"}, "audit_objectives": ["Check works"]}' \
            if tag.endswith("overview") else f"Summary of {custom_id}."
        return {"custom_id": custom_id, "content": content, "error": None}

    def _source_pdf_path(self, data):
        return Path("/nonexistent.pdf")

    def _save_overview_results(self, results, ids):
        self.saved["overview"] = results

    def _save_summary_results(self, results, ids, grounding=None):
        self.saved["summary"] = results

    def get_hierarchical_output_path(self, report_id):
        return self.batch_jobs_dir / f"{report_id}_hierarchical.json"


def run(tmp_path, reports):
    service = StubService(tmp_path)
    for i, data in enumerate(reports):
        service.cache[f"f{i}.json"] = data
    r = Phase10aRun(service, [f"f{i}.json" for i in range(len(reports))], "ts")
    r.run(max_workers=8)
    return service, r


def test_requests_wait_for_their_inputs(tmp_path):
    service, r = run(tmp_path, [report(), report("R_2025_02")])
    tags = [t for t, _ in service.order]
    assert tags.count("phase10a.overview") == 2 and tags.count("phase10a.summary") == 10
    for rid in ("R_2025_01", "R_2025_02"):
        rep = r.reports[rid]
        variant_prompts = [p for cid, p in service.prompts.items() if cid.startswith("sm_") and rid in cid]
        assert len(variant_prompts) == 5
        # Variants see every chapter summary and the overview's scope
        assert all("# CHAPTER SUMMARIES" in p and "2019-24" in p for p in variant_prompts)
        assert rep.roots_left == 0 and rep.overview_done
    saved = json.loads((tmp_path / "R_2025_01_hierarchical.json").read_text())
    assert saved["method"] == "bottom_up" and {c["title"] for c in saved["chapter_summaries"]} == {
        "Chapter 1 Introduction", "Chapter 2 Findings", "Chapter 3 Conclusion"}
    chapter_prompt = next(p for cid, p in service.prompts.items() if "Chapter: Chapter 2 Findings" in p)
    assert "2.1 Delays:" in chapter_prompt and "2.2 Payments:" in chapter_prompt


def _prompt_hashes(service):
    return {cid: hashlib.sha1(p.encode()).hexdigest() for cid, p in service.prompts.items()}


def test_prompts_are_the_same_whether_10b_writes_first_or_not(tmp_path):
    """BatchService.preload reads the files before Phase 10b changes them."""
    from src.batch_pipeline.batch_service import BatchService

    files = []
    for rid in ("R_2025_01", "R_2025_02"):
        path = tmp_path / f"{rid}_chunks.json"
        path.write_text(json.dumps(report(rid)))
        files.append(path)

    def service_for(files_to_preload):
        svc = BatchService.__new__(BatchService)
        svc._chunks_cache = {}
        svc.preload(files_to_preload)
        stub = StubService(tmp_path)
        stub._read_chunks = svc._read_chunks
        return stub

    before = service_for(files)
    # Phase 10b rewrites the chunk files (image captions hydrated) after preload
    for path in files:
        data = json.loads(path.read_text())
        data["child_chunks"][0]["content"] = "HYDRATED BY 10b"
        path.write_text(json.dumps(data))
    Phase10aRun(before, files, "ts").run(max_workers=4)

    for path, rid in zip(files, ("R_2025_01", "R_2025_02")):
        path.write_text(json.dumps(report(rid)))
    after = service_for(files)
    Phase10aRun(after, files, "ts").run(max_workers=4)
    assert _prompt_hashes(before) == _prompt_hashes(after)


def test_summaries_written_to_parents(tmp_path):
    chunk_file = tmp_path / "R_chunks.json"
    chunk_file.write_text(json.dumps(report()))
    hier = tmp_path / "R_hierarchical.json"
    hier.write_text(json.dumps({"chapter_summaries": [{"parent_chunk_id": "P2", "summary": "Chapter two."}],
                                "section_summaries": [{"parent_chunk_id": "P21", "summary": "Delays."}]}))
    assert write_content_summaries(chunk_file, hier) == 2
    parents = {p["chunk_id"]: p for p in json.loads(chunk_file.read_text())["parent_chunks"]}
    assert parents["P2"]["content_summary"] == "Chapter two." and parents["P21"]["content_summary"] == "Delays."


def test_variant_input_ranks_findings_and_uses_cited_tables():
    long_text = "Audit noticed losses. " * 60
    findings = [
        {"finding_id": "a", "severity": "low", "monetary_value_paise": 10, "text": "low one",
         "source_chunk_id": "c1"},
        {"finding_id": "b", "severity": "critical", "monetary_value_paise": 5, "text": long_text,
         "evidence_links": [{"evidence_type": "table", "evidence_id": "t2"}]},
        {"finding_id": "c", "severity": "critical", "monetary_value_paise": 50, "text": "big critical"},
        {"finding_id": "d", "severity": "critical", "monetary_value_paise": 99, "text": "restated",
         "is_restatement": True},
    ]
    assert [f["finding_id"] for f in rank_findings(findings)] == ["c", "b", "a", "d"]
    tables = [{"chunk_id": f"t{i}", "content_type": "table_markdown", "content": f"| table {i} |",
               "parent_chunk_id": "P9"} for i in range(1, 12)]
    data = {"report_metadata": {"report_title": "R"},
            "semantic_enrichment": {"findings": findings, "statistics": {"findings": {"total_monetary_crore": 999}},
                                    "section_classifications": [{"chunk_id": "PX", "section_type": "executive_summary"}]},
            "child_chunks": tables + [{"chunk_id": "e1", "parent_chunk_id": "PX", "content_type": "paragraph",
                                       "content": "The executive summary says the scheme failed in many districts."}]}
    text = build_summary_input(data, chapter_summaries=[("Chapter 2", "Chapter two summary.")])
    assert "999" not in text  # no summed total line
    assert long_text.strip()[:1000] in text  # not cut at 600 characters
    assert text.index("big critical") < text.index("low one")
    assert "The executive summary says" in text and "# CHAPTER SUMMARIES" in text
    assert [t["chunk_id"] for t in key_tables(data, rank_findings(findings))][0] == "t2"


@pytest.mark.parametrize("has_summaries", [True, False])
def test_indexer_reads_parent_summaries(has_summaries):
    from src.rag_pipeline.indexer import Indexer

    indexer = Indexer.__new__(Indexer)
    indexer._summaries_from_chunks = {}
    upserted = []
    indexer.qdrant_service = type("Q", (), {"upsert_hierarchical_summaries": lambda self, pts: upserted.extend(pts)})()
    indexer.embedding_service = type("E", (), {"dense_service": type("D", (), {"embed_single": lambda self, t: [0.1]})()})()
    parents = [{"chunk_id": "P2", "toc_entry": "Chapter 2", "hierarchy": {"level_1": "Chapter 2"},
                "content_summary": "Chapter two." if has_summaries else None},
               {"chunk_id": "P21", "toc_entry": "2.1", "hierarchy": {"level_1": "Chapter 2", "level_2": "2.1"},
                "content_summary": "Delays." if has_summaries else None}]
    count = indexer.index_parent_summaries("R", parents, "union")
    assert count == (2 if has_summaries else 0)
    if has_summaries:
        assert {p["payload"]["content_type"] for p in upserted} == {"chapter_summary", "section_summary"}


@pytest.mark.parametrize("content,empty", [
    ("", True), ("   ", True), ("data/extraction_images/charts/x.png", True), ("x.PNG", True),
    ("Chart: enrolment 2019-24", False), ("OVERVIEW", False),
])
def test_image_chunks_without_text_are_not_indexed(content, empty):
    from src.rag_pipeline.indexer import _empty_image_chunk

    assert _empty_image_chunk({"content_type": "image_caption", "content": content}) is empty
    assert _empty_image_chunk({"content_type": "paragraph", "content": ""}) is False


def test_empty_audit_period_filled_from_overview(tmp_path):
    data = report()
    data["semantic_enrichment"] = {"temporal_coverage": {"audit_period": None},
                                   "findings": [{"finding_id": "f1", "audit_period": None}]}
    chunk_file = tmp_path / "R_chunks.json"
    chunk_file.write_text(json.dumps(data))
    overview = tmp_path / "R_overview.json"
    overview.write_text(json.dumps({"audit_scope": {"period": {"start": "2018-19", "end": "2022-23"}}}))
    write_content_summaries(chunk_file, tmp_path / "missing.json", overview)
    enrichment = json.loads(chunk_file.read_text())["semantic_enrichment"]
    period = enrichment["temporal_coverage"]["audit_period"]
    assert period and period.get("start_year") == 2018 and enrichment["findings"][0]["audit_period"] == period
