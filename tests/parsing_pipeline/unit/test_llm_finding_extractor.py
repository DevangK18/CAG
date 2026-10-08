"""Phase 9 Gemini extraction: planning, item checks, amounts, fallback and restatements (no calls)."""
import json
from types import SimpleNamespace

import pytest

from src.core.data_contracts import Finding, SectionClassification
from src.parsing_pipeline.instrumentation import get_noop_emitter
from src.parsing_pipeline.modules.enrichment import llm_finding_extractor as lfx
from src.parsing_pipeline.modules.enrichment.llm_items import cited_paragraphs, mark_restatements
from src.parsing_pipeline.modules.semantic_enrichment_service import SemanticEnrichmentService

RID = "2025_99_Test_Report"


def chunk(i, content, ctype="paragraph", level_1="Chapter 2 Audit findings", page=10, parent="P2"):
    return {
        "chunk_id": f"{RID}_child_p{page:03d}_{ctype}_{i:04d}",
        "parent_chunk_id": parent,
        "content_type": ctype,
        "content": content,
        "hierarchy": {"level_1": level_1},
        "source_page_physical": page,
    }


CHILDREN = [
    chunk(0, "Executive Summary", "header", level_1="Executive Summary", page=2, parent="P1"),
    chunk(1, "Audit noticed that the Society paid ₹3.15 crore to a contractor without sanction (Paragraph 2.1).",
          level_1="Executive Summary", page=2, parent="P1"),
    chunk(2, "2.1 Irregular payment", "header"),
    chunk(3, "Audit observed that the Society released ₹3.15 crore to the contractor without the sanction of "
             "the competent authority. The payment of ₹40 lakh for design was also irregular."),
    chunk(4, "The Ministry stated (June 2024) that the payment was regularised. The reply is not acceptable."),
    chunk(5, "Recommendation 2.1: The Ministry may ensure that payments are made only after sanction."),
    chunk(6, "A footnote", "footnote"),
]
METADATA = {"report_id": RID, "report_title": "Report No. 99 of 2025 (Compliance Audit)",
            "government_body_type": "union", "report_type": "Compliance Audit"}


def plan():
    return lfx.plan_calls(RID, METADATA, CHILDREN, "compliance", max_chars=24000)


def record(items, status="ok", p=None):
    p = p or plan()
    results = [lfx.CallResult(c.call_id, status, items if i == 0 else []) for i, c in enumerate(p.calls)]
    return lfx.extraction_record(p, results, {"model": "gemini-3.8-flash", "thinking_level": "low",
                                              "temperature": "default"})


def test_plan_numbers_only_paragraphs_and_lists_and_shows_headings():
    p = plan()
    assert p.numbering == {1: CHILDREN[1]["chunk_id"], 2: CHILDREN[3]["chunk_id"],
                           3: CHILDREN[4]["chunk_id"], 4: CHILDREN[5]["chunk_id"]}
    text = p.calls[0].text
    assert "# 2.1 Irregular payment" in text and "[C2] Audit observed" in text
    assert "footnote" not in text
    assert "## Section: Executive Summary" in text and "compliance audit" in p.instruction


def test_plan_splits_long_sections_at_chunk_boundaries():
    long = [chunk(i, "Audit observed a shortfall. " * 40) for i in range(10)]
    p = lfx.plan_calls(RID, METADATA, long, "general", max_chars=3000)
    assert len(p.calls) > 2
    assert sorted(n for c in p.calls for n in c.numbers) == list(range(1, 11))
    assert all(len(c.text) <= 3000 + 200 for c in p.calls)


def test_find_anchor_ignores_case_whitespace_and_punctuation():
    content = 'Audit  observed that the "Society" released ₹3.15 crore'
    assert lfx.find_anchor(content, "audit observed that the Society released") == 0
    assert lfx.find_anchor(content, "the Society paid") == -1


def test_check_items_drops_bad_numbers_and_unfound_anchors():
    items = [
        {"kind": "finding", "chunks": [2], "anchor": "Audit observed that the Society released"},
        {"kind": "finding", "chunks": [99], "anchor": "Audit observed that the Society released"},
        {"kind": "finding", "chunks": [3], "anchor": "This text is not in the chunk at all"},
        {"kind": "finding", "chunks": [2], "anchor": "Audit observed that the Society released"},
    ]
    kept, stats = lfx.check_items(record(items), CHILDREN)
    assert len(kept) == 1
    assert stats == {"returned": 4, "kept": 1, "bad_chunk_number": 1, "anchor_not_found": 1, "duplicate": 1}


def test_items_in_one_chunk_split_its_text_and_get_stable_ids():
    items = [
        {"kind": "finding", "chunks": [2], "anchor": "Audit observed that the Society released"},
        {"kind": "finding", "chunks": [2], "anchor": "The payment of ₹40 lakh for design"},
    ]
    kept, _ = lfx.check_items(record(items), CHILDREN)
    assert kept[0].text.endswith("competent authority.")
    assert kept[1].text.startswith("The payment of ₹40 lakh")
    again, _ = lfx.check_items(record(list(reversed(items))), CHILDREN)
    assert [k.item_id for k in kept] == [k.item_id for k in again]
    assert kept[0].item_id.endswith("_1") and kept[1].item_id.endswith("_2")


def test_multi_chunk_item_starts_where_its_anchor_is():
    items = [{"kind": "finding", "chunks": [2, 3], "anchor": "Audit observed that the Society released"}]
    kept, _ = lfx.check_items(record(items), CHILDREN)
    assert kept[0].chunk_ids == [CHILDREN[3]["chunk_id"], CHILDREN[4]["chunk_id"]]
    assert "reply is not acceptable" in kept[0].text


def test_amount_comes_from_the_text_not_the_model():
    from src.parsing_pipeline.modules.enrichment.monetary_processor import MonetaryProcessor

    by_id = {c["chunk_id"]: c for c in CHILDREN}
    items = [{"kind": "finding", "chunks": [2], "anchor": "Audit observed that the Society released",
              "impact_chunk": 2, "impact_text": "₹3.15 crore"}]
    kept, _ = lfx.check_items(record(items), CHILDREN)
    _, primary = lfx.impact_amount(kept[0], by_id, MonetaryProcessor())
    assert primary.value.normalized_paise == 3_150_000_000

    # An amount the text does not print is never used
    kept[0].impact_text = "₹9.99 crore"
    _, primary = lfx.impact_amount(kept[0], by_id, MonetaryProcessor())
    assert primary is None


def test_build_from_llm_findings_recommendations_and_restatement():
    items = [
        {"kind": "finding", "chunks": [1], "anchor": "Audit noticed that the Society paid",
         "impact_chunk": 1, "impact_text": "₹3.15 crore", "finding_type": "irregular_expenditure"},
        {"kind": "finding", "chunks": [2, 3], "anchor": "Audit observed that the Society released",
         "impact_chunk": 2, "impact_text": "₹3.15 crore", "finding_type": "irregular_expenditure"},
        {"kind": "recommendation", "chunks": [4], "anchor": "Recommendation 2.1: The Ministry may ensure",
         "rec_number": "2.1", "addressee": "Ministry"},
    ]
    svc = SemanticEnrichmentService()
    sections = [SectionClassification(chunk_id="P1", section_title="Executive Summary",
                                      section_type="executive_summary", confidence=0.9)]
    findings, recs, stats = svc._extract_findings_and_recommendations(
        RID, [{"chunk_id": "P1"}, {"chunk_id": "P2", "toc_entry": "2.1 Irregular payment"}], CHILDREN,
        sections, "union", record(items), get_noop_emitter())
    assert stats["method"] == "llm" and stats["items"]["kept"] == 3
    exec_f, chapter_f = findings
    assert chapter_f.extraction_method == "llm" and chapter_f.monetary_value_crore == 3.15
    assert chapter_f.section == "2.1 Irregular payment" and not chapter_f.is_restatement
    assert exec_f.is_restatement and exec_f.location == "executive_summary"
    assert exec_f.restates == chapter_f.finding_id
    (rec,) = recs
    assert rec.extraction_strategy == "llm" and rec.target_entity == "Ministry" and rec.rec_number == "2.1"


def test_failed_section_falls_back_to_regex_and_is_counted():
    svc = SemanticEnrichmentService()
    findings, _, stats = svc._extract_findings_and_recommendations(
        RID, [], CHILDREN, [], "union", record([], status="failed"), get_noop_emitter())
    assert stats["calls_failed"] == len(plan().calls)
    assert findings and all(f.extraction_method == "regex_fallback" for f in findings)


def test_regex_cross_check_counts_but_does_not_add():
    svc = SemanticEnrichmentService()
    findings, _, stats = svc._extract_findings_and_recommendations(
        RID, [], CHILDREN, [], "union", record([]), get_noop_emitter())
    assert findings == [] and stats["regex_only_findings"] >= 1


def test_without_llm_record_regex_runs_alone():
    svc = SemanticEnrichmentService()
    findings, _, stats = svc._extract_findings_and_recommendations(
        RID, [], CHILDREN, [], "union", None, get_noop_emitter())
    assert stats == {"method": "regex"} and findings


def test_cited_paragraphs():
    assert cited_paragraphs("(Paras 2.1.1, 2.1.2 and 2.3)") == ["2.1.1", "2.1.2", "2.3"]
    assert cited_paragraphs("as discussed in Paragraph 4.2") == ["4.2"]


def test_restatement_needs_a_match():
    f1 = Finding(finding_id="a", report_id=RID, text="Overall the scheme fell short.", summary="",
                 finding_type="other", severity="low", source_chunk_id=CHILDREN[1]["chunk_id"])
    f2 = Finding(finding_id="b", report_id=RID, text="Weather stations were idle for years.", summary="",
                 finding_type="other", severity="low", source_chunk_id=CHILDREN[3]["chunk_id"])
    mark_restatements([f1, f2], CHILDREN, [])
    assert f1.is_restatement and f1.restates is None and not f2.is_restatement


def test_run_call_parses_items_and_reports_failures():
    p = plan()
    response = SimpleNamespace(
        text=json.dumps({"items": [{"kind": "finding", "chunks": [2], "anchor": "Audit observed"}]}),
        parsed=None, usage_metadata=None, candidates=[])
    client = SimpleNamespace(models=SimpleNamespace(generate_content=lambda **kw: response))
    result = lfx.run_call(p, p.calls[0], "gemini-3.8-flash", "low", client=client)
    assert result.status == "ok" and result.items[0]["chunks"] == [2]

    def fail(**kw):
        raise ValueError("400 INVALID_ARGUMENT")

    bad = lfx.run_call(p, p.calls[0], "gemini-3.8-flash", "low",
                       client=SimpleNamespace(models=SimpleNamespace(generate_content=fail)))
    assert bad.status == "failed" and "INVALID_ARGUMENT" in bad.error


def test_run_plans_yields_every_report_in_order():
    p1, p2 = plan(), lfx.plan_calls("other", METADATA, CHILDREN, "general")
    response = SimpleNamespace(text='{"items": []}', parsed=None, usage_metadata=None, candidates=[])
    client = SimpleNamespace(models=SimpleNamespace(generate_content=lambda **kw: response))
    settings = {"model": "gemini-3.8-flash", "thinking_level": "low", "temperature": "default"}
    out = list(lfx.run_plans([p1, p2], settings, client=client))
    assert [rid for rid, _ in out] == [RID, "other"]
    assert out[0][1]["calls"][0]["status"] == "ok" and out[0][1]["model"] == "gemini-3.8-flash"


@pytest.mark.parametrize("calls_failed,expected", [(0, False), (2, True)])
def test_fallback_sections_are_losses(calls_failed, expected):
    from src.parsing_pipeline.main import PipelineOrchestrator
    from src.parsing_pipeline.pipeline_state import PipelineState

    orch = PipelineOrchestrator.__new__(PipelineOrchestrator)
    orch.state = PipelineState()
    orch._record_phase9_extraction("R", {"method": "llm", "calls": 5, "calls_failed": calls_failed})
    assert ("R" in orch.state.phase9_losses) is expected
    assert orch.state.phase9_extraction["R"]["calls"] == 5


def test_anchor_tolerates_footnote_markers_and_runs_on_from_a_lead_in_chunk():
    assert lfx.find_anchor("INCOIS had many commitments[^8] in the field", "INCOIS had many commitments in the field") == 0
    index, offset = lfx.locate_anchor(
        ["Rule 37 requires budgets.", "Audit noticed that:", "• In seven out of 85 schools, no fire NOC."],
        "Audit noticed that: • In seven out of 85",
    )
    assert (index, offset) == (1, 0)
