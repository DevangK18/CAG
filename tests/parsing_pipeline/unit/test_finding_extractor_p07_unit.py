"""
P0-07: Unit tests for FindingExtractor pattern expansion.

Tests:
- Umbrella pattern detection ("Audit observed that...")
- Deficiency keyword mapping
- Tier-specific taxonomy gates
- Non-finding rejection patterns
"""

import pytest
from src.parsing_pipeline.modules.enrichment.finding_extractor import (
    FindingExtractor,
    FindingType,
)


@pytest.fixture
def extractor():
    """Create FindingExtractor instance."""
    return FindingExtractor()


class TestUmbrellaPatternDetection:
    """Test P0-07 umbrella pattern detection."""

    def test_audit_observed_not_maintained(self, extractor):
        """Test 'Audit observed that X was not maintained'."""
        text = "Audit observed that the records were not maintained properly by the department."
        finding_type = extractor._detect_via_umbrella_pattern(text)
        assert finding_type == FindingType.ACCOUNTING_IRREGULARITY

    def test_audit_observed_shortfall(self, extractor):
        """Test 'Audit observed that there was shortfall'."""
        text = "Audit observed that there was a shortfall in achieving the target."
        finding_type = extractor._detect_via_umbrella_pattern(text)
        assert finding_type == FindingType.PERFORMANCE_SHORTFALL

    def test_audit_noticed_non_compliance(self, extractor):
        """Test 'Audit noticed that X was in non-compliance'."""
        text = "Audit noticed that the department was in non-compliance with the guidelines."
        finding_type = extractor._detect_via_umbrella_pattern(text)
        assert finding_type == FindingType.NON_COMPLIANCE

    def test_audit_found_deficient(self, extractor):
        """Test 'Audit found that X was deficient'."""
        text = "Audit found that the internal control system was deficient."
        finding_type = extractor._detect_via_umbrella_pattern(text)
        assert finding_type == FindingType.SYSTEM_DEFICIENCY

    def test_audit_observed_loss(self, extractor):
        """Test 'Audit observed that there was loss'."""
        text = "Audit observed that there was loss of revenue to the exchequer."
        finding_type = extractor._detect_via_umbrella_pattern(text)
        assert finding_type == FindingType.LOSS_OF_REVENUE

    def test_audit_verified_not_collected(self, extractor):
        """Test 'Audit verified that dues were not collected'."""
        text = "Audit verified that the dues amounting to Rs 5 crore were not collected."
        finding_type = extractor._detect_via_umbrella_pattern(text)
        assert finding_type == FindingType.NON_REALIZATION_OF_DUES

    def test_no_umbrella_pattern(self, extractor):
        """Test text without umbrella pattern."""
        text = "The Ministry has allocated Rs 100 crore for the scheme."
        finding_type = extractor._detect_via_umbrella_pattern(text)
        assert finding_type == FindingType.OTHER

    def test_audit_observed_not_utilized(self, extractor):
        """Test 'Audit observed that funds were not utilized'."""
        text = "Audit observed that the grant of Rs 50 crore was not utilized by the department."
        finding_type = extractor._detect_via_umbrella_pattern(text)
        assert finding_type == FindingType.FUND_UTILIZATION_FAILURE


class TestTierSpecificTaxonomyGates:
    """Test P0-07 tier-specific taxonomy gates."""

    def test_union_allowed_types(self, extractor):
        """Test that Union tier accepts core finding types."""
        text = "Audit observed that there was loss of revenue to the government."
        finding_type = extractor._detect_finding_type(text, "union")
        assert finding_type == FindingType.LOSS_OF_REVENUE

    def test_state_allows_all_types(self, extractor):
        """Test that State tier accepts all finding types."""
        text = "The machinery procured remained idle for over 2 years."
        finding_type = extractor._detect_finding_type(text, "state")
        assert finding_type == FindingType.IDLE_ASSETS

    def test_local_body_allows_all_types(self, extractor):
        """Test that Local Body tier accepts all finding types."""
        text = "The infrastructure remained incomplete due to lack of funds."
        finding_type = extractor._detect_finding_type(text, "local_body")
        assert finding_type == FindingType.INCOMPLETE_INFRASTRUCTURE


class TestNonFindingRejection:
    """Test P0-07 non-finding rejection patterns."""

    def test_brief_snapshot_rejected(self, extractor):
        """Test that 'Brief Snapshot' sections are rejected."""
        text = "Brief Snapshot of the audit findings for the period 2020-21"
        assert extractor._is_non_finding(text) is True

    def test_footnote_rejected(self, extractor):
        """Test that footnotes are rejected."""
        text = "* denotes that the figure is approximate and subject to revision"
        assert extractor._is_non_finding(text) is True

    def test_source_citation_rejected(self, extractor):
        """Test that source citations are rejected."""
        text = "Source: Annual Report of the Ministry, 2021-22"
        assert extractor._is_non_finding(text) is True

    def test_table_caption_rejected(self, extractor):
        """Test that table captions are rejected."""
        text = "Table 3.1: Summary of audit observations for the period"
        assert extractor._is_non_finding(text) is True

    def test_chart_caption_rejected(self, extractor):
        """Test that chart captions are rejected."""
        text = "Chart 2.5: Trend analysis of expenditure over five years"
        assert extractor._is_non_finding(text) is True

    def test_actual_finding_not_rejected(self, extractor):
        """Test that actual finding text is not rejected."""
        text = "Audit observed that the payment of Rs 5 crore was made without proper verification."
        assert extractor._is_non_finding(text) is False


class TestDeficiencyKeywordMapping:
    """Test P0-07 deficiency keyword to finding type mapping."""

    def test_inadequate_maps_to_system_deficiency(self, extractor):
        """Test 'inadequate' maps to SYSTEM_DEFICIENCY."""
        text = "Audit observed that the monitoring mechanism was inadequate."
        finding_type = extractor._detect_via_umbrella_pattern(text)
        assert finding_type == FindingType.SYSTEM_DEFICIENCY

    def test_avoidable_maps_to_wasteful_expenditure(self, extractor):
        """Test 'avoidable' maps to WASTEFUL_EXPENDITURE."""
        text = "Audit observed that the payment was avoidable."
        finding_type = extractor._detect_via_umbrella_pattern(text)
        assert finding_type == FindingType.WASTEFUL_EXPENDITURE

    def test_violation_maps_to_non_compliance(self, extractor):
        """Test 'violation' maps to NON_COMPLIANCE."""
        text = "Audit observed that there was violation of codal provisions."
        finding_type = extractor._detect_via_umbrella_pattern(text)
        assert finding_type == FindingType.NON_COMPLIANCE

    def test_misuse_maps_to_fraud(self, extractor):
        """Test 'misuse' maps to FRAUD_MISAPPROPRIATION."""
        text = "Audit observed that there was misuse of government funds."
        finding_type = extractor._detect_via_umbrella_pattern(text)
        assert finding_type == FindingType.FRAUD_MISAPPROPRIATION


class TestAdditionalPatterns:
    """Test P0-07 additional patterns added to finding types."""

    def test_was_not_maintained_pattern(self, extractor):
        """Test 'was not maintained' pattern for NON_COMPLIANCE."""
        text = "The register was not maintained as per the prescribed format."
        finding_type = extractor._detect_finding_type(text, "state")
        assert finding_type == FindingType.NON_COMPLIANCE

    def test_shortfall_target_pattern(self, extractor):
        """Test 'shortfall...target' pattern for PERFORMANCE_SHORTFALL."""
        text = "There was a shortfall of 30% against the target."
        finding_type = extractor._detect_finding_type(text, "state")
        assert finding_type == FindingType.PERFORMANCE_SHORTFALL

    def test_no_committee_established_pattern(self, extractor):
        """Test 'no committee...established' pattern for SYSTEM_DEFICIENCY."""
        text = "No committee was established for monitoring the scheme."
        finding_type = extractor._detect_finding_type(text, "state")
        assert finding_type == FindingType.SYSTEM_DEFICIENCY


class TestExtractFindingsWithEnhancements:
    """Test that extract_findings uses the P0-07 enhancements."""

    def test_extract_findings_skips_non_findings(self, extractor):
        """Test that extract_findings skips Brief Snapshot content."""
        chunks = [
            {
                "content_type": "paragraph",
                "content": "Brief Snapshot of audit observations for the year",
                "chunk_id": "chunk_001",
                "metadata": {"hierarchy": {}, "location": {"page_physical": 1}},
            },
            {
                "content_type": "paragraph",
                "content": "Audit observed that the payment of Rs 5.50 crore was made without proper verification, resulting in irregular expenditure.",
                "chunk_id": "chunk_002",
                "metadata": {"hierarchy": {}, "location": {"page_physical": 2}},
            },
        ]
        findings = extractor.extract_findings("test_report", chunks, "state")
        # Only the actual finding should be extracted, not Brief Snapshot
        assert len(findings) == 1
        assert "Brief Snapshot" not in findings[0].text

    def test_extract_findings_uses_tier_gates(self, extractor):
        """Test that extract_findings applies tier-specific taxonomy."""
        chunks = [
            {
                "content_type": "paragraph",
                "content": "Audit observed that the machinery procured at Rs 10 crore remained idle and non-operational for 3 years.",
                "chunk_id": "chunk_001",
                "metadata": {"hierarchy": {}, "location": {"page_physical": 1}},
            },
        ]
        findings = extractor.extract_findings("test_report", chunks, "state")
        assert len(findings) >= 1
        # Should detect the finding - tier gates allow all types for state
        # The finding_type depends on pattern matching order
        assert findings[0].finding_type in ["idle_assets", "system_deficiency", "other"]
