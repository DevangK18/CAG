"""
P0-08: Unit tests for RecommendationExtractor enhancements.

Tests:
- List-after-cue pattern ("We recommend that:\n1. ...")
- Verb rejection patterns (PAC/Guideline citations)
- Enhanced addressee extraction
"""

import pytest
from src.parsing_pipeline.modules.enrichment.recommendation_extractor import (
    RecommendationExtractor,
    ExtractedRecommendation,
)


@pytest.fixture
def extractor():
    """Create RecommendationExtractor instance."""
    return RecommendationExtractor()


class TestListAfterCuePattern:
    """Test P0-08 list-after-cue pattern extraction."""

    def test_basic_list_after_cue(self, extractor):
        """Test basic 'We recommend that:\n1. ...' pattern."""
        chunks = [
            {
                "content": """We recommend that:
1. The Ministry should strengthen internal controls.
2. The Department may expedite the pending cases.
3. Regular monitoring should be ensured.""",
                "chunk_id": "chunk_001",
                "source_page_physical": 10,
                "hierarchy": {"level_1": "Chapter 3"},
            }
        ]
        recs = extractor._extract_list_after_cue(chunks, "test_report")
        assert len(recs) == 3
        assert "strengthen internal controls" in recs[0].text
        assert recs[0].extraction_strategy == "list_after_cue"
        assert recs[0].confidence == 0.90

    def test_audit_recommends_list_pattern(self, extractor):
        """Test 'Audit recommends that:\n1. ...' pattern."""
        chunks = [
            {
                "content": """Audit recommends that:
1. A comprehensive review of the scheme should be undertaken.
2. The backlog of cases should be cleared expeditiously.""",
                "chunk_id": "chunk_002",
                "source_page_physical": 15,
                "hierarchy": {"level_1": "Chapter 4"},
            }
        ]
        recs = extractor._extract_list_after_cue(chunks, "test_report")
        assert len(recs) == 2
        assert "comprehensive review" in recs[0].text

    def test_no_list_after_cue(self, extractor):
        """Test text without list-after-cue pattern."""
        chunks = [
            {
                "content": "The Ministry should consider revising the guidelines.",
                "chunk_id": "chunk_003",
                "source_page_physical": 20,
                "hierarchy": {},
            }
        ]
        recs = extractor._extract_list_after_cue(chunks, "test_report")
        assert len(recs) == 0


class TestVerbRejectionPatterns:
    """Test P0-08 verb rejection patterns."""

    def test_pac_observation_rejected(self, extractor):
        """Test that PAC observations are rejected."""
        text = "PAC2020 was of the view that the Ministry should take corrective action."
        assert extractor._is_verb_false_positive(text) is True

    def test_guidelines_mandate_rejected(self, extractor):
        """Test that 'Guidelines mandate' citations are rejected."""
        text = "The GFR Guidelines mandate that all expenditure should be approved."
        assert extractor._is_verb_false_positive(text) is True

    def test_paragraph_mandates_rejected(self, extractor):
        """Test that 'Paragraph X mandates' citations are rejected."""
        text = "Paragraph 12.5 of the Manual states that verification should be done."
        assert extractor._is_verb_false_positive(text) is True

    def test_as_per_act_rejected(self, extractor):
        """Test that 'As per the Act' citations are rejected."""
        text = "As per the FRBM Act, the government should maintain fiscal discipline."
        assert extractor._is_verb_false_positive(text) is True

    def test_section_stipulates_rejected(self, extractor):
        """Test that 'Section X stipulates' citations are rejected."""
        text = "Section 15 of the Act stipulates that returns should be filed quarterly."
        assert extractor._is_verb_false_positive(text) is True

    def test_ministry_stated_rejected(self, extractor):
        """Test that 'Ministry has stated that' citations are rejected."""
        text = "Ministry has stated that action should be taken within 30 days."
        assert extractor._is_verb_false_positive(text) is True

    def test_actual_recommendation_not_rejected(self, extractor):
        """Test that actual recommendations are not rejected."""
        text = "Audit recommends that the Ministry should strengthen internal controls."
        assert extractor._is_verb_false_positive(text) is False

    def test_simple_should_not_rejected(self, extractor):
        """Test that simple 'should' recommendations are not rejected."""
        text = "The Department should expedite settlement of pending cases."
        assert extractor._is_verb_false_positive(text) is False


class TestEnhancedAddresseeExtraction:
    """Test P0-08 enhanced addressee extraction."""

    def test_ministry_should_pattern(self, extractor):
        """Test extraction of 'Ministry of X should' addressee."""
        text = "The Ministry of Railways should strengthen monitoring mechanisms."
        addressee = extractor._extract_target(text)
        assert addressee is not None
        assert "Railways" in addressee

    def test_department_may_pattern(self, extractor):
        """Test extraction of 'Department of X may' addressee."""
        text = "The Department of Health may consider revising the guidelines."
        addressee = extractor._extract_target(text)
        assert addressee is not None

    def test_acronym_should_pattern(self, extractor):
        """Test extraction of 'NHAI should' addressee."""
        text = "NHAI should ensure timely completion of the project."
        addressee = extractor._extract_target(text)
        assert addressee == "NHAI"

    def test_recommended_that_ministry_pattern(self, extractor):
        """Test 'It is recommended that Ministry should' pattern."""
        text = "It is recommended that the Ministry of Finance should review the scheme."
        addressee = extractor._extract_target(text)
        assert addressee is not None

    def test_generic_addressee_rejected(self, extractor):
        """Test that generic pronouns are rejected."""
        text = "The payments should be verified before release."
        # 'The' alone should not be extracted as an addressee
        addressee = extractor._extract_target(text)
        # Either None or a proper entity, not 'The'
        if addressee:
            assert addressee.lower() != "the"

    def test_long_addressee_truncated(self, extractor):
        """Test that overly long addressees are truncated."""
        text = "Ministry of Road Transport and Highways and National Highways Authority of India and State PWDs should coordinate."
        addressee = extractor._extract_target(text)
        if addressee:
            assert len(addressee) <= 50


class TestExtractAllWithEnhancements:
    """Test extract_all method with P0-08 enhancements."""

    def test_list_after_cue_in_extract_all(self, extractor):
        """Test that list-after-cue is used in extract_all."""
        parent_chunks = [
            {"chunk_id": "parent_001", "toc_entry": "Chapter 3: Audit Findings"}
        ]
        child_chunks = [
            {
                "content": """We recommend that:
1. The Ministry should strengthen controls.
2. Regular monitoring should be ensured.""",
                "chunk_id": "child_001",
                "parent_chunk_id": "parent_001",
                "source_page_physical": 10,
                "content_type": "paragraph",
                "hierarchy": {},
            }
        ]
        section_classifications = []
        recs = extractor.extract_all("test_report", parent_chunks, child_chunks, section_classifications)
        # Should find the list-after-cue recommendations
        list_cue_recs = [r for r in recs if r.extraction_strategy == "list_after_cue"]
        assert len(list_cue_recs) == 2

    def test_verb_false_positives_filtered(self, extractor):
        """Test that verb false positives are filtered out."""
        parent_chunks = []
        child_chunks = [
            {
                "content": "PAC2020 was of the view that the Ministry should take action.",
                "chunk_id": "child_001",
                "parent_chunk_id": "",
                "source_page_physical": 5,
                "content_type": "paragraph",
                "hierarchy": {},
            },
            {
                "content": "The Ministry should strengthen the internal control mechanism.",
                "chunk_id": "child_002",
                "parent_chunk_id": "",
                "source_page_physical": 6,
                "content_type": "paragraph",
                "hierarchy": {},
            },
        ]
        section_classifications = []
        recs = extractor.extract_all("test_report", parent_chunks, child_chunks, section_classifications)
        # PAC citation should be filtered out
        assert all("PAC2020" not in r.text for r in recs)


class TestRecNumberExtraction:
    """Test recommendation number extraction from list-after-cue."""

    def test_rec_number_from_list(self, extractor):
        """Test that rec_number is extracted from numbered list."""
        chunks = [
            {
                "content": """We recommend that:
1. The Ministry should strengthen controls.
2. The Department should review the process.""",
                "chunk_id": "chunk_001",
                "source_page_physical": 10,
                "hierarchy": {},
            }
        ]
        recs = extractor._extract_list_after_cue(chunks, "test_report")
        assert recs[0].rec_number == "Recommendation 1"
        assert recs[1].rec_number == "Recommendation 2"


class TestInterimVerbPatterns:
    """PR 6 section 5: recommendation forms from the gold labels."""

    @staticmethod
    def _verb_recs(extractor, text):
        chunks = [{"content": text, "chunk_id": "c1", "source_page_physical": 14,
                   "content_type": "paragraph", "hierarchy": {"level_1": "Chapter 2"}}]
        return extractor._extract_verb_based(chunks, "r")

    @pytest.mark.parametrize("text", [
        # 2025_08 R002: "N)" numbering, mixed-case acronym
        "2) MoES may clearly define the revised targets commensurate with the resources during "
        "reformulation to enable assessment of achievements against the targets.",
        # OD_2025_05 R017: "The Department may <verb>"
        "The Department may take steps to maintain the normative Pupil- Teacher Ratio by engaging "
        "additional teachers in the schools experiencing shortfalls.",
        # OD_2025_05 R003 / HP_2022 R002: passive "may be ..."
        "Efficient utilisation of allocated funds may be ensured to deliver the educational needs "
        "of the students to the best extent.",
        "Audit memos may be issued to the auditee unit.",
        # HP_2019: roman numeral item
        "ii. Income and expenditure of the Panchayat may be shown separately in the cash book.",
        # BR_2024_03 R001: acronym followed by a comma
        "The UD&HD may ensure, by effective monitoring, timely collection of user charges.",
        # BR_2024_03 R005: plural acronym subject
        "ULBs may strictly ensure segregation of waste at source and door-to-door collection.",
    ])
    def test_recommendation_forms_found(self, extractor, text):
        assert len(self._verb_recs(extractor, text)) == 1

    @pytest.mark.parametrize("text", [
        # OD p.128: under IGNORECASE "[A-Z]{2,8}" matched any word ("uniforms should")
        "During 2018-23, free uniforms should reach students before the session began, but the "
        "supply was delayed in all the sampled districts.",
        # audit rebuttals (2025_08, 2025_38)
        "The reply needs to be viewed in light of the fact that only 30 per cent of the Automatic "
        "Weather Stations were functional.",
        "Reply of the Management may be viewed in the light of the fact that the management has "
        "accepted that there were delays.",
        # passive narrative, not advice
        "It may be noted that funds were released in the last month of the financial year.",
        "It may be noticed that similar recommendations had been made during previous years.",
    ])
    def test_non_recommendations_rejected(self, extractor, text):
        assert self._verb_recs(extractor, text) == []

    def test_acronym_pattern_is_case_sensitive(self, extractor):
        acronym = extractor._verb[3]
        assert acronym.search("CBDT may ensure that all cases are reviewed. ")
        assert not acronym.search("schools should be provided with labs. ")
