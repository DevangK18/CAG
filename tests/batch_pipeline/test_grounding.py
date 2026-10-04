"""
Number grounding check for summaries (D-10a-07).

Calibrated on real output: the regenerated 2025_38 union summaries (correct, with
rounded figures) pass at the 10% threshold, while the OD_2025_05 summaries written
without report input (invented figures) fail. The fixtures below reproduce both
cases in miniature.
"""

import pytest

from src.batch_pipeline.grounding import (
    DEFAULT_THRESHOLD_PCT,
    build_source_text,
    check_grounding,
    numbers,
    source_numbers,
)

UNION_CHUNKS = {
    "report_metadata": {
        "report_id": "2025_38_Performance_Audit_of_Blast_Furnace",
        "report_title": "Performance Audit of Blast Furnace",
        "report_no": "38",
        "report_year": 2025,
    },
    "parent_chunks": [
        {"toc_entry": "Chapter 3 Capital expenditure 2018-19 to 2022-23"},
    ],
    "child_chunks": [
        {"content": "3.4.2 The company incurred `6,259.25 crore on relining of 14 blast furnaces."},
        {"content": "Avoidable expenditure of Rs.1,23,456.78 lakh was noticed in 23 units."},
        {"content": "Hot metal output fell short by 45.67 per cent against the target of 2,150 tonnes."},
        {
            "content": "| Year | Loss |",
            "structured_data": {"rows": [["2021-22", 387.04]]},
        },
    ],
}

# Figures as a good summary writes them: rounded, truncated, regrouped.
CORRECT_UNION_SUMMARY = """# Executive Brief
Report No. 38 of 2025 examined 14 blast furnaces over 2018-19 to 2022-23.
- Relining cost ₹6,259.3 crore (about ₹6,259 crore).
- Avoidable expenditure of ₹1,23,456 lakh across 23 units.
- Output fell short by 45.7% (45.67 per cent) against 2,150 tonnes.
- The 2021-22 loss was ₹387 crore (p.112, para 3.4.2).
"""

# Figures that are not in the report, including the old prompt examples.
FABRICATED_SUMMARY = """# Headlines
Government Lost ₹12,000 Crore to Contract Irregularities: Audit
- ₹12,000 Crore is enough to build 2,400 government schools.
- 60% of plants missed targets; ₹1,200 Crore was diverted.
- Enough to give ₹1,000 to 12 crore families.
- Relining cost ₹6,259 crore.
"""


@pytest.fixture
def union_source():
    return build_source_text(UNION_CHUNKS)


def test_correct_union_summary_with_rounded_figures_passes(union_source):
    result = check_grounding(CORRECT_UNION_SUMMARY, union_source)
    assert result["ungrounded"] == 0, result["examples"]
    assert result["grounded"] is True
    assert set(result) == {"numbers", "ungrounded", "ungrounded_pct", "examples", "grounded"}


def test_fabricated_summary_fails(union_source):
    result = check_grounding(FABRICATED_SUMMARY, union_source)
    assert result["grounded"] is False
    assert result["ungrounded_pct"] > DEFAULT_THRESHOLD_PCT
    assert "12000" in result["examples"]
    assert "60" in result["examples"]
    assert "6259" not in result["examples"]


def test_threshold_is_configurable(union_source):
    text = "Relining cost ₹6,259 crore and ₹999 crore for 14 furnaces and 23 units."
    result = check_grounding(text, union_source)
    assert (result["numbers"], result["ungrounded"]) == (4, 1)
    assert result["grounded"] is False  # 25% > 10%
    assert check_grounding(text, union_source, threshold_pct=25)["grounded"] is True


def test_accepts_precomputed_source_numbers(union_source):
    known = source_numbers(union_source)
    assert check_grounding(CORRECT_UNION_SUMMARY, known) == check_grounding(
        CORRECT_UNION_SUMMARY, union_source
    )


def test_summary_without_numbers_is_grounded():
    result = check_grounding("No amounts are stated.", "₹5,000 crore")
    assert result == {
        "numbers": 0, "ungrounded": 0, "ungrounded_pct": 0.0, "examples": [], "grounded": True,
    }


@pytest.mark.parametrize(
    "source, summary",
    [
        ("1,23,45,678", "12345678"),  # Indian grouping
        ("12345678", "1,23,45,678"),
        ("123,456,789", "12,34,56,789"),  # Western vs Indian grouping
        ("6,259.25", "6,259.3"),  # rounded to 1 dp
        ("6,259.25", "6259.2"),  # truncated to 1 dp
        ("6,259.25", "6,259"),  # rounded to integer
        ("2.675", "2.68"),  # half-up, not banker's rounding
        ("12.50", "12.5"),  # trailing zero
        ("Rs.500 crore", "500"),
    ],
)
def test_rounding_truncation_and_grouping(source, summary):
    assert check_grounding(summary, source)["ungrounded"] == 0


@pytest.mark.parametrize(
    "source, summary",
    [
        ("6,259.25", "6,260"),  # rounding to tens is a new figure
        ("6,259.25", "6,300"),
        ("387.04", "387.4"),
        ("1,500 crore", "15"),
    ],
)
def test_other_numbers_are_ungrounded(source, summary):
    assert check_grounding(summary, source)["ungrounded"] == 1


def test_numbers_skips_small_counts_page_cites_and_ordinals():
    text = "Para 3.4.2 (p.91, pp.12) lists 7 units, the 15th Finance Commission and 45.5%."
    assert numbers(text) == ["3.4", "45.5"]


def test_build_source_text_reads_chunks_parents_metadata_and_tables(union_source):
    for fragment in ["6,259.25", "2018-19", "Blast Furnace", "387.04", "38"]:
        assert fragment in union_source


def test_build_source_text_adds_pdf_text(tmp_path):
    fitz = pytest.importorskip("fitz")
    pdf = tmp_path / "r.pdf"
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "Only the PDF says 4,321.5 crore")
    doc.save(pdf)
    doc.close()

    assert "4321.5" not in source_numbers(build_source_text({"child_chunks": []}))
    assert "4321.5" in source_numbers(build_source_text({"child_chunks": []}, pdf))
    # A missing PDF is not an error: the pipeline may not have it
    assert build_source_text({"child_chunks": []}, tmp_path / "missing.pdf") == ""
