"""Page and money conversions in the API consumers (PR 6, section 7).

Page convention: every API page field is the 0-based physical page; the
frontend's toViewerPage() is the only place that adds 1. Server-composed
labels (citation keys, chart/table titles) print the 1-based physical page.
"""

from types import SimpleNamespace

import pytest

from src.api.services import asset_service, report_service, streaming_wrapper
from src.api.utils.table_utils import disambiguate_table_names


# =============================================================================
# N-01: chat citations
# =============================================================================


def _rag_citation(page, section="2.3 Toll collection"):
    return SimpleNamespace(
        report_id="2023_07_NHAI",
        section=section,
        page=page,  # 1-based label, as RAGService.build_citations sets it
        score=0.9,
        finding_type=None,
        severity=None,
        amount_crore=None,
        entities_mentioned=[],
        section_type=None,
        is_recommendation=False,
    )


@pytest.fixture
def no_registry(monkeypatch):
    monkeypatch.setattr(streaming_wrapper, "get_report_by_id", lambda _id: None)


def test_citation_page_physical_is_zero_based(no_registry):
    [c] = streaming_wrapper._convert_citations([_rag_citation(page=37)])
    # The label the LLM cites stays 1-based ...
    assert c.citation_key == "2.3 Toll collection, p.37"
    assert c.page_logical == "37"
    # ... and the navigation field is the 0-based physical page, so the
    # frontend's single +1 opens page 37, not 38.
    assert c.page_physical == 36


def test_citation_on_first_page(no_registry):
    [c] = streaming_wrapper._convert_citations([_rag_citation(page=1)])
    assert c.page_physical == 0


def test_citation_map_keeps_label_key(no_registry):
    citations = streaming_wrapper._convert_citations([_rag_citation(page=5)])
    cmap = streaming_wrapper._build_citation_map(citations)
    assert cmap["2.3 Toll collection, p.5"]["page_physical"] == 4


# =============================================================================
# Assets: page is 0-based physical, titles print 1-based
# =============================================================================


def _chunks_doc():
    return {
        "child_chunks": [
            {
                "chunk_id": "c1",
                "content_type": "paragraph",
                "content": "Figure 2.1: Trend of toll revenue",
                "source_page_physical": 0,
                "hierarchy": {"level_1": "Chapter 2"},
            },
            {
                # Same page as the formal title: must be skipped as a duplicate
                "chunk_id": "c2",
                "content_type": "chart_data_path",
                "content": "",
                "source_page_physical": 0,
                "structured_data": {"title": "dup"},
            },
            {
                "chunk_id": "c3",
                "content_type": "chart_data_path",
                "content": "",
                "source_page_physical": 4,
                "structured_data": None,
            },
            {
                "chunk_id": "t1",
                "content_type": "table_markdown",
                "content": "| A | B |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |",
                "source_page_physical": 0,
                "hierarchy": {},
            },
        ]
    }


@pytest.fixture
def fake_report(monkeypatch):
    monkeypatch.setattr(asset_service, "_load_report_json", lambda _id: _chunks_doc())


def test_chart_pages_are_zero_based(fake_report):
    charts = asset_service.extract_charts("r", use_cache=False)
    by_id = {c.source_chunk_id: c for c in charts}
    assert by_id["c1"].page == 0
    assert "c2" not in by_id  # deduplicated against c1 on the same page
    assert by_id["c3"].page == 4
    assert by_id["c3"].title == "Chart (Page 5)"


def test_table_page_is_zero_based(fake_report):
    [table] = asset_service.extract_tables("r", use_cache=False)
    assert table.page == 0
    assert table.title.endswith("Page 1")


def test_table_disambiguation_labels_first_page():
    tables = [
        {"title": "Status of works", "page": 0},
        {"title": "Status of works", "page": 6},
    ]
    names = [t["display_caption"] for t in disambiguate_table_names(tables)]
    assert names == ["Status of works (Page 1)", "Status of works (Page 7)"]


# =============================================================================
# N-03: monetary_impact
# =============================================================================


def test_old_total_is_not_shown():
    # Files written before the sum existed: their "total" could count money twice
    semantic = {"statistics": {"findings": {"total_monetary_crore": 1234.5}}}
    assert report_service._format_monetary_impact(semantic) is None
    assert report_service._monetary_impact_label(semantic) is None
    assert report_service._format_monetary_impact({"monetary_statistics": {"total_amount_crore": 12.0}}) is None


def test_sum_shown_with_its_label():
    semantic = {"statistics": {"findings": {"impact_sum_crore": 1234.5, "impact_sum_finding_count": 12,
                                            "total_monetary_crore": 1234.5}}}
    assert report_service._format_monetary_impact(semantic) == "₹1,234.50 crore"
    assert report_service._monetary_impact_label(semantic) == "Sum of amounts cited in 12 findings"
    one = {"statistics": {"findings": {"impact_sum_crore": 3.0, "impact_sum_finding_count": 1}}}
    assert report_service._monetary_impact_label(one) == "Sum of amounts cited in 1 finding"


@pytest.mark.parametrize("semantic", [{}, {"statistics": {"findings": {"impact_sum_crore": 0, "impact_sum_finding_count": 0}}}])
def test_monetary_impact_none_without_amount(semantic):
    assert report_service._format_monetary_impact(semantic) is None


# =============================================================================
# N-05: extract_other_findings treats total_amount_* as paise
# =============================================================================


@pytest.fixture
def extract_monetary_value():
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "scripts/pipeline/extract_other_findings.py"
    spec = importlib.util.spec_from_file_location("extract_other_findings", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.extract_monetary_value


@pytest.mark.parametrize(
    "finding, expected",
    [
        ({"total_amount_inr": 1_000_000_000}, "₹1.00 Cr"),  # 1e9 paise = 1 crore
        ({"total_amount_inr": 25_000_000_000}, "₹25.00 Cr"),
        ({"total_amount_inr": 50_000_000}, "₹5.00 L"),  # 5 lakh
        ({"total_amount_inr": 123_400}, "₹1,234"),  # rupees
        ({"total_amount_paise": 1_000_000_000}, "₹1.00 Cr"),
        ({}, "none"),
    ],
)
def test_extract_monetary_value_paise(extract_monetary_value, finding, expected):
    assert extract_monetary_value(finding) == expected


# =============================================================================
# Qdrant payload: a missing logical page is "", not "None"
# =============================================================================


def test_embedding_payload_page_logical_none():
    from src.rag_pipeline.embedding_service import EmbeddingService

    svc = EmbeddingService.__new__(EmbeddingService)
    svc.prepare_text_for_embedding = lambda *a, **k: "text"
    svc.dense_service = SimpleNamespace(embed_batch=lambda texts, _p: [[0.0] for _ in texts])
    svc.sparse_service = None

    chunk = {"chunk_id": "c", "content": "x", "source_page_physical": 3, "source_page_logical": None}
    _, _, _, [payload] = svc.process_chunks([chunk], [], None, show_progress=False)
    assert payload["page_physical"] == 3
    assert payload["page_logical"] == ""


# =============================================================================
# N-07: overview prompt labels page numbers as 0-based indices
# =============================================================================


def test_overview_prompt_page_labels():
    from src.batch_pipeline.prompts.overview_extraction import build_overview_prompt

    doc = {
        "parent_chunks": [{"toc_entry": "Chapter 2", "toc_level": 1, "page_range_physical": [17, 30]}],
        "child_chunks": [
            {
                "content_type": "paragraph",
                "hierarchy": {"level_1": "Introduction"},
                "content": "This audit examined toll collection across plazas.",
                "source_page_physical": 3,
            }
        ],
        "report_metadata": {},
    }
    prompt = build_overview_prompt(doc)
    # Same 0-based numbers that topics_covered stores, but no "p.N" label
    # that reads as a page a human would look up.
    assert "Chapter 2 (page index 17)" in prompt
    assert "[page index 3]" in prompt
    assert "(p.17)" not in prompt
