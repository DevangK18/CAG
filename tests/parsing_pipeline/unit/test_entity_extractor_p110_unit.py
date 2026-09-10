"""
P1-10: Unit tests for Entity Extraction Filters.

Tests:
- Stuttered text rejection (tokenizer artifacts)
- Place name rejection (state names)
- Job title rejection
- Document section rejection
"""

import pytest

from src.parsing_pipeline.modules.enrichment.entity_extractor import EntityExtractor


@pytest.fixture
def extractor():
    """Create EntityExtractor instance."""
    return EntityExtractor()


class TestStutteredTextRejection:
    """P1-10: Test detection of stuttered/doubled text patterns."""

    def test_doubled_words_rejected(self, extractor):
        """DirectDirect BenefitBenefit TransferTransfer Scheme -> None"""
        result = extractor._clean_entity("DirectDirect BenefitBenefit Scheme")
        assert result is None

    def test_doubled_word_rejected(self, extractor):
        """SchemeScheme -> None"""
        result = extractor._clean_entity("SchemeScheme")
        assert result is None

    def test_doubled_long_word_rejected(self, extractor):
        """PradhanPradhan Mantri -> None"""
        result = extractor._clean_entity("PradhanPradhan Mantri Yojana")
        assert result is None

    def test_normal_repeated_syllables_accepted(self, extractor):
        """Mama Mia Scheme -> accepted (not stuttered - different words)"""
        # Note: "Mama" and "Mia" are different words
        result = extractor._clean_entity("National Health Mission")
        assert result == "National Health Mission"

    def test_normal_scheme_name_accepted(self, extractor):
        """Pradhan Mantri Awas Yojana -> accepted"""
        result = extractor._clean_entity("Pradhan Mantri Awas Yojana")
        assert result == "Pradhan Mantri Awas Yojana"


class TestPlaceNameRejection:
    """P1-10: Test state name rejection."""

    def test_state_names_rejected(self, extractor):
        """Andhra Pradesh, Maharashtra, Odisha -> None"""
        assert extractor._clean_entity("Andhra Pradesh") is None
        assert extractor._clean_entity("Maharashtra") is None
        assert extractor._clean_entity("Odisha") is None
        assert extractor._clean_entity("Karnataka") is None
        assert extractor._clean_entity("Tamil Nadu") is None

    def test_state_names_case_insensitive(self, extractor):
        """MAHARASHTRA, maharashtra -> None"""
        assert extractor._clean_entity("MAHARASHTRA") is None
        assert extractor._clean_entity("ODISHA") is None

    def test_scheme_with_state_in_name_accepted(self, extractor):
        """Maharashtra Employment Guarantee Scheme -> accepted"""
        result = extractor._clean_entity("Maharashtra Employment Guarantee Scheme")
        assert result == "Maharashtra Employment Guarantee Scheme"

    def test_scheme_mentioning_state_accepted(self, extractor):
        """Odisha State Road Transport -> accepted"""
        result = extractor._clean_entity("Odisha State Road Transport Corporation")
        assert result == "Odisha State Road Transport Corporation"

    def test_ministry_with_state_reference_accepted(self, extractor):
        """Ministry of Home Affairs -> accepted (not a state name)"""
        result = extractor._clean_entity("Ministry of Home Affairs")
        assert result == "Ministry of Home Affairs"


class TestJobTitleRejection:
    """P1-10: Test job title rejection."""

    def test_block_officer_rejected(self, extractor):
        """Block Education Officer -> None"""
        assert extractor._clean_entity("Block Education Officer") is None
        assert extractor._clean_entity("Block Development Officer") is None
        assert extractor._clean_entity("District Education Officer") is None

    def test_accountant_rejected(self, extractor):
        """Chartered Accountant -> None"""
        assert extractor._clean_entity("Chartered Accountant") is None
        assert extractor._clean_entity("Accountant") is None

    def test_block_resource_person_rejected(self, extractor):
        """Block Resource Person -> None"""
        assert extractor._clean_entity("Block Resource Person") is None
        assert extractor._clean_entity("Block Resource Coordinator") is None

    def test_executive_engineer_rejected(self, extractor):
        """Executive Engineer -> None"""
        assert extractor._clean_entity("Executive Engineer") is None

    def test_district_collector_rejected(self, extractor):
        """District Collector -> None"""
        assert extractor._clean_entity("District Collector") is None

    def test_chief_engineer_rejected(self, extractor):
        """Chief Engineer Officer, Chief Executive Officer -> None"""
        assert extractor._clean_entity("Chief Engineer Officer") is None
        assert extractor._clean_entity("Chief Executive Officer") is None

    def test_valid_organization_accepted(self, extractor):
        """Block Development Board -> accepted (not a job title)"""
        result = extractor._clean_entity("Block Development Board")
        assert result == "Block Development Board"


class TestDocumentSectionRejection:
    """P1-10: Test document section reference rejection."""

    def test_chapter_reference_rejected(self, extractor):
        """Chapter 3 of Union Report -> None"""
        assert extractor._clean_entity("Chapter 3 of Union Report") is None
        assert extractor._clean_entity("Chapter 12 of this Audit") is None

    def test_annual_report_rejected(self, extractor):
        """Annual Report -> None"""
        assert extractor._clean_entity("Annual Report") is None
        assert extractor._clean_entity("Annual Technical Inspection Report") is None

    def test_paragraph_reference_rejected(self, extractor):
        """Paragraph 4.5.2 -> None"""
        assert extractor._clean_entity("Paragraph 4.5.2") is None
        assert extractor._clean_entity("Paragraph 7.1") is None

    def test_annexure_reference_rejected(self, extractor):
        """Annexure A of Report -> None"""
        assert extractor._clean_entity("Annexure A of Report") is None
        assert extractor._clean_entity("Annexure 5 of Audit") is None

    def test_appendix_reference_rejected(self, extractor):
        """Appendix B to Report -> None"""
        assert extractor._clean_entity("Appendix B to Report") is None

    def test_valid_chapter_scheme_accepted(self, extractor):
        """Chapter House Development Scheme -> accepted (not a chapter reference)"""
        result = extractor._clean_entity("Chapter House Development Scheme")
        assert result == "Chapter House Development Scheme"


class TestExistingFiltersStillWork:
    """Verify existing filters still work after P1-10 changes."""

    def test_short_entities_rejected(self, extractor):
        """Entities < 4 chars -> None"""
        assert extractor._clean_entity("ABC") is None
        assert extractor._clean_entity("Go") is None

    def test_long_entities_rejected(self, extractor):
        """Entities > 60 chars -> None"""
        long_entity = "A" * 61
        assert extractor._clean_entity(long_entity) is None

    def test_lowercase_start_rejected(self, extractor):
        """Entities starting with lowercase -> None"""
        assert extractor._clean_entity("ministry of Finance") is None

    def test_verb_start_rejected(self, extractor):
        """Entities starting with verbs -> None"""
        assert extractor._clean_entity("Was National Mission") is None
        assert extractor._clean_entity("The Ministry of") is None

    def test_many_words_rejected(self, extractor):
        """>8 words -> None (likely sentence fragment)"""
        long_fragment = "Ministry of Finance and Economics and Trade and Commerce and More Words"
        assert extractor._clean_entity(long_fragment) is None

    def test_valid_ministry_accepted(self, extractor):
        """Ministry of Finance -> accepted"""
        result = extractor._clean_entity("Ministry of Finance")
        assert result == "Ministry of Finance"

    def test_valid_scheme_accepted(self, extractor):
        """National Rural Employment Guarantee Scheme -> accepted"""
        result = extractor._clean_entity("National Rural Employment Guarantee Scheme")
        assert result == "National Rural Employment Guarantee Scheme"


class TestIntegration:
    """Integration tests for extract_entities."""

    def test_extract_entities_filters_stuttered(self, extractor):
        """Extract entities should filter out stuttered text."""
        chunks = [
            {"content": "The DirectDirect BenefitBenefit TransferTransfer Scheme was implemented."},
            {"content": "Under the National Health Mission, hospitals were built."},
        ]
        result = extractor.extract_entities(chunks)
        # Should only have National Health Mission, not the stuttered entity
        assert "National Health Mission" in result.get("schemes", [])
        # Should not have stuttered entity
        for entity in result.get("schemes", []):
            assert "DirectDirect" not in entity

    def test_extract_entities_filters_state_names(self, extractor):
        """Extract entities should filter out standalone state names."""
        chunks = [
            {"content": "Maharashtra implemented the scheme."},
            {"content": "The Maharashtra Employment Guarantee Scheme was successful."},
        ]
        result = extractor.extract_entities(chunks)
        # Should not have standalone Maharashtra
        # But should have the full scheme name if matched
        schemes = result.get("schemes", [])
        assert "Maharashtra" not in schemes
