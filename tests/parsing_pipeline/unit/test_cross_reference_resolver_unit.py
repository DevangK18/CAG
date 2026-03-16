"""
Unit tests for P3-6: Cross-Reference Resolver
Tests detection and resolution of para/section/chapter/table references
"""

import pytest
from src.parsing_pipeline.modules.enrichment.cross_reference_resolver import CrossReferenceResolver


@pytest.fixture
def resolver():
    return CrossReferenceResolver()


@pytest.fixture
def sample_parent_chunks():
    return [
        {
            "chunk_id": "parent_1",
            "toc_entry": "1.1 Introduction",
            "page_range_physical": [1, 3]
        },
        {
            "chunk_id": "parent_2",
            "toc_entry": "2.1 Audit Findings",
            "page_range_physical": [4, 10]
        },
        {
            "chunk_id": "parent_3",
            "toc_entry": "3.2.1 Implementation Status",
            "page_range_physical": [11, 15]
        },
        {
            "chunk_id": "parent_4",
            "toc_entry": "Chapter III - Compliance",
            "page_range_physical": [16, 25]
        },
        {
            "chunk_id": "parent_5",
            "toc_entry": "Annexure A - Details",
            "page_range_physical": [26, 30]
        }
    ]


@pytest.fixture
def sample_child_chunks():
    return [
        {
            "chunk_id": "child_1",
            "content": "As discussed in Para 3.2.1, the implementation was delayed.",
            "content_type": "paragraph",
            "source_page_physical": 12
        },
        {
            "chunk_id": "child_2",
            "content": "Refer to Table 1.3 for detailed breakdown.",
            "content_type": "paragraph",
            "source_page_physical": 5
        },
        {
            "chunk_id": "child_3",
            "content": "| Header 1 | Header 2 |\n|----------|----------|\n| Data     | Data     |",
            "content_type": "table_markdown",
            "hierarchy": {"level_1": "Table 1.3 - Financial Data"},
            "source_page_physical": 5
        },
        {
            "chunk_id": "child_4",
            "content": "As per Chapter III guidelines, all departments must comply.",
            "content_type": "paragraph",
            "source_page_physical": 18
        },
        {
            "chunk_id": "child_5",
            "content": "See Section 2.1 for audit methodology.",
            "content_type": "paragraph",
            "source_page_physical": 8
        }
    ]


class TestPatternDetection:
    """Test reference pattern detection."""

    def test_para_reference_basic(self, resolver):
        text = "As discussed in Para 3.2.1 above."
        matches = []
        for pattern, ref_type in resolver._patterns:
            for match in pattern.finditer(text):
                matches.append((ref_type, match.group(1)))

        assert len(matches) >= 1
        assert any(ref_type == "para" and target == "3.2.1" for ref_type, target in matches)

    def test_section_reference(self, resolver):
        text = "Refer to Section 2.1 for details."
        matches = []
        for pattern, ref_type in resolver._patterns:
            for match in pattern.finditer(text):
                matches.append((ref_type, match.group(1)))

        assert len(matches) >= 1
        assert any(ref_type == "section" and target == "2.1" for ref_type, target in matches)

    def test_chapter_reference_roman(self, resolver):
        text = "As per Chapter III guidelines."
        matches = []
        for pattern, ref_type in resolver._patterns:
            for match in pattern.finditer(text):
                matches.append((ref_type, match.group(1)))

        assert len(matches) >= 1
        assert any(ref_type == "chapter" and target == "III" for ref_type, target in matches)

    def test_chapter_reference_numeric(self, resolver):
        text = "See Chapter 3 for more information."
        matches = []
        for pattern, ref_type in resolver._patterns:
            for match in pattern.finditer(text):
                matches.append((ref_type, match.group(1)))

        assert len(matches) >= 1
        assert any(ref_type == "chapter" and target == "3" for ref_type, target in matches)

    def test_table_reference_basic(self, resolver):
        text = "Details are in Table 1.3."
        matches = []
        for pattern, ref_type in resolver._patterns:
            for match in pattern.finditer(text):
                matches.append((ref_type, match.group(1)))

        assert len(matches) >= 1
        assert any(ref_type == "table" and target in ["1.3", "1"] for ref_type, target in matches)

    def test_table_reference_with_no(self, resolver):
        text = "Refer to Table No. 2 for breakdown."
        matches = []
        for pattern, ref_type in resolver._patterns:
            for match in pattern.finditer(text):
                matches.append((ref_type, match.group(1)))

        assert len(matches) >= 1
        assert any(ref_type == "table" for ref_type, target in matches)

    def test_multiple_references_in_text(self, resolver):
        text = "Para 2.1 and Para 3.2.1 both discuss this issue."
        matches = []
        for pattern, ref_type in resolver._patterns:
            for match in pattern.finditer(text):
                matches.append((ref_type, match.group(1)))

        para_matches = [target for ref_type, target in matches if ref_type == "para"]
        assert len(para_matches) >= 2

    def test_case_insensitive(self, resolver):
        text = "see section 2.1 and PARA 3.2.1"
        matches = []
        for pattern, ref_type in resolver._patterns:
            for match in pattern.finditer(text):
                matches.append((ref_type, match.group(1)))

        assert len(matches) >= 2


class TestSectionIndexBuilding:
    """Test building section index from parent/child chunks."""

    def test_builds_index_from_numbered_sections(self, resolver, sample_parent_chunks):
        index = resolver._build_section_index(sample_parent_chunks, [])

        assert "1.1" in index
        assert "2.1" in index
        assert "3.2.1" in index
        assert index["1.1"]["chunk_id"] == "parent_1"
        assert index["1.1"]["chunk_type"] == "parent"

    def test_builds_chapter_index(self, resolver, sample_parent_chunks):
        index = resolver._build_section_index(sample_parent_chunks, [])

        assert "chapter_iii" in index
        assert index["chapter_iii"]["chunk_id"] == "parent_4"

    def test_builds_table_index(self, resolver, sample_child_chunks):
        index = resolver._build_section_index([], sample_child_chunks)

        assert "table_1.3" in index
        assert index["table_1.3"]["chunk_id"] == "child_3"
        assert index["table_1.3"]["chunk_type"] == "child"

    def test_empty_chunks_return_empty_index(self, resolver):
        index = resolver._build_section_index([], [])
        assert index == {}

    def test_index_stores_page_numbers(self, resolver, sample_parent_chunks):
        index = resolver._build_section_index(sample_parent_chunks, [])

        assert index["1.1"]["page"] == 1
        assert index["2.1"]["page"] == 4


class TestReferenceResolution:
    """Test end-to-end reference resolution."""

    def test_resolves_para_reference(self, resolver, sample_parent_chunks, sample_child_chunks):
        references = resolver.resolve_references(sample_child_chunks, sample_parent_chunks)

        # Find the para 3.2.1 reference
        para_refs = [r for r in references if r["reference_type"] == "para" and r["reference_target"] == "3.2.1"]
        assert len(para_refs) > 0

        ref = para_refs[0]
        assert ref["resolved"] is True
        assert ref["resolved_chunk_id"] == "parent_3"
        assert ref["resolved_chunk_type"] == "parent"
        assert ref["source_chunk_id"] == "child_1"

    def test_resolves_section_reference(self, resolver, sample_parent_chunks, sample_child_chunks):
        references = resolver.resolve_references(sample_child_chunks, sample_parent_chunks)

        section_refs = [r for r in references if r["reference_type"] == "section" and r["reference_target"] == "2.1"]
        assert len(section_refs) > 0

        ref = section_refs[0]
        assert ref["resolved"] is True
        assert ref["resolved_chunk_id"] == "parent_2"

    def test_resolves_chapter_reference(self, resolver, sample_parent_chunks, sample_child_chunks):
        references = resolver.resolve_references(sample_child_chunks, sample_parent_chunks)

        chapter_refs = [r for r in references if r["reference_type"] == "chapter"]
        assert len(chapter_refs) > 0

        ref = chapter_refs[0]
        assert ref["resolved"] is True
        assert ref["resolved_chunk_id"] == "parent_4"

    def test_resolves_table_reference(self, resolver, sample_parent_chunks, sample_child_chunks):
        references = resolver.resolve_references(sample_child_chunks, sample_parent_chunks)

        table_refs = [r for r in references if r["reference_type"] == "table"]
        assert len(table_refs) > 0

        # At least one should resolve
        resolved_tables = [r for r in table_refs if r["resolved"]]
        assert len(resolved_tables) > 0

    def test_unresolved_reference(self, resolver, sample_parent_chunks):
        child_chunks = [{
            "chunk_id": "child_x",
            "content": "As discussed in Para 99.99.99 which does not exist.",
            "content_type": "paragraph",
            "source_page_physical": 1
        }]

        references = resolver.resolve_references(child_chunks, sample_parent_chunks)

        para_refs = [r for r in references if r["reference_target"] == "99.99.99"]
        assert len(para_refs) > 0
        assert para_refs[0]["resolved"] is False
        assert para_refs[0]["resolved_chunk_id"] is None

    def test_self_references_filtered(self, resolver):
        # A parent chunk that references itself
        parent_chunks = [{
            "chunk_id": "parent_1",
            "toc_entry": "2.1 Findings",
            "page_range_physical": [1, 5]
        }]

        child_chunks = [{
            "chunk_id": "parent_1",  # Same ID as parent
            "content": "This Section 2.1 discusses findings.",
            "content_type": "header",
            "source_page_physical": 1
        }]

        references = resolver.resolve_references(child_chunks, parent_chunks)

        # Should not create self-reference
        self_refs = [r for r in references if r["source_chunk_id"] == r.get("resolved_chunk_id")]
        assert len(self_refs) == 0

    def test_stores_reference_text(self, resolver, sample_parent_chunks, sample_child_chunks):
        references = resolver.resolve_references(sample_child_chunks, sample_parent_chunks)

        assert len(references) > 0
        for ref in references:
            assert "reference_text" in ref
            assert len(ref["reference_text"]) > 0
            assert len(ref["reference_text"]) <= 60  # Truncated

    def test_stores_source_page(self, resolver, sample_parent_chunks, sample_child_chunks):
        references = resolver.resolve_references(sample_child_chunks, sample_parent_chunks)

        for ref in references:
            assert "source_page" in ref
            assert ref["source_page"] > 0

    def test_stores_resolved_page(self, resolver, sample_parent_chunks, sample_child_chunks):
        references = resolver.resolve_references(sample_child_chunks, sample_parent_chunks)

        resolved_refs = [r for r in references if r["resolved"]]
        for ref in resolved_refs:
            assert "resolved_page" in ref
            assert ref["resolved_page"] is not None


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_chunks(self, resolver):
        references = resolver.resolve_references([], [])
        assert references == []

    def test_no_references_in_content(self, resolver, sample_parent_chunks):
        child_chunks = [{
            "chunk_id": "child_1",
            "content": "This is plain text with no references.",
            "content_type": "paragraph",
            "source_page_physical": 1
        }]

        references = resolver.resolve_references(child_chunks, sample_parent_chunks)
        assert len(references) == 0

    def test_malformed_hierarchy(self, resolver):
        child_chunks = [{
            "chunk_id": "child_1",
            "content": "Reference to Table 1.3",
            "content_type": "table_markdown",
            "hierarchy": None,  # Malformed
            "source_page_physical": 1
        }]

        references = resolver.resolve_references(child_chunks, [])
        # Should not crash, just not resolve
        assert isinstance(references, list)

    def test_missing_page_range(self, resolver):
        parent_chunks = [{
            "chunk_id": "parent_1",
            "toc_entry": "1.1 Introduction",
            "page_range_physical": None
        }]

        child_chunks = [{
            "chunk_id": "child_1",
            "content": "See Para 1.1",
            "content_type": "paragraph",
            "source_page_physical": 1
        }]

        references = resolver.resolve_references(child_chunks, parent_chunks)
        # Should still resolve, just with page = 0
        assert len(references) > 0

    def test_unicode_in_references(self, resolver):
        child_chunks = [{
            "chunk_id": "child_1",
            "content": "Para 2.1 – with en-dash",
            "content_type": "paragraph",
            "source_page_physical": 1
        }]

        parent_chunks = [{
            "chunk_id": "parent_1",
            "toc_entry": "2.1 Findings",
            "page_range_physical": [1, 5]
        }]

        references = resolver.resolve_references(child_chunks, parent_chunks)
        assert len(references) > 0

    def test_complex_toc_entries(self, resolver):
        parent_chunks = [{
            "chunk_id": "parent_1",
            "toc_entry": "3.2.1 Implementation Status (As on March 2023)",
            "page_range_physical": [10, 15]
        }]

        child_chunks = [{
            "chunk_id": "child_1",
            "content": "Refer to Para 3.2.1 for status.",
            "content_type": "paragraph",
            "source_page_physical": 12
        }]

        references = resolver.resolve_references(child_chunks, parent_chunks)
        resolved = [r for r in references if r["resolved"]]
        assert len(resolved) > 0


class TestDataStructure:
    """Test reference data structure completeness."""

    def test_reference_has_all_fields(self, resolver, sample_parent_chunks, sample_child_chunks):
        references = resolver.resolve_references(sample_child_chunks, sample_parent_chunks)

        assert len(references) > 0
        for ref in references:
            assert "source_chunk_id" in ref
            assert "source_page" in ref
            assert "reference_type" in ref
            assert "reference_target" in ref
            assert "reference_text" in ref
            assert "resolved_chunk_id" in ref
            assert "resolved_chunk_type" in ref
            assert "resolved_page" in ref
            assert "resolved" in ref
            assert isinstance(ref["resolved"], bool)

    def test_reference_type_values(self, resolver, sample_parent_chunks, sample_child_chunks):
        references = resolver.resolve_references(sample_child_chunks, sample_parent_chunks)

        valid_types = {"para", "section", "chapter", "table"}
        for ref in references:
            assert ref["reference_type"] in valid_types

    def test_chunk_type_values(self, resolver, sample_parent_chunks, sample_child_chunks):
        references = resolver.resolve_references(sample_child_chunks, sample_parent_chunks)

        resolved_refs = [r for r in references if r["resolved"]]
        for ref in resolved_refs:
            assert ref["resolved_chunk_type"] in {"parent", "child"}
