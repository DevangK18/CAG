"""Every reader of the output works on files written before PR 9 and after it.

One old file (PR 8 schema: *_inr names, no restatement fields, old totals, top-down
summaries) and one new file (PR 9 schema) are served side by side.
"""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.batch_pipeline import process_results
from src.core.data_contracts import Finding, Recommendation

OLD, NEW = "2024_01_Old_Report", "2025_01_New_Report"
NEW_ONLY = {"extraction_method", "source_chunk_ids", "location", "is_restatement", "restates",
            "total_amount_paise", "monetary_value_paise"}


def finding(rid, n, crore, **extra):
    paise = int(crore * 1e9)
    return Finding(finding_id=f"{rid}_finding_{n:03d}", report_id=rid, text=f"Audit observed a loss of ₹{crore} crore.",
                   summary="Loss", finding_type="loss_of_revenue", severity="high", monetary_value_paise=paise,
                   monetary_value_crore=crore, total_amount_paise=paise, page=10, chapter="Chapter 2",
                   source_chunk_id=f"{rid}_c{n}", **extra).model_dump()


def old_finding(rid, n, crore):
    f = finding(rid, n, crore)
    return {k: v for k, v in f.items() if k not in NEW_ONLY}


def chunk_file(rid, new):
    findings = ([finding(rid, 1, 5.0, location="chapter"), finding(rid, 2, 5.0, location="executive_summary",
                                                                 is_restatement=True, restates=f"{rid}_finding_001")]
                if new else [old_finding(rid, 1, 5.0), old_finding(rid, 2, 5.0)])
    rec = Recommendation(recommendation_id=f"{rid}_rec_001", report_id=rid, text="The Ministry may recover the loss.",
                         summary="Recover", page=12).model_dump()
    stats = {"findings": {"total_count": 2, "total_monetary_crore": 10.0, "by_severity": {"high": 2}, "by_type": {}}}
    if new:
        stats["findings"].update({"distinct_count": 1, "restatement_count": 1, "impact_sum_crore": 5.0,
                                  "impact_sum_finding_count": 1, "largest_finding_crore": 5.0})
    return {
        "report_metadata": {"report_id": rid, "report_title": f"Report {rid}", "report_no": "1 of 2025",
                            "government_body_type": "union", "source_filename": f"{rid}.pdf"},
        "parent_chunks": [{"chunk_id": f"{rid}_P1", "toc_entry": "Chapter 2", "toc_level": 1,
                           "hierarchy": {"level_1": "Chapter 2"}, "page_range_physical": [9, 12],
                           "content_summary": "Chapter two." if new else None}],
        "child_chunks": [{"chunk_id": f"{rid}_c1", "parent_chunk_id": f"{rid}_P1", "content_type": "paragraph",
                          "content": "Audit observed a loss of ₹5.0 crore.", "source_page_physical": 10}],
        "semantic_enrichment": {"findings": findings, "recommendations": [rec], "statistics": stats,
                                "section_classifications": [], "entities": {}},
    }


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    from src.api.routes import overview, summaries
    from src.api.services import report_service

    processed = tmp_path / "data" / "processed" / "union"
    processed.mkdir(parents=True)
    sums = tmp_path / "data" / "batch_jobs" / "summaries"
    sums.mkdir(parents=True)
    for rid, new in ((OLD, False), (NEW, True)):
        path = processed / f"{rid}_chunks.json"
        path.write_text(json.dumps(chunk_file(rid, new)))
        # The overview file the routes read is built from the chunk file
        (processed / f"{rid}_overview.json").write_text(json.dumps(process_results.extract_overview_from_json(path)))
        (sums / f"{rid}_summaries.json").write_text(json.dumps({
            "report_id": rid, "variants": {"executive": {"content": "## Context & Scope\nAudit of X.", "word_count": 4}},
            "variant_count": 1}))
    monkeypatch.setattr(overview, "DATA_DIR", tmp_path / "data" / "processed")
    monkeypatch.setattr(overview, "SUMMARIES_DIR", sums)
    monkeypatch.setattr(summaries, "BATCH_JOBS_DIR", tmp_path / "data" / "batch_jobs")
    monkeypatch.setattr(summaries, "SUMMARIES_DIR", sums)
    settings = type("S", (), {"PROCESSED_DIR": tmp_path / "data" / "processed", "BASE_DIR": tmp_path})()
    monkeypatch.setattr(report_service, "settings", settings)
    monkeypatch.setattr(report_service, "_initialized", False)
    return tmp_path


@pytest.fixture
def client(data_dir):
    from src.api.routes import overview, reports, summaries

    app = FastAPI()
    app.include_router(reports.router, prefix="/api/reports")
    app.include_router(overview.router, prefix="/api")
    app.include_router(summaries.router, prefix="/api")
    return TestClient(app)


@pytest.mark.parametrize("rid", [OLD, NEW])
def test_findings_route(client, rid):
    body = client.get(f"/api/reports/{rid}/findings").json()
    assert body["total"] == 2 and all(f["amount_crore"] == 5.0 for f in body["findings"])
    flags = [f["is_restatement"] for f in body["findings"]]
    assert flags == ([False, True] if rid == NEW else [False, False])


@pytest.mark.parametrize("rid", [OLD, NEW])
def test_recommendations_route(client, rid):
    body = client.get(f"/api/reports/{rid}/recommendations").json()
    assert body["total"] == 1 and body["recommendations"][0]["text"].startswith("The Ministry")


@pytest.mark.parametrize("rid", [OLD, NEW])
def test_overview_and_summaries_routes(client, rid):
    overview = client.get(f"/api/reports/{rid}/overview").json()
    assert overview["findings_summary"]["total_count"] == 2
    assert (overview["findings_summary"]["impact_sum_crore"] == 5.0) is (rid == NEW)
    assert client.get(f"/api/reports/{rid}/summaries").status_code == 200


@pytest.mark.parametrize("rid", [OLD, NEW])
def test_report_detail_route(client, rid):
    detail = client.get(f"/api/reports/{rid}").json()
    if rid == NEW:
        assert detail["findings_count"] == 1  # the restatement is not a second finding
        assert detail["monetary_impact"] == "₹5.00 crore"
        assert detail["monetary_impact_label"] == "Sum of amounts cited in 1 finding"
    else:
        assert detail["findings_count"] == 2 and detail["monetary_impact"] is None


@pytest.mark.parametrize("new", [False, True])
def test_index_payload(new):
    from src.rag_pipeline.embedding_service import SemanticPayloadExtractor

    data = chunk_file(NEW if new else OLD, new)
    payload = SemanticPayloadExtractor().extract_for_chunk(data["child_chunks"][0], data["semantic_enrichment"])
    assert payload["finding_type"] == "loss_of_revenue" and payload["total_amount_crore"] == 5.0


@pytest.mark.parametrize("new", [False, True])
def test_entity_graph_reads_finding_text(tmp_path, new):
    from src.entity_graph.entity_service import ChunkLoader

    rid = NEW if new else OLD
    (tmp_path / "union").mkdir()
    (tmp_path / "union" / f"{rid}_chunks.json").write_text(json.dumps(chunk_file(rid, new)))
    loader = ChunkLoader(tmp_path)
    assert "loss" in loader.get_finding_description(f"{rid}_finding_001")
