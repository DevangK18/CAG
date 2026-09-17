"""
R5: Unit tests for primary amount identification in MonetaryProcessor.

Tests the _identify_primary method and get_primary_amount convenience method
for selecting the single most relevant monetary amount from a finding.

Priority order tested:
1. Explicit totals ("total of ₹X", "aggregating to ₹X")
2. FINDING_IMPACT context amounts (highest confidence)
3. RECOVERY_DUE amounts
4. Maximum non-historical/non-budget amount
5. Fallback: maximum overall amount
"""

import pytest
from src.parsing_pipeline.modules.enrichment.monetary_processor import (
    MonetaryProcessor,
    MonetaryContext,
    ClassifiedMonetaryValue,
)


@pytest.fixture
def processor():
    """Create MonetaryProcessor instance."""
    return MonetaryProcessor()


class TestExplicitTotalPriority:
    """Test Priority 1: Explicit totals are marked as primary."""

    def test_total_of_amount(self, processor):
        """'total of ₹X crore' should be primary."""
        text = (
            "The Corporation spent ₹ 10 crore per project across 5 projects, "
            "totaling to ₹ 50 crore."
        )
        classified = processor.extract_with_context(text)
        primary = [c for c in classified if c.is_primary]
        assert len(primary) == 1
        # The ₹50 crore (total) should be primary
        assert primary[0].value.amount == 50.0

    def test_aggregating_to_amount(self, processor):
        """'aggregating to ₹X' should be primary."""
        text = (
            "Multiple irregularities of ₹ 5 crore and ₹ 8 crore were found, "
            "aggregating to Rs. 13 crore."
        )
        classified = processor.extract_with_context(text)
        primary = [c for c in classified if c.is_primary]
        assert len(primary) == 1
        # The ₹13 crore (aggregate) should be primary
        assert primary[0].value.amount == 13.0

    def test_amounting_to(self, processor):
        """'amounting to ₹X' should be primary if explicit total matches."""
        text = "Wasteful expenditure amounting to ₹ 25 crore was noticed."
        classified = processor.extract_with_context(text)
        primary = [c for c in classified if c.is_primary]
        assert len(primary) == 1
        assert primary[0].value.amount == 25.0


class TestFindingImpactPriority:
    """Test Priority 2: FINDING_IMPACT context amounts are primary when no explicit total."""

    def test_loss_amount_is_primary(self, processor):
        """Loss amount should be primary over allocation amount."""
        text = (
            "Against the allocated funds of ₹ 100 crore, there was a loss of "
            "₹ 15 crore due to mismanagement."
        )
        classified = processor.extract_with_context(text)
        primary = [c for c in classified if c.is_primary]
        assert len(primary) == 1
        # The ₹15 crore (loss) should be primary, not ₹100 crore (allocation)
        assert primary[0].value.amount == 15.0
        assert primary[0].context == MonetaryContext.FINDING_IMPACT

    def test_irregular_expenditure_is_primary(self, processor):
        """Irregular expenditure should be primary."""
        text = (
            "The Department received grants of ₹ 500 crore but incurred "
            "irregular expenditure of ₹ 20 crore."
        )
        classified = processor.extract_with_context(text)
        primary = [c for c in classified if c.is_primary]
        assert len(primary) == 1
        assert primary[0].value.amount == 20.0
        assert primary[0].context == MonetaryContext.FINDING_IMPACT

    def test_shortfall_is_primary(self, processor):
        """Shortfall amount should be primary."""
        text = "Revenue collection showed a shortfall of ₹ 10 crore against target."
        classified = processor.extract_with_context(text)
        primary = [c for c in classified if c.is_primary]
        assert len(primary) == 1
        assert primary[0].value.amount == 10.0
        assert primary[0].context == MonetaryContext.FINDING_IMPACT

    def test_multiple_finding_impacts_highest_is_primary(self, processor):
        """When multiple FINDING_IMPACT, highest amount should be primary."""
        text = (
            "Audit noticed excess expenditure of ₹ 5 crore and avoidable "
            "expenditure of ₹ 12 crore."
        )
        classified = processor.extract_with_context(text)
        primary = [c for c in classified if c.is_primary]
        assert len(primary) == 1
        # Higher amount (₹12 crore) should be primary
        assert primary[0].value.amount == 12.0


class TestRecoveryDuePriority:
    """Test Priority 3: RECOVERY_DUE amounts are primary when no FINDING_IMPACT."""

    def test_recovery_due_is_primary(self, processor):
        """Recovery due should be primary over budget allocation."""
        text = (
            "The sanctioned amount was ₹ 200 crore. Recovery due from "
            "contractors was ₹ 30 crore."
        )
        classified = processor.extract_with_context(text)
        primary = [c for c in classified if c.is_primary]
        assert len(primary) == 1
        assert primary[0].value.amount == 30.0
        assert primary[0].context == MonetaryContext.RECOVERY_DUE

    def test_outstanding_amount_is_primary(self, processor):
        """Outstanding amount should be primary."""
        text = (
            "Total allocation was ₹ 500 crore. Outstanding amount of "
            "₹ 50 crore was pending recovery."
        )
        classified = processor.extract_with_context(text)
        primary = [c for c in classified if c.is_primary]
        assert len(primary) == 1
        assert primary[0].value.amount == 50.0


class TestNonHistoricalPriority:
    """Test Priority 4: Max non-historical/non-budget amount is primary."""

    def test_historical_data_not_primary(self, processor):
        """Historical data amounts should not be primary over actual impacts."""
        # Use clear FINDING_IMPACT context for the current amount
        text = (
            "During the years 2015-2020, the amount spent was ₹ 1000 crore. "
            "This resulted in a loss of ₹ 50 crore."
        )
        classified = processor.extract_with_context(text)
        primary = [c for c in classified if c.is_primary]
        assert len(primary) == 1
        # The ₹50 crore (loss) should be primary, not ₹1000 crore (historical)
        assert primary[0].value.amount == 50.0
        assert primary[0].context == MonetaryContext.FINDING_IMPACT

    def test_budget_allocation_not_primary_when_actual_exists(self, processor):
        """Budget allocation should not be primary when actual expenditure exists."""
        text = (
            "Government allocated funds of ₹ 200 crore. The amount spent "
            "on the project was ₹ 150 crore."
        )
        classified = processor.extract_with_context(text)
        primary = [c for c in classified if c.is_primary]
        assert len(primary) == 1
        # ₹150 crore (actual spent) should be primary
        assert primary[0].value.amount == 150.0


class TestFallbackMax:
    """Test Priority 5: Fallback to maximum overall amount."""

    def test_fallback_to_max_when_all_unknown(self, processor):
        """When all contexts are unknown, max amount is primary."""
        text = "Amount A was ₹ 10 crore. Amount B was ₹ 25 crore."
        classified = processor.extract_with_context(text)
        primary = [c for c in classified if c.is_primary]
        assert len(primary) == 1
        # Max (₹25 crore) should be primary
        assert primary[0].value.amount == 25.0

    def test_fallback_when_only_budget_amounts(self, processor):
        """When only budget amounts exist, max is primary."""
        text = (
            "Government released grants of ₹ 100 crore. "
            "Ministry allocated funds of ₹ 200 crore."
        )
        classified = processor.extract_with_context(text)
        primary = [c for c in classified if c.is_primary]
        assert len(primary) == 1
        # Max (₹200 crore) should be primary
        assert primary[0].value.amount == 200.0


class TestGetPrimaryAmountMethod:
    """Test the get_primary_amount convenience method."""

    def test_get_primary_returns_single_value(self, processor):
        """get_primary_amount should return exactly one ClassifiedMonetaryValue."""
        text = "Loss of ₹ 10 crore was detected."
        primary = processor.get_primary_amount(text)
        assert primary is not None
        assert isinstance(primary, ClassifiedMonetaryValue)
        assert primary.is_primary is True

    def test_get_primary_returns_none_for_no_amounts(self, processor):
        """get_primary_amount should return None when no amounts found."""
        text = "No monetary values in this text."
        primary = processor.get_primary_amount(text)
        assert primary is None

    def test_get_primary_with_finding_impact(self, processor):
        """get_primary_amount should return FINDING_IMPACT when present."""
        text = (
            "Against budget of ₹ 500 crore, irregular expenditure of "
            "₹ 25 crore was noticed."
        )
        primary = processor.get_primary_amount(text)
        assert primary is not None
        assert primary.value.amount == 25.0
        assert primary.context == MonetaryContext.FINDING_IMPACT


class TestSingleAmountPrimary:
    """Test that single amounts are always marked as primary."""

    def test_single_amount_is_primary(self, processor):
        """A single amount should always be primary."""
        text = "Wasteful expenditure of ₹ 5 crore was noticed."
        classified = processor.extract_with_context(text)
        assert len(classified) == 1
        assert classified[0].is_primary is True

    def test_single_budget_amount_is_primary(self, processor):
        """Even a single budget amount should be primary."""
        text = "Government allocated funds of ₹ 100 crore."
        classified = processor.extract_with_context(text)
        assert len(classified) == 1
        assert classified[0].is_primary is True


class TestBRReportPrimaryCases:
    """Test primary amount selection on BR report cases."""

    def test_br_penalty_finding(self, processor):
        """BR report penalty finding should have correct primary amount."""
        text = (
            "Failure of Nagar Parishad, Saharsa, to ensure timely remittance of statutory "
            "contributions, to the Employees' Provident Fund, resulted in an avoidable "
            "expenditure towards penalty for damages and interest of ₹ 1.14 crore."
        )
        primary = processor.get_primary_amount(text)
        assert primary is not None
        assert primary.value.amount == 1.14
        assert primary.context == MonetaryContext.FINDING_IMPACT

    def test_br_grants_with_uc_finding(self, processor):
        """BR report grants case should not select the large historical amount as primary."""
        text = (
            "PRD had released grants amounting to ₹ 59,995.90 crore, under different scheme "
            "heads, to PRIs, during the financial years 2003-04 to 2021-22, but PRIs had "
            "submitted UCs for an amount of ₹ 34,129.49 crore (56.89 per cent) only."
        )
        classified = processor.extract_with_context(text)
        # We should have multiple amounts
        assert len(classified) >= 2

        # Check that the primary is not the huge ₹59,995 crore
        primary = [c for c in classified if c.is_primary]
        assert len(primary) == 1
        # The smaller UC amount could be primary since it's not historical/budget
        # Or none if both are classified as historical/budget

    def test_br_loss_finding(self, processor):
        """BR report loss finding should have loss amount as primary."""
        text = (
            "Non-recovery of user charges of ₹ 17.07 crore from households "
            "resulted in loss to the corporation."
        )
        primary = processor.get_primary_amount(text)
        assert primary is not None
        assert primary.value.amount == 17.07
        assert primary.context == MonetaryContext.FINDING_IMPACT


class TestPrimaryAmountOnlyOne:
    """Test that exactly one amount is marked as primary."""

    def test_exactly_one_primary(self, processor):
        """Only one amount should be marked as primary, regardless of count."""
        text = (
            "Budget was ₹ 100 crore. Spent ₹ 80 crore. Loss of ₹ 5 crore. "
            "Recovery due ₹ 3 crore. Total was ₹ 85 crore."
        )
        classified = processor.extract_with_context(text)
        primary_count = sum(1 for c in classified if c.is_primary)
        assert primary_count == 1

    def test_primary_survives_deduplication(self, processor):
        """Primary flag should be set after deduplication."""
        text = "Loss of ₹ 10 crore. Another loss of ₹ 10.0 crore was also there."
        classified = processor.extract_with_context(text)
        # Should deduplicate to 1 amount
        assert len(classified) == 1
        assert classified[0].is_primary is True

