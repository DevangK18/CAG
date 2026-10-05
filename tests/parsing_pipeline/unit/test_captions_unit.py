"""Unit lines above tables and charts (captions module)."""

import pytest

from src.parsing_pipeline.modules.captions import is_unit_line, unit_of


@pytest.mark.parametrize("text,expected", [
    ("(Status in percentage)", True),
    ("(Figures represent percentage)", True),
    ("(unit: kg/tonne of hot metal)", True),
    ("(In per cent)", True),
    ("(Amount: ₹ in crore)", True),
    ("(Source: Finance Accounts)", False),
    ("(Refer Paragraph 2.1)", False),
    ("(i) Funds were spent", False),
])
def test_unit_lines(text, expected):
    assert is_unit_line(text) is expected


def test_money_unit_only_for_money_lines():
    assert unit_of("(Amount: ₹ in crore)") == "₹ in crore"
    assert unit_of("(Status in percentage)") is None
