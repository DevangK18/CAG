"""
Unit tests for P3-5: Annexure-Finding Linking

Tests annexure reference detection and linking including:
1. Annexure reference pattern detection
2. ID normalization
3. Annexure parent indexing
4. Reference resolution (exact and fuzzy)
5. Finding attribution
"""

import pytest
from src.parsing_pipeline.modules.enrichment.annexure_linker import AnnexureLinker


@pytest.fixture
def linker():
    """Fixture providing an AnnexureLinker instance."""
    return AnnexureLinker()


@pytest.fixture
def sample_parent_chunks():
    """Fixture providing sample parent chunks including annexures."""
    return [
        {
            "chunk_id": "parent_1",
            "toc_entry": "Chapter 1: Introduction",
            "page_range_physical": [1, 10],
        },
        {
            "chunk_id": "annexure_a",
            "toc_entry": "Annexure-A: Details of Expenditure",
            "page_range_physical": [45, 50],
        },
        {
            "chunk_id": "annexure_b",
            "toc_entry": "Annexure B - Revenue Data",
            "page_range_physical": [51, 55],
        },
        {
            "chunk_id": "appendix_1",
            "toc_entry": "Appendix-I: Methodology",
            "page_range_physical": [56, 60],
        },
    ]


@pytest.fixture
def sample_findings():
    """Fixture providing sample findings."""
    return [
        {
            "finding_id": "finding_1",
            "source_chunk_id": "chunk_1",
            "text": "Loss of revenue as per Annexure-A",
        },
        {
            "finding_id": "finding_2",
            "source_chunk_id": "chunk_2",
            "text": "Details in Appendix-I",
        },
    ]


# ==================== ID NORMALIZATION TESTS ====================


def test_normalize_annexure_id_basic(linker):
    """Test basic annexure ID normalization."""
    assert linker._normalize_annexure_id("Annexure-A") == "appendix:a"
    assert linker._normalize_annexure_id("Annexure A") == "appendix:a"
    assert linker._normalize_annexure_id("ANNEXURE - A") == "appendix:a"
    # Annexure and Appendix are the same thing
    assert linker._normalize_annexure_id("Appendix A") == "appendix:a"


def test_normalize_annexure_id_with_numbers(linker):
    """Test normalization with numeric suffixes."""
    assert linker._normalize_annexure_id("Annexure-1") == "appendix:1"
    assert linker._normalize_annexure_id("Annexure 3.1") == "appendix:3.1"
    assert linker._normalize_annexure_id("Appendix-15 (i)") == "appendix:15(i)"


def test_normalize_annexure_id_complex(linker):
    """Test normalization of complex IDs."""
    # A Roman number meets its Arabic form
    assert linker._normalize_annexure_id("Annexure - II") == "appendix:2"
    assert linker._normalize_annexure_id("Appendix B-1") == "appendix:b-1"


# ==================== ANNEXURE PARENT INDEXING TESTS ====================


def test_find_annexure_parents_basic(linker, sample_parent_chunks):
    """Test finding and indexing annexure parents."""
    index = linker._find_annexure_parents(sample_parent_chunks)

    assert index["appendix:a"]["chunk_id"] == "annexure_a"
    assert index["appendix:b"]["chunk_id"] == "annexure_b"
    assert index["appendix:1"]["chunk_id"] == "appendix_1"
    assert len(index) == 3  # Excludes Chapter 1


def test_find_annexure_parents_case_insensitive(linker):
    """Test case-insensitive detection of annexure parents."""
    parents = [
        {"chunk_id": "a1", "toc_entry": "ANNEXURE-A"},
        {"chunk_id": "a2", "toc_entry": "annexure B"},
        {"chunk_id": "a3", "toc_entry": "Appendix-I"},
    ]

    index = linker._find_annexure_parents(parents)

    assert len(index) == 3


def test_find_annexure_parents_no_annexures(linker):
    """Test empty index when no annexures present."""
    parents = [
        {"chunk_id": "p1", "toc_entry": "Chapter 1"},
        {"chunk_id": "p2", "toc_entry": "Section 2.1"},
    ]

    index = linker._find_annexure_parents(parents)

    assert index == {}


# ==================== REFERENCE DETECTION TESTS ====================


def test_link_annexures_details_given_pattern(
    linker, sample_parent_chunks, sample_findings
):
    """Test detection of 'Details are given in Annexure-A' pattern."""
    child_chunks = [
        {
            "chunk_id": "chunk_1",
            "content": "The audit observed irregularities. Details are given in Annexure-A.",
        }
    ]

    links = linker.link_annexures(child_chunks, sample_parent_chunks, [])

    assert len(links) == 1
    assert links[0]["target_annexure_ref"] == "Annexure-A"
    assert links[0]["resolved"] is True
    assert "Details are given in Annexure-A" in links[0]["reference_text"]


def test_link_annexures_as_per_pattern(linker, sample_parent_chunks, sample_findings):
    """Test detection of 'as per Annexure-A' pattern."""
    child_chunks = [
        {
            "chunk_id": "chunk_1",
            "content": "Revenue loss as per Annexure-A amounted to ₹100 crore.",
        }
    ]

    links = linker.link_annexures(child_chunks, sample_parent_chunks, [])

    assert len(links) == 1
    assert links[0]["target_annexure_ref"] == "Annexure-A"
    assert "as per Annexure-A" in links[0]["reference_text"]


def test_link_annexures_vide_pattern(linker, sample_parent_chunks, sample_findings):
    """Test detection of 'vide Annexure-A' pattern."""
    child_chunks = [
        {
            "chunk_id": "chunk_1",
            "content": "The details vide Annexure-A show significant discrepancies.",
        }
    ]

    links = linker.link_annexures(child_chunks, sample_parent_chunks, [])

    assert len(links) == 1
    assert links[0]["target_annexure_ref"] == "Annexure-A"


def test_link_annexures_parenthetical_pattern(
    linker, sample_parent_chunks, sample_findings
):
    """Test detection of '(Annexure-A)' pattern."""
    child_chunks = [
        {
            "chunk_id": "chunk_1",
            "content": "The audit findings (Annexure-A) indicate revenue loss.",
        }
    ]

    links = linker.link_annexures(child_chunks, sample_parent_chunks, [])

    assert len(links) == 1
    assert links[0]["target_annexure_ref"] == "Annexure-A"


def test_link_annexures_appendix_pattern(linker, sample_parent_chunks, sample_findings):
    """Test detection of Appendix references."""
    child_chunks = [
        {
            "chunk_id": "chunk_1",
            "content": "Methodology details are shown in Appendix-I.",
        }
    ]

    links = linker.link_annexures(child_chunks, sample_parent_chunks, [])

    assert len(links) == 1
    assert links[0]["target_annexure_ref"] == "Appendix-I"
    assert links[0]["resolved"] is True


def test_link_annexures_multiple_references(
    linker, sample_parent_chunks, sample_findings
):
    """Test detection of multiple annexure references in same chunk."""
    child_chunks = [
        {
            "chunk_id": "chunk_1",
            "content": "Details in Annexure-A and Annexure B show revenue and expenditure data.",
        }
    ]

    links = linker.link_annexures(child_chunks, sample_parent_chunks, [])

    assert len(links) == 2
    refs = [link["target_annexure_ref"] for link in links]
    assert "Annexure-A" in refs
    assert "Annexure B" in refs


# ==================== RESOLUTION TESTS ====================


def test_link_annexures_exact_match(linker, sample_parent_chunks, sample_findings):
    """Test exact match resolution between reference and parent."""
    child_chunks = [{"chunk_id": "chunk_1", "content": "See Annexure-A for details."}]

    links = linker.link_annexures(child_chunks, sample_parent_chunks, [])

    assert len(links) == 1
    assert links[0]["resolved"] is True
    assert links[0]["target_parent_chunk_id"] == "annexure_a"


def test_link_annexures_fuzzy_match(linker, sample_parent_chunks, sample_findings):
    """Test fuzzy match when exact match fails (e.g., Annexure B vs Annexure B - Revenue Data)."""
    child_chunks = [{"chunk_id": "chunk_1", "content": "Revenue data in Annexure B."}]

    links = linker.link_annexures(child_chunks, sample_parent_chunks, [])

    assert len(links) == 1
    assert links[0]["resolved"] is True
    assert links[0]["target_parent_chunk_id"] == "annexure_b"


def test_link_annexures_unresolved(linker, sample_parent_chunks, sample_findings):
    """Test unresolved reference when annexure doesn't exist."""
    child_chunks = [
        {
            "chunk_id": "chunk_1",
            "content": "Details in Annexure-Z (not present in document).",
        }
    ]

    links = linker.link_annexures(child_chunks, sample_parent_chunks, [])

    assert len(links) == 1
    assert links[0]["resolved"] is False
    assert links[0]["target_parent_chunk_id"] is None


def test_link_annexures_normalized_comparison(linker):
    """Test that resolution uses normalized IDs for comparison."""
    parents = [{"chunk_id": "ann_a", "toc_entry": "Annexure - A"}]

    child_chunks = [{"chunk_id": "c1", "content": "See ANNEXURE A for details."}]

    links = linker.link_annexures(child_chunks, parents, [])

    assert len(links) == 1
    assert links[0]["resolved"] is True


# ==================== FINDING ATTRIBUTION TESTS ====================


def test_link_annexures_finding_attribution(
    linker, sample_parent_chunks, sample_findings
):
    """Test that links from findings include finding_id."""
    child_chunks = [
        {"chunk_id": "chunk_1", "content": "Revenue loss as per Annexure-A."}
    ]

    links = linker.link_annexures(child_chunks, sample_parent_chunks, sample_findings)

    assert len(links) == 1
    assert links[0]["source_type"] == "finding"
    assert links[0]["finding_id"] == "finding_1"


def test_link_annexures_paragraph_source(linker, sample_parent_chunks):
    """Test that links from non-finding chunks are marked as paragraph."""
    child_chunks = [{"chunk_id": "chunk_nonf", "content": "See Annexure-A."}]

    links = linker.link_annexures(child_chunks, sample_parent_chunks, [])

    assert len(links) == 1
    assert links[0]["source_type"] == "paragraph"
    assert "finding_id" not in links[0] or links[0].get("finding_id") is None


# ==================== EDGE CASES TESTS ====================


def test_link_annexures_no_annexures_in_doc(linker):
    """Test behavior when document has no annexures."""
    parents = [{"chunk_id": "p1", "toc_entry": "Chapter 1"}]

    child_chunks = [{"chunk_id": "c1", "content": "See Annexure-A (doesn't exist)."}]

    links = linker.link_annexures(child_chunks, parents, [])

    # Recorded, unresolved: a report without appendix parents still keeps its references
    assert len(links) == 1
    assert links[0]["resolved"] is False
    assert links[0]["target_parent_chunk_id"] is None


def test_link_annexures_no_references(linker, sample_parent_chunks):
    """Test behavior when no annexure references are found."""
    child_chunks = [
        {"chunk_id": "c1", "content": "This paragraph has no annexure references."}
    ]

    links = linker.link_annexures(child_chunks, sample_parent_chunks, [])

    assert links == []


def test_link_annexures_empty_chunks(linker, sample_parent_chunks):
    """Test behavior with empty chunk list."""
    links = linker.link_annexures([], sample_parent_chunks, [])

    assert links == []


def test_link_annexures_reference_text_truncation(linker, sample_parent_chunks):
    """Test that reference_text is truncated to 120 chars."""
    long_text = "Details are given in Annexure-A regarding " + "x" * 200

    child_chunks = [{"chunk_id": "c1", "content": long_text}]

    links = linker.link_annexures(child_chunks, sample_parent_chunks, [])

    assert len(links) == 1
    assert len(links[0]["reference_text"]) <= 120


def test_link_annexures_case_variations(linker):
    """Test detection with various case patterns."""
    parents = [{"chunk_id": "a1", "toc_entry": "Annexure-A"}]

    child_chunks = [
        {"chunk_id": "c1", "content": "See ANNEXURE-A."},
        {"chunk_id": "c2", "content": "See annexure A."},
        {"chunk_id": "c3", "content": "See Annexure - A."},
    ]

    links = linker.link_annexures(child_chunks, parents, [])

    # All should be detected and resolved
    assert len(links) == 3
    assert all(link["resolved"] for link in links)


def test_link_annexures_roman_numerals(linker):
    """Test detection and resolution of Roman numeral annexures."""
    parents = [
        {"chunk_id": "ann_i", "toc_entry": "Annexure-I"},
        {"chunk_id": "ann_ii", "toc_entry": "Annexure-II"},
    ]

    child_chunks = [
        {"chunk_id": "c1", "content": "Details in Annexure-I and Annexure-II."}
    ]

    links = linker.link_annexures(child_chunks, parents, [])

    assert len(links) == 2
    assert all(link["resolved"] for link in links)


def test_link_data_structure(linker, sample_parent_chunks):
    """Test that link data structure contains all expected fields."""
    child_chunks = [{"chunk_id": "c1", "content": "See Annexure-A."}]

    links = linker.link_annexures(child_chunks, sample_parent_chunks, [])

    assert len(links) == 1
    link = links[0]

    # Check required fields
    assert "source_chunk_id" in link
    assert "source_type" in link
    assert "target_annexure_ref" in link
    assert "target_annexure_norm" in link
    assert "target_parent_chunk_id" in link
    assert "reference_text" in link
    assert "resolved" in link


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


# ==================== EXACT ID MATCHING (C-9-03) ====================


def test_link_resolves_to_same_number_not_prefix(linker):
    """Appendix 2.1 never lands on Appendix 2.10; Appendix-1 never on Appendix-15(i)."""
    parents = [
        {"chunk_id": "app_2_10", "toc_entry": "Appendix 2.10 Statement of arrears"},
        {"chunk_id": "app_2_1", "toc_entry": "Appendix 2.1 Statement of savings"},
        {"chunk_id": "app_15_i", "toc_entry": "Appendix-15(i) Blocked funds"},
        {"chunk_id": "app_1", "toc_entry": "Appendix 1 Functions devolved"},
    ]
    child_chunks = [
        {"chunk_id": "c1", "content": "Savings occurred in 12 units (Appendix 2.1)."},
        {
            "chunk_id": "c2",
            "content": "Twenty-nine functions (Appendix-1) were devolved.",
        },
    ]
    links = {
        link["source_chunk_id"]: link
        for link in linker.link_annexures(child_chunks, parents, [])
    }
    assert links["c1"]["target_parent_chunk_id"] == "app_2_1"
    assert links["c2"]["target_parent_chunk_id"] == "app_1"


def test_link_sub_appendix_falls_back_to_its_appendix(linker):
    """'Appendix-3(i)' resolves to 'Appendix 3' when the report has no 3(i) of its own."""
    parents = [{"chunk_id": "app_3", "toc_entry": "Appendix 3 Audit coverage"}]
    child_chunks = [
        {"chunk_id": "c1", "content": "45 GPs were selected (Appendix-3(i))."}
    ]
    links = linker.link_annexures(child_chunks, parents, [])
    assert links[0]["target_parent_chunk_id"] == "app_3"
    assert links[0]["resolved_by"] == "ancestor"


def test_link_ambiguous_prefix_left_unresolved(linker):
    """'Appendix 15' with 15(i) and 15(ii) is ambiguous; one sub-appendix is not."""
    parents = [
        {"chunk_id": "a", "toc_entry": "Appendix-15(i) Works not started"},
        {"chunk_id": "b", "toc_entry": "Appendix-15(ii) Works not completed"},
        {"chunk_id": "c", "toc_entry": "Appendix-16(i) Unspent funds"},
    ]
    child_chunks = [
        {"chunk_id": "c1", "content": "Details in Appendix 15 and in Appendix 16."}
    ]
    links = {
        link["target_annexure_norm"]: link
        for link in linker.link_annexures(child_chunks, parents, [])
    }
    assert links["appendix:15"]["resolved"] is False
    assert links["appendix:16"]["target_parent_chunk_id"] == "c"


def test_link_falls_back_to_appendix_heading_chunks(linker):
    """All annexures under one 'Annexures' parent: the heading chunk that starts each one."""
    parents = [
        {"chunk_id": "body", "toc_entry": "4.1 Data services"},
        {"chunk_id": "annexures", "toc_entry": "Annexures"},
    ]
    child_chunks = [
        {
            "chunk_id": "c1",
            "parent_chunk_id": "body",
            "content_type": "paragraph",
            "content": "The status is given in Annexure II and in Annexure I.",
        },
        {
            "chunk_id": "h1",
            "parent_chunk_id": "annexures",
            "content_type": "header",
            "content": "Annexure I (Refer Para 4.1)",
        },
        {
            "chunk_id": "t1",
            "parent_chunk_id": "annexures",
            "content_type": "table_markdown",
            "content": "| a | b |\n| --- | --- |\n| 1 | 2 |\n| Annexure II (Refer Para 4.2) |",
        },
    ]
    links = {
        link["target_annexure_norm"]: link
        for link in linker.link_annexures(child_chunks, parents, [])
    }
    assert set(links) == {"appendix:1", "appendix:2"}  # the headings are not references
    assert links["appendix:1"]["target_chunk_id"] == "h1"
    assert links["appendix:1"]["target_parent_chunk_id"] == "annexures"
    assert links["appendix:2"]["target_chunk_id"] == "t1"


def test_link_attributes_multi_chunk_findings(linker):
    """A finding spanning several chunks owns references in any of them."""
    parents = [{"chunk_id": "a", "toc_entry": "Appendix 4 Records"}]
    child_chunks = [
        {"chunk_id": "c2", "content": "Registers were not kept (Appendix-4)."}
    ]
    findings = [
        {"finding_id": "f1", "source_chunk_id": "c1", "source_chunk_ids": ["c1", "c2"]}
    ]
    links = linker.link_annexures(child_chunks, parents, findings)
    assert links[0]["source_type"] == "finding"
    assert links[0]["finding_id"] == "f1"
