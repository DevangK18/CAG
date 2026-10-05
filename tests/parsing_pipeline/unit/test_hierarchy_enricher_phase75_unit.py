"""
Phase 7.5 (hierarchy enricher) regression tests for B-7.5-01/02/03.

- Sub-section detection is scoped to parent membership, not page range.
- Detected sections are created once, with IDs that include the enclosing
  parent; the narrowest parent wins; no invented L1 parents.
- Safety valve: a bad result falls back to the input unchanged.
- Post-sync only touches re-parented children.
"""

import copy
import logging
from collections import Counter

import pytest

from src.core.data_contracts import ParentChunk
from src.parsing_pipeline.modules.hierarchy_enricher import (
    AGGRESSIVE_REASONS,
    DetectedSection,
    HierarchyEnricher,
    aggressive_for_reason,
    should_enrich_hierarchy,
)

RID = "BR_test"


def parent(pid, title, level, start, end, hierarchy=None):
    return {
        "chunk_id": pid,
        "report_id": RID,
        "toc_entry": title,
        "toc_level": level,
        "page_range_physical": [start, end],
        "page_range_logical": [str(start + 1), str(end + 1)],
        "hierarchy": hierarchy or {f"level_{level}": title},
    }


def child(cid, parent_dict, page, y, content, ctype="paragraph", hierarchy=None):
    h = dict(parent_dict["hierarchy"]) if hierarchy is None else hierarchy
    bbox = [50.0, float(y), 500.0, float(y) + 12.0]
    return {
        "chunk_id": cid,
        "parent_chunk_id": parent_dict["chunk_id"],
        "report_id": RID,
        "content_type": ctype,
        "content": content,
        "source_page_physical": page,
        "source_page_logical": str(page + 1),
        "source_bbox": bbox,
        "hierarchy": h,
        "metadata": {
            "location": {"page_physical": page, "page_logical": str(page + 1), "bbox": bbox},
            "hierarchy": dict(h),
        },
    }


def body(n):
    return f"Body paragraph {n} with enough words to never look like a heading at all."


def outside_count(parents, children, tol=0):
    lookup = {p["chunk_id"]: p for p in parents}
    n = 0
    for c in children:
        p = lookup[c["parent_chunk_id"]]
        s, e = p["page_range_physical"]
        if not (s - tol <= c["source_page_physical"] <= e + tol):
            n += 1
    return n


@pytest.fixture
def flat_overlapping():
    """BR-like flat TOC: a junk wide L1 'Corporation' [5, 30] overlaps
    'Organisational setup of PRIs 1.2' [10, 11] and 'Functioning of PRIs 1.3'
    [12, 14]. Children belong to exactly one parent (Phase 7 membership)."""
    corp = parent("p_corp", "Corporation", 1, 5, 30)
    org = parent("p_org", "Organisational setup of PRIs 1.2", 1, 10, 11)
    fun = parent("p_fun", "Functioning of PRIs 1.3", 1, 12, 14)
    children = [
        # Members of 'Organisational setup 1.2'
        child("c01", org, 10, 80, "1.2 Organisational set-up of PRIs", "header"),
        child("c02", org, 10, 120, body(2)),
        child("c03", org, 10, 300, "1.2.1 Structure of the Panchayats", "header"),
        child("c04", org, 10, 340, body(4)),
        child("c05", org, 11, 100, body(5)),
        child("c06", org, 11, 400, "1.2.2 Powers of the Gram Sabha", "header"),
        child("c07", org, 11, 440, body(7)),
        # Members of 'Functioning of PRIs 1.3'
        child("c08", fun, 12, 90, body(8)),
        child("c09", fun, 12, 200, "1.3.1 Standing Committees of PRIs", "header"),
        child("c10", fun, 13, 100, body(10)),
        child("c11", fun, 13, 300, "Recommendations", "header"),
        child("c12", fun, 14, 100, body(12)),
        # Members of 'Corporation' (its own content, pp. 20-21)
        child("c13", corp, 20, 100, body(13)),
        child("c14", corp, 20, 200, "2.1.1 Revenue of Municipal Corporations", "header"),
        child("c15", corp, 21, 100, body(15)),
        # Member of 'Corporation' with a custom hierarchy, before any heading
        child("c16", corp, 6, 100, body(16), hierarchy={"level_1": "Custom kept"}),
    ]
    return [corp, org, fun], children


class TestMembershipScoping:
    def test_unique_ids_and_single_detection(self, flat_overlapping):
        parents, children = flat_overlapping
        enricher = HierarchyEnricher()
        out_p, out_c = enricher.enrich_hierarchy(parents, children, RID, aggressive=True)

        assert enricher.last_outcome["status"] == "applied"
        ids = [p["chunk_id"] for p in out_p]
        assert len(ids) == len(set(ids))

        titles = Counter(p["toc_entry"] for p in out_p if p.get("detected_by"))
        # Each heading created exactly once (old code: under every overlapping parent)
        assert titles == Counter(
            {
                "1.2.1 Structure of the Panchayats": 1,
                "1.2.2 Powers of the Gram Sabha": 1,
                "1.3.1 Standing Committees of PRIs": 1,
                "2.1.1 Revenue of Municipal Corporations": 1,
            }
        )

    def test_sections_belong_to_the_parent_whose_members_they_are(self, flat_overlapping):
        parents, children = flat_overlapping
        out_p, out_c = HierarchyEnricher().enrich_hierarchy(parents, children, RID, aggressive=True)
        lookup = {p["chunk_id"]: p for p in out_p}
        by_title = {p["toc_entry"]: p for p in out_p}

        assert by_title["1.2.1 Structure of the Panchayats"]["parent_chunk_id"] == "p_org"
        assert by_title["1.3.1 Standing Committees of PRIs"]["parent_chunk_id"] == "p_fun"
        assert by_title["2.1.1 Revenue of Municipal Corporations"]["parent_chunk_id"] == "p_corp"

        # Every re-parented child stays inside its original parent's subtree
        original = {c["chunk_id"]: c["parent_chunk_id"] for c in children}
        for c in out_c:
            p = lookup[c["parent_chunk_id"]]
            if p.get("detected_by"):
                assert p["parent_chunk_id"] == original[c["chunk_id"]]

        # The wide 'Corporation' did not capture children of the narrow parents
        corp_tree = {"p_corp"} | {
            p["chunk_id"] for p in out_p if p.get("parent_chunk_id") == "p_corp"
        }
        assert {c["chunk_id"] for c in out_c if c["parent_chunk_id"] in corp_tree} == {
            "c13", "c14", "c15", "c16"
        }
        assert sum(1 for c in out_c if c["hierarchy"].get("level_1") == "Corporation") == 3

    def test_children_inside_parent_pages_and_assignment(self, flat_overlapping):
        parents, children = flat_overlapping
        out_p, out_c = HierarchyEnricher().enrich_hierarchy(parents, children, RID, aggressive=True)
        assert outside_count(out_p, out_c) == 0

        by_title = {p["toc_entry"]: p for p in out_p}
        sub = by_title["1.2.1 Structure of the Panchayats"]
        assert sub["page_range_physical"] == [10, 11]  # heading page -> last assigned child
        assigned = {c["chunk_id"] for c in out_c if c["parent_chunk_id"] == sub["chunk_id"]}
        assert assigned == {"c03", "c04", "c05"}
        # Content before the first sub-section stays with the original parent
        stay = {c["chunk_id"] for c in out_c if c["parent_chunk_id"] == "p_org"}
        assert stay == {"c01", "c02"}
        # Level is relative to the enclosing parent: "1.2.1" is one below "… 1.2" (B-7.5-01)
        assert by_title["1.2.1 Structure of the Panchayats"]["hierarchy"] == {
            "level_1": "Organisational setup of PRIs 1.2",
            "level_2": "1.2.1 Structure of the Panchayats",
        }

    def test_no_invented_l1_and_no_duplicate_of_existing_parent(self, flat_overlapping):
        parents, children = flat_overlapping
        out_p, _ = HierarchyEnricher().enrich_hierarchy(parents, children, RID, aggressive=True)
        new = [p for p in out_p if p.get("detected_by")]
        # "Recommendations" (standalone L1 pattern) under an L1 parent is not created
        assert all(p["toc_level"] > 1 for p in new)
        assert not any("Recommendation" in p["toc_entry"] for p in new)
        # "1.2 Organisational set-up of PRIs" duplicates the TOC parent "... 1.2"
        assert not any(p["toc_entry"].startswith("1.2 ") for p in new)


class TestNestedParents:
    def test_narrowest_parent_wins_for_same_heading(self):
        chapter = parent("p_ch", "Chapter 1 Overview", 1, 1, 20)
        sect = parent(
            "p_12", "1.2 Audit framework", 2, 5, 8,
            hierarchy={"level_1": "Chapter 1 Overview", "level_2": "1.2 Audit framework"},
        )
        children = [
            child("c1", chapter, 2, 100, body(1)),
            # The same heading emitted twice on p.6, once into each parent
            child("c2", chapter, 6, 200, "1.2.3 Findings on audit framework", "header"),
            child("c3", sect, 6, 200, "1.2.3 Findings on audit framework", "header"),
            child("c4", sect, 6, 260, body(4)),
            child("c5", sect, 7, 100, body(5)),
        ]
        enricher = HierarchyEnricher()
        out_p, out_c = enricher.enrich_hierarchy([chapter, sect], children, RID, aggressive=True)
        new = [p for p in out_p if p.get("detected_by")]
        assert len(new) == 1
        sub = new[0]
        assert sub["parent_chunk_id"] == "p_12"
        assert sub["toc_level"] == 3
        assert sub["hierarchy"] == {
            "level_1": "Chapter 1 Overview",
            "level_2": "1.2 Audit framework",
            "level_3": "1.2.3 Findings on audit framework",
        }
        moved = {c["chunk_id"] for c in out_c if c["parent_chunk_id"] == sub["chunk_id"]}
        assert moved == {"c3", "c4", "c5"}
        # The chapter's copy of the heading is left where it was
        assert next(c for c in out_c if c["chunk_id"] == "c2")["parent_chunk_id"] == "p_ch"

    def test_ids_include_enclosing_parent(self):
        s = DetectedSection(
            section_id="1.1.1", title="1.1.1 State Profile", level=3,
            page_physical=22, page_logical="4",
        )
        a = HierarchyEnricher._sub_parent_id(s, "parent_A", RID)
        b = HierarchyEnricher._sub_parent_id(s, "parent_B", RID)
        assert a != b

    def test_pydantic_parents_with_tuple_ranges(self):
        p = ParentChunk(
            chunk_id="p1", report_id=RID, hierarchy={"level_1": "Chapter"},
            page_range_physical=(0, 3), page_range_logical=("1", "4"),
            toc_entry="Chapter", toc_level=1,
        )
        pd = p.model_dump() if hasattr(p, "model_dump") else p.dict()
        children = [
            child("c1", pd, 1, 100, "1.1 Introduction to the audit", "header"),
            child("c2", pd, 2, 100, body(2)),
        ]
        out_p, out_c = HierarchyEnricher().enrich_hierarchy([p], children, RID)
        assert len(out_p) == 2
        assert out_c[1]["parent_chunk_id"] == out_p[1]["chunk_id"]


class TestSafetyValve:
    def test_rejected_result_returns_input_unchanged(self, flat_overlapping, monkeypatch, caplog):
        parents, children = flat_overlapping
        before_p, before_c = copy.deepcopy(parents), copy.deepcopy(children)
        enricher = HierarchyEnricher()
        monkeypatch.setattr(
            enricher, "_validate_enrichment", lambda *a, **k: ["3 duplicate parent ids"]
        )
        with caplog.at_level(logging.WARNING):
            out_p, out_c = enricher.enrich_hierarchy(parents, children, RID, aggressive=True)

        assert out_p is parents and out_c is children
        assert parents == before_p and children == before_c  # input never mutated
        assert enricher.last_outcome["status"] == "rejected"
        assert any(
            r.levelno == logging.WARNING and "rejected" in r.getMessage() for r in caplog.records
        )

    def test_valve_detects_duplicate_ids(self):
        e = HierarchyEnricher()
        p = [parent("a", "A", 1, 0, 5), parent("a", "A copy", 2, 0, 5)]
        c = [child("c1", p[0], 1, 10, body(1))]
        problems = e._validate_enrichment(p[:1], c, p, c, set())
        assert any("duplicate parent ids" in x for x in problems)

    def test_valve_detects_child_outside_parent_pages(self):
        e = HierarchyEnricher()
        big = parent("big", "Big", 1, 0, 50)
        sub = parent("sub", "1.1 Sub", 2, 10, 10)
        c_in = [child("c1", big, 20, 10, body(1))]
        c_out = copy.deepcopy(c_in)
        c_out[0]["parent_chunk_id"] = "sub"
        problems = e._validate_enrichment([big], c_in, [big, sub], c_out, {"c1"})
        assert any("outside" in x for x in problems)
        # +/-1 page is tolerated
        c_out[0]["source_page_physical"] = 11
        c_out[0]["metadata"]["location"]["page_physical"] = 11
        assert e._validate_enrichment([big], c_in, [big, sub], c_out, {"c1"}) == []

    def test_valve_detects_takeover_by_one_top_level_section(self):
        """The BR failure: 96% of children ending up under level_1 'Corporation'."""
        e = HierarchyEnricher()
        parents = [parent(f"p{i}", f"Section {i}", 1, i, i) for i in range(10)]
        c_in = [child(f"c{i}", parents[i % 10], i % 10, 10, body(i)) for i in range(50)]
        c_out = copy.deepcopy(c_in)
        for c in c_out:
            c["hierarchy"] = {"level_1": "Corporation"}
        problems = e._validate_enrichment(parents, c_in, parents, c_out, set())
        assert any("level_1" in x and "Corporation" in x for x in problems)

    def test_valve_allows_preexisting_concentration(self):
        e = HierarchyEnricher()
        p = parent("only", "Only", 1, 0, 9)
        c = [child(f"c{i}", p, i % 10, 10, body(i)) for i in range(20)]
        assert e._validate_enrichment([p], c, [p], c, set()) == []


class TestPostSync:
    def test_untouched_children_keep_their_hierarchy(self, flat_overlapping):
        parents, children = flat_overlapping
        before = copy.deepcopy(children)
        # Give an untouched member of 'Functioning' a hierarchy that differs from its parent
        children[7]["hierarchy"] = {"level_1": "Functioning of PRIs 1.3", "level_2": "kept"}
        out_p, out_c = HierarchyEnricher().enrich_hierarchy(parents, children, RID, aggressive=True)
        by_id = {c["chunk_id"]: c for c in out_c}

        assert by_id["c08"]["parent_chunk_id"] == "p_fun"
        assert by_id["c08"]["hierarchy"] == {"level_1": "Functioning of PRIs 1.3", "level_2": "kept"}
        assert by_id["c16"]["parent_chunk_id"] == "p_corp"
        assert by_id["c16"]["hierarchy"] == {"level_1": "Custom kept"}

        # Re-parented children do get their new parent's hierarchy, in both places
        lookup = {p["chunk_id"]: p for p in out_p}
        c04 = by_id["c04"]
        assert c04["hierarchy"] == lookup[c04["parent_chunk_id"]]["hierarchy"]
        assert c04["metadata"]["hierarchy"] == c04["hierarchy"]

        # Input dicts were not mutated
        before[7]["hierarchy"] = children[7]["hierarchy"]
        assert children == before


class TestTriggerConsistency:
    def test_aggressive_for_reason(self):
        assert AGGRESSIVE_REASONS == {"flat_hierarchy", "high_concentration", "oversized_parent"}
        for r in AGGRESSIVE_REASONS:
            assert aggressive_for_reason(r) is True
        assert aggressive_for_reason("few_parents") is False
        assert aggressive_for_reason(None) is False

    def test_flat_trigger_and_aggressive_flag_do_not_change_result(self, flat_overlapping):
        parents, children = flat_overlapping
        filler = [parent(f"f{i}", f"Filler {i}", 1, 40 + i, 40 + i) for i in range(10)]
        reason = should_enrich_hierarchy(parents + filler, children)
        assert reason == (True, "flat_hierarchy")
        a = HierarchyEnricher().enrich_hierarchy(parents, children, RID, aggressive=True)
        b = HierarchyEnricher().enrich_hierarchy(parents, children, RID, aggressive=False)
        assert a == b


class TestNumberedFit:
    """Only numbered sections that fit their enclosing parent create parents (B-7.5-01)."""

    @pytest.mark.parametrize("section_id,parent_number,parent_level,expected", [
        ("5.5.2", "5.5", 2, 3),
        ("5.5.2.1", "5.5", 2, 4),
        ("4.1.1", "5.5", 2, None),
        ("5.5", "5.5", 2, None),
        ("5.2", "5", 1, 2),
        ("2.1.1", None, 1, 2),
    ])
    def test_fit_level(self, section_id, parent_number, parent_level, expected):
        assert HierarchyEnricher._fit_level(section_id, parent_number, parent_level) == expected

    @pytest.mark.parametrize("title,number", [
        ("5.5 Planning and strategy", "5.5"),
        ("Planning and Strategy of Solid Waste 5.4", "5.4"),
        ("Chapter V Performance Audit", "5"),
        ("V PERFORMANCE AUDIT Urban Development", "5"),
        ("Corporation", None),
    ])
    def test_enclosing_number(self, title, number):
        assert HierarchyEnricher._enclosing_number({"toc_entry": title}) == number

    def test_list_items_never_create_parents(self):
        org = parent("p_org", "Organisational setup of PRIs 1.2", 1, 10, 12)
        children = [
            child("c1", org, 10, 80, "ii Devolution of Funds", "header"),
            child("c2", org, 10, 120, body(2)),
            child("c3", org, 11, 80, "(a) Collection of user charges", "header"),
            child("c4", org, 11, 120, body(4)),
            child("c5", org, 12, 80, "1.2.1 Structure of the Panchayats", "header"),
            child("c6", org, 12, 120, body(6)),
        ]
        out_p, _ = HierarchyEnricher().enrich_hierarchy([org], children, RID, aggressive=True)
        assert [p["toc_entry"] for p in out_p if p.get("detected_by")] == ["1.2.1 Structure of the Panchayats"]
