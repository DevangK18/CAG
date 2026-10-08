"""
Unit tests for P1-3: Evidence Cross-Reference Linking (evidence_linker.py)

Tests reference extraction, evidence resolution, and linking logic.
"""

import pytest
from src.parsing_pipeline.modules import evidence_linker


class TestReferenceExtraction:
    """Test extraction of references from text."""

    def setup_method(self):
        """Set up test fixtures."""
        self.linker = evidence_linker.EvidenceLinker()

    def test_extract_table_reference(self):
        """Test extraction of table references."""
        text = "As shown in Table 3.2, the expenditure was ₹847 crore."
        refs = self.linker.extract_references(text)

        table_refs = [r for r in refs if r.reference_type == "table"]
        assert len(table_refs) > 0
        assert table_refs[0].identifier == "3.2"
        assert "Table 3.2" in table_refs[0].matched_text

    def test_extract_multiple_table_references(self):
        """Test extraction of multiple table references."""
        text = "Table 3.2 shows revenue, while Table 4.1 shows expenditure."
        refs = self.linker.extract_references(text)

        table_refs = [r for r in refs if r.reference_type == "table"]
        assert len(table_refs) >= 2
        identifiers = [r.identifier for r in table_refs]
        assert "3.2" in identifiers
        assert "4.1" in identifiers

    def test_extract_annexure_reference(self):
        """Test extraction of annexure references."""
        text = "Details are provided in Annexure A."
        refs = self.linker.extract_references(text)

        annexure_refs = [r for r in refs if r.reference_type == "annexure"]
        assert len(annexure_refs) > 0
        assert (
            annexure_refs[0].identifier == "a"
        )  # normalized: Annexure and Appendix meet

    def test_extract_paragraph_reference(self):
        """Test extraction of paragraph references."""
        text = "As mentioned in Para 3.2.1, the payment was irregular."
        refs = self.linker.extract_references(text)

        para_refs = [r for r in refs if r.reference_type == "paragraph"]
        assert len(para_refs) > 0
        assert para_refs[0].identifier == "3.2.1"

    def test_extract_page_reference(self):
        """Test extraction of page references."""
        text = "The details are on page 42 of the report."
        refs = self.linker.extract_references(text)

        page_refs = [r for r in refs if r.reference_type == "page"]
        assert len(page_refs) > 0
        assert page_refs[0].identifier in ["42", "42"]

    def test_extract_mixed_references(self):
        """Test extraction of mixed reference types."""
        text = "As per Para 3.2, Table 4.5 and Annexure B (page 25), the loss was ₹100 crore."
        refs = self.linker.extract_references(text)

        ref_types = {r.reference_type for r in refs}
        assert "paragraph" in ref_types
        assert "table" in ref_types
        assert "annexure" in ref_types
        assert "page" in ref_types

    def test_no_references_in_plain_text(self):
        """Test that plain text without references returns empty list."""
        text = "This is a simple sentence without any references."
        refs = self.linker.extract_references(text)

        assert len(refs) == 0


class TestReferencePatternVariations:
    """Test various reference pattern variations."""

    def setup_method(self):
        """Set up test fixtures."""
        self.linker = evidence_linker.EvidenceLinker()

    def test_table_reference_variations(self):
        """Test various table reference formats."""
        test_cases = [
            ("Table 3.2", "3.2"),
            ("as shown in Table 3.2", "3.2"),
            ("vide Table 4.1", "4.1"),
            ("refer Table 5", "5"),
            ("(Table 3.2.1)", "3.2.1"),
        ]

        for text, expected_id in test_cases:
            refs = self.linker.extract_references(text)
            table_refs = [r for r in refs if r.reference_type == "table"]
            assert len(table_refs) > 0, f"Failed to extract from: {text}"
            assert (
                table_refs[0].identifier == expected_id
            ), f"Expected {expected_id}, got {table_refs[0].identifier} from: {text}"

    def test_annexure_reference_variations(self):
        """Test various annexure reference formats."""
        test_cases = [
            ("Annexure A", "A"),
            ("Annexure-B", "B"),
            ("Annexure III", "3"),  # Roman numbers meet their Arabic form
            ("Appendix 2.1", "2.1"),
            ("Appendix C", "C"),
            ("as per Annexure D", "D"),
            ("(Annexure E)", "E"),
        ]

        for text, expected_id in test_cases:
            refs = self.linker.extract_references(text)
            annexure_refs = [r for r in refs if r.reference_type == "annexure"]
            assert len(annexure_refs) > 0, f"Failed to extract from: {text}"
            # Normalize to uppercase for comparison
            assert (
                annexure_refs[0].identifier.upper() == expected_id
            ), f"Expected {expected_id}, got {annexure_refs[0].identifier} from: {text}"

    def test_paragraph_reference_variations(self):
        """Test various paragraph reference formats."""
        test_cases = [
            ("Para 3.2", "3.2"),
            ("Paragraph 4.5.1", "4.5.1"),
            ("Para. 2.3", "2.3"),
            ("as mentioned in Para 5.1", "5.1"),
            ("(Paras 6.1 and 6.2)", "6.1"),
        ]

        for text, expected_id in test_cases:
            refs = self.linker.extract_references(text)
            para_refs = [r for r in refs if r.reference_type == "paragraph"]
            assert len(para_refs) > 0, f"Failed to extract from: {text}"
            assert (
                para_refs[0].identifier == expected_id
            ), f"Expected {expected_id}, got {para_refs[0].identifier} from: {text}"

    def test_page_reference_variations(self):
        """Test various page reference formats."""
        test_cases = [
            ("page 42", "42"),
            ("pages 25-30", "25"),  # Should extract first page
            ("(p. 15)", "15"),
            ("at page 100", "100"),
        ]

        for text, expected_id in test_cases:
            refs = self.linker.extract_references(text)
            page_refs = [r for r in refs if r.reference_type == "page"]
            assert len(page_refs) > 0, f"Failed to extract from: {text}"
            # Page might have leading zeros or range, so check start
            assert (
                page_refs[0].identifier.startswith(expected_id.lstrip("0"))
                or page_refs[0].identifier == expected_id
            )


# Chunk shapes as Phase 8 writes them
def _parent(chunk_id, title, page=1):
    return {
        "chunk_id": chunk_id,
        "toc_entry": title,
        "toc_level": title.count(".") + 1,
        "page_range_physical": [page, page],
    }


def _table(chunk_id, number, parent="p_3_2"):
    return {
        "chunk_id": chunk_id,
        "parent_chunk_id": parent,
        "content_type": "table_markdown",
        "content": f"Table {number}: Expenditure Details\n| a | b |\n| --- | --- |",
        "structured_data": {"table_number": number},
        "source_page_physical": 5,
    }


class TestEvidenceLinking:
    """Test linking findings to evidence."""

    def setup_method(self):
        """Set up test fixtures."""
        self.linker = evidence_linker.EvidenceLinker()

    def test_link_finding_to_table(self):
        """A table_markdown chunk is found by its table number."""
        finding = {
            "finding_id": "report_001_finding_001",
            "text": "As shown in Table 3.2, the expenditure was irregular.",
        }
        links = self.linker.link_finding_to_evidence(
            finding, [], [_table("table_001", "3.2")]
        )

        table_links = [link for link in links if link.evidence_type == "table"]
        assert len(table_links) == 1
        assert table_links[0].evidence_id == "table_001"
        assert table_links[0].finding_id == "report_001_finding_001"

    def test_link_finding_to_paragraph(self):
        """A paragraph reference resolves to the section with that number."""
        finding = {
            "finding_id": "report_001_finding_002",
            "text": "As mentioned in Para 4.5, the approval was missing.",
        }
        parents = [
            _parent("p_4_5", "4.5 Approvals"),
            _parent("p_4_5_1", "4.5.1 Delays"),
        ]

        links = self.linker.link_finding_to_evidence(
            finding, [], [], parent_chunks=parents
        )

        para_links = [link for link in links if link.evidence_type == "paragraph"]
        assert [link.evidence_id for link in para_links] == ["p_4_5"]

    def test_paragraph_falls_back_to_nearest_section(self):
        """'Para 4.5.1.3' (not a contents entry) resolves to section 4.5.1, at lower confidence."""
        finding = {"finding_id": "f", "text": "As discussed in Para 4.5.1.3 above."}
        parents = [
            _parent("p_4_5", "4.5 Approvals"),
            _parent("p_4_5_1", "4.5.1 Delays"),
        ]

        links = self.linker.link_finding_to_evidence(
            finding, [], [], parent_chunks=parents
        )

        assert [link.evidence_id for link in links] == ["p_4_5_1"]
        assert links[0].confidence < 0.95

    def test_paragraph_numbers_not_joined_from_hierarchy(self):
        """['2.1 Planning', '2.1.1 Funds'] is section 2.1.1, never '2.2'."""
        finding = {"finding_id": "f", "text": "See Para 2.2 on staffing."}
        chunks = [
            {
                "chunk_id": "c1",
                "parent_chunk_id": "p_211",
                "content": "x",
                "hierarchy": {"level_1": "2.1 Planning", "level_2": "2.1.1 Funds"},
            },
            {
                "chunk_id": "c2",
                "parent_chunk_id": "p_22",
                "content": "y",
                "hierarchy": {"level_1": "Chapter 2", "level_2": "2.2 Staffing"},
            },
        ]
        links = self.linker.link_finding_to_evidence(finding, [], chunks)
        assert [link.evidence_id for link in links] == ["p_22"]

    def test_other_documents_paragraph_not_linked(self):
        """'Paragraph 4.4.1 of SSIF' is the framework's paragraph, not this report's."""
        finding = {
            "finding_id": "f",
            "text": "Paragraph 4.4.1 of SSIF requires mapping of habitations.",
        }
        links = self.linker.link_finding_to_evidence(
            finding, [], [], parent_chunks=[_parent("p", "4.4.1 Mapping")]
        )
        assert links == []

    def test_appendix_linked_to_its_parent(self):
        """'Appendix' is recognised, with its dotted number intact."""
        finding = {
            "finding_id": "f",
            "text": "Students were deprived of uniforms (Appendix 8.1).",
        }
        parents = [
            _parent("a81", "Appendix 8.1 Statement of students"),
            _parent("a8", "Appendix 8 Other"),
        ]
        links = self.linker.link_finding_to_evidence(
            finding, [], [], parent_chunks=parents
        )
        assert [(link.evidence_type, link.evidence_id) for link in links] == [
            ("annexure", "a81")
        ]

    def test_page_reference_not_linked(self):
        """A bare page number points at nothing in the report: extracted, not linked."""
        finding = {
            "finding_id": "report_001_finding_003",
            "text": "The issue is documented on page 42.",
        }

        assert self.linker.link_finding_to_evidence(finding, [], []) == []
        assert any(
            r.reference_type == "page"
            for r in self.linker.extract_references(finding["text"])
        )

    def test_own_chunk_is_not_evidence(self):
        """A finding whose chunk is the table's caption does not link to its own table."""
        table = _table("t1", "3.2")
        finding = {
            "finding_id": "f",
            "text": table["content"],
            "source_chunk_ids": ["t1"],
        }
        assert self.linker.link_finding_to_evidence(finding, [], [table]) == []

    def test_link_finding_with_multiple_evidence(self):
        """Test linking finding with multiple evidence items."""
        finding = {
            "finding_id": "report_001_finding_004",
            "text": "As per Para 3.2 and Table 4.1, the expenditure in Annexure A exceeded limits.",
        }
        parents = [
            _parent("p_3_2", "3.2 Expenditure"),
            _parent("ann_a", "Annexure A: Detailed Breakdown"),
        ]

        links = self.linker.link_finding_to_evidence(
            finding, [_table("table_041", "4.1")], [], parent_chunks=parents
        )

        assert {(link.evidence_type, link.evidence_id) for link in links} == {
            ("paragraph", "p_3_2"),
            ("table", "table_041"),
            ("annexure", "ann_a"),
        }

    def test_no_links_for_finding_without_references(self):
        """Test that findings without references have no links."""
        finding = {
            "finding_id": "report_001_finding_005",
            "text": "The expenditure was irregular and violated rules.",
        }

        links = self.linker.link_finding_to_evidence(finding, [], [])

        assert len(links) == 0


class TestEvidenceResolution:
    """Test evidence resolution helpers."""

    def setup_method(self):
        """Set up test fixtures."""
        self.linker = evidence_linker.EvidenceLinker()

    def test_parse_page_number(self):
        """Test parsing page numbers."""
        assert self.linker._parse_page_number("42") == 42
        assert (
            self.linker._parse_page_number("25-30") == 25
        )  # Range should return first
        assert self.linker._parse_page_number("100") == 100


class TestBulkLinking:
    """Test bulk linking operations."""

    def setup_method(self):
        """Set up test fixtures."""
        self.linker = evidence_linker.EvidenceLinker()

    def test_link_all_findings(self):
        """Test linking multiple findings."""
        findings = [
            {"finding_id": "f1", "text": "As per Table 3.2, the loss was ₹100 crore."},
            {"finding_id": "f2", "text": "Para 4.5 mentions the approval process."},
            {
                "finding_id": "f3",
                "text": "The expenditure was irregular.",
            },  # No references
        ]
        chunks = [
            _table("t1", "3.2"),
            {
                "chunk_id": "c1",
                "parent_chunk_id": "p_4_5",
                "content": "Approval...",
                "hierarchy": {"level_1": "Chapter 4", "level_2": "4.5 Approvals"},
            },
        ]

        all_links = self.linker.link_all_findings(findings, [], chunks)

        assert "f1" in all_links
        assert "f2" in all_links
        assert "f3" not in all_links  # No references, so no links
        assert any(link.evidence_type == "table" for link in all_links["f1"])
        assert [link.evidence_id for link in all_links["f2"]] == ["p_4_5"]


class TestLinkCoverageStatistics:
    """Test link coverage calculation."""

    def test_calculate_coverage_with_links(self):
        """Test coverage calculation with some linked findings."""
        findings = [
            {"finding_id": "f1"},
            {"finding_id": "f2"},
            {"finding_id": "f3"},
        ]

        evidence_links = {
            "f1": [
                evidence_linker.EvidenceLink(
                    link_id="l1",
                    finding_id="f1",
                    evidence_type="table",
                    evidence_id="t1",
                    reference_text="Table 3.2",
                    confidence=0.95,
                )
            ],
            "f2": [
                evidence_linker.EvidenceLink(
                    link_id="l2",
                    finding_id="f2",
                    evidence_type="paragraph",
                    evidence_id="p1",
                    reference_text="Para 4.5",
                    confidence=0.9,
                ),
                evidence_linker.EvidenceLink(
                    link_id="l3",
                    finding_id="f2",
                    evidence_type="page",
                    evidence_id="42",
                    reference_text="page 42",
                    confidence=0.85,
                ),
            ],
        }

        stats = evidence_linker.calculate_link_coverage(findings, evidence_links)

        assert stats["total_findings"] == 3
        assert stats["findings_with_links"] == 2
        assert abs(stats["coverage_percentage"] - 66.67) < 0.1
        assert stats["total_links"] == 3
        assert abs(stats["avg_links_per_finding"] - 1.0) < 0.1
        assert stats["links_by_type"]["table"] == 1
        assert stats["links_by_type"]["paragraph"] == 1
        assert stats["links_by_type"]["page"] == 1

    def test_calculate_coverage_no_findings(self):
        """Test coverage calculation with no findings."""
        stats = evidence_linker.calculate_link_coverage([], {})

        assert stats["total_findings"] == 0
        assert stats["findings_with_links"] == 0
        assert stats["coverage_percentage"] == 0.0


class TestEdgeCases:
    """Test edge cases and error handling."""

    def setup_method(self):
        """Set up test fixtures."""
        self.linker = evidence_linker.EvidenceLinker()

    def test_empty_finding_text(self):
        """Test handling of empty finding text."""
        finding = {"finding_id": "f1", "text": ""}
        links = self.linker.link_finding_to_evidence(finding, [], [])
        assert len(links) == 0

    def test_finding_without_text_field(self):
        """Test handling of finding without text field."""
        finding = {"finding_id": "f1"}
        links = self.linker.link_finding_to_evidence(finding, [], [])
        assert len(links) == 0

    def test_duplicate_references(self):
        """Test handling of duplicate references in text."""
        finding = {
            "finding_id": "f1",
            "text": "Table 3.2 shows revenue. As seen in Table 3.2, the amount was high.",
        }

        links = self.linker.link_finding_to_evidence(finding, [_table("t1", "3.2")], [])

        # One link per target: "(Annexure 8)" and "Annexure 8" are not two links
        table_links = [link for link in links if link.evidence_type == "table"]
        assert len(table_links) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
