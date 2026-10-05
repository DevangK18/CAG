"""Phase 5.5: heading test, one entry per number, placement by page and position."""

import pytest

from src.core.data_contracts import DocumentTask
from src.parsing_pipeline.modules.toc_reconciliation_service import TOCReconciliationService


@pytest.fixture
def service():
    svc = TOCReconciliationService(min_docling_headers=1)
    svc._body_size = 11.0
    return svc


def _h(title, page, y=100.0, bold=True, size=12.0, in_table=False):
    return {"title": title, "page": page, "y_position": y, "bbox": [50, y, 500, y + 14],
            "level": 2, "bold": bold, "size": size, "in_table": in_table}


@pytest.mark.parametrize("title,kw,reason", [
    ("2.3 Utilisation of grants", {}, None),
    ("Chapter-2 Results of Audit", {}, None),
    ("Executive Summary", {"bold": False, "size": 11.0}, None),
    ("Inflexible expenditure", {}, None),
    ("Recommendation 2.1", {}, "box_or_note"),
    ("The Department did not release ₹ 4.57 crore to the ULBs", {}, "amount"),
    ("Audit noticed that funds were not utilised.", {}, "sentence"),
    ("ii Devolution of Funds", {}, "list_item"),
    ("(a) Collection of user charges", {}, "list_item"),
    ("Source: Finance Accounts", {}, "box_or_note"),
    ("Name of Gram Panchayat", {"in_table": True}, "in_table"),
    ("Inflexible expenditure", {"bold": False, "size": 11.0}, "body_style"),
    ("3.1 Belongs to another chapter", {}, "chapter_mismatch"),
])
def test_heading_test(service, title, kw, reason):
    current = [[1, "Chapter-2 Results of Audit", 10]]
    admitted, rejected = service._admit_headers([_h(title, 12, **kw)], current)
    if reason is None:
        assert len(admitted) == 1, rejected
    else:
        assert [r for _, r in rejected] == [reason]


def test_repeated_row_label_rejected_but_known_sections_kept(service):
    headers = [_h("Gram Panchayats", 12), _h("Gram Panchayats", 30),
               _h("Recommendations", 14), _h("Recommendations", 32)]
    admitted, rejected = service._admit_headers(headers, [])
    assert [h["title"] for h in admitted] == ["Recommendations", "Recommendations"]
    assert {r for _, r in rejected} == {"repeated"}


def test_numbers_must_not_go_backwards(service):
    headers = [_h("2.3 Funds", 12), _h("2.1 Repeated in a box", 13), _h("2.4 Staff", 14)]
    admitted, rejected = service._admit_headers(headers, [[1, "Chapter-2 Audit", 10]])
    assert [h["title"] for h in admitted] == ["2.3 Funds", "2.4 Staff"]
    assert rejected[0][1] == "number_backwards"


def test_one_entry_per_chapter_and_section_number(service):
    current = [[1, "Chapter-3 Access to Education", 38], [2, "3.1 Enrolment", 38]]
    toc = current + [[1, "Chapter 3 Access to Education", 36], [1, "CHAPTER-III", 38],
                     [2, "3.1 Enrolment of children", 39], [2, "3.2 Dropouts", 40],
                     [2, "Appendix 3.1 List of schools", 90], [2, "Appendix 3.1 List of schools", 91]]
    result = service._dedupe_by_number(toc, current)
    titles = [e[1] for e in result]
    assert titles.count("Chapter-3 Access to Education") == 1
    assert "Chapter 3 Access to Education" not in titles and "CHAPTER-III" not in titles
    assert "3.1 Enrolment" in titles and "3.1 Enrolment of children" not in titles
    assert "3.2 Dropouts" in titles
    assert sum(t.startswith("Appendix 3.1") for t in titles) == 1


def test_place_entries_matches_on_page_and_orders_by_y(service):
    task = DocumentTask(report_id="r", source_url="", local_pdf_path="", initial_metadata={})
    toc = [[2, "Recommendation 2.1", 30], [2, "2.2 Financial Management", 30],
           [2, "1.4 Financial profile", 15]]
    headers = [_h("3.4 Financial profile", 36, y=476.0), _h("1.4 Financial profile", 15, y=210.0),
               _h("2.2 Financial Management", 30, y=160.0), _h("Recommendation 2.1", 30, y=73.0)]
    placed, positions = service._place_entries(task, toc, headers, {})
    assert [e[1] for e in placed] == ["1.4 Financial profile", "Recommendation 2.1", "2.2 Financial Management"]
    # The y of "1.4" comes from its own page, not from "3.4 Financial profile" on p.36
    assert positions["15_1.4 Financial profile"] == 210.0
    assert positions["30_2.2 Financial Management"] == 160.0
