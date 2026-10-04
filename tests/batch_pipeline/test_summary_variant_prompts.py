"""
Sentinel tests for summary variant prompts.

State and local_body templates used to be f-strings containing ``{input}``, which
Python evaluated as the built-in ``input`` function. The rendered prompt said
``<built-in function input>`` where the report data should have been. These tests
render every tier x variant through the public ``get_summary_prompt`` the way
``batch_service`` does, and check that the report data actually lands in the prompt.
"""

import inspect
import re

import pytest

from src.batch_pipeline.prompts import summary_variants
from src.batch_pipeline.prompts.summary_variants import (
    VARIANTS,
    build_summary_input,
    get_summary_prompt,
)

SENTINEL = "SENTINEL_REPORT_DATA_7f3a"

# (tier, state_name, audit_category): local_body is covered with and without the
# ATIR branch, which injects extra text into the journalist and simple templates.
TIER_CASES = [
    ("union", None, "performance"),
    ("state", "Karnataka", "compliance"),
    ("local_body", "Bihar", "atir"),
    ("local_body", "Kerala", "performance"),
]

WRONG_CRORE = re.compile(
    r"1\s*crore\s*=\s*100\s*lakhs?\s*=\s*1\s*million", re.IGNORECASE
)


def _json_data(tier, state_name, audit_category, finding_text="Finding text"):
    return {
        "report_metadata": {
            "report_id": f"{tier}_2024_1_test",
            "report_title": f"Test {tier} Report",
            "report_no": "1",
            "report_type": "Performance Audit",
            "department": "Test Department",
            "government_body_type": tier,
            "state_name": state_name,
            "audit_category": audit_category,
        },
        "semantic_enrichment": {
            "statistics": {
                "findings": {
                    "total_count": 1,
                    "total_monetary_crore": 12.5,
                    "by_severity": {"high": 1},
                    "by_type": {"non_compliance": {"count": 1}},
                }
            },
            "findings": [
                {
                    "severity": "high",
                    "finding_type": "non_compliance",
                    "text": finding_text,
                    "monetary_value": 125_000_000,
                    "monetary_values": [{"raw_text": "`12.50 crore"}],
                    "chapter": "Chapter 2",
                    "section": "2.1",
                    "page": 14,
                }
            ],
            "recommendations": [
                {"text": "Strengthen controls", "chapter": "Chapter 2", "page": 20}
            ],
        },
        "child_chunks": [],
    }


def _case_id(case):
    tier, _, category = case
    return f"{tier}-{category}"


@pytest.mark.parametrize("case", TIER_CASES, ids=_case_id)
@pytest.mark.parametrize("variant", VARIANTS)
def test_sentinel_input_rendered(variant, case):
    data = _json_data(*case)
    prompt = get_summary_prompt(variant, SENTINEL, data)

    assert SENTINEL in prompt
    assert "<built-in function" not in prompt
    assert "{input}" not in prompt


@pytest.mark.parametrize("case", TIER_CASES, ids=_case_id)
@pytest.mark.parametrize("variant", VARIANTS)
def test_production_path_renders_report_data(variant, case):
    """Mirror batch_service: build_summary_input(data) then get_summary_prompt."""
    data = _json_data(*case, finding_text=f"Audit observed {SENTINEL} in records")
    summary_input = build_summary_input(data)
    prompt = get_summary_prompt(variant, summary_input, data)

    assert summary_input in prompt
    assert SENTINEL in prompt
    assert "<built-in function" not in prompt
    # build_summary_input embeds JSON (by_severity etc.); its braces must survive
    assert '{"high": 1}' in prompt


def test_guard_raises_on_fstring_input_template(monkeypatch):
    """The original bug: {input} interpolated inside an f-string."""

    def broken(*args, **kwargs):
        return f"Summarise this report.\n\n## Report Data\n{input}\n"

    monkeypatch.setattr(summary_variants, "_get_executive_prompt", broken)
    data = _json_data("state", "Karnataka", "compliance")

    with pytest.raises(ValueError, match="did not render the report data"):
        get_summary_prompt("executive", SENTINEL, data)


def test_guard_raises_when_template_has_no_input_placeholder(monkeypatch):
    def no_placeholder(*args, **kwargs):
        return "Summarise this report.\n"

    monkeypatch.setattr(summary_variants, "_get_policy_prompt", no_placeholder)
    data = _json_data("union", None, "performance")

    with pytest.raises(ValueError, match="did not render the report data"):
        get_summary_prompt("policy", SENTINEL, data)


def test_no_wrong_crore_conversion_in_source():
    source = inspect.getsource(summary_variants)
    assert not WRONG_CRORE.search(source)


@pytest.mark.parametrize("case", TIER_CASES, ids=_case_id)
@pytest.mark.parametrize("variant", VARIANTS)
def test_no_wrong_crore_conversion_in_rendered_prompt(variant, case):
    prompt = get_summary_prompt(variant, SENTINEL, _json_data(*case))
    assert not WRONG_CRORE.search(prompt)
