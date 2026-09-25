"""
Tests for Phase 10b request hygiene: non-data images are not sent to Gemini,
and malformed JSON responses are re-requested.
"""

import asyncio
from types import SimpleNamespace

from google.genai import types

from src.batch_pipeline.enrichment.gemini_visual_extractor import GeminiVisualExtractor
from src.batch_pipeline.prompts.summary_variants import get_summary_prompt


def _extractor():
    return GeminiVisualExtractor.__new__(GeminiVisualExtractor)


def _image_chunk(page, bbox):
    return {"source_page_physical": page, "metadata": {"location": {"bbox": bbox}}}


def test_signature_and_cover_images_skipped():
    ext = _extractor()
    assert ext._is_non_data_image(_image_chunk(110, [300, 600, 420, 655]))  # signature ~120x55
    assert ext._is_non_data_image(_image_chunk(0, [196, 389, 400, 606]))  # cover-page logo


def test_chart_sized_images_kept():
    ext = _extractor()
    assert not ext._is_non_data_image(_image_chunk(40, [80, 200, 276, 370]))  # smallest real chart
    assert not ext._is_non_data_image(_image_chunk(40, [70, 300, 520, 450]))  # wide, short chart


def test_invalid_json_is_re_requested():
    ext = _extractor()
    replies = iter(['{"chart_type": "bar", "series": [1,', '{"chart_type": "bar"}'])
    mime_types = []

    async def fake_generate(**kwargs):
        mime_types.append(kwargs["config"].response_mime_type)
        return SimpleNamespace(text=next(replies))

    ext._generate = fake_generate
    result = asyncio.run(ext._generate_json(
        "chart", model="m", contents=[],
        config=types.GenerateContentConfig(temperature=0.1, max_output_tokens=8192),
    ))
    assert result["success"] and result["chart_type"] == "bar"
    assert mime_types == ["application/json", "application/json"]


def test_summary_input_quotes_amounts_not_sums():
    data = {
        "report_metadata": {"report_title": "T", "government_body_type": "union"},
        "semantic_enrichment": {
            "statistics": {"findings": {"total_count": 1, "total_monetary_crore": 500.0}},
            "findings": [{
                "text": "Excess of ` 500 crore against ` 120 crore",
                "severity": "high",
                "monetary_value": 500 * 10**9,
                "total_amount_inr": 620 * 10**9,
                "monetary_values": [{"raw_text": "` 500 crore"}, {"raw_text": "` 120 crore"}],
            }],
        },
    }
    from src.batch_pipeline.prompts.summary_variants import build_summary_input

    summary_input = build_summary_input(data)
    assert "Amounts cited: ₹ 500 crore; ₹ 120 crore" in summary_input
    assert "62,000" not in summary_input  # old paise/1e7 bug: 620 crore shown as 62,000
    prompt = get_summary_prompt("policy", summary_input, data)
    assert "Never output fill-in placeholders" in prompt
    assert "Template" not in prompt
