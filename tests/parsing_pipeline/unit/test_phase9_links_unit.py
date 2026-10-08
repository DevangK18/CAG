"""
Phase 9 links and classification: cross-references, executive-summary citations,
previous-audit references, audit period, section roles and entities.
"""

import pytest

from src.parsing_pipeline.modules.enrichment.cross_reference_resolver import (
    CrossReferenceResolver,
    ReferenceIndex,
    expand_number_list,
    find_references,
    normalize_appendix_id,
    roman_to_int,
)
from src.parsing_pipeline.modules.enrichment.entity_extractor import EntityExtractor
from src.parsing_pipeline.modules.enrichment.executive_summary_parser import (
    ExecutiveSummaryParser,
)
from src.parsing_pipeline.modules.enrichment.section_classifier import SectionClassifier
from src.parsing_pipeline.modules.enrichment.temporal_extractor import (
    TemporalExtractor,
    fill_audit_period_from_overview,
)


def parent(chunk_id, title, level_1=None, level=None, page=1):
    hierarchy = {"level_1": level_1 or title}
    if level_1 and level_1 != title:
        hierarchy["level_2"] = title
    return {
        "chunk_id": chunk_id,
        "toc_entry": title,
        "toc_level": level or (1 if not level_1 or level_1 == title else 2),
        "hierarchy": hierarchy,
        "page_range_physical": [page, page],
    }


def child(chunk_id, parent_id, content, content_type="paragraph", page=1, **extra):
    return {
        "chunk_id": chunk_id,
        "parent_chunk_id": parent_id,
        "content": content,
        "content_type": content_type,
        "source_page_physical": page,
        **extra,
    }


def refs(text, kinds=("para", "section", "chapter", "table", "appendix")):
    return [(r.kind, r.target) for r in find_references(text, kinds)]


# ── reference parsing ─────────────────────────────────────────────────────


class TestReferenceParsing:
    def test_lists_ranges_and_ampersands(self):
        assert expand_number_list("2.1.1, 2.1.2, 2.2 and 2.3") == [
            "2.1.1",
            "2.1.2",
            "2.2",
            "2.3",
        ]
        assert expand_number_list("3.1 to 3.4") == ["3.1", "3.2", "3.3", "3.4"]
        assert expand_number_list("3.5.3 & 3.5.4.2.") == ["3.5.3", "3.5.4.2"]

    def test_plural_paras(self):
        assert refs("(Paras 2.1.1, 2.1.2, 2.2 and 2.3)") == [
            ("para", "2.1.1"),
            ("para", "2.1.2"),
            ("para", "2.2"),
            ("para", "2.3"),
        ]

    def test_chapter_forms(self):
        assert refs("discussed in Chapter-4 of this report") == [("chapter", "4")]
        assert refs("Chapter - III") == [("chapter", "3")]
        assert refs("Chapters 5 and 6 of this Report") == [
            ("chapter", "5"),
            ("chapter", "6"),
        ]
        assert roman_to_int("XIV") == 14

    def test_other_documents_skipped(self):
        assert refs("Paragraph 4.4.1 of SSIF suggests") == []
        assert refs("Section 2.1 of the Act provides") == []
        assert refs("Chapter VI of GFR") == []
        assert refs("Para 3.1 of the Report No. 5 of 2020") == []
        assert refs("NEP 2020 (Paragraph 6.9) envisages") == []
        # This report's own
        assert refs("Para 3.2.2 of Chapter 3") == [("para", "3.2.2"), ("chapter", "3")]
        assert refs("Paragraph 4.2.1 of this Report") == [("para", "4.2.1")]

    def test_table_needs_capitalised_keyword_and_no_year(self):
        assert refs("the time table 2019-20") == []
        assert refs("as given in Table-6 (i)") == [("table", "6(i)")]

    def test_appendix_ids(self):
        assert normalize_appendix_id("Appendix-15 (ii)") == "15(ii)"
        assert normalize_appendix_id("Annexure IV") == "4"
        assert refs("(Appendix-3(i))", ("appendix",)) == [("appendix", "3(i)")]
        assert refs("Appendix 2.1 to 2.3", ("appendix",)) == [
            ("appendix", "2.1"),
            ("appendix", "2.2"),
            ("appendix", "2.3"),
        ]
        assert refs("Annexure Details", ("appendix",)) == []


# ── cross-reference resolver ──────────────────────────────────────────────


class TestCrossReferences:
    def setup_method(self):
        self.parents = [
            parent("ch1", "Chapter-1 Introduction"),
            parent("s11", "1.1 Background", "Chapter-1 Introduction"),
            parent("ch3", "Chapter III Ocean Observation"),
            parent(
                "s321", "3.2.1 Procurement", "Chapter III Ocean Observation", level=3
            ),
        ]

    def test_table_caption_is_not_a_reference(self):
        table = child(
            "t1",
            "s321",
            "Table 3.2: Funds released\n| a | b |\n| --- | --- |",
            "table_markdown",
            structured_data={"table_number": "3.2"},
        )
        caption = child("cap", "s321", "Table 3.3: Staff in position", "caption")
        text = child(
            "p1", "s11", "The funds are given in Table 3.2 and staff in Table 3.3."
        )
        found = CrossReferenceResolver().resolve_references(
            [table, caption, text], self.parents
        )
        assert [(x["source_chunk_id"], x["reference_target"]) for x in found] == [
            ("p1", "3.2"),
            ("p1", "3.3"),
        ]
        assert all(x["resolved"] for x in found)
        assert found[0]["resolved_chunk_id"] == "t1"

    def test_table_found_by_caption_before_it(self):
        caption = child("cap", "s321", "Table 4: Details of staff", "caption", page=5)
        table = child(
            "t1", "s321", "| a | b |\n| --- | --- |", "table_markdown", page=5
        )
        index = ReferenceIndex(self.parents, [caption, table])
        assert index.tables["4"]["chunk_id"] == "t1"

    def test_chapter_dash_and_roman(self):
        chunks = [child("p1", "s11", "Discussed in Chapter 3 and in Chapter I below.")]
        found = CrossReferenceResolver().resolve_references(chunks, self.parents)
        assert {x["reference_target"]: x["resolved_chunk_id"] for x in found} == {
            "3": "ch3",
            "1": "ch1",
        }

    def test_deep_paragraph_falls_back_to_ancestor(self):
        chunks = [child("p1", "s11", "as stated in Para 3.2.1.4 above")]
        found = CrossReferenceResolver().resolve_references(chunks, self.parents)
        assert found[0]["resolved_chunk_id"] == "s321"
        assert found[0]["resolved_by"] == "ancestor"

    def test_chapter_heading_is_not_a_reference(self):
        chunks = [child("h", "ch3", "Chapter III: Ocean Observation", "header")]
        assert CrossReferenceResolver().resolve_references(chunks, self.parents) == []

    def test_contents_table_skipped(self):
        toc = child(
            "toc",
            "ch1",
            "| | Chapter | Page No. |\n| --- | --- | --- |\n| Chapter I | Intro | 1 |",
            "table_markdown",
        )
        assert CrossReferenceResolver().resolve_references([toc], self.parents) == []

    def test_one_entry_per_target_per_chunk(self):
        chunks = [child("p1", "s11", "Para 3.2.1 shows this; (Para 3.2.1) again.")]
        assert (
            len(CrossReferenceResolver().resolve_references(chunks, self.parents)) == 1
        )


# ── executive summary ─────────────────────────────────────────────────────


class TestExecutiveSummary:
    def setup_method(self):
        self.parents = [
            parent("es", "Executive Summary"),
            parent("es_sub", "Key Audit Findings", "Executive Summary"),
            parent("es_rec", "Recommendations", "Executive Summary"),
            parent("ch2", "Chapter II Management"),
            parent("s211", "2.1.1 Delays", "Chapter II Management", level=3),
            parent("s22", "2.2 Funds", "Chapter II Management"),
            parent("s23", "2.3 Staff", "Chapter II Management"),
        ]

    def parse(self, children):
        return ExecutiveSummaryParser().parse_executive_summary(
            self.parents, children, []
        )

    def test_standalone_citation_joins_previous_item(self):
        index = self.parse(
            [
                child(
                    "c1",
                    "es_sub",
                    "Audit noticed delays in approval of projects and release of funds.",
                ),
                child("c2", "es_sub", "(Paras 2.1.1, 2.2 & 2.3)"),
            ]
        )
        assert index["total_items"] == 1
        item = index["items"][0]
        assert item["paragraph_citations"] == ["2.1.1", "2.2", "2.3"]
        assert item["resolved_chunk_ids"] == ["s211", "s22", "s23"]
        assert item["item_type"] == "finding"

    def test_whole_subtree_and_ranges(self):
        index = self.parse(
            [
                child(
                    "c1",
                    "es_rec",
                    "The Ministry may consider reviewing staffing norms (Paragraphs 2.2 to 2.3).",
                ),
            ]
        )
        assert index["items"][0]["paragraph_citations"] == ["2.2", "2.3"]
        assert index["items"][0]["item_type"] == "recommendation"

    def test_finding_cues_win_over_ensure(self):
        parser = ExecutiveSummaryParser()
        text = "Audit noticed that the Department did not ensure timely release, leading to delays."
        assert parser._item_type(text, None) == "finding"

    def test_numbered_title_found(self):
        parents = [
            parent("es", "5.Executive Summary"),
            parent("x", "Chapter 1 Introduction"),
        ]
        chunks = [
            child(
                "c1",
                "es",
                "Audit observed shortfall in utilisation of funds during 2019-22.",
            )
        ]
        index = ExecutiveSummaryParser().parse_executive_summary(parents, chunks, [])
        assert index["total_items"] == 1

    def test_table_rows_become_items(self):
        table = (
            "| GLYPH<1> | In three ULBs, funds of ₹4.74 crore remained unutilised. (Paragraph 2.2) |\n"
            "| GLYPH<1> | Six ULBs sanctioned advances without adjustment of earlier ones. (Paragraph 2.3) |"
        )
        index = self.parse([child("t", "es_sub", table, "table_markdown")])
        assert [i["paragraph_citations"] for i in index["items"]] == [["2.2"], ["2.3"]]


# ── temporal ──────────────────────────────────────────────────────────────


class TestAuditPeriod:
    @pytest.mark.parametrize(
        "text,period",
        [
            ("Audit covered the activities for the period 2017-2022 and", (2017, 2022)),
            (
                "test audit done for the period 2017-18 and 2018-19, as well",
                (2017, 2019),
            ),
            ("accounts for the year 2022-23 were examined", (2022, 2023)),
            ("covering the period 2020-21", (2020, 2021)),
            ("during FY 2018-19 to FY 2020-21", (2018, 2021)),
            ("during the period 2015-22", (2015, 2022)),
            ("during 2016-17 audit of 45 GPs", (2016, 2017)),
        ],
    )
    def test_forms(self, text, period):
        result = TemporalExtractor().extract_audit_period(text)
        assert (result["start_year"], result["end_year"]) == period

    def test_scope_before_trend_tables(self):
        chunks = [
            child(
                "i1",
                "intro",
                "Funds allotted for the period from 2014-15 to 2018-19 are in Table-2.",
            ),
            child(
                "s1",
                "scope",
                "During the year 2017-18, test-check of accounts of 45 GPs was done.",
            ),
            child(
                "s2",
                "scope",
                "During the year 2018-19, test-check of 103 GPs was done.",
            ),
        ]
        sections = [
            {"chunk_id": "intro", "section_type": "introduction"},
            {"chunk_id": "scope", "section_type": "audit_scope"},
        ]
        result = TemporalExtractor().extract_temporal_metadata(chunks, sections)
        assert result["audit_period"] == {"start_year": 2017, "end_year": 2019}

    def test_fill_from_overview(self):
        coverage = {"audit_period": None}
        overview = {
            "audit_scope": {
                "period": {
                    "start": "2018-19",
                    "end": "2022-23",
                    "description": "5 years",
                }
            }
        }
        assert fill_audit_period_from_overview(coverage, overview) is True
        assert coverage["audit_period"] == {"start_year": 2018, "end_year": 2023}
        assert coverage["audit_period_source"] == "overview"

    def test_fill_keeps_existing_and_handles_missing(self):
        coverage = {"audit_period": {"start_year": 2019, "end_year": 2021}}
        assert (
            fill_audit_period_from_overview(
                coverage, {"audit_scope": {"period": {"start": "2010-11"}}}
            )
            is False
        )
        assert (
            fill_audit_period_from_overview(
                {"audit_period": None}, {"audit_scope": None}
            )
            is False
        )
        coverage = {"audit_period": None}
        overview = {
            "audit_scope": {
                "period": {
                    "start": None,
                    "end": None,
                    "description": "April 2019 to March 2022",
                }
            }
        }
        assert fill_audit_period_from_overview(coverage, overview) is True
        assert coverage["audit_period"] == {"start_year": 2019, "end_year": 2022}


class TestPreviousAuditRefs:
    def test_atn_inside_place_names_is_not_a_reference(self):
        text = (
            "Observatories at Visakhapatnam and Ratnagiri were set up in January 2022."
        )
        assert TemporalExtractor().extract_previous_audit_refs(text) == []

    def test_atn_year_in_same_sentence_only(self):
        extractor = TemporalExtractor()
        assert (
            extractor.extract_previous_audit_refs(
                "ATNs were awaited. Funds of 2019 lapsed."
            )
            == []
        )
        assert [
            r["year"]
            for r in extractor.extract_previous_audit_refs(
                "ATNs due in 2019 were awaited."
            )
        ] == [2019]

    def test_own_report_number_excluded(self):
        chunks = [
            {
                "content": "Report No. 8 of 2025 (Compliance Audit)",
                "report_no": "08 of 2025",
            },
            {
                "content": "This was pointed out in Report No. 12 of 2019.",
                "report_no": "08 of 2025",
            },
        ]
        refs_found = TemporalExtractor().extract_temporal_metadata(chunks, None)[
            "previous_audit_refs"
        ]
        assert [r["raw_text"] for r in refs_found] == ["Report No. 12 of 2019"]

    def test_two_references_same_year_both_kept(self):
        chunks = [
            {"content": "Pending paras from 2018 noted."},
            {"content": "This was pointed out in Report No. 4 of 2018."},
        ]
        refs_found = TemporalExtractor().extract_temporal_metadata(chunks, None)[
            "previous_audit_refs"
        ]
        assert len(refs_found) == 2


# ── section roles ─────────────────────────────────────────────────────────


class TestSectionRoles:
    def setup_method(self):
        self.parents = [
            parent("fm", "Front matter"),
            parent("pre", "Preface"),
            parent("es", "Executive Summary"),
            parent(
                "es1",
                "Key Audit Findings and Recommendations Project Management",
                "Executive Summary",
            ),
            parent("ch1", "Chapter I Introduction"),
            parent("s11", "1.1 About INCOIS", "Chapter I Introduction"),
            parent("s16", "1.6 Audit Objectives", "Chapter I Introduction"),
            parent("s18", "1.8 Audit Scope and Sampling", "Chapter I Introduction"),
            parent("ch2", "Chapter II Management of Projects"),
            parent(
                "s21",
                "2.1 Delays in approval of projects",
                "Chapter II Management of Projects",
            ),
            parent("s24", "2.4 Conclusion", "Chapter II Management of Projects"),
            parent("s25", "2.5 Recommendations", "Chapter II Management of Projects"),
            parent(
                "r31",
                "Recommendation 3.1 Review the norms",
                "Chapter II Management of Projects",
            ),
            parent("ann", "Annexures"),
            parent("app", "Appendix 2.1 Statement of savings", "List of Appendices"),
            parent("abb", "Abbreviations"),
        ]

    def types(self, children=None):
        results = SectionClassifier().classify_sections(self.parents, children)
        return {r.chunk_id: r for r in results}

    def test_roles_from_position_and_title(self):
        t = {k: v.section_type for k, v in self.types().items()}
        assert t == {
            "fm": "front_matter",
            "pre": "preface",
            "es": "executive_summary",
            "es1": "executive_summary",  # the whole executive-summary subtree
            "ch1": "introduction",
            "s11": "introduction",
            "s16": "audit_objectives",
            "s18": "audit_scope",
            "ch2": "findings",
            "s21": "findings",
            "s24": "conclusion",
            "s25": "recommendations",
            "r31": "recommendations",
            "ann": "annexure",
            "app": "annexure",
            "abb": "glossary",
        }

    def test_content_cues_raise_confidence(self):
        plain = self.types()["s21"].confidence
        cued = self.types(
            [
                child(
                    "c",
                    "s21",
                    "Audit observed that approvals were delayed by 200 days.",
                )
            ]
        )["s21"]
        assert cued.confidence > plain
        assert not cued.is_low_confidence

    def test_disagreement_is_low_confidence(self):
        children = [
            child("c1", "s11", "Audit observed that the posts were vacant."),
            child("c2", "s11", "It was noticed that funds lapsed."),
        ]
        result = self.types(children)["s11"]
        assert result.section_type == "introduction"
        assert result.is_low_confidence

    def test_no_structure_is_low_confidence_other(self):
        result = SectionClassifier().classify_sections(
            [{"chunk_id": "x", "toc_entry": "Miscellaneous"}]
        )[0]
        assert (result.section_type, result.is_low_confidence) == ("other", True)

    def test_overview_inside_a_chapter_is_not_executive_summary(self):
        parents = [
            parent("ch1", "Chapter 1 Introduction"),
            parent("ov", "1.2 Overview of the scheme", "Chapter 1 Introduction"),
        ]
        result = SectionClassifier().classify_sections(parents)
        assert result[1].section_type == "introduction"


# ── entities ──────────────────────────────────────────────────────────────


class TestEntities:
    def test_acronym_definitions_are_not_schemes(self):
        text = (
            "Gross Enrolment Ratio (GER) declined. Head Master (HM) posts were vacant. "
            "Funds under Pradhan Mantri Awas Yojana (PMAY) were idle."
        )
        entities = EntityExtractor().extract_entities([{"content": text}])
        assert entities["schemes"] == ["Pradhan Mantri Awas Yojana"]
        assert "Gross Enrolment Ratio (GER)" in entities["acronyms"]
        assert "Head Master (HM)" in entities["acronyms"]

    def test_scheme_starts_at_a_capitalised_run(self):
        text = (
            "There are seven Centrally Sponsored Scheme components. "
            "The DLC is to monitor the implementation of the Scheme."
        )
        assert EntityExtractor().extract_entities([{"content": text}])["schemes"] == [
            "Centrally Sponsored Scheme"
        ]

    def test_aliases_and_goi_suffix(self):
        text = "Ministry of Education, GoI and Ministry of Education issued orders. NHAI and FCI replied."
        entities = EntityExtractor().extract_entities([{"content": text}])
        assert entities["ministries"] == ["Ministry of Education"]
        assert "Food Corporation of India" in entities["organizations"]

    def test_dedupe_by_whole_words(self):
        deduped = EntityExtractor()._deduplicate_by_substring(
            {"Gram Panchayat", "Gram Panchayats", "Day Meals"}
        )
        assert deduped == {"Gram Panchayat", "Gram Panchayats", "Day Meals"}

    def test_per_finding_list_is_stable(self):
        text = "Ministry of Finance and Ministry of Defence funded the Swachh Bharat Mission."
        extractor = EntityExtractor()
        assert extractor.extract_entities_from_text(
            text
        ) == extractor.extract_entities_from_text(text)


def test_repeated_table_caption_counted_once():
    """A table split over pages repeats its caption; its reference is one reference."""
    parents = [
        parent("s", "5.1.3.1 Sub-projects", "Chapter 5", level=4),
        parent("ann", "Annexures"),
    ]
    caption = "| Annexure III (Refer Para 5.1.3.1) Coastal Monitoring |"
    chunks = [
        child(
            "t1", "ann", caption + "\n| --- |\n| row 1 |", "table_markdown", page=136
        ),
        child(
            "t2", "ann", caption + "\n| --- |\n| row 2 |", "table_markdown", page=137
        ),
    ]
    found = CrossReferenceResolver().resolve_references(chunks, parents)
    assert [x["source_chunk_id"] for x in found] == ["t1"]
