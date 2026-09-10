"""
P2-20: Unit tests for footnote_index type fix.

The _build_footnote_index method should return Dict[str, Dict] keyed by
footnote number, not List[Dict].
"""

import pytest
from src.parsing_pipeline.modules.assembly_service import AssemblyService


@pytest.fixture
def assembly_service(tmp_path):
    """Create an AssemblyService with temp output directory."""
    return AssemblyService(output_dir=str(tmp_path))


class TestFootnoteIndexTypeP220:
    """P2-20: Verify footnote_index returns dict, not list."""

    def test_returns_dict_not_list(self, assembly_service):
        """P2-20: footnote_index should be a dict, not a list."""
        child_chunks = [
            {
                "content_type": "footnote",
                "content": "[Footnote 1] This is footnote content.",
                "chunk_id": "chunk_001",
                "source_page_physical": 5,
                "source_page_logical": 3,
                "hierarchy": {"L1": "Chapter 1"},
            }
        ]

        result = assembly_service._build_footnote_index(child_chunks)

        assert isinstance(result, dict), "footnote_index should be dict, not list"
        assert not isinstance(result, list)

    def test_footnote_keyed_by_number(self, assembly_service):
        """P2-20: Footnotes should be keyed by their number."""
        child_chunks = [
            {
                "content_type": "footnote",
                "content": "[Footnote 7] Seventh footnote.",
                "chunk_id": "chunk_007",
                "source_page_physical": 10,
                "source_page_logical": 8,
                "hierarchy": {"L1": "Chapter 2"},
            }
        ]

        result = assembly_service._build_footnote_index(child_chunks)

        assert "7" in result
        assert result["7"]["content"] == "[Footnote 7] Seventh footnote."
        assert result["7"]["chunk_id"] == "chunk_007"
        assert result["7"]["page_physical"] == 10
        assert result["7"]["page_logical"] == 8
        assert result["7"]["parent_section"] == {"L1": "Chapter 2"}

    def test_multiple_footnotes_keyed(self, assembly_service):
        """P2-20: Multiple footnotes should have unique keys."""
        child_chunks = [
            {
                "content_type": "footnote",
                "content": "[Footnote 1] First footnote.",
                "chunk_id": "chunk_001",
                "source_page_physical": 5,
                "hierarchy": {},
            },
            {
                "content_type": "footnote",
                "content": "[Footnote 2] Second footnote.",
                "chunk_id": "chunk_002",
                "source_page_physical": 6,
                "hierarchy": {},
            },
            {
                "content_type": "footnote",
                "content": "[Footnote 3] Third footnote.",
                "chunk_id": "chunk_003",
                "source_page_physical": 7,
                "hierarchy": {},
            },
        ]

        result = assembly_service._build_footnote_index(child_chunks)

        assert len(result) == 3
        assert "1" in result
        assert "2" in result
        assert "3" in result
        assert result["1"]["content"] == "[Footnote 1] First footnote."
        assert result["2"]["content"] == "[Footnote 2] Second footnote."
        assert result["3"]["content"] == "[Footnote 3] Third footnote."

    def test_no_footnotes_returns_empty_dict(self, assembly_service):
        """P2-20: No footnotes should return empty dict {}, not []."""
        child_chunks = [
            {
                "content_type": "paragraph",
                "content": "Regular paragraph content.",
                "chunk_id": "chunk_001",
            },
            {
                "content_type": "table_markdown",
                "content": "| A | B |",
                "chunk_id": "chunk_002",
            },
        ]

        result = assembly_service._build_footnote_index(child_chunks)

        assert result == {}
        assert isinstance(result, dict)

    def test_unnumbered_footnote_gets_auto_key(self, assembly_service):
        """P2-20: Unnumbered footnotes should get auto_N keys."""
        child_chunks = [
            {
                "content_type": "footnote",
                "content": "[Footnote] Unnumbered footnote without a number.",
                "chunk_id": "chunk_001",
                "source_page_physical": 5,
                "hierarchy": {},
            },
            {
                "content_type": "footnote",
                "content": "A footnote without standard format.",
                "chunk_id": "chunk_002",
                "source_page_physical": 6,
                "hierarchy": {},
            },
        ]

        result = assembly_service._build_footnote_index(child_chunks)

        assert "auto_1" in result
        assert "auto_2" in result
        assert result["auto_1"]["content"] == "[Footnote] Unnumbered footnote without a number."
        assert result["auto_2"]["content"] == "A footnote without standard format."

    def test_duplicate_footnote_numbers_handled(self, assembly_service):
        """P2-20: Duplicate footnote numbers should overwrite (later wins)."""
        child_chunks = [
            {
                "content_type": "footnote",
                "content": "[Footnote 1] First occurrence.",
                "chunk_id": "chunk_001",
                "source_page_physical": 5,
                "hierarchy": {},
            },
            {
                "content_type": "footnote",
                "content": "[Footnote 1] Second occurrence (duplicate).",
                "chunk_id": "chunk_002",
                "source_page_physical": 10,
                "hierarchy": {},
            },
        ]

        result = assembly_service._build_footnote_index(child_chunks)

        # Only one "1" key, and it should be the second occurrence
        assert len(result) == 1
        assert "1" in result
        assert result["1"]["content"] == "[Footnote 1] Second occurrence (duplicate)."
        assert result["1"]["chunk_id"] == "chunk_002"
        assert result["1"]["page_physical"] == 10
