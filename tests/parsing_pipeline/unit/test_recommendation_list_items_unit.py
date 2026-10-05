"""Recommendation sections whose items arrive as separate list chunks."""

from src.parsing_pipeline.modules.enrichment.recommendation_extractor import RecommendationExtractor


def test_modal_may_items_in_a_recommendations_section():
    chunks = [
        {"chunk_id": f"c{i}", "parent_chunk_id": "p_recs", "content_type": "list", "content": text,
         "source_page_physical": 11, "hierarchy": {"level_1": "Executive Summary", "level_2": "Recommendations"}}
        for i, text in enumerate([
            "2) MoES may clearly define the revised targets commensurate with the resources.",
            "4) INCOIS may devise and follow a systematic procurement and deployment plan.",
            "The audit findings are summarised below for the Ministry and INCOIS.",
        ])
    ]
    recs = RecommendationExtractor()._extract_from_sections(chunks, {"p_recs"}, "R")
    assert [r.text[:2] for r in recs] == ["2)", "4)"]
