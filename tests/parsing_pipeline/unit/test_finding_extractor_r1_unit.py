"""
R1: Unit tests for contextual/statistical pattern rejection in FindingExtractor.

Tests the NON_FINDING_PATTERNS additions that block background statistics
from being extracted as findings.

Key patterns tested:
- Multi-year span patterns (e.g., "during FYs 2003-04 to 2021-22")
- Table reference patterns (e.g., "as depicted in Table 1.6")
- Source compilation patterns (e.g., "compiled by the AG")
- Background allocation patterns (e.g., "released grants of ₹60,000 crore during...")
"""

import pytest
from src.parsing_pipeline.modules.enrichment.finding_extractor import FindingExtractor


@pytest.fixture
def extractor():
    """Create FindingExtractor instance."""
    return FindingExtractor()


class TestMultiYearSpanPatterns:
    """Test R1 multi-year span pattern rejection."""

    def test_reject_fy_range_to_format(self, extractor):
        """Reject 'during FYs 2003-04 to 2021-22' format."""
        text = (
            "Audit observed that PRD had released grants amounting to ₹ 59,995.90 crore, "
            "under different scheme heads, to PRIs, during the financial years 2003-04 to "
            "2021-22, but PRIs had submitted UCs for an amount of ₹ 34,129.49 crore."
        )
        assert extractor._is_non_finding(text) is True

    def test_reject_during_years_dash_format(self, extractor):
        """Reject 'during years 2003-2022' format."""
        text = (
            "As per data compiled, UD&HD had sanctioned Grants-in-Aids of ₹ 31,564.70 crore, "
            "during the years 2003-2022 against which UCs were pending."
        )
        assert extractor._is_non_finding(text) is True

    def test_reject_from_fy_to_format(self, extractor):
        """Reject 'from FY 2015-16 to 2021-22' format."""
        text = (
            "The total allocation from FY 2015-16 to 2021-22 was ₹ 500 crore "
            "as shown in Table 3.1."
        )
        assert extractor._is_non_finding(text) is True

    def test_reject_for_period_from_format(self, extractor):
        """Reject 'for the period from FY 2018' format."""
        text = (
            "Grants released for the period from FY 2018 onwards amounted to ₹ 200 crore."
        )
        assert extractor._is_non_finding(text) is True

    def test_accept_current_year_finding(self, extractor):
        """Accept findings about current year with monetary values."""
        text = (
            "Audit observed that the Department incurred an irregular expenditure of "
            "₹ 10.50 crore on procurement of equipment without following tender procedures."
        )
        assert extractor._is_non_finding(text) is False

    def test_accept_loss_finding_with_year_reference(self, extractor):
        """Accept actual finding even if it mentions a year."""
        text = (
            "In 2021, the Corporation failed to recover user charges amounting to "
            "₹ 15.32 crore resulting in loss of revenue."
        )
        assert extractor._is_non_finding(text) is False


class TestTableReferencePatterns:
    """Test R1 table reference pattern rejection."""

    def test_reject_as_depicted_in_table(self, extractor):
        """Reject 'as depicted in Table X.X' format."""
        text = (
            "The position of release and adjustment of grants is as depicted in Table 1.6."
        )
        assert extractor._is_non_finding(text) is True

    def test_reject_as_shown_in_table(self, extractor):
        """Reject 'as shown in Table X.X' format."""
        text = (
            "Details of pendency of UCs are as shown in Table 3.7 below."
        )
        assert extractor._is_non_finding(text) is True

    def test_reject_given_in_following_table(self, extractor):
        """Reject 'given in the following Table' format."""
        text = (
            "The year-wise position of grants released is given in the following Table."
        )
        assert extractor._is_non_finding(text) is True

    def test_accept_finding_referencing_table_later(self, extractor):
        """Accept finding that happens to reference a table later in text."""
        # The pattern should check intro (first 300 chars), so if table ref
        # is after 300 chars, it should not reject. We need enough text to push
        # the table reference past the 300 char boundary.
        text = (
            "Audit observed that the Municipal Corporation irregularly paid ₹ 25 crore "
            "to contractors without proper verification of work completion. This resulted "
            "in wasteful expenditure amounting to significant loss. The contractor had not "
            "submitted the required documents for verification. The Department failed to "
            "conduct proper scrutiny of the bills submitted. Further details of the "
            "irregular payments are given in Table 5.2."  # Table ref is now after 300 chars
        )
        # Verify the table ref is actually after 300 chars
        assert len(text) > 350
        assert "Table 5.2" in text[300:]
        # The table ref is after 300 chars, so intro check won't catch it
        assert extractor._is_non_finding(text) is False


class TestSourceCompilationPatterns:
    """Test R1 source compilation pattern rejection."""

    def test_reject_compiled_by_ag(self, extractor):
        """Reject 'compiled by the AG' format."""
        text = (
            "As per data relating to UCs, compiled by the office of the AG (A&E), "
            "Bihar Patna, it was observed that UD&HD had sanctioned ₹ 31,564.70 crore."
        )
        assert extractor._is_non_finding(text) is True

    def test_reject_source_office(self, extractor):
        """Reject '(Source: Office of AG)' format."""
        text = (
            "(Source: Office of AG, Bihar) The total amount released was ₹ 100 crore."
        )
        assert extractor._is_non_finding(text) is True

    def test_reject_based_on_data_provided_by(self, extractor):
        """Reject 'based on the data provided by' format."""
        text = (
            "As per the data provided by the Department, the total sanctioned amount "
            "was ₹ 5,000 crore during 2015-2022."
        )
        assert extractor._is_non_finding(text) is True

    def test_accept_audit_sourced_finding(self, extractor):
        """Accept actual finding discovered by audit."""
        text = (
            "Audit scrutiny revealed that the Department had made excess payment of "
            "₹ 5.50 crore due to incorrect calculation of rates."
        )
        assert extractor._is_non_finding(text) is False


class TestBackgroundAllocationPatterns:
    """Test R1 background release/allocation pattern rejection."""

    def test_reject_released_grants_during_pattern(self, extractor):
        """Reject 'released grants amounting to ₹X during different schemes'."""
        text = (
            "PRD had released grants amounting to ₹ 59,995.90 crore under different "
            "scheme heads to PRIs during the period."
        )
        assert extractor._is_non_finding(text) is True

    def test_reject_allocated_funds_for_various(self, extractor):
        """Reject 'allocated funds of ₹X for various purposes'."""
        text = (
            "The Government had allocated funds of ₹ 1,500 crore for various "
            "infrastructure development projects."
        )
        assert extractor._is_non_finding(text) is True

    def test_reject_sanctioned_gia_to_different(self, extractor):
        """Reject 'sanctioned GIA of ₹X to different bodies'."""
        text = (
            "The Department had sanctioned GIA of ₹ 2,000 crore to different ULBs "
            "during the audit period."
        )
        assert extractor._is_non_finding(text) is True

    def test_accept_irregular_sanction(self, extractor):
        """Accept actual finding about irregular sanction."""
        text = (
            "Audit noticed that the sanctioning authority irregularly sanctioned "
            "₹ 50 lakh without obtaining necessary approvals."
        )
        assert extractor._is_non_finding(text) is False


class TestUCPendingContextPatterns:
    """Test R1 UC/adjustment pending context pattern rejection."""

    def test_reject_ucs_submitted_as_of_march(self, extractor):
        """Reject 'UCs for ₹X crore (56%) only as of March 2023'."""
        text = (
            "PRIs had submitted UCs for an amount of ₹ 34,129.49 crore (56.89 per cent) "
            "only (as of March 2023)."
        )
        assert extractor._is_non_finding(text) is True

    def test_reject_utilisation_certificates_as_on(self, extractor):
        """Reject 'UCs for ₹X as of March' format - matches actual report data."""
        # This matches the pattern we saw in BR report: "UCs for an amount of ₹X (Y%) only (as of March 2023)"
        text = (
            "UCs for an amount of ₹ 500 crore (42 per cent) only (as of March 2023) "
            "were submitted by the PRIs."
        )
        assert extractor._is_non_finding(text) is True


class TestActualFindingsNotRejected:
    """Ensure actual audit findings are NOT rejected by R1 patterns."""

    def test_accept_loss_of_revenue(self, extractor):
        """Accept loss of revenue finding."""
        text = (
            "Audit observed a loss of revenue of ₹ 62.76 crore due to "
            "non-imposition of penalty on delayed payments."
        )
        assert extractor._is_non_finding(text) is False

    def test_accept_irregular_expenditure(self, extractor):
        """Accept irregular expenditure finding."""
        text = (
            "The Corporation incurred irregular expenditure of ₹ 15.50 crore on "
            "construction works without obtaining technical sanction."
        )
        assert extractor._is_non_finding(text) is False

    def test_accept_wasteful_expenditure(self, extractor):
        """Accept wasteful expenditure finding."""
        text = (
            "Failure of Nagar Parishad to ensure timely remittance resulted in "
            "avoidable expenditure of ₹ 1.14 crore towards penalty."
        )
        assert extractor._is_non_finding(text) is False

    def test_accept_non_recovery(self, extractor):
        """Accept non-recovery finding."""
        text = (
            "Non-recovery of user charges of ₹ 17.07 crore from households "
            "resulted in loss to the corporation."
        )
        assert extractor._is_non_finding(text) is False

    def test_accept_idle_assets(self, extractor):
        """Accept idle assets finding."""
        text = (
            "Equipment costing ₹ 3.50 crore remained idle for over two years "
            "due to absence of trained personnel."
        )
        assert extractor._is_non_finding(text) is False

    def test_accept_fraud_finding(self, extractor):
        """Accept fraud/misappropriation finding."""
        text = (
            "Audit noticed suspected misappropriation of ₹ 25 lakh due to "
            "fictitious bills submitted by the contractor."
        )
        assert extractor._is_non_finding(text) is False


class TestBRReportProblematicCases:
    """Test specific problematic cases from BR_2024_03 report."""

    def test_reject_br_prd_grants_case(self, extractor):
        """Reject the specific BR report PRD grants case (₹94,125 crore issue)."""
        text = (
            "Audit observed that PRD had released grants amounting to ₹ 59,995.90 crore, "
            "under different scheme heads, to PRIs, during the financial years 2003-04 to "
            "2021-22, but PRIs had submitted UCs for an amount of ₹ 34,129.49 crore "
            "(56.89 per cent) only (as of March 2023), as depicted in Table 1.6."
        )
        assert extractor._is_non_finding(text) is True

    def test_reject_br_udhd_gia_case(self, extractor):
        """Reject the specific BR report UD&HD GIA case (₹63,129 crore issue)."""
        text = (
            "As per data relating to UCs, compiled by the office of the AG (A&E), Bihar "
            "Patna, it was observed that UD&HD had sanctioned Grants-in-Aids (GIA) of "
            "₹ 31,564.70 crore, during the period from FYs 2003-04 to 2021-22 against "
            "which UCs of ₹ 19,445.30 crore were submitted while ₹ 12,119.42 crore "
            "(38 per cent) were pending for adjustment (as of March 2023), as given in Table 3.7."
        )
        assert extractor._is_non_finding(text) is True

    def test_accept_br_actual_finding(self, extractor):
        """Accept actual finding from BR report."""
        text = (
            "Failure of Nagar Parishad, Saharsa, to ensure timely remittance of statutory "
            "contributions, to the Employees' Provident Fund, resulted in an avoidable "
            "expenditure towards penalty for damages and interest of ₹ 1.14 crore."
        )
        assert extractor._is_non_finding(text) is False
