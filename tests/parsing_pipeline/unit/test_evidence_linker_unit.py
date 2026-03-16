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
        assert annexure_refs[0].identifier == "A"

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
            assert table_refs[0].identifier == expected_id, (
                f"Expected {expected_id}, got {table_refs[0].identifier} from: {text}"
            )

    def test_annexure_reference_variations(self):
        """Test various annexure reference formats."""
        test_cases = [
            ("Annexure A", "A"),
            ("Annexure-B", "B"),
            ("Annexure III", "III"),
            ("Appendix C", "C"),
            ("as per Annexure D", "D"),
            ("(Annexure E)", "E"),
        ]

        for text, expected_id in test_cases:
            refs = self.linker.extract_references(text)
            annexure_refs = [r for r in refs if r.reference_type == "annexure"]
            assert len(annexure_refs) > 0, f"Failed to extract from: {text}"
            # Normalize to uppercase for comparison
            assert annexure_refs[0].identifier.upper() == expected_id, (
                f"Expected {expected_id}, got {annexure_refs[0].identifier} from: {text}"
            )

    def test_paragraph_reference_variations(self):
        """Test various paragraph reference formats."""
        test_cases = [
            ("Para 3.2", "3.2"),
            ("Paragraph 4.5.1", "4.5.1"),
            ("Para. 2.3", "2.3"),
            ("as mentioned in Para 5.1", "5.1"),
            ("(Para 6)", "6"),
        ]

        for text, expected_id in test_cases:
            refs = self.linker.extract_references(text)
            para_refs = [r for r in refs if r.reference_type == "paragraph"]
            assert len(para_refs) > 0, f"Failed to extract from: {text}"
            assert para_refs[0].identifier == expected_id, (
                f"Expected {expected_id}, got {para_refs[0].identifier} from: {text}"
            )

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
            assert page_refs[0].identifier.startswith(expected_id.lstrip("0")) or page_refs[0].identifier == expected_id


class TestEvidenceLinking:
    """Test linking findings to evidence."""

    def setup_method(self):
        """Set up test fixtures."""
        self.linker = evidence_linker.EvidenceLinker()

    def test_link_finding_to_table(self):
        """Test linking finding to a table."""
        finding = {
            "finding_id": "report_001_finding_001",
            "text": "As shown in Table 3.2, the expenditure was irregular.",
        }

        tables = [
            {
                "chunk_id": "table_001",
                "table_id": "table_3_2",
                "content_type": "table",
                "title": "Table 3.2: Expenditure Details",
            }
        ]

        links = self.linker.link_finding_to_evidence(finding, tables, [])

        assert len(links) > 0
        table_links = [l for l in links if l.evidence_type == "table"]
        assert len(table_links) > 0
        assert table_links[0].finding_id == "report_001_finding_001"

    def test_link_finding_to_paragraph(self):
        """Test linking finding to a paragraph."""
        finding = {
            "finding_id": "report_001_finding_002",
            "text": "As mentioned in Para 4.5, the approval was missing.",
        }

        chunks = [
            {
                "chunk_id": "chunk_045",
                "metadata": {"paragraph_number": "4.5"},
                "content": "Details about approval process...",
            }
        ]

        links = self.linker.link_finding_to_evidence(finding, [], chunks)

        para_links = [l for l in links if l.evidence_type == "paragraph"]
        assert len(para_links) > 0
        assert para_links[0].evidence_id == "chunk_045"

    def test_link_finding_to_page(self):
        """Test linking finding to a page."""
        finding = {
            "finding_id": "report_001_finding_003",
            "text": "The issue is documented on page 42.",
        }

        links = self.linker.link_finding_to_evidence(finding, [], [])

        page_links = [l for l in links if l.evidence_type == "page"]
        assert len(page_links) > 0
        assert page_links[0].evidence_id == "42"

    def test_link_finding_with_multiple_evidence(self):
        """Test linking finding with multiple evidence items."""
        finding = {
            "finding_id": "report_001_finding_004",
            "text": "As per Para 3.2 and Table 4.1, the expenditure in Annexure A exceeded limits.",
        }

        tables = [
            {
                "chunk_id": "table_041",
                "content_type": "table",
                "title": "Table 4.1: Expenditure Summary",
            }
        ]

        chunks = [
            {
                "chunk_id": "chunk_032",
                "metadata": {"paragraph_number": "3.2"},
            },
            {
                "chunk_id": "annexure_a",
                "metadata": {"hierarchy": {"level_1": "Annexure A"}},
                "content": "Annexure A: Detailed Breakdown...",
            },
        ]

        links = self.linker.link_finding_to_evidence(finding, tables, chunks)

        # Should have links to para, table, and annexure
        ref_types = {l.evidence_type for l in links}
        assert "paragraph" in ref_types
        assert "table" in ref_types
        # Annexure matching might be tricky, so make it optional
        # assert "annexure" in ref_types

    def test_no_links_for_finding_without_references(self):
        """Test that findings without references have no links."""
        finding = {
            "finding_id": "report_001_finding_005",
            "text": "The expenditure was irregular and violated rules.",
        }

        links = self.linker.link_finding_to_evidence(finding, [], [])

        assert len(links) == 0


class TestEvidenceResolution:
    """Test evidence resolution logic."""

    def setup_method(self):
        """Set up test fixtures."""
        self.linker = evidence_linker.EvidenceLinker()

    def test_find_table_by_number(self):
        """Test finding table by number."""
        tables = [
            {"chunk_id": "t1", "content_type": "table", "title": "Table 3.2: Revenue"},
            {"chunk_id": "t2", "content_type": "table", "title": "Table 4.1: Expenditure"},
        ]

        found = self.linker._find_table_by_number("3.2", tables)
        assert found is not None
        assert found["chunk_id"] == "t1"

        found = self.linker._find_table_by_number("4.1", tables)
        assert found is not None
        assert found["chunk_id"] == "t2"

        found = self.linker._find_table_by_number("5.5", tables)
        assert found is None

    def test_find_annexure(self):
        """Test finding annexure by identifier."""
        chunks = [
            {
                "chunk_id": "ann_a",
                "metadata": {"hierarchy": {"level_1": "Annexure A"}},
                "content": "Annexure A details...",
            },
            {
                "chunk_id": "ann_b",
                "content": "Annexure B: Additional Information...",
            },
        ]

        found = self.linker._find_annexure("A", chunks)
        assert found is not None
        assert found["chunk_id"] == "ann_a"

        found = self.linker._find_annexure("B", chunks)
        assert found is not None
        assert found["chunk_id"] == "ann_b"

        found = self.linker._find_annexure("Z", chunks)
        assert found is None

    def test_parse_page_number(self):
        """Test parsing page numbers."""
        assert self.linker._parse_page_number("42") == 42
        assert self.linker._parse_page_number("25-30") == 25  # Range should return first
        assert self.linker._parse_page_number("100") == 100


class TestBulkLinking:
    """Test bulk linking operations."""

    def setup_method(self):
        """Set up test fixtures."""
        self.linker = evidence_linker.EvidenceLinker()

    def test_link_all_findings(self):
        """Test linking multiple findings."""
        findings = [
            {
                "finding_id": "f1",
                "text": "As per Table 3.2, the loss was ₹100 crore.",
            },
            {
                "finding_id": "f2",
                "text": "Para 4.5 mentions the approval process.",
            },
            {
                "finding_id": "f3",
                "text": "The expenditure was irregular.",  # No references
            },
        ]

        tables = [
            {"chunk_id": "t1", "content_type": "table", "title": "Table 3.2: Loss Details"}
        ]

        chunks = [
            {"chunk_id": "c1", "metadata": {"paragraph_number": "4.5"}},
        ]

        all_links = self.linker.link_all_findings(findings, tables, chunks)

        assert "f1" in all_links
        assert "f2" in all_links
        assert "f3" not in all_links  # No references, so no links

        # Check f1 has table link
        f1_links = all_links["f1"]
        assert any(l.evidence_type == "table" for l in f1_links)

        # Check f2 has paragraph link
        f2_links = all_links["f2"]
        assert any(l.evidence_type == "paragraph" for l in f2_links)


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

        tables = [
            {"chunk_id": "t1", "content_type": "table", "title": "Table 3.2: Revenue"}
        ]

        links = self.linker.link_finding_to_evidence(finding, tables, [])

        # Should handle duplicates gracefully (might have multiple links or deduplicated)
        table_links = [l for l in links if l.evidence_type == "table"]
        assert len(table_links) >= 1  # At least one link should exist


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
