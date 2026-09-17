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
            "page_range_physical": [1, 10]
        },
        {
            "chunk_id": "annexure_a",
            "toc_entry": "Annexure-A: Details of Expenditure",
            "page_range_physical": [45, 50]
        },
        {
            "chunk_id": "annexure_b",
            "toc_entry": "Annexure B - Revenue Data",
            "page_range_physical": [51, 55]
        },
        {
            "chunk_id": "appendix_1",
            "toc_entry": "Appendix-I: Methodology",
            "page_range_physical": [56, 60]
        }
    ]


@pytest.fixture
def sample_findings():
    """Fixture providing sample findings."""
    return [
        {
            "finding_id": "finding_1",
            "source_chunk_id": "chunk_1",
            "text": "Loss of revenue as per Annexure-A"
        },
        {
            "finding_id": "finding_2",
            "source_chunk_id": "chunk_2",
            "text": "Details in Appendix-I"
        }
    ]


# ==================== ID NORMALIZATION TESTS ====================


def test_normalize_annexure_id_basic(linker):
    """Test basic annexure ID normalization."""
    assert linker._normalize_annexure_id("Annexure-A") == "annexure_a"
    assert linker._normalize_annexure_id("Annexure A") == "annexure_a"
    assert linker._normalize_annexure_id("ANNEXURE - A") == "annexure_a"


def test_normalize_annexure_id_with_numbers(linker):
    """Test normalization with numeric suffixes."""
    assert linker._normalize_annexure_id("Annexure-1") == "annexure_1"
    assert linker._normalize_annexure_id("Annexure 3.1") == "annexure_3.1"


def test_normalize_annexure_id_complex(linker):
    """Test normalization of complex IDs."""
    assert linker._normalize_annexure_id("Annexure - II") == "annexure_ii"
    assert linker._normalize_annexure_id("Appendix B-1") == "appendix_b_1"


# ==================== ANNEXURE PARENT INDEXING TESTS ====================


def test_find_annexure_parents_basic(linker, sample_parent_chunks):
    """Test finding and indexing annexure parents."""
    index = linker._find_annexure_parents(sample_parent_chunks)

    assert "annexure_a_details_of_expenditure" in index
    assert "annexure_b_revenue_data" in index
    assert "appendix_i_methodology" in index
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


def test_link_annexures_details_given_pattern(linker, sample_parent_chunks, sample_findings):
    """Test detection of 'Details are given in Annexure-A' pattern."""
    child_chunks = [
        {
            "chunk_id": "chunk_1",
            "content": "The audit observed irregularities. Details are given in Annexure-A."
        }
    ]

    links = linker.link_annexures(child_chunks, sample_parent_chunks, [])

    assert len(links) == 1
    assert links[0]["target_annexure_ref"] == "Annexure-A"
    assert links[0]["resolved"] == True
    assert "Details are given in Annexure-A" in links[0]["reference_text"]


def test_link_annexures_as_per_pattern(linker, sample_parent_chunks, sample_findings):
    """Test detection of 'as per Annexure-A' pattern."""
    child_chunks = [
        {
            "chunk_id": "chunk_1",
            "content": "Revenue loss as per Annexure-A amounted to ₹100 crore."
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
            "content": "The details vide Annexure-A show significant discrepancies."
        }
    ]

    links = linker.link_annexures(child_chunks, sample_parent_chunks, [])

    assert len(links) == 1
    assert links[0]["target_annexure_ref"] == "Annexure-A"


def test_link_annexures_parenthetical_pattern(linker, sample_parent_chunks, sample_findings):
    """Test detection of '(Annexure-A)' pattern."""
    child_chunks = [
        {
            "chunk_id": "chunk_1",
            "content": "The audit findings (Annexure-A) indicate revenue loss."
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
            "content": "Methodology details are shown in Appendix-I."
        }
    ]

    links = linker.link_annexures(child_chunks, sample_parent_chunks, [])

    assert len(links) == 1
    assert links[0]["target_annexure_ref"] == "Appendix-I"
    assert links[0]["resolved"] == True


def test_link_annexures_multiple_references(linker, sample_parent_chunks, sample_findings):
    """Test detection of multiple annexure references in same chunk."""
    child_chunks = [
        {
            "chunk_id": "chunk_1",
            "content": "Details in Annexure-A and Annexure B show revenue and expenditure data."
        }
    ]

    links = linker.link_annexures(child_chunks, sample_parent_chunks, [])

    assert len(links) == 2
    refs = [l["target_annexure_ref"] for l in links]
    assert "Annexure-A" in refs
    assert "Annexure B" in refs


# ==================== RESOLUTION TESTS ====================


def test_link_annexures_exact_match(linker, sample_parent_chunks, sample_findings):
    """Test exact match resolution between reference and parent."""
    child_chunks = [
        {
            "chunk_id": "chunk_1",
            "content": "See Annexure-A for details."
        }
    ]

    links = linker.link_annexures(child_chunks, sample_parent_chunks, [])

    assert len(links) == 1
    assert links[0]["resolved"] == True
    assert links[0]["target_parent_chunk_id"] == "annexure_a"


def test_link_annexures_fuzzy_match(linker, sample_parent_chunks, sample_findings):
    """Test fuzzy match when exact match fails (e.g., Annexure B vs Annexure B - Revenue Data)."""
    child_chunks = [
        {
            "chunk_id": "chunk_1",
            "content": "Revenue data in Annexure B."
        }
    ]

    links = linker.link_annexures(child_chunks, sample_parent_chunks, [])

    assert len(links) == 1
    assert links[0]["resolved"] == True
    assert links[0]["target_parent_chunk_id"] == "annexure_b"


def test_link_annexures_unresolved(linker, sample_parent_chunks, sample_findings):
    """Test unresolved reference when annexure doesn't exist."""
    child_chunks = [
        {
            "chunk_id": "chunk_1",
            "content": "Details in Annexure-Z (not present in document)."
        }
    ]

    links = linker.link_annexures(child_chunks, sample_parent_chunks, [])

    assert len(links) == 1
    assert links[0]["resolved"] == False
    assert links[0]["target_parent_chunk_id"] is None


def test_link_annexures_normalized_comparison(linker):
    """Test that resolution uses normalized IDs for comparison."""
    parents = [
        {"chunk_id": "ann_a", "toc_entry": "Annexure - A"}
    ]

    child_chunks = [
        {"chunk_id": "c1", "content": "See ANNEXURE A for details."}
    ]

    links = linker.link_annexures(child_chunks, parents, [])

    assert len(links) == 1
    assert links[0]["resolved"] == True


# ==================== FINDING ATTRIBUTION TESTS ====================


def test_link_annexures_finding_attribution(linker, sample_parent_chunks, sample_findings):
    """Test that links from findings include finding_id."""
    child_chunks = [
        {
            "chunk_id": "chunk_1",
            "content": "Revenue loss as per Annexure-A."
        }
    ]

    links = linker.link_annexures(child_chunks, sample_parent_chunks, sample_findings)

    assert len(links) == 1
    assert links[0]["source_type"] == "finding"
    assert links[0]["finding_id"] == "finding_1"


def test_link_annexures_paragraph_source(linker, sample_parent_chunks):
    """Test that links from non-finding chunks are marked as paragraph."""
    child_chunks = [
        {
            "chunk_id": "chunk_nonf", "content": "See Annexure-A."
        }
    ]

    links = linker.link_annexures(child_chunks, sample_parent_chunks, [])

    assert len(links) == 1
    assert links[0]["source_type"] == "paragraph"
    assert "finding_id" not in links[0] or links[0].get("finding_id") is None


# ==================== EDGE CASES TESTS ====================


def test_link_annexures_no_annexures_in_doc(linker):
    """Test behavior when document has no annexures."""
    parents = [
        {"chunk_id": "p1", "toc_entry": "Chapter 1"}
    ]

    child_chunks = [
        {"chunk_id": "c1", "content": "See Annexure-A (doesn't exist)."}
    ]

    links = linker.link_annexures(child_chunks, parents, [])

    assert links == []


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

    child_chunks = [
        {"chunk_id": "c1", "content": long_text}
    ]

    links = linker.link_annexures(child_chunks, sample_parent_chunks, [])

    assert len(links) == 1
    assert len(links[0]["reference_text"]) <= 120


def test_link_annexures_case_variations(linker):
    """Test detection with various case patterns."""
    parents = [
        {"chunk_id": "a1", "toc_entry": "Annexure-A"}
    ]

    child_chunks = [
        {"chunk_id": "c1", "content": "See ANNEXURE-A."},
        {"chunk_id": "c2", "content": "See annexure-a."},
        {"chunk_id": "c3", "content": "See Annexure-a."},
    ]

    links = linker.link_annexures(child_chunks, parents, [])

    # All should be detected and resolved
    assert len(links) == 3
    assert all(l["resolved"] for l in links)


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
    assert all(l["resolved"] for l in links)


def test_link_data_structure(linker, sample_parent_chunks):
    """Test that link data structure contains all expected fields."""
    child_chunks = [
        {"chunk_id": "c1", "content": "See Annexure-A."}
    ]

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
